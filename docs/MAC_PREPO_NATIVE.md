# Isolated cumulative Mac prepo measurement

`tools/run_mac_prepo_native.py` is an original standard-library POSIX runner and
input-copy helper. It incorporates candidate 081's owned-group approach, with
independent synthetic verification. 081 remains failed: its 369 readbacks wrote
to retained data. Historical 078's 79.556-second launch also remains failed.
Neither result nor supervisor is treated as accepted by this integration.

The production `platform_mac.cpp` resolves `NX_DATA_ROOT`. `nvn_debug.cpp` writes
presented readbacks and arbitrary debug textures beneath that root's `frames`.
`nvn_shaders.cpp` reads `spirv/results.tsv` and writes enabled miss dumps beneath
`shader_misses`. `loader.cpp` uses `NX_LOG`, including its `.prev` rotation.
Landed `svc_misc.cpp` saves supported prepo reports beneath `user/prepo`.
Relative diagnostic files use the process working directory. The filesystem
adapter can open mounted assets for writing; canonical asset links therefore
are not assumed immutable for this measurement.

`copy_inputs` copies only explicit analysis, extract and spirv trees into a fresh
run root. It rejects internal input links/special files, existing destinations
and symlink ancestors. Every output starts fresh: data/user, data/frames,
data/shader_misses, trace, cwd, home and tmp. Copies share no file inodes with
canonical inputs. Old user/frame/trace trees and command files are never copied.
`assert_isolated` rejects symlinks, special files and multiply linked files.
This is controlled trusted-runtime isolation, not an OS security sandbox against
malicious concurrent filesystem replacement or an arbitrary executable.

The frozen environment preserves PATH alone and replaces HOME/TMPDIR/XDG cache
paths. All inherited NX capture/trace/debug settings, Vulkan overrides and dynamic
loader injection variables are discarded. Intended NX settings are explicit:
trace, real NVN, presented readbacks every frame, shader miss capture, program and
pipeline trace, verified format profile and loader. Presence-based debug options
are omitted rather than assigned zero. No arbitrary texture override is enabled.

The CLI requires an already prepared isolated root, loader and profile:

```sh
python3 tools/run_mac_prepo_native.py --run-root PRIVATE_FRESH_ROOT \
  --loader VERIFIED_DYLIB --profile VERIFIED_PROFILE \
  --evidence PRIVATE_FRESH_ROOT/guest -- /absolute/path/to/astral
```

The guest allowance is at most 40 seconds, with a whole-supervisor bound of at
most 60 seconds. Session mode (`--session`), for play sessions that must outlast
cutscenes, allows at most 600 guest seconds and 630 seconds overall
(the CLI sets total = guest + 30), with the same owned-group supervision,
cleanup and reserve. Astral's first opening cutscene runs about 300 s and cannot
be skipped. Every presented frame is dumped by default (about 4.3 MB each at
30 fps, about 77 GB for a full 600 s session), so long sessions should sample
with `--dump-frames N` (every Nth presented frame, 1..600) and check free disk
space first. TERM and KILL graces are finite, and inventory calls have their
own timeout. The process starts in an owned session/group; only that group is
signalled, including descendants left after leader exit. Observed group escapes must also be absent before cleanup can be verified;
unavailable inventories reject verification. On macOS a guest that exits before the session check reports ESRCH from
getpgid/getsid while still unreaped; the runner then requires the zombie's
process-table row to show it leads its own group, and reaps the leader before
group signalling. A `ps` that exceeds its one-second timeout is retried, at most three attempts
and only while the whole-run bound keeps its reserve; the receipt counts
`inventory_timeouts`, and exhausted retries or any other inventory failure still
refuse certification. Retries keep a 4 s reserve of the total bound. Opt-in `ACS_TEST_EVIDENCE_DIR` retains a failed CLI fixture's
captured output, inner receipt/logs and process table. The program must not
daemonize. A sampled process table cannot prove ownership of an unobserved child
that immediately detaches; the native runtime and compiler are trusted not to do
that. Build mode separately permits at most 900 seconds total, reserved cleanup,
and the integration invokes CMake with exactly two jobs. No clean rebuild runs.
Receipts retain command, cwd, monotonic elapsed time, status/signal, signals sent,
observed owned PIDs and final group absence. Control success is distinct from
application success, rendering, displayed frames and gameplay.

