# Static recompilation and HLE coverage audit

Unit **COVERAGE-008**, October 20, 2026. This audits static ARM64-to-C++
recompilation and host emulation; it does not measure decompilation progress.
Only methodology and aggregate measurements belong in this document. Detailed
addresses, imported symbols, generated-source excerpts, traces, frames and
ranked findings remain in ignored `.local/units/COVERAGE-008/`.

## Method

`tools/coverage_audit.py` uses the Python standard library. It reads:

1. Generated `funcs.h`, `table.cpp`, `code_*.cpp` and `report.txt` for each module.
   It compares declared, dispatch-listed and emitted functions, inventories actual
   trap sites, local branch labels, fixed dispatch targets, indirect tails,
   jump-table fallback emissions, SVCs, system-register accesses and instruction
   no-ops. Multiple emitted copies of one trap address count as one site.
2. An optional, private analysis manifest from the **same lifter and inputs**.
   Its generated-table hashes must match. This adds function ranges, PLT links,
   boot roots, uncovered text and precise unresolved-branch addresses. Generated
   branch evidence joins those addresses instead of counting each twice.
3. Runtime source, including HLE registrations, small fixed-result/unsupported
   handlers, literal IPC success-only lambdas and the top-level kernel SVC
   switch. These are candidates, not a full C++ semantic analysis. Nested switch
   cases are excluded from the SVC inventory.
4. Runtime traces: actual HLE, SVC and IPC calls; NVN first-call fallback
   witnesses; missing imports/services/commands; instruction traps; and failed
   dispatch. Lookup requests and profiler summaries are not calls. A fallback
   first-call witness does not add a second hit to the matching HLE call in
   that execution; a witness in an independent execution still contributes.
5. Optional reviewed semantic findings in a private catalog. Every catalog
   source excerpt has a line number and an exact source SHA-256 check.

The tool joins imports with HLE registrations and cross-module exports, with
undefined weak imports separate from missing strong imports. Counts describe
symbol-table entries, not relocation counts or the number of implemented APIs.
An import is not, by itself, proof that the game calls it.

Ranking is **observed at runtime**, then **reachable through the static
direct-call graph**, then **unproven**. Within each tier, reviewed severity,
observed call count, import references and stable IDs break ties. Boot roots,
constructors, direct calls and resolved PLT links seed the graph. Reachability
is at function granularity and overapproximates feasible paths. Indirect
calls/callbacks make graph absence inconclusive: the tool never relabels that
absence as “proven unreachable.”

Synthetic continuations after the end of a lifted range are reported separately
from missing explicit branch targets. A continuation following a nonreturning
error handler can legitimately never execute even though its containing
function is reachable. Unresolved indirect tails are ordinary runtime dispatch
candidates until an actual failed-dispatch trace establishes a failure.

### Run

```sh
python3 tools/coverage_audit.py \
  --gen "$PRIVATE_GENERATED" \
  --runtime-source "$PRIVATE_RUNTIME/src" \
  --analysis "$PRIVATE/analysis.json" \
  --catalog "$PRIVATE/catalog.json" \
  --trace "$PRIVATE/route/guest.log" \
  --nvn-trace "$PRIVATE/route/data/nvn_trace.txt" \
  --out "$PRIVATE/audit"
```

`--analysis`, `--catalog`, and `--trace` are optional; repeat `--trace` for
independent logs. Duplicate paths are read once. Use one log per execution:
copied or overlapping logs from the same execution would inflate counts.
The optional `--nvn-trace` sidecar contains capped fallback argument samples.
These appear as `sampled_fallback_calls`, separate from general call
observations; they are never added to the corresponding HLE count. Ranking
uses the larger lower bound. Procedure-lookup lines in the sidecar are ignored.
The output is `report.json` (ranked private evidence and input hashes) and
`aggregate.json` (counts). Files are mode 0600; destinations inside a Git
repository must be ignored. **Do not commit the detailed report.**

