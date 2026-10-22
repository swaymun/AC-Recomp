#!/usr/bin/env python3
"""Join private static-lift inventories, runtime-source candidates and traces.

Standard library only. This is a conservative evidence inventory, not a C++
compiler or proof of guest correctness. See docs/ASTRAL_COVERAGE_AUDIT.md.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess


HEX = r"0x[0-9a-fA-F]+"
FUNC = re.compile(r"^void (\w+)_([0-9a-fA-F]{8,})\(nx::CPU&")
SYMBOL = re.compile(
    r'^\s*\{("(?:\\.|[^"\\])*"), (0x[0-9a-fA-F]+), (\d+), (\d+), (\d+), ([01])\},')
TRAP = re.compile(r'nx::unimpl\(c, NXB \+ (0x[0-9a-fA-F]+)ull, "([^"]*)"')
REG = re.compile(r'NX_HLE\("([^"]+)",\s*(\w+)\)')
RANKS = {"runtime_hit": 0, "static_reachable": 1, "unproven": 2}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def scrub(text):
    """Blank comments/strings without changing offsets; suitable for brace scans."""
    # A digit separator (500'000) is not the start of a character literal.
    token = r"""//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|(?<![\w])'(?:\\(?:[0-7]{1,3}|x[\da-fA-F]+|.)|[^\\'\n])'"""
    return re.sub(token, lambda m: "".join("\n" if c == "\n" else " " for c in m[0]), text)


def close_brace(mask, start):
    level = 0
    for i in range(start, len(mask)):
        if mask[i] == "{":
            level += 1
        elif mask[i] == "}":
            level -= 1
            if not level:
                return i
    raise ValueError("unbalanced C++ block")


def evidence(path, line, text):
    return {"path": str(path), "line": line, "text": text.strip()[:700]}