Synthetic verification uses fake Python executables and temporary input trees,
including real fork/session and temporary Git integration. It exercises hostile
inherited capture settings, old links, canonical-write sentinels, fresh second
runs, hardlinks, timeout escalation, leftover descendants, an unrelated process,
observed escape, failed inventories and bounded fake compiler execution. Tests
never launch the game or use credentials/cloud capacity.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_mac_prepo_native.py -v
git diff --check main HEAD
```

Actual measured results from the single authorized integration follow below.
Independent Astra/medium exact-head patch/result review is mandatory before the
parent's guarded landing; this worker does not land or spawn a reviewer.

## Measured 086 integration

The assigned base and landed 083 are
`e2294d0f5c395844ba1f82aeae7bcf067fcfe0d7`, independently reviewed by
Astra/medium run `b45a9912c5434a1b8fe6a05bb51f10db` and guarded-landed before
this work. Parent V5 readiness arrived before input freeze. V5 receipt SHA256 is
`fd94350b43d4cbbc776f10c7c32cd1714f19f4436b29d31c0272f187b8a9c61c`;
1,207 offline-ready products are distinct from actual consumption. The requested
V4 receipt identity was also checked. All V5 products, merged TSV, batch
preflights and production parser identities were verified. Loader receipt and
explicit SDL library matched the brief's exact hashes.

Private `.local/mac-prepo-native-086/` retains source/config/binary snapshots,
old receipts, input freeze, all commands and measured receipts. Before applying
083, the current cumulative source/config/binary matched the retained 078 final
identities. Independent composition of upstream `svc_misc.cpp` with landed
bootstrap/APM and then prepo matched the stable source exactly. Only prepo was
applied to native-current; other selected sources stayed unchanged. Every
compile command retained strict and Apple high-memory flags.

The incremental two-job build compiled `svc_misc.cpp` and linked successfully:
4.270 seconds outer supervisor, exit 0. The prior executable SHA256
`dd69e7e2a407c20ab424dfcf8b59446cc3bbd958f6f270f0684afda6ad0ddb1a`
was preserved; new executable SHA256 is
`d6959ca7d93c940e798786314cbdf29311e3d1391c3af967acc5b198321f64ca`.
There was no clean rebuild or second build.

The first build cleanup receipt conservatively failed because compiler children
used separate groups, despite having exited. That original receipt is retained
unchanged. An additional inventory verified **every observed PID absent at
39.901 seconds from build start**, within the 900-second bound, before guest
launch. This is disclosed control reconciliation, not a claim the original
control passed. LLDB similarly used separate groups: original probe receipts
remain control-failed, with all observed PIDs separately confirmed absent within
55.718 and 39.612 seconds from their respective metadata start times. These
checks preceded further native execution. No outside group was signalled.

The one normal guest run reached its 40-second deadline and received TERM,
returning 0 during orderly shutdown. Supervisor/outer durations were
40.574/40.574 seconds, within 60; cleanup passed with no remaining group members,
no observed escapes and no errors. This exit is **not application completion**.
The two optional LLDB probes took 24.104 and 23.777 seconds of supervision and
explicitly killed their inferiors. Probe one captured a bind then stopped at an
optimized cold helper with an invalid context register; probe two used only the
actual function entry. No further build, guest run or debugger probe occurred.

The native run used fresh full copies of 9,912 files (10,369,558,046 bytes), with
no symlinks or hardlinks into canonical data. Post-run canonical content hashes,
sizes, mtimes, device and inode identities all matched. None of the copied input
files changed; 1,023 new run files were recorded, including fresh frame/miss/report
outputs. Separate debugger roots were also fully copied and passed isolation
checks. Earlier failed evidence was never changed.

Observed separately:

- Vulkan 1.3 on Apple M5 Pro, a Metal-compatible surface and a 2560x1440,
  three-image blitted swapchain were created.
- The production reader loaded 1,207 TSV records. The run requested 1,287 unique
  shader hashes, consumed/reflected 1,206 and missed 81. Offline completeness,
  compute coverage and semantic shader correctness remain unknown.
- The last emitted draw summary had 55,076 attempted draws: 0 done, 232 with no
  program and 54,844 with no vertex shader. No graphics pipeline creation/link
  success was logged. Later attempts beyond that periodic summary are not
  reconstructed into a total.
- Actual `prepo:u` command 10103 executed twice, with authenticated PID 1. Both
  local records have complete original host framing and payload lengths 15 and
  10 bytes (files 88 and 87 bytes). This proves local persistence, not delivery.
  No fatal line occurred before timeout; absence of a later service failure
  within this window does not prove service completeness.
- There were 854 presented readbacks. 853 are byte-black; frame 1 is a uniform
  RGB(20,20,26) clear. Visual inspection of converted frames 1 and 5 corroborates
  blank output. No genuine game frame or gameplay was verified, so no first-game-
  frame notification was emitted. A present count is not displayed game content.

## Exact successor

The second probe recorded 16 function-entry observations on one actual command
buffer. It alternated separately loaded vertex-only programs with mask `0x1`
and fragment-only programs with mask `0x2`, and also observed compute mask
`0x20`. Program-to-shader trace correlation proves those first two stage roles.
Production `nvn_state.cpp::BindProgram` records the mask, but
`nvn_draw_state.cpp::apply` handles BindProgram with only `s.program = c.a[0]`.
`nvn_draw.cpp::draw` then searches that single program for a vertex stage.
A fragment-only bind therefore replaces the separately bound vertex stage.
Together with actual zero-draw telemetry, this establishes a concrete next
stage-binding defect; the remaining missing shaders are a separate limitation.

A narrow successor should implement per-stage program binding in a new original
runtime overlay, with production replay/draw-selection regressions for vertex
then fragment, mixed/cleared masks, compute separation and command-buffer state
replay. Inspect `nvn_draw_state.h/.cpp`, `nvn_state.cpp`, `nvn_draw.cpp` and all
other consumers of `State::program` before fixing; combined-stage callers must
remain covered. Then independent review/landing and a separately authorized
cumulative native measurement are required. This unit changes no runtime defect.

Final runner improvements retain historical escapes as evidence but certify
cleanup only when **all observed PIDs** and group members are absent; live escapes
and failed inventories still fail. A dedicated retired-escape subprocess test
covers this distinction. Inventory timeout is finite at one second. Early
fixture iterations exposed macOS `/var` symlink aliases and overly short timing
assumptions, and the initial half-second inventory timeout failed closed under
load; those outputs remain private. Final tests use resolved temporary roots and
bounded scheduling allowances. Native measurements preceded these final
conservative runner refinements; the supervisor algorithm and measured private
scripts/identities are retained, and native execution was not repeated for them.

Mac remains partial. Linux remains partial at
`a3a1951d61785f2395e3441e6c46fa0a835160b6`; Windows remains blocked at
`ab9a8d672db64a88e1c120ad019b8094c24d8abe`. iPhone simulator and iPad simulator
remain separately partial at `1ac6acb1d2d27ff59698d06c2d60c28f036a23e8`, tested
26.5 / minimum 26.0, physical devices unverified. Semantic correctness is unknown
beyond measured checks; cross-ISA byte match is N/A. No provider, transfer,
credential, install, remote/mobile, paid inference or landing action occurred.