The optional analysis format is `{"schema":1,"modules":[...]}`. Each module
provides `name`, `table_sha256`, `functions` as `[start,end)` byte offsets,
`roots`, decimal-string-keyed `plt`, `unresolved_br`, and `jump_tables`.
Coverage fields are `text_bytes`, `decoded_instructions`,
`function_ranges`, `uncovered_text_bytes`, `undecoded_uncovered_bytes`,
`decoded_uncovered_ranges`, `decoded_uncovered_mnemonics`,
`padding_uncovered_ranges`, and `nonpadding_uncovered_ranges`.
The retained private exporter imports the owner's pinned `recomp.nso` and
`recomp.analysis` under its existing dependency environment, with bytecode
writing disabled. It analyzes inputs without regenerating or modifying them.
It unions discovered function ranges, compares them against four-byte text
words and records decoded uncovered ranges. Padding here means decoded
`udf`/`brk`/`nop` words; this label is a classification, not a proof of intent.

The catalog is `{"schema":1,"gaps":[...]}`. Each finding needs `id`, `category`,
`detail`, `source_sha256`, and `evidence` with `path`, `line` and an exact line
substring `text`. Optional `symbol`, `service`/`command`, or `svc` fields join
call evidence; `action` and integer `severity` document the proposed next step.
Use IDs matching the report to enrich existing candidates.

## Static measurements

The owner build was inspected read-only; copies of the executable and runtime
sources, writable runtime data, and all audit output are unit-owned. No keys or
owner saves were copied. A fresh application of the branch's macOS patch
series to the pinned upstream source was also compared with the runtime
snapshot. Exact revision and file hashes are private.

| Measurement | Main module | SDK module |
| --- | ---: | ---: |
| Declared / dispatch-listed / emitted functions | 27,763 / 27,763 / 27,763 | 33,573 / 33,573 / 33,573 |
| Lifter-reported handled instructions | 2,569,151 | 1,302,326 |
| Lifter-reported unhandled instructions | 0 | 0 |
| Actual emitted trap sites | 133 | 308 |
| Resolved jump tables | 2,692 | 531 |
| Unresolved indirect tails, excluding PLT | 1,247 | 856 |
| Decoded text words outside discovered function ranges | 44,360 | 36,658 |
| Of those, `udf` / `nop` | 44,175 / 185 | 36,622 / 36 |
| Other decoded instructions outside ranges | 0 | 0 |
| Undecoded bytes outside ranges | 0 | 0 |

The combined **61,336 emitted functions** have no missing declared/listed body.
The **441 trap sites** comprise **56 architectural traps** and **385 undecodable
words**. There are zero caught unsupported-instruction emissions in these
files. The lifter's “unhandled 0” excludes both explicit architectural trap
handlers and its undecodable-word branch, so it must not be used as a count
of emitted traps.

The **81,018 uncovered decoded words** are exclusively padding-like words.
This audit found no ordinary instruction omitted outside the discovered
ranges. It cannot prove the lifter discovered every possible entry point,
correctly modeled every instruction, or resolved all computed control flow.
All **2,103 unresolved indirect tails** retain runtime dispatch; the
**3,223 resolved jump tables** retain a default runtime-dispatch path too.
There are **2,873 unmapped synthetic continuations**, with **zero missing
explicit direct-call/tail targets**. Sampled continuations follow abort calls.
They remain conservative candidates, not confirmed missed executable code.
The generated code also contains **282 no-op instruction emissions** (mostly
prefetch and NOP), and two system-register IDs; both register IDs are handled.

The source inventory recognizes **1,106 HLE registrations**, **48 SVC cases**,
and **60 SVC IDs in generated code**. Fifteen generated SVC IDs have no
recognized implementation; five implemented cases are success-only no-ops
(one of those five has no generated call site). There are **68 small
fixed-result HLE candidates**, **10 explicitly unsupported capability
registrations**, and **11 literal success-only IPC service/command candidates**
(eight handler definitions, including a setup helper shared by two services).
These counts include deliberate host policies and benign acknowledgements;
they are not counts of confirmed defects.

The **333 imported symbol entries** resolve as **72 HLE**, **252 guest exports**,
and **9 undefined weak**; there are **zero unresolved strong imports** in
this inventory. Registered function presence does not establish semantic
implementation. Generic IPC and import strictness also does not cover the
separate NVN tracing fallback.

## Runtime acceptance