class Audit:
    def __init__(self):
        self.gaps = {}
        self.files = {}
        self.modules = {}
        self.symbols = []
        self.hle = {}
        self.edges = defaultdict(set)
        self.dynamic_direct_evidence = {}
        self.roots = set()
        self.plt = {}
        self.observed = Counter()
        self.observations = {}
        self.trace_summaries = {}
        self.svc_sites = defaultdict(list)
        self.svc_cases = set()
        self.sysreg_sites = defaultdict(list)
        self.mrs_cases = set()
        self.defined_nodes = set()
        self.table_nodes = set()
        self.analysis = {}
        self.branch_sites = {}
        self.warnings = []

    def remember(self, path, role):
        path = Path(path).resolve()
        self.files[str(path)] = {"sha256": digest(path), "bytes": path.stat().st_size, "role": role}

    def gap(self, key, category, detail, ev=None, **fields):
        g = self.gaps.setdefault(key, {
            "id": key, "category": category, "detail": detail,
            "reachability": "unproven", "runtime_hits": 0, "evidence": [],
            "severity": 4 if category in ("hle_fixed_result", "ipc_noop_candidate",
                                         "ipc_noop_unmapped_service", "unmapped_synthetic_continuation") else 2,
        })
        if ev and ev not in g["evidence"] and len(g["evidence"]) < 8:
            g["evidence"].append(ev)
        g.update(fields)
        return g

    def read_analysis(self, path):
        """Optional external lifter manifest; no import/execution of game code."""
        self.remember(path, "lifter_analysis")
        doc = json.loads(Path(path).read_text())
        if doc.get("schema") != 1 or not isinstance(doc.get("modules"), list):
            raise ValueError("analysis requires schema=1 and modules list")
        for item in doc["modules"]:
            name = item["name"]
            if name in self.analysis:
                raise ValueError("duplicate analysis module")
            self.analysis[name] = item
            for pc, symbol in item.get("plt", {}).items():
                self.plt[f"{name}:{int(pc):x}"] = symbol
            for start in item.get("roots", []):
                self.roots.add(f"{name}:{start:x}")
            for start, end in item.get("nonpadding_uncovered_ranges",
                                       item.get("decoded_uncovered_ranges", [])):
                if end <= start or (end - start) % 4:
                    raise ValueError("invalid decoded uncovered range")
                self.gap(f"unlifted:{name}:{start:x}", "decoded_outside_function_ranges",
                         "Decoded text outside discovered function ranges; may be padding/data.",
                         evidence(path, 0, f"{name} [{start:#x}, {end:#x})"),
                         instructions=(end - start) // 4, module=name, address=start)
            branches = sorted(item.get("unresolved_br", []))
            for start, end in item.get("functions", []):
                self.branch_sites[f"{name}:{start:x}"] = branches[
                    bisect.bisect_left(branches, start):bisect.bisect_left(branches, end)]
            for pc in branches:
                self.gap(f"indirect:{name}:{pc:x}", "indirect_tail_dispatch",
                         "Unresolved static target uses runtime dispatch; not itself a failure.",
                         evidence(path, 0, f"analysis BR at {pc:#x}"), module=name, address=pc)

    def read_generated(self, root):
        dirs = sorted(p.parent for p in Path(root).glob("*/table.cpp"))
        if not dirs:
            raise ValueError("no generated */table.cpp files")
        for directory in dirs:
            name = directory.name
            table_path = directory / "table.cpp"
            self.remember(table_path, "generated_table")
            table = table_path.read_text()
            declared = set()
            table_entries = set()
            definitions = set()
            counters = Counter()
            noops = Counter()
            funcs_h = directory / "funcs.h"
            self.remember(funcs_h, "generated_declarations")
            for m in re.finditer(r"void (\w+)_([0-9a-fA-F]{8,})\(", funcs_h.read_text()):
                declared.add(f"{m[1]}:{int(m[2], 16):x}")
            for m in re.finditer(r"\{(0x[0-9a-fA-F]+), (\w+)_([0-9a-fA-F]{8,})\}", table):
                key = f"{name}:{int(m[1], 16):x}"
                table_entries.add(key)
                if key != f"{m[2]}:{int(m[3], 16):x}":
                    self.gap("table-mismatch:" + key, "dispatch_table_mismatch",
                             "Dispatch entry offset differs from named generated function.",
                             evidence(table_path, table[:m.start()].count("\n") + 1, m[0]))
            for i, line in enumerate(table.splitlines(), 1):
                m = SYMBOL.match(line)
                if m:
                    sym = {"module": name, "name": json.loads(m[1]), "value": int(m[2], 16),
                           "size": int(m[3]), "type": int(m[4]), "bind": int(m[5]),
                           "imported": bool(int(m[6])), "line": i, "path": str(table_path)}
                    self.symbols.append(sym)
                    if not sym["imported"] and sym["name"] in ("nnMain", "nninitStartup"):
                        self.roots.add(f"{name}:{sym['value']:x}")
            for m in re.finditer(r"static const uint64_t init_array\[\] = \{([^}]*)\}", table):
                self.roots.update(f"{name}:{int(v, 16):x}" for v in re.findall(HEX, m[1]) if int(v, 16))
            for path in sorted(directory.glob("code_*.cpp")):
                self.remember(path, "generated_code")
                current = None
                branch_index = 0
                previous_line = ""
                labels, targets = set(), set()

                def finish():
                    for target in targets - labels:
                        self.gap(f"label:{current}:{target}", "missing_local_branch_label",
                                 "Generated goto has no matching label in this function.",
                                 evidence(path, 0, target), function=current)

                with path.open() as f:
                    for ln, line in enumerate(f, 1):
                        m = FUNC.match(line)
                        if m:
                            if current:
                                finish()
                            current = f"{m[1]}:{int(m[2], 16):x}"
                            definitions.add(current)
                            branch_index = 0
                            labels, targets = set(), set()
                            continue
                        if not current:
                            continue
                        labels.update(re.findall(r"^(L_[A-F0-9]+):", line))
                        targets.update(re.findall(r"goto (L_[A-F0-9]+)", line))
                        for m in re.finditer(r"\b(\w+)_([0-9a-fA-F]{8,})\(c\)", line):
                            self.edges[current].add(f"{m[1]}:{int(m[2], 16):x}")
                        for m in re.finditer(r"nx::call\(c, NXB \+ (" + HEX + r")ull\)", line):
                            target = f"{name}:{int(m[1], 16):x}"
                            self.edges[current].add(target)
                            self.dynamic_direct_evidence[(current, target)] = (
                                evidence(path, ln, line), "//" not in line, previous_line.strip())
                        m = TRAP.search(line)
                        if m:
                            pc, reason = int(m[1], 16), m[2]
                            category = ("undecodable_trap" if reason.startswith("undecodable") else
                                        "architectural_trap" if reason in ("udf", "brk") else
                                        "unsupported_instruction")
                            g = self.gap(f"trap:{name}:{pc:x}", category, reason,
                                         evidence(path, ln, line), module=name, address=pc)
                            contexts = g.setdefault("functions", [])
                            if current not in contexts:
                                contexts.append(current)
                            counters["trap_emissions"] += 1
                        if "// br " in line and "switch (" not in line:
                            counters["indirect_tail_emissions"] += 1
                            if current not in self.plt:
                                sites = self.branch_sites.get(current, [])
                                key = (f"indirect:{name}:{sites[branch_index]:x}" if branch_index < len(sites)
                                       else f"indirect:{name}:{path.name}:{ln}")
                                branch_index += 1
                                self.gap(key, "indirect_tail_dispatch",
                                         "Unresolved static target uses runtime dispatch; not itself a failure.",
                                         evidence(path, ln, line), function=current)
                        if "// blr " in line:
                            counters["indirect_call_emissions"] += 1
                        if "default: nx::call" in line:
                            counters["jump_table_fallback_emissions"] += 1
                        for m in re.finditer(r"nx::svc\(c,\s*(" + HEX + r"|\d+)", line):
                            self.svc_sites[int(m[1], 0)].append((current, evidence(path, ln, line)))
                        for m in re.finditer(r"nx::(mrs|msr)\(c,\s*(" + HEX + r"|\d+)", line):
                            self.sysreg_sites[(m[1], int(m[2], 0))].append(
                                (current, evidence(path, ln, line)))
                        m = re.match(r"\s*;\s*// (\w+)", line)
                        if m:
                            noops[m[1]] += 1
                        if line.strip():
                            previous_line = line
                if current:
                    finish()
            for key in (declared | table_entries) - definitions:
                self.gap("missing-function:" + key, "missing_generated_function",
                         "Declared or dispatch-listed function has no emitted body.",
                         evidence(table_path, 0, key), function=key)
            self.defined_nodes.update(definitions)
            self.table_nodes.update(table_entries)
            report_path = directory / "report.txt"
            reported = {}
            if report_path.exists():
                self.remember(report_path, "lifter_report")
                raw = report_path.read_text()
                m = re.search(r"functions (\d+), handled (\d+), unhandled (\d+)", raw)
                if m:
                    reported.update(zip(("functions", "handled", "unhandled"), map(int, m.groups())))
                m = re.search(r"jump tables (\d+), unresolved br .*? (\d+)", raw)
                if m:
                    reported.update(zip(("jump_tables", "unresolved_br"), map(int, m.groups())))
            self.modules[name] = dict(counters, declared_functions=len(declared),
                                      table_functions=len(table_entries), emitted_functions=len(definitions),
                                      reported=reported, no_op_emissions=dict(sorted(noops.items())))
            analysis = self.analysis.get(name)
            if analysis:
                if analysis.get("table_sha256") != digest(table_path):
                    raise ValueError(f"analysis does not match generated table for {name}")
                discovered = {f"{name}:{start:x}" for start, _ in analysis.get("functions", [])}
                for key in sorted(discovered - definitions):
                    self.gap("missing-discovered:" + key, "missing_discovered_function",
                             "Fresh analysis discovered an entry that has no generated function body.",
                             evidence(directory / "report.txt", 0, key), function=key)
                self.modules[name]["analysis"] = {
                    k: analysis[k] for k in ("text_bytes", "decoded_instructions", "function_ranges",
                                             "uncovered_text_bytes", "undecoded_uncovered_bytes")
                    if k in analysis}
                self.modules[name]["analysis"]["uncovered_mnemonics"] = analysis.get(
                    "decoded_uncovered_mnemonics", {})
                self.modules[name]["analysis"]["padding_uncovered_instructions"] = sum(
                    (end - start) // 4 for start, end in analysis.get("padding_uncovered_ranges", []))
                self.modules[name]["analysis"]["jump_table_target_entries"] = sum(
                    len(targets) for targets in analysis.get("jump_tables", {}).values())
        if not self.analysis:
            self.warnings.append("No analysis manifest: undiscovered text and PLT classification are unknown.")

    def read_runtime(self, root):
        root = Path(root)
        paths = sorted(root.rglob("*.cpp"))
        if not paths:
            raise ValueError("no runtime C++ sources")
        for path in paths:
            self.remember(path, "runtime_source")
            raw = path.read_text(encoding="utf-8-sig")
            mask = scrub(raw)
            bodies = {}
            spans = []
            for m in re.finditer(r"\b(?:void|uint32_t|uint64_t|bool|std::shared_ptr<Service>)"
                                 r"\s+(\w+)\s*\([^;{}]*\)\s*\{", mask):
                end = close_brace(mask, m.end() - 1)
                bodies[m[1]] = (raw[m.end():end], m.start())
                spans.append((m.start(), end, m[1]))
            for m in REG.finditer(raw):
                symbol, handler = m.groups()
                self.hle[symbol] = {"path": str(path), "line": raw[:m.start()].count("\n") + 1,
                                    "handler": handler}
                body, at = bodies.get(handler, ("", 0))
                clean = re.sub(r"\s+", "", scrub(body))
                # Strictly small bodies only. Bigger functions need semantic review.
                kind = None
                constant = r"(?:[A-Za-z_]\w*|[-~]?(?:0x[0-9a-fA-F]+|\d+)[uUlL]*|uint64_t\(-1\))"
                if handler in bodies and (not clean or re.fullmatch(r"c\.x\[0\]=" + constant + ";", clean)):
                    kind = "hle_fixed_result"
                if re.match(r"\s*fatal\(", body) and "unsupported" in body and body.count(";") == 1:
                    kind = "hle_unsupported_capability"
                if kind:
                    self.gap("hle:" + symbol, kind,
                             f"Registered handler {handler}: constant/no-op or unsupported capability; review semantics.",
                             evidence(path, raw[:at].count("\n") + 1, body),
                             symbol=symbol, handler=handler)
            # Candidate-only lexical inventory of literal IPC no-op lambdas.
            for m in re.finditer(r"(?:\w+(?:->|\.))?cmds\[(\d+)\]\s*=\s*\[[^\]]*\]\s*"
                                 r"\(IpcCtx&[^)]*\)\s*\{\s*return 0u?;\s*\}", mask):
                # Service literals are kept in raw, which shares mask offsets.
                enclosing = [s for s in spans if s[0] < m.start() < s[1]]
                scope = min(enclosing, key=lambda s: s[1] - s[0]) if enclosing else (0, len(raw), "")
                prefix = raw[scope[0]:m.start()]
                literals = list(re.finditer(r'(?:svc|Service|make_shared<Service>)\("([^"]+)"', prefix))
                services = [literals[-1][1]] if literals else []
                if not services and scope[2]:
                    # Shared setup helper: bind to each actual registrar's object name.
                    for reg in re.finditer(r'ServiceRegistrar\s+\w+\("[^"]+",\s*\[\]\s*\{(.*?)\}\);',
                                           raw, re.S):
                        if re.search(r"\b" + re.escape(scope[2]) + r"\(\*\w+\)", reg[1]):
                            services.extend(re.findall(r'make_shared<Service>\("([^"]+)"', reg[1]))
                ln = raw[:m.start()].count("\n") + 1
                for service in sorted(set(services)):
                    self.gap(f"ipc:{service}:{int(m[1])}", "ipc_noop_candidate",
                             "Literal success-only handler; service identity inferred lexically, review required.",
                             evidence(path, ln, raw[m.start():m.end()]), service=service, command=int(m[1]))
                if not services:
                    self.gap(f"ipc-source:{path.name}:{ln}", "ipc_noop_unmapped_service",
                             "Literal success-only command; service identity could not be inferred.",
                             evidence(path, ln, raw[m.start():m.end()]), command=int(m[1]))
            if path.name == "kernel.cpp":
                self._kernel(raw, mask, path)
            if path.name == "main.cpp" and "mrs" in bodies:
                self.mrs_cases.update(int(x, 0) for x in re.findall(
                    r"\bcase\s+(" + HEX + r"|\d+)\s*:", scrub(bodies["mrs"][0])))

    def _kernel(self, raw, mask, path):
        start = mask.find("switch (imm)")
        if start < 0:
            self.warnings.append("kernel.cpp has no recognized SVC switch")
            return
        start = mask.index("{", start)
        end = close_brace(mask, start)
        body = mask[start + 1:end]
        cases = list(re.finditer(r"\bcase\s+(0x[0-9a-fA-F]+|\d+)\s*:", body))
        # Only case labels at the outer switch level; nested enum switches excluded.
        outer = []
        depth = 0
        cursor = 0
        for m in cases:
            segment = body[cursor:m.start()]
            depth += segment.count("{") - segment.count("}")
            cursor = m.start()
            if depth == 0:
                outer.append(m)
        pending = []
        for i, m in enumerate(outer):
            number = int(m[1], 0)
            self.svc_cases.add(number)
            pending.append(number)
            stop = outer[i + 1].start() if i + 1 < len(outer) else len(body)
            code = body[m.end():stop].strip()
            if not code:
                continue
            if re.fullmatch(r"break\s*;", code):
                for number in pending:
                    at = start + 1 + m.start()
                    self.gap(f"svc:{number}", "svc_noop", "SVC returns success without changing state.",
                             evidence(path, raw[:at].count("\n") + 1,
                                      raw[at:start + 1 + stop]), svc=number)
            pending = []

    def read_catalog(self, path):
        """Reviewed semantic gaps with source-hash binding, never arbitrary code."""
        self.remember(path, "reviewed_catalog")
        doc = json.loads(Path(path).read_text())
        if doc.get("schema") != 1:
            raise ValueError("catalog requires schema=1")
        for item in doc["gaps"]:
            ev = item["evidence"]
            source = Path(ev["path"])
            if digest(source) != item["source_sha256"]:
                raise ValueError("catalog source hash mismatch")
            lines = source.read_text().splitlines()
            if not 1 <= ev["line"] <= len(lines) or ev["text"] not in lines[ev["line"] - 1]:
                raise ValueError("catalog excerpt does not match source line")
            self.remember(source, "reviewed_runtime_source")
            fields = {k: item[k] for k in ("symbol", "service", "command", "svc", "action", "severity")
                      if k in item}
            g = self.gap(item["id"], item["category"], item["detail"], ev, reviewed=True, **fields)
            g.update(category=item["category"], detail=item["detail"])

    def observe(self, key, path, ln, line):
        self.observed[key] += 1
        self.observations.setdefault(key, evidence(path, ln, line))

    def read_nvn_trace(self, path):
        """Capped trace_stub argument samples, kept separate from general calls."""
        self.remember(path, "nvn_fallback_samples")
        with Path(path).open(errors="replace") as f:
            for ln, line in enumerate(f, 1):
                m = re.match(r"\s*\d+\s+(\w+)\([^)]*\)\s+lr ", line)
                if not m:
                    continue  # '# real ...' is only a procedure lookup
                key = "hle:" + m[1]
                g = self.gap(key, "nvn_fallback", "Executed NVN trace_stub; argument samples are capped.",
                             evidence(path, ln, line), symbol=m[1])
                g["sampled_fallback_calls"] = g.get("sampled_fallback_calls", 0) + 1
                if not self.observed[key]:
                    self.observe(key, path, ln, line)

    def read_trace(self, path):
        self.remember(path, "runtime_trace")
        before = self.observed.copy()
        with Path(path).open(errors="replace") as f:
            for ln, line in enumerate(f, 1):
                # Match actual call lines, not lookup, profiler or arbitrary substrings.
                text = line.strip()
                m = re.fullmatch(r"hle (\S+)", text)
                if m:
                    self.observe("hle:" + m[1], path, ln, line)
                m = re.match(r"svc (0x[0-9a-fA-F]+|\d+) from ", text)
                if m:
                    self.observe(f"svc:{int(m[1], 0)}", path, ln, line)
                m = re.match(r"(mrs|msr) (0x[0-9a-fA-F]+|\d+) (?:at lr|=)", text)
                if m:
                    key = f"sysreg:{m[1]}:{int(m[2], 0)}"
                    self.gap(key, "system_register_fallback", "Runtime logged generic system-register fallback.",
                             evidence(path, ln, line))
                    self.observe(key, path, ln, line)
                m = re.match(r"ipc: (?:tipc )?(\S+) cmd (\d+)(?:$| not implemented)", text)
                if m:
                    key = f"ipc:{m[1]}:{int(m[2])}"
                    self.observe(key, path, ln, line)
                    if "not implemented" in text:
                        self.gap(key, "ipc_missing_command", "Runtime used an unimplemented IPC command.",
                                 evidence(path, ln, line))
                m = re.match(r"nvn: first call of (\w+) ", text)
                if m:
                    key = "hle:" + m[1]
                    self.gap(key, "nvn_fallback", "Executed trace_stub: Initialize returns 1, others return 0.",
                             evidence(path, ln, line), symbol=m[1])
                    # First-call witness, not an extra call on top of NX_TRACE's hle line.
                    self.observations.setdefault(key, evidence(path, ln, line))
                    if self.observed[key] == before[key]:
                        self.observed[key] += 1
                for pattern, prefix, category in (
                    (r"strict IPC missing command: service=(\S+) command=(\d+)",
                     "ipc", "ipc_missing_command"),
                    (r"strict IPC missing service: (\S+)", "service", "ipc_missing_service"),
                    (r"ipc: no implementation for service '([^']+)'", "service", "ipc_missing_service"),
                    (r"strict missing function: (\S+)", "hle", "missing_import"),
                    (r"missing import called: (\S+)", "hle", "missing_import"),
                    (r"strict unhandled SVC: (0x[0-9a-fA-F]+|\d+)", "svc", "svc_missing"),
                    (r"unhandled svc (0x[0-9a-fA-F]+|\d+)", "svc", "svc_missing"),
                ):
                    m = re.search(pattern, text)
                    if m:
                        parts = list(m.groups())
                        if prefix == "svc":
                            parts[0] = str(int(parts[0], 0))
                        key = prefix + ":" + ":".join(parts)
                        self.gap(key, category, text, evidence(path, ln, line))
                        self.observe(key, path, ln, line)
                m = re.search(r"unimplemented instruction at (\w+)\+([0-9a-fA-F]+)", text)
                if m:
                    key = f"trap:{m[1]}:{int(m[2], 16):x}"
                    self.gap(key, "executed_trap", text, evidence(path, ln, line))
                    self.observe(key, path, ln, line)
                if text.startswith("FATAL:") and "unsupported" in text:
                    key = "contract:" + hashlib.sha256(text.encode()).hexdigest()[:20]
                    self.gap(key, "runtime_unsupported_contract", text, evidence(path, ln, line))
                    self.observe(key, path, ln, line)
                if text.startswith("FATAL: call into the middle of a function:") or text.startswith("FATAL: call to "):
                    target_text = text.split(" (lr ")[0].split(", lr ")[0]
                    m = re.search(r"\b(\w+)\+([0-9a-fA-F]+)", target_text)
                    key = (f"direct-target:{m[1]}:{int(m[2], 16):x}" if m else
                           "dispatch:" + hashlib.sha256(text.encode()).hexdigest()[:20])
                    self.gap(key, "unresolved_runtime_dispatch", text, evidence(path, ln, line))
                    self.observe(key, path, ln, line)
        delta = self.observed - before
        self.trace_summaries[str(Path(path).resolve())] = {
            "observed_unique": dict(sorted(Counter(k.split(":")[0] for k in delta).items())),
            "observed_lines": dict(sorted({
                kind: sum(n for key, n in delta.items() if key.split(":")[0] == kind)
                for kind in {k.split(":")[0] for k in delta}
            }.items())),
        }

    def finish(self):
        exports = {}
        for s in self.symbols:
            if not s["imported"] and s["bind"] != 0 and s["name"]:
                exports.setdefault(s["name"], s)  # loader retains the first visible definition
        imports = defaultdict(list)
        resolutions = Counter()
        for s in self.symbols:
            if not s["imported"] or not s["name"]:
                continue
            imports[s["name"]].append(s)
            if s["name"] in self.hle and s["type"] in (0, 2):
                resolutions["hle"] += 1
            elif s["name"] in exports:
                resolutions["guest_export"] += 1
            elif s["bind"] == 2:
                resolutions["weak_undefined"] += 1
            else:
                resolutions["unresolved"] += 1
                self.gap("hle:" + s["name"], "unresolved_import",
                         "Imported symbol has no matching guest export or recognized HLE registration.",
                         evidence(s["path"], s["line"], s["name"]), symbol=s["name"])
        for node, symbol in self.plt.items():
            if symbol in self.hle:
                self.edges[node].add("hle:" + symbol)
            elif symbol in exports:
                s = exports[symbol]
                self.edges[node].add(f"{s['module']}:{s['value']:x}")
        for caller, targets in list(self.edges.items()):
            for target in targets:
                if not target.startswith("hle:") and target not in self.table_nodes:
                    ev, synthetic, prior = self.dynamic_direct_evidence.get(
                        (caller, target), (evidence("generated-call-graph", 0, f"{caller} -> {target}"),
                                           False, ""))
                    g = self.gap("direct-target:" + target,
                                 "unmapped_synthetic_continuation" if synthetic else "missing_direct_dispatch_target",
                                 ("Synthetic end-of-range continuation lacks a dispatch entry; often after a "
                                  "nonreturning call. Function reachability does not prove this edge executes."
                                  if synthetic else "Generated call/tail target has no dispatch-table entry."),
                                 ev, target=target, preceding_line=prior)
                    if caller not in g.setdefault("functions", []):
                        g["functions"].append(caller)
        reachable = set(self.roots)
        todo = list(reachable)
        while todo:
            for dest in self.edges[todo.pop()] - reachable:
                reachable.add(dest)
                todo.append(dest)
        for svc, sites in self.svc_sites.items():
            if svc not in self.svc_cases:
                self.gap(f"svc:{svc}", "svc_missing", "Generated SVC has no recognized kernel switch case.",
                         sites[0][1], svc=svc)
            if f"svc:{svc}" in self.gaps:
                g = self.gaps[f"svc:{svc}"]
                g["static_sites"] = len(sites)
                g["functions"] = sorted({node for node, _ in sites})
        for (op, register), sites in self.sysreg_sites.items():
            if op == "msr" or register not in self.mrs_cases:
                self.gap(f"sysreg:{op}:{register}", "system_register_fallback",
                         "Generated system-register access reaches generic logging/zero fallback.",
                         sites[0][1], functions=sorted({node for node, _ in sites}),
                         static_sites=len(sites))
        for key, g in self.gaps.items():
            symbol = g.get("symbol")
            if symbol in imports:
                g["import_references"] = len(imports[symbol])
                for s in imports[symbol][:2]:
                    ev = evidence(s["path"], s["line"], s["name"])
                    if ev not in g["evidence"]:
                        g["evidence"].append(ev)
            nodes = g.get("functions", []) + ([g["function"]] if "function" in g else [])
            if key in reachable or any(n in reachable for n in nodes):
                g["reachability"] = "static_reachable"
            if self.observed[key]:
                g["reachability"] = "runtime_hit"
                g["runtime_hits"] = self.observed[key]
                ev = self.observations[key]
                if ev not in g["evidence"]:
                    g["evidence"].append(ev)
        gaps = sorted(self.gaps.values(), key=lambda g: (
            RANKS[g["reachability"]], g.get("severity", 2),
            -max(g["runtime_hits"], g.get("sampled_fallback_calls", 0)),
            -g.get("import_references", 0), g["id"]))
        for i, g in enumerate(gaps, 1):
            g["rank"] = i
        summary = {
            "modules": self.modules,
            "import_entries": sum(resolutions.values()),
            "import_resolution": dict(sorted(resolutions.items())),
            "hle_registrations": len(self.hle),
            "svc_cases": len(self.svc_cases),
            "generated_svc_ids": len(self.svc_sites),
            "generated_system_register_ids": len(self.sysreg_sites),
            "root_functions": len(self.roots),
            "direct_graph_reachable_nodes": len(reachable),
            "gaps": len(gaps),
            "by_category": dict(sorted(Counter(g["category"] for g in gaps).items())),
            "by_reachability": dict(sorted(Counter(g["reachability"] for g in gaps).items())),
            "runtime_observed_unique": {
                prefix: sum(v > 0 and k.startswith(prefix + ":") for k, v in self.observed.items())
                for prefix in ("hle", "ipc", "svc", "trap", "dispatch", "sysreg")
            },
            "runtime_dispatch_failures": sum(g["reachability"] == "runtime_hit" and
                                            g["category"] == "unresolved_runtime_dispatch" for g in gaps),
        }
        return {
            "schema": 1, "summary": summary, "gaps": gaps,
            "observed_calls": [{"id": k, "hits": n, "first": self.observations[k]}
                               for k, n in sorted(self.observed.items()) if n],
            "trace_summaries": self.trace_summaries,
            "inputs": self.files, "warnings": self.warnings,
            "limitations": [
                "Static reachability is a direct-call overapproximation at function granularity, not path feasibility.",
                "Indirect calls, callbacks and dynamically requested services make non-reachability inconclusive.",
                "Unproven means not established reachable, never proven unreachable.",
                "Runtime call counts are log observations; a call does not prove correct semantics.",
                "IPC no-op identities are lexical candidates unless reviewed with a hash-bound catalog.",
                "C++ conditional branches and registration macros are not fully preprocessed.",
                "Unknown command space, executed basic blocks and total semantic completeness have no denominator.",
            ],
        }


def private_output(path):
    """Refuse a nonignored Git destination; temp dirs outside repositories work."""
    path = Path(path).resolve()
    parent = path
    while not parent.exists():
        parent = parent.parent
    result = subprocess.run(["git", "-C", str(parent), "rev-parse", "--show-toplevel"],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        repo = Path(result.stdout.strip())
        ignored = subprocess.run(["git", "-C", str(repo), "check-ignore", "--quiet", str(path)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if ignored.returncode:
            raise ValueError("report destination must be Git-ignored (contains private game evidence)")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gen", type=Path, required=True)
    p.add_argument("--runtime-source", type=Path, required=True)
    p.add_argument("--analysis", type=Path)
    p.add_argument("--catalog", type=Path)
    p.add_argument("--trace", type=Path, action="append", default=[])
    p.add_argument("--nvn-trace", type=Path, action="append", default=[],
                   help="optional capped NVN argument samples; counted separately from --trace")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        out = private_output(args.out)
        a = Audit()
        if args.analysis:
            a.read_analysis(args.analysis)
        a.read_generated(args.gen)
        a.read_runtime(args.runtime_source)
        if args.catalog:
            a.read_catalog(args.catalog)
        # Duplicate filenames must not double-count the same trace.
        for path in sorted({p.resolve() for p in args.trace}):
            a.read_trace(path)
        for path in sorted({p.resolve() for p in args.nvn_trace}):
            a.read_nvn_trace(path)
        report = a.finish()
        for name, value in (("report.json", report), ("aggregate.json", report["summary"])):
            path = out / name
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
            path.chmod(0o600)
        print(json.dumps(report["summary"], sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        p.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
