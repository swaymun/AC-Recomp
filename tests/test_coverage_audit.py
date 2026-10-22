"""Original synthetic fixtures; no game code, cloud access or native game runs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.coverage_audit import Audit, close_brace, digest, private_output, scrub


SCRIPT = Path(__file__).resolve().parents[1] / "tools/coverage_audit.py"


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gen = self.root / "gen"
        self.module = self.gen / "demo"
        self.module.mkdir(parents=True)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        (self.module / "funcs.h").write_text(
            "void demo_00000010(nx::CPU& c);\n"
            "void demo_00000020(nx::CPU& c);\n"
            "void demo_00000030(nx::CPU& c);\n"
            "void demo_00000040(nx::CPU& c);\n")
        (self.module / "table.cpp").write_text('''
static const nx::FuncEntry funcs[] = {
    {0x10, demo_00000010},
    {0x20, demo_00000020},
    {0x30, demo_00000030},
    {0x40, demo_00000040},
};
static const nx::Symbol symbols[] = {
    {"nnMain", 0x10, 4, 2, 1, 0},
    {"apiNoop", 0x0, 0, 2, 1, 1},
    {"guestFn", 0x20, 4, 2, 1, 0},
    {"guestFn", 0x0, 0, 2, 1, 1},
    {"missingFn", 0x0, 0, 2, 1, 1},
    {"optionalFn", 0x0, 0, 2, 2, 1},
};
static const uint64_t init_array[] = {0x10, 0};
''')
        (self.module / "code_000.cpp").write_text('''
void demo_00000010(nx::CPU& NX_RESTRICT c) {
    demo_00000020(c); // bl #0x20
    nx::svc(c, 0x2, NXB + 0x14ull); // svc #2
    nx::svc(c, 0x7f, NXB + 0x18ull); // svc #127
}
void demo_00000020(nx::CPU& NX_RESTRICT c) {
    nx::unimpl(c, NXB + 0x20ull, "brk"); // brk #1
}
void demo_00000030(nx::CPU& NX_RESTRICT c) {
    nx::unimpl(c, NXB + 0x30ull, "undecodable 0x12345678");
    { nx::call(c, c.x[3]); return; } // br x3
}
''')
        (self.module / "report.txt").write_text(
            "functions 4, handled 8, unhandled 0\n"
            "jump tables 0, unresolved br (indirect tail calls) 1\n")
        (self.runtime / "hle.cpp").write_text('''
void ok(CPU& c) { c.x[0] = 0; }
void byte_swap(CPU& c) { c.x[0] = bswap(uint32_t(c.x[0])); }
void unsupported(CPU&) { fatal("unsupported host capability: %s", hle_current_name()); }
NX_HLE("apiNoop", ok);
NX_HLE("apiByteSwap", byte_swap);
NX_HLE("apiUnsupported", unsupported);
auto make() {
    auto s = std::make_shared<Service>("ITest");
    s->cmds[5] = [](IpcCtx&) { return 0u; };
    s->cmds[6] = [](IpcCtx& c) { c.push<uint32_t>(0); return 0u; };
    return s;
}
''')
        (self.runtime / "kernel.cpp").write_text('''
static void svc_impl(CPU& c, uint32_t imm, uint64_t pc) {
    switch (imm) {
        case 0x02:
        case 0x03:
            break;
        case 0x04: {
            // numeric separators and nested cases must not confuse the parser
            int64_t ns = 2'000'000;
            switch (c.x[0]) { case 0x77: c.x[1] = ns; break; }
            break;
        }
        default: fatal("strict unhandled SVC: %#x", imm);
    }
}
''')
        self.log = self.root / "guest.log"
        self.log.write_text(
            "hle apiNoop\nhle apiNoop\n"
            "svc 0x2 from demo+14\n"
            "ipc: ITest cmd 5\n"
            "nvnDeviceGetProcAddress(0, nvnMissing)\n"
            "hle nvnMissing\n"
            "nvn: first call of nvnMissing (lr demo+10)\n"
            "FATAL: call into the middle of a function: demo+123 (lr demo+30)\n")

    def audit(self, trace=True):
        a = Audit()
        a.read_generated(self.gen)
        a.read_runtime(self.runtime)
        if trace:
            a.read_trace(self.log)
        return a

    def test_traps_are_not_hidden_by_zero_unhandled(self):
        result = self.audit(False).finish()
        gaps = {g["id"]: g for g in result["gaps"]}
        self.assertEqual(result["summary"]["modules"]["demo"]["reported"]["unhandled"], 0)
        self.assertEqual(gaps["trap:demo:20"]["category"], "architectural_trap")
        self.assertEqual(gaps["trap:demo:30"]["category"], "undecodable_trap")
        self.assertEqual(gaps["trap:demo:20"]["reachability"], "static_reachable")
        self.assertEqual(gaps["trap:demo:30"]["reachability"], "unproven")
        self.assertIn("missing-function:demo:40", gaps)

    def test_runtime_beats_static_and_unproven(self):
        result = self.audit().finish()
        groups = [g["reachability"] for g in result["gaps"]]
        rank = {"runtime_hit": 0, "static_reachable": 1, "unproven": 2}
        self.assertEqual([rank[g] for g in groups], sorted(rank[g] for g in groups))
        gaps = {g["id"]: g for g in result["gaps"]}
        self.assertEqual(gaps["hle:apiNoop"]["runtime_hits"], 2)
        self.assertEqual(gaps["hle:nvnMissing"]["runtime_hits"], 1)
        self.assertEqual(gaps["ipc:ITest:5"]["reachability"], "runtime_hit")
        self.assertTrue(any(g["category"] == "unresolved_runtime_dispatch" for g in gaps.values()))
        self.assertNotIn("hle:apiByteSwap", gaps)
        self.assertNotIn("ipc:ITest:6", gaps)

    def test_import_join_distinguishes_hle_guest_weak_missing(self):
        r = self.audit().finish()
        self.assertEqual(r["summary"]["import_resolution"],
                         {"hle": 1, "guest_export": 1, "weak_undefined": 1, "unresolved": 1})
        gap = next(g for g in r["gaps"] if g["id"] == "hle:apiNoop")
        self.assertEqual(gap["import_references"], 1)
        self.assertTrue(any(e["text"] == "apiNoop" for e in gap["evidence"]))

    def test_svc_fallthrough_cases_and_unknown_ids(self):
        a = self.audit()
        self.assertEqual(a.svc_cases, {2, 3, 4})
        gaps = {g["id"]: g for g in a.finish()["gaps"]}
        self.assertEqual(gaps["svc:2"]["category"], "svc_noop")
        self.assertEqual(gaps["svc:3"]["category"], "svc_noop")
        self.assertEqual(gaps["svc:127"]["category"], "svc_missing")
        self.assertEqual(gaps["svc:127"]["reachability"], "static_reachable")

    def test_shared_ipc_setup_joins_both_services_without_scope_bleed(self):
        with (self.runtime / "hle.cpp").open("a") as f:
            f.write('''
std::shared_ptr<Service> irrelevant() { return std::make_shared<Service>("Previous"); }
void setup(Service& s) { s.cmds[17] = [](IpcCtx&) { return 0u; }; }
ServiceRegistrar r_a("a", [] { auto s = std::make_shared<Service>("a"); setup(*s); return s; });
ServiceRegistrar r_b("b", [] { auto s = std::make_shared<Service>("b"); setup(*s); return s; });
''')
        self.log.write_text("ipc: b cmd 17\n")
        gaps = {g["id"]: g for g in self.audit().finish()["gaps"]}
        self.assertNotIn("ipc:Previous:17", gaps)
        self.assertIn("ipc:a:17", gaps)
        self.assertEqual(gaps["ipc:b:17"]["reachability"], "runtime_hit")

    def test_duplicate_function_traps_deduplicated(self):
        path = self.module / "code_000.cpp"
        with path.open("a") as f:
            f.write('''void demo_00000050(nx::CPU& c) {
    nx::unimpl(c, NXB + 0x20ull, "brk"); // shared tail
}
''')
        g = next(g for g in self.audit().finish()["gaps"] if g["id"] == "trap:demo:20")
        self.assertEqual(len(g["functions"]), 2)
        self.assertEqual(g["reachability"], "static_reachable")

    def test_no_lookup_or_profiler_false_hit(self):
        self.log.write_text("nvnDeviceGetProcAddress(0, nvnUncalled)\n"
                            "svc profile: role 1: svc 0x3 from demo+1\n"
                            "random text hle apiNoop\n")
        result = self.audit().finish()
        self.assertEqual(result["summary"]["runtime_observed_unique"],
                         dict.fromkeys(("hle", "ipc", "svc", "trap", "dispatch", "sysreg"), 0))
        self.assertFalse(any(g["id"] == "hle:nvnUncalled" for g in result["gaps"]))

    def test_runtime_fatal_joins_existing_trap(self):
        self.log.write_text("FATAL: unimplemented instruction at demo+30: bad (lr demo+10)\n"
                            "FATAL: strict IPC missing command: service=ITest command=7\n"
                            "FATAL: strict unhandled SVC: 0x7f caller=demo+14\n"
                            "FATAL: strict missing function: absent (lr demo+10)\n")
        gaps = {g["id"]: g for g in self.audit().finish()["gaps"]}
        for key in ("trap:demo:30", "ipc:ITest:7", "svc:127", "hle:absent"):
            self.assertEqual(gaps[key]["reachability"], "runtime_hit")

    def test_manifest_binds_table_and_plt_reachability(self):
        with (self.module / "code_000.cpp").open("a") as f:
            f.write("void demo_00000060(nx::CPU& c) {\n"
                    "    { nx::call(c, c.x[17]); return; } // br x17\n}\n")
        path = self.root / "analysis.json"
        item = {"name": "demo", "table_sha256": digest(self.module / "table.cpp"),
                "roots": [0x60], "plt": {"96": "apiNoop"},
                "decoded_uncovered_ranges": [[0x90, 0x98]], "unresolved_br": [0x34]}
        path.write_text(json.dumps({"schema": 1, "modules": [item]}))
        a = Audit()
        a.read_analysis(path)
        a.read_generated(self.gen)
        a.read_runtime(self.runtime)
        r = a.finish()
        gaps = {g["id"]: g for g in r["gaps"]}
        self.assertEqual(gaps["hle:apiNoop"]["reachability"], "static_reachable")
        self.assertEqual(gaps["unlifted:demo:90"]["instructions"], 2)
        self.assertFalse(any(g.get("function") == "demo:60" and
                             g["category"] == "indirect_tail_dispatch" for g in r["gaps"]))
        (self.module / "table.cpp").write_text("// changed\n")
        with self.assertRaisesRegex(ValueError, "does not match"):
            a.read_generated(self.gen)

    def test_review_catalog_requires_exact_source_and_excerpt(self):
        source = self.runtime / "hle.cpp"
        item = {"id": "ipc:ITest:5", "category": "reviewed_noop", "detail": "Synthetic reviewed command.",
                "source_sha256": digest(source),
                "evidence": {"path": str(source), "line": 10,
                             "text": source.read_text().splitlines()[9]},
                "service": "ITest", "command": 5, "action": "Implement the synthetic contract."}
        path = self.root / "catalog.json"
        path.write_text(json.dumps({"schema": 1, "gaps": [item]}))
        a = self.audit()
        a.read_catalog(path)
        g = next(g for g in a.finish()["gaps"] if g["id"] == item["id"])
        self.assertTrue(g["reviewed"])
        self.assertEqual(g["category"], "reviewed_noop")
        source.write_text(source.read_text() + "// drift\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            a.read_catalog(path)

    def test_cpp_scrubber_handles_literals_comments_and_digit_separators(self):
        text = '{ int n=500\'000; char c=\'}\'; const char* s="}"; /* } */ }'
        mask = scrub(text)
        self.assertEqual(close_brace(mask, 0), len(text) - 1)
        self.assertIn("500'000", mask)

    def test_cli_is_deterministic_and_deduplicates_trace_paths(self):
        out = self.root / "out"
        cmd = [sys.executable, str(SCRIPT), "--gen", str(self.gen),
               "--runtime-source", str(self.runtime), "--trace", str(self.log),
               "--trace", str(self.log), "--out", str(out)]
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        first = (out / "report.json").read_bytes()
        r = json.loads(first)
        self.assertEqual(next(g for g in r["gaps"] if g["id"] == "hle:apiNoop")["runtime_hits"], 2)
        self.assertEqual(json.loads(p.stdout), json.loads((out / "aggregate.json").read_text()))
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(first, (out / "report.json").read_bytes())
        if os.name != "nt":
            self.assertEqual((out / "report.json").stat().st_mode & 0o777, 0o600)

    def test_private_output_refuses_nonignored_git_path(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        with self.assertRaisesRegex(ValueError, "Git-ignored"):
            private_output(self.root / "report")
        (self.root / ".gitignore").write_text(".local/\n")
        private_output(self.root / ".local/report")
        self.assertTrue((self.root / ".local/report").is_dir())

    def test_empty_generated_tree_fails_instead_of_zero_coverage_claim(self):
        with self.assertRaisesRegex(ValueError, "no generated"):
            Audit().read_generated(self.root / "missing")

    def test_missing_direct_dispatch_and_sysreg_fallback(self):
        with (self.module / "code_000.cpp").open("a") as f:
            f.write("void demo_00000070(nx::CPU& c) {\n"
                    " nx::call(c, NXB + 0x999ull);\n"
                    " c.x[0] = nx::mrs(c, 0xdf00);\n"
                    " nx::msr(c, 0xd123, c.x[1]);\n}\n")
        (self.runtime / "main.cpp").write_text(
            "uint64_t mrs(CPU& c, uint32_t sysreg) {\n"
            "switch (sysreg) { case 0xdf00: return 19200000; default: return 0; }\n}\n")
        self.log.write_text("msr 0xd123 = 42 at lr demo+70\n")
        gaps = {g["id"]: g for g in self.audit().finish()["gaps"]}
        self.assertIn("direct-target:demo:999", gaps)
        self.assertNotIn("sysreg:mrs:57088", gaps)
        self.assertEqual(gaps["sysreg:msr:53539"]["reachability"], "runtime_hit")

    def test_dispatch_failure_attaches_to_static_target(self):
        with (self.module / "code_000.cpp").open("a") as f:
            f.write("void demo_00000070(nx::CPU& c) {\n"
                    " nx::call(c, NXB + 0x999ull); // b #0x999\n}\n")
        self.log.write_text("FATAL: call into the middle of a function: demo+999 (lr demo+70)\n")
        r = self.audit().finish()
        g = next(g for g in r["gaps"] if g["id"] == "direct-target:demo:999")
        self.assertEqual(g["reachability"], "runtime_hit")
        self.assertEqual(g["category"], "unresolved_runtime_dispatch")
        self.assertEqual(r["summary"]["runtime_dispatch_failures"], 1)
        self.assertTrue(any(e["path"].endswith("code_000.cpp") for e in g["evidence"]))

    def test_fresh_discovered_entry_missing_from_generated_output(self):
        path = self.root / "analysis.json"
        path.write_text(json.dumps({"schema": 1, "modules": [{
            "name": "demo", "table_sha256": digest(self.module / "table.cpp"),
            "functions": [[0x80, 0x90]], "roots": [0x80],
        }]}))
        a = Audit()
        a.read_analysis(path)
        a.read_generated(self.gen)
        a.read_runtime(self.runtime)
        g = next(g for g in a.finish()["gaps"] if g["id"] == "missing-discovered:demo:80")
        self.assertEqual(g["reachability"], "static_reachable")

    def test_legacy_stubs_and_unsupported_contract_are_observed(self):
        self.log.write_text("ipc: no implementation for service 'absent', using a stub\n"
                            "unhandled svc 0x7f from demo+10 (x0 0 x1 0 x2 0)\n"
                            "FATAL: codec: unsupported request mode 7\n")
        r = self.audit().finish()
        gaps = {g["id"]: g for g in r["gaps"]}
        self.assertEqual(gaps["service:absent"]["reachability"], "runtime_hit")
        self.assertEqual(gaps["svc:127"]["runtime_hits"], 1)
        self.assertTrue(any(g["category"] == "runtime_unsupported_contract" and
                            g["reachability"] == "runtime_hit" for g in r["gaps"]))

    def test_nvn_sidecar_keeps_capped_samples_separate_from_calls(self):
        p = self.root / "nvn_trace.txt"
        p.write_text("# real nvnOnlyLookedUp = demo+10\n"
                     "  1 nvnMissing(0, 0, 0) lr demo+10\n"
                     "  2 nvnMissing(1, 0, 0) lr demo+10\n")
        a = self.audit()
        a.read_nvn_trace(p)
        gaps = {g["id"]: g for g in a.finish()["gaps"]}
        self.assertEqual(gaps["hle:nvnMissing"]["runtime_hits"], 1)
        self.assertEqual(gaps["hle:nvnMissing"]["sampled_fallback_calls"], 2)
        self.assertNotIn("hle:nvnOnlyLookedUp", gaps)

    def test_first_call_in_independent_run_is_not_lost(self):
        second = self.root / "second.log"
        second.write_text("nvn: first call of nvnMissing (lr demo+10)\n")
        a = self.audit()
        a.read_trace(second)
        r = a.finish()
        g = next(g for g in r["gaps"] if g["id"] == "hle:nvnMissing")
        self.assertEqual(g["runtime_hits"], 2)
        self.assertEqual(r["trace_summaries"][str(second.resolve())]["observed_lines"], {"hle": 1})


if __name__ == "__main__":
    unittest.main()