The **title → character setup → motorcycle chase** route is covered by a
completed **485.198-second headless execution on the real Mac**, reused from
RENDER-009. This worker independently inspected its frame dumps at the title
prompt, profile editor and two later chase positions. The original process
receipt reports bounded termination and verified cleanup. Selected frames,
the entire log, input configuration, receipt and copy hashes are retained
under the private `reused-route/` directory. This was not a new execution by
COVERAGE-008 and was not a physical controller test.

That route records **16 distinct NVN procedures executing the tracing fallback**.
These are real call witnesses, not just procedure lookups. The route's general
HLE/IPC/SVC tracing was disabled, so each first-call witness is a **lower bound
of one**, not a total call count. Its linker reports **108 HLE resolutions,
22,770 cross-module resolutions and zero unresolved relocations**, a different
denominator from the static symbol-entry inventory. No instruction trap or
unresolved-dispatch fatal was observed in that log.

The five inspected runtime files governing dispatch, IPC, controller/audio
HLE and NVN fallback have identical hashes between the owner source snapshot
and the reused run's source as observed after the run. This does not certify
the entire reused executable's build provenance; its observed binary hash,
source comparison and receipt are recorded separately. Rendering artifacts
remain visible in the chase; route coverage does not mean rendering correctness.

A separate COVERAGE-008 startup execution completed **60.207 seconds** on the
real Mac through `mac-game-lock`, with general HLE/SVC/IPC tracing, headless and
muted settings, isolated data and frame dumps. Its receipt reports controlled
termination, exit code zero, verified cleanup and no remaining descendants.
The five dumped frames end in the opening research-lab movie; this execution
alone does **not** establish chase coverage.

| Startup trace measurement | Observations | Distinct calls |
| --- | ---: | ---: |
| HLE | 5,528,775 | 155 |
| IPC service/command pairs | 91 | 48 |
| SVC IDs | 298,376 | 23 |

None of the fifteen statically missing or five success-only SVC candidates
was observed in this startup trace. Neither execution logged an instruction
trap or unresolved-dispatch fatal. This is bounded route evidence, not a
guarantee that those paths cannot execute elsewhere. Verbose tracing affects
performance; these runs are not performance measurements.

The merged report contains **5,542 candidate records**: **35 observed at
runtime**, **10 additional statically reachable**, and **5,497 unproven**.
The runtime tier comprises **16 NVN fallbacks**, **17 fixed-result/no-op HLE
handlers**, and **two success-only IPC commands**. These include deliberate
host adaptations and initialization acknowledgements, so 35 is not a confirmed
defect count. Across both logs, the union is **158 distinct HLE calls**, **48
IPC pairs**, and **23 SVC IDs**. The chase sidecar adds **388 capped argument
samples**, kept separate from general call counts.

The authoritative private artifacts are `audit-final/report.json`,
`audit-final/aggregate.json`, and `TOP_10_PRIVATE.md`. The ranked top ten
include exact source and trace evidence plus a concrete validation or
implementation action. `route-01/` retains this worker's startup evidence;
`reused-route/` retains the independently inspected full-route evidence.
After rebasing, a fresh application of the macOS patch series still supplied
no explicit HLE registration for any of the sixteen observed fallback methods.

## Verification and limits

```sh
python3 -m unittest discover -s tests -p 'test_coverage_audit.py'
```

All **20 tests passed**. Tests use original synthetic C++/trace/manifest fixtures and real CLI/Git
subprocesses in temporary directories. They cover trap accounting independent
of the lifter counter, import resolution, shared-site deduplication, static and
runtime ranking, missing dispatch, nested SVC switches, numeric separators,
system-register fallbacks, exact catalog provenance, deterministic output,
duplicate trace paths, independent-execution first-call accounting, separate
capped sample counts and refusal to write private reports to nonignored Git
paths. They do not execute game code or contact cloud resources.

There is no exhaustive IPC-command denominator, executed-basic-block coverage,
or semantic correctness percentage. The source scan does not fully preprocess
C++ conditionals or expand arbitrary registration macros. Hashes identify the
files inspected; they do not independently prove that a historical executable
was built from every matching source byte. Frame inspection is separate from
trace evidence. Mac headless execution cannot establish real audio-device
timing, physical controller behavior, Windows behavior or late-game coverage.

Independent review of the committed head belongs to the parent orchestrator;
no nested review is run or silently waived in this unit.
