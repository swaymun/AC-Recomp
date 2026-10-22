# Windows performance investigation

Current decision: [WIN-GATE-034](#win-gate-034-practical-gate-failed-defaults-remain-opt-in)
failed ordinary stability; the eight switches remain opt-in.

WIN-PERF-020 follows the shared-VM WIN-PERF-017 attempt. Its goal is a dynamic-FPS
build capped at 60 fps at the title, an in-engine cutscene and the File 01 highway
chase. A successful build or a 60 fps title alone does not pass that gate.
Private evidence belongs under `.local/units/WIN-PERF-020/` on the Mac and
`C:\acr\units\WIN-PERF-020\` on Windows. Game inputs, lifted code, shader binaries,
saves, executables, maps, profiles and recordings stay outside Git.

## Overlay and integration

`astral-windows-perf.patch` is enabled after `astral-windows-desktop.patch` in
`series.windows`. Linux and macOS do not include it. Its Windows Astral changes
are:

- Stop SDL gamepad/joystick polling after the launcher returns Play. Gameplay
  uses the native XInput path; SDL video/events and keyboard mappings remain
  initialized. `NX_WIN_KEEP_SDL_GAMEPAD=1` retains the old lifetime for same-binary
  diagnosis (a presence switch, so `0` also retains it).
- Compare eight GPU write-back words at once with AVX2 and mask-store only changed
  32-bit lanes. Unchanged destination words retain concurrent guest CPU writes.
  The original 8-byte prefix and byte tail handle the remainder. Missing or short
  snapshots and `NX_WRITE_BACK_WHOLE` retain the existing full-copy fallback.
- Read actual thread CPU time using `GetThreadTimes`, summing kernel and user
  FILETIME counters and converting 100 ns units to ns. Windows previously
  reported zero CPU use in these runtime counters.
- Enable the existing opt-in `NX_FRAME_LOG` present-interval log on Windows,
  including the headless path. This does not activate Apple pipeline prewarming.

The vector loop additionally requires `NX_ASTRAL_STRICT`, `_WIN32` and `_M_X64`.
Windows already builds with `/arch:AVX2`; there is no added CPU requirement.
`NX_WIN_SCALAR_WRITEBACK=1` selects the original loop in the same executable for
A/B measurements. This is a presence switch: `0` also selects scalar behavior.
A whole-range copy or a load/blend/store of destination bytes would violate the
changed-word contract and is not an equivalent optimization.

## Build and measurement method

The baseline is repository main `8310017` with the pinned runtime
`010ed7a596a621c15d3a8dfa5795ca8c3668b066` and the complete Windows patch series
before this overlay. Baseline and candidate share private interval diagnostics,
the verified imported control-context header, and identical generated code.
The separate private generation tree copies `gen-dynamic-carry/main` and the
unmodified SDK tree. Both builds explicitly use:

```text
-DNX_GAME=astral
-DNX_GEN_DIR=C:/acr/units/WIN-PERF-020/gen
-DNX_MAIN_VARIANT_LIST=
-DNX_ASTRAL_FPS_MODE=dynamic-60-cap
```

This is the dynamic 60-cap build with the optional scene-boundary carry lift,
not the legacy five-site 60 fps sibling. See [ASTRAL_HIGH_FPS.md](ASTRAL_HIGH_FPS.md).
Private cut/timer observers are identical in both variants. Their source/input
hashes, generated archive hashes, compiler commands, link maps and executable
SHA-256 receipts establish what was actually tested. The native receipts are
`build-receipt.json` and `build-sdl-receipt.json` in the private unit root; the
recorded main/SDK library hashes match across all variants. These are measurement
inputs, not distributed game code. The branch is rebased onto `bf4d060`;
`main` advanced from baseline `8310017` to that commit only in documentation.

The recreated Windows Server 2025 VM reports a Xeon at a nominal 2.20 GHz,
four cores/eight logical processors, 32 GB RAM, NVIDIA L4, driver 596.86 and
Vulkan 1.4.329. Its RTX Virtual Workstation license is permanent and active.
The nominal clock is not a measurement of effective single-thread frequency.
The lead later allowed short fidelity-unit runs on the same VM. Both units use
a shared exclusive game lease; the lead requires 60 seconds between own runs so
the other unit can acquire it. No peer game is killed. Before each launch this
runner requires no `astral*` process and 15 sustained seconds below 15% total
CPU and 10% GPU load. It records process paths continuously and stops only its
own game if another game appears. Accepted ROI context uses complete two-second
watchdog buckets within the ROI, subtracting owned game CPU from system CPU.
Adjacent activity remains in the raw log; it is not folded into the ROI.

Windowed runs use the existing admin console session, a 1920×1080 desktop and
`run_interactive.ps1`; XAudio2 feeds VB-Cable. Headless runs use the runtime's
timer audio fallback and do not establish device A/V sync. The scripted ViGEm
XInput pad uses the default Nintendo positional layout: Xbox B is game A/confirm,
and Xbox A is game B/cancel. JSON-lines pad commands, the runtime input recorder
and the `NX_INPUT_SCRIPT` configuration are retained with each run. The recorder
runs before automatic script events are appended, so it records physical pad
input, not an independent observation of every scripted event. Scene captures
confirm the route's visible transitions. Saves are private to the unit; the owner
installation is read-only.

`NX_FRAME_LOG=1` records individual present timestamps and intervals. CPU-only
sampler windows read `GetThreadTimes` without suspending threads, and their exact
start/end QPC timestamps select the matching frame and GPU samples. FPS is
`1000 / mean(interval_ms)`. The **1% low** is `1000 / mean(slowest ceil(N/100)
intervals)`; p99 frame time is reported separately. Runtime replay, encode,
fence wait, other-submit, present and upload counters use complete 60-frame
buckets inside each window. Present is a separate stage and is not added twice.

The instruction sampler briefly suspends each owned thread, reads its PC and
immediately resumes it. Those samples are resolved against the exact executable's
link map and the VM's DLL export RVAs. Instruction sampling is outside the accepted
FPS windows because suspension perturbs timing. PC percentages are wall samples,
not a second measurement of CPU utilization. `nvidia-smi dmon` supplies GPU load,
power and clocks. For WIN-PERF-020's synchronous path, the existing async GPU timestamp
counter must not be interpreted as measured GPU execution time. The resident
overlay later adds separately queried synchronous timestamps, described below.

On-demand frame dumps confirm scene identity and support baseline/candidate visual
comparison. Captures and their adjacent stalls are outside the timing windows.
Separate console NVENC/WASAPI recordings check picture and device audio. An eight-
second synthetic preflight produced 1920×1080/15 fps/120 frames and eight seconds
of 48 kHz stereo float loopback, mean −21.1 dBFS and peak −18.1 dBFS. Its inspected
frame shows the console desktop; it is capture-path evidence, not game rendering
or game synchronization evidence. `vulkaninfo --summary` independently exited 0
and enumerated the L4. Setup's initial Vulkan failure was a PowerShell native-
stderr loader-warning handling issue; the raw successful summary is retained.

## Results and acceptance

**60 fps is not achieved.** The profiles identify remaining serialized CPU buffer
preparation, write-back/retirement and waits. This is a measured limit of the
current runtime on this VM, not proof that the VM hardware is the only possible
cause. Full visual/A/V and independent-review gates remain open.

Private inputs became ready at 17:15:47Z. The first native baseline build took
457.929 seconds (406 steps); subsequent overlay rebuilds changed only runtime
objects. No measurements from the previous contended VM are substituted here.
Actual baseline scene windows have been collected; candidate results follow
below. Each is a single accepted ROI; small differences are point estimates,
not confidence intervals. The game-free overlay tests execute scalar/AVX2 production functions on
5,248
randomized size/alignment cases per run, read-only unchanged destinations,
no-access guard pages, tails and snapshot fallbacks. Full Windows-series
application is tested against a private pinned upstream clone. A supplemental
native Windows SDL fixture checks the actual helper with absent/`1`/`0` escape
values, joystick dependency release, retained video/events and keyboard mapping.
These fixture results are separate from gameplay acceptance.

### Baseline (windowed with XAudio2 / VB-Cable)

The original baseline executable is SHA-256
`bc97e95a2e2fb7d547972c5d2efbc165833a9069b13b0836ccfef6f463bcabb6`.
The fresh-game route and observed inputs are under private `runs/cold-A/`.
The opening lab is an in-engine cutscene: captures show the NPCs and the renderer
records draws and compute dispatches. The chase capture shows the police bike,
truck enemies and shooting tutorial, rather than a menu or prerecorded video.

| Scene / CPU-only ROI | Frames | Average fps | 1% low fps | p99 ms | Replay / encode / fence / other / present ms | Upload MB/frame | GPU SM / memory utilization |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |
| Title, 20 s | 845 | 42.288 | 25.724 | 36.077 | 7.022 / 0.078 / 4.326 / 2.822 / 2.534 | 11.892 | 28.25% / 7.35% |
| Opening lab cutscene, 15 s | 320 | 21.441 | 17.918 | 53.442 | 13.883 / 0.100 / 6.528 / 2.895 / 1.825 | 28.063 | 19.33% / 1.00% |
| File 01 chase, 20 s | 260 | 13.058 | 11.023 | 85.792 | 31.800 / 0.130 / 16.355 / 9.470 / 2.690 | 61.248 | 22.85% / 10.20% |

GPU SM clocks averaged 210 MHz in these windows; memory was 405 MHz at title/chase
and 6251 MHz in the cutscene. These low-power clock observations do not establish
that the L4 is saturated or that a faster GPU is needed. No global driver/power
setting was changed. Complete in-window background CPU buckets peaked at 5.14%,
3.59% and 9.11% respectively; only the owned game was present. The adjacent chase
log contains a 15.21% transient outside the ROI, retained rather than hidden.

| Scene | Unused SDL joystick core busy | Replay/guest-render thread core busy | That thread CPU ms/frame | Next two threads core busy |
| --- | ---: | ---: | ---: | --- |
| Title | 98.82% | 66.87% | 15.81 | 11.64%, 9.45% |
| Cutscene | 98.96% | 79.37% | 37.02 | 9.69%, 9.58% |
| Chase | 98.36% | 69.69% | 53.37 | 17.50%, 15.00% |

The separate chase instruction profile (`chase-baseline-profile.json`) attributes
24.34%/23.90% of the SDL worker's wall samples to acquiring/releasing an SRW lock.
The title sample was also resolved using the official matching SDL PDB to
`SDL_LockMutex_srw`. Native gameplay polls XInput directly; this launcher-only
worker is unnecessary once Play returns. This is measured software overhead, not
proof of an unavoidable VM limit.

The chase replay/guest-render thread profile spends 21.74% of wall samples in
`NtWaitForMultipleObjects`, 7.48% in `NtWaitForAlertByThreadId`, 9.60% in
`apply_write_back`, and 11.99% at two `memmove` PCs. These samples are not mutually
exclusive stage timers and should not be added to the runtime buckets. They
support testing the SIMD merge and reducing memory round trips/serialized waits;
they do not justify replacing the changed-word merge with CPU write-watch.

A separate baseline chase desktop/device capture is 12.000 seconds,
1920×1080, 358 encoded frames (nominal 30 fps capture). The simultaneous 48 kHz
stereo WASAPI recording is 12 seconds, mean −19.2 dBFS, peak −3.7 dBFS. This
proves the capture contained device audio; duration/non-silence alone do not
prove lip-sync or absence of cumulative picture/audio drift.

### Candidate, windowed

Candidate SHA-256
`a604adb4903331f4edeadf9387988abc679385b6a648952b8499bb73fdab5a2c`
contains the SIMD merge, real CPU counters, interval logging and launcher-gamepad
shutdown. Generated main/SDK libraries are byte-identical to the baseline. Its
pipeline cache is explicitly seeded from the completed baseline; cold-start
hitch comparisons are consequently not claimed. The accepted title window is
`title-stable`, after a confirmed rendered title and the same two Xbox A
presses as the baseline. The early `title` window overlapping loading and the
first cutscene label at a Nintendo-overlay boundary remain raw, excluded data.

| Scene | Frames / seconds | Average / 1% low fps | p99 ms | Replay / encode / fence / other / present ms | Upload MB | GPU SM / memory utilization | Dominant CPU / CPU ms per frame |
| --- | --- | --- | ---: | --- | ---: | --- | --- |
| Title (`title-stable`) | 886 / 20 | 44.347 / 27.666 | 34.664 | 7.031 / 0.079 / 4.310 / 2.318 / 2.566 | 11.823 | 29.11% / 7.79% | 63.36% / 14.29 |
| Lab (`cutscene-stable`) | 443 / 20 | 22.187 / 17.534 | 50.773 | 14.008 / 0.103 / 6.468 / 2.377 / 1.862 | 27.920 | 19.50% / 1.00% | 75.08% / 33.84 |
| Highway chase (`chase`) | 282 / 20 | 14.124 / 12.393 | 78.865 | 32.035 / 0.135 / 11.168 / 7.760 / 2.038 | 55.373 | 18.90% / 1.00% | 75.00% / 53.10 |

The SDL joystick thread is absent from the native candidate CPU snapshot after
controller hotplug. The title improves 4.87% in this pair, while eliminating nearly
one core of unrelated work. The lab windows are different authored shots, so its
small average difference is not a controlled same-shot speedup claim. Neither
scene holds 60 fps. The lab's dominant thread alone requires 33.84 CPU ms/frame:
60 fps would require at least 2.03× its measured CPU throughput even if every
wait and every other stage were free. This is a conservative necessary bound,
not a prediction for a particular desktop CPU or a claim that source changes
cannot remove the work.

The candidate chase's dominant thread still needs **53.10 CPU ms/frame**. Even
with no waits or other work, 60 fps requires at least **3.19×** its current
per-thread throughput, or removal of 68.6% of that thread's work. Its separate
instruction profile has 16.09% wall samples in `NtWaitForMultipleObjects`,
7.27% in `NtWaitForAlertByThreadId`, 8.05% in changed-word write-back, 14.47%
at two `memmove` PCs and 4.13% in `NtFreeVirtualMemory`. Residency, allocation
reuse and overlap remain substantial software opportunities. A desktop CPU
would need this measured throughput improvement **plus** sufficient GPU/fence
headroom; no untested CPU model is promised to meet it, and GHz ratios alone
are not a valid extrapolation. This is not a hardware-only conclusion.

The actual stored dynamic timer also matters. Complete roughly one-second
observer buckets within baseline/candidate chase ROIs give world-speed ratios
**0.874757 / 0.939342** (`sum(step)/(30*wall_seconds)`), with every bucket
hitting the inherited two-tick maximum. The title and lab are approximately
1.0. As documented in [ASTRAL_HIGH_FPS.md](ASTRAL_HIGH_FPS.md), rendering below
15 fps therefore slows simulation. A 60-cap label does not repair this, and
full chase A/V synchronization is **not passed**. The separate candidate
12-second console clip does contain dispatcher speech at 8.8–11.52 seconds
matching the displayed “Attention … eyewitness reports” subtitle in adjacent
8/10-second frames; this rejects a large offset at that early checkpoint,
not later drift or frame-exact lip-sync.

Title PPMs `cold-A/00961` and `sdl-C/02101` are both 1600×900. RGB mean absolute
error is 1.084/255 over the whole image and 0.069/255 over the background after
excluding the animated bracelet region (x480..1120, y160..760). Animated poses
are different. Lab/chase captures have been inspected for scene identity and
existing artifacts, but a pose-matched visual oracle for all three scenes
remains open; the byte-contract fixture is not a replacement for that gate.

### Opt-in submission overlap experiment

The same candidate was run with `NX_PIPELINED=2` (replay-thread setting unchanged),
using an explicitly recorded fresh-game route and the same warm pipeline cache.
This is an experiment, not an enabled default in this overlay.

| Windowed scene | Average / 1% low fps | Replay / fence / other / present ms | Measured Vulkan GPU busy / span ms | Dominant thread CPU ms/frame |
| --- | --- | --- | --- | ---: |
| Title | 48.258 / 29.010 | 7.234 / 3.523 / 2.365 / 1.491 | 3.723 / 3.773 | 14.39 |
| Lab cutscene | 22.879 / 16.677 | 14.023 / 5.597 / 2.564 / 1.693 | 5.914 / 5.964 | 34.15 |
| Highway chase | 12.782 / 8.702 | 34.257 / 14.517 / 8.247 / 1.800 | 15.183 / 15.240 | 56.11 |

These timestamp results have zero unready query results in accepted buckets.
They distinguish actual GPU execution from CPU waits: the lab still takes roughly
43.71 ms/frame while its GPU work is about 5.91 ms. The runtime's title diagnostics
show 60/60 submits split but 60/60 write-backs deferred until the whole submit,
zero after the first part; the first part contains 89% of replay. Existing overlap
therefore does not remove most serialized work. The chase does not improve in this scene pair, and its CPU service alone is
more than three 60-fps budgets. Scene/clock differences prevent treating this as
an isolated percentage regression, but there is no three-scene 60-fps result.
No default change is justified, especially given the documented native-driver
regressions.

A second chase profile unwound the busiest thread's native stack using
`StackWalk64`, outside all FPS ROIs: **1,729 samples, zero context failures,
1,723 ten-PC stacks** (`chase-pipe-stack-all.json`). It resolves the previously
ambiguous copies and waits to concrete paths:

- 20.24% of wall samples share the stack `vkWaitForFences → wait_fences →
  retire_oldest → frame_submit`.
- 7.00% share `apply_write_back → retire_oldest → frame_submit → gpu_submit`.
- 10.18% at the two leading `memmove` PCs share `written_bind → build_sets →
  dispatch_call → replay_list → gpu_submit`: these copies are bound compute-range
  preparation, not unrelated guest audio or UI work.
- 1.97% share heap release through vector destruction and `retire_oldest`.
- 8.44% share the guest kernel condition-variable/SVC wait path, distinct from
  Vulkan fence waits.

Percentages above describe individual leading stack groups, not exclusive totals
for entire subsystems. The exact executable map and loaded DLL bases were used;
DLL export-nearest names and folded C++ template object labels have their usual
symbolization limits. This supports a follow-up that pools snapshots, tracks
upload generations and keeps GPU results resident with explicit CPU visibility.
It does not support removing synchronization or copying stale unchanged words
for a nominal FPS gain. The SIMD/controller changes and opt-in overlap have not met 60.
Further work requires this larger lifetime/visibility change or a measured faster host.

### Headless comparison

The hidden-window runs explicitly set `NX_HEADLESS=1`, use the same fresh-game
script and cache seed, and log timer-paced audio with no XAudio2 device. The
Vulkan surface may still be created during initialization, but `gpu_present`
returns through `present_headless` before swapchain presentation. The timing
counter named present still includes entry/drain housekeeping; it is not a
measurement of `vkQueuePresentKHR` in these runs. Zero-valued synchronous
`NX_GPU_PROFILE=3` output is unavailable GPU timing, not zero GPU execution.

| Run / scene | FPS / 1% low | p99 ms | Replay / encode / fence / other / present ms | Upload MB | GPU SM / memory % | Render/guest CPU ms/frame |
| --- | --- | ---: | --- | ---: | --- | ---: |
| head-A / title | 47.197 / 29.044 | 32.584 | 6.926 / 0.098 / 4.206 / 2.825 / 1.256 | 11.738 | 19.05 / 0.95 | 15.21 |
| head-A / cutscene | 20.176 / 16.586 | 56.716 | 14.150 / 0.113 / 10.027 / 2.902 / 1.498 | 27.988 | 19.70 / 8.05 | 35.93 |
| head-A / chase | 12.662 / 8.126 | 97.856 | 34.300 / 0.153 / 15.903 / 9.963 / 1.477 | 56.193 | 18.15 / 7.00 | 56.82 |
| head-C / title | 49.636 / 29.802 | 31.795 | 6.834 / 0.094 / 4.184 / 2.302 / 1.218 | 11.666 | 19.70 / 1.00 | 13.36 |
| head-C / cutscene | 20.710 / 17.343 | 53.213 | 14.088 / 0.110 / 10.035 / 2.368 / 1.427 | 27.982 | 20.85 / 8.50 | 34.10 |
| head-C / chase | 13.155 / 8.599 | 92.275 | 33.720 / 0.150 / 15.880 / 7.777 / 1.547 | 56.070 | 18.05 / 7.11 | 52.68 |

The baseline headless SDL worker remains 97.65–99.14% busy on one core.
The CPU service column excludes that unrelated worker and identifies the busiest
remaining guest/render thread. All six headless ROIs pass the same non-game CPU
and single-game checks.
GPU SM/memory clocks stay at 210/405 MHz in all six windows; the candidate
removes the SDL worker. The chase render thread drops from 56.82 to 52.68 CPU
ms/frame, still at least 3.16× the entire 60-fps CPU budget.

### Remaining acceptance work

- **Performance target: FAIL.** No accepted title, lab or chase window holds 60
  fps on this VM. The measured CPU work and serialized memory/retirement paths
  remain; a hardware-only explanation is not established.
- **Correctness: PARTIAL.** Native changed-word, alignment/guard-page and SDL
  lifetime/keyboard tests pass, XInput reaches all three rendered scenes, and
  captures are retained. Pose-matched frame comparison and long device A/V sync
  remain open; sub-15-fps timer slowdown is measured.
- **Integration: PARTIAL.** The full Windows series applies and the actual
  dynamic-60-cap executable builds and runs. The required builder test has an
  out-of-scope exact-list assertion described below.
- **Review: PENDING.** Parent-owned exact-head independent review is required;
  this worker did not start a nested review or silently waive one.

The next implementation unit should address persistent upload generations and
snapshot reuse under explicit CPU/GPU visibility rules, guided by the identified
`written_bind`, deduplication and retirement stacks. Replay-thread overlap,
pose-matched three-scene A/B, device A/V and an actually measured desktop CPU
comparison remain follow-ups. Existing MAILBOX, host-cached memory and timer
settings already apply; toggling them again is not a demonstrated fix.

The required build suite hard-codes the Windows series, so enabling this overlay
requires its series assertion to include the new entry. The Windows integration
suite has the same assertion. Those two test files are outside the original unit
scope. The exact required builder command currently executes 55 tests: 54 pass
and one fails solely on that expected-series assertion. A private minimal diff
is prepared for the lead; scope approval is pending. No independent review is claimed: exact-head review belongs to the parent
under this unit's prohibition on nested reviews.

## Comparison-port findings

Read-only source comparison uses [Puddz/AstralChain-PC](https://github.com/Puddz/AstralChain-PC/tree/d627f49d2fc3469d38cd329aa08eb0de8b9eed83)
at `d627f49d2fc3469d38cd329aa08eb0de8b9eed83` (MIT, game 1.0.1) and
PC-GAP-001's handoff. Its advertised desktop performance is not a measurement on this L4 VM.
The important distinctions are:

| Technique | Current runtime / consequence |
| --- | --- |
| CPU write-watch plus persistent GPU heap/vertex/index caches | Our buffer uploads are reused within a submit. Windows write-watch could reduce later uploads, but it does not identify words changed by GPU compute. It cannot replace changed-word write-back safely. Independent generations are needed for consumers of shared dirty tracking. |
| GPU-resident results and lazy CPU visibility | Our completion path copies and compares bound compute ranges. Persistent residency could remove round trips; it requires explicit CPU-read, alias, lifetime and synchronization handling. |
| Submission overlap and sequence completion | Windows defaults to synchronous replay/submission. Existing pipelining is opt-in and documents native-driver correctness/performance regressions; measure it and compare frames before changing the default. |
| Pipeline recipes and background compilation | SPIR-V is already translated offline. At this checkpoint Windows had a driver pipeline cache and Apple-only recipe prewarm; PC-SHADER-027 below ports the latter. Measure new-pipeline time separately from steady replay. |
| Loading-time texture preparation | Untiling/upload work remains synchronous at first use. Attribute its cost before moving it to background work with retained input lifetimes. |

Both ports already use host threads for guest threads and prefer MAILBOX
presentation. Our Windows series also already selects host-cached coherent upload
memory and high-resolution waitable timers. Re-enabling an existing setting is
not evidence of an optimization. The AVX2 loop is original runtime work inherited
from WIN-PERF-017; no comparison-port code was executed or copied into it.

## WIN-RESIDENT-022: bounded synchronous residency (iteration 1)

The follow-up carries all three WIN-PERF-020 commits and fixes the Windows-series
expectations in both builder/Windows tests. `astral-windows-resident.patch` follows
`astral-windows-perf.patch`. This is a bounded first implementation of P1/P2;
full lazy materialization and asynchronous lifetime changes remain separate work.

`NX_RESIDENT=1` opts into one 256 MiB host-visible, coherent, cached Vulkan arena.
The patch reserves **only the guest heap** with `MEM_WRITE_WATCH` when residency
is requested. A failed reservation, unknown/non-heap range, oversized range,
exhausted arena, failed query/allocation, or asynchronous submission uses the
original upload path. Residency is off unless explicitly requested. It is not a
device-local heap mirror, and it does not enable submission overlap.

One locked Windows owner uses `GetWriteWatch(WRITE_WATCH_FLAG_RESET)` with room
for every queried page, distributes page generations, and never lets one cache
entry consume another entry's dirty state. Each entry remembers independent page
generations. Its snapshot precedes the copy; writes racing that copy therefore
remain dirty for the next harvest. Generation rollover changes an epoch and
forces refresh; epoch exhaustion disables tracking. Commit/decommit and NVN pool
finalization invalidate identities even if Windows clears its write-watch bits.
The per-page and independent-consumer design is informed by Puddz/AstralChain-PC
(MIT), `runtime/nvn_hle.h:241–350` and
`runtime/las/nvn/vulkan/exec.c:2619–2861`; the implementation is original.

Read-only vertex/uniform/storage bindings of at least 4 KB use persistent copies
on dedup misses. Smaller reads retain the original copy path: write-watch query
work outweighed their cheap copies in the initial ablation.
A graphics shader with a nonzero conservative storage-write mask permanently disables
read persistence for that process. The baseline only copies compute storage back;
a graphics write can otherwise change a cached read allocation without a dirty
CPU page. Existing descriptors stay alive and within-submit sharing remains valid;
future read misses fall back. Compute storage keeps its eager changed-word merge.
Index bindings use that same per-submit dedup path only while residency is enabled.
With residency disabled, they retain the original per-draw upload lifetime. Disjoint writable storage
ranges retain their input and original snapshot, refreshing dirty pages of both.
Overlapping/merged ranges and GPU-composed reads retain the original ring path.
Within a submit, a replacement gets a fresh arena stretch so recorded commands
cannot observe later CPU updates. The arena is recycled only at the next
synchronous submit boundary after completion and writeback. Writable padding is
zeroed again on every new binding, because an earlier dispatch could have changed
it. The backing allocation is bounded; snapshots are retained only by bounded
entries or the current submit.

GPU results still undergo the original **eager changed-word merge**, including
WIN-PERF-020's AVX2 path. No CPU page protection, lazy GPU writeback, whole-range
GPU-to-CPU memcpy, completion publication change, or fence removal is introduced.
Read-only cache entries cannot substitute for a GPU-written range within a
submit: `written_read` continues to resolve those bytes first. Async/pipelined
submissions bypass residency altogether.

| Switch | Meaning |
| --- | --- |
| `NX_RESIDENT=0` / unset | Original upload/snapshot/index lifetimes; opt-in telemetry remains. |
| `NX_RESIDENT=1` | Enable eligible synchronous read and writable-storage entries. |
| `NX_WRITE_WATCH=0` | Disable heap write-watch; every resident request falls back. |
| `NX_RESIDENT_READ=0` | Disable persistent read-only bindings. |
| `NX_RESIDENT_MIN_READ=0` | Also cache tiny read-only ranges; default cutoff is 4096 bytes. Parsed once per process. |
| `NX_RESIDENT_STORAGE=0` | Disable persistent writable storage and snapshot reuse. |
| `NX_RESIDENT_LOG=1` | Per-present copied/snapshot bytes, dirty pages, hits/misses/bypasses, scanned/changed writeback bytes, query ns, fence ns and arena occupancy. This is a presence switch. |

`copied` counts buffer input bytes in the dedup/index/written-region paths,
including deduplicated host scratch. It excludes standalone host-scratch uploads,
texture staging and padding zeroing. `snapshot` covers written-region originals;
the optional separate-compute debug path is not fully instrumented for copies.
`dirty_pages` sums OS page reports across harvests;
a page written and harvested again can be counted again. `fence_ns` is the
synchronous wait counter; async timing remains in the existing frame buckets.

GPU timestamps also cover the synchronous path when `NX_GPU_PROFILE=3`: a
reserved query slot is reset at command-buffer begin and read only after the
existing fence. It adds no wait and does not require enabling async merely to
measure GPU busy time. Headline A/B runs use the same instrumentation settings.

### Verification and measurement status

The production tracker/cache fixtures exercise independent consumers, partial
pages, writes racing copying, free/reuse invalidation, rollover, same-submit
copy-on-write, padding, graphics-writer fallback, disabled switches, unknown ranges, async bypass and arena
exhaustion. The cache fixture supplies fake mapped Vulkan memory and does **not**
establish driver correctness. The combined instrumented scalar/AVX2 merge runs
the same 5,248-case randomized and guard-page oracle as the perf overlay. Native
Windows tests additionally execute real write-watch reset and decommit/recommit.
The complete Windows patch series is independently reconstructed from the pinned
upstream reference and compared with the prepared runtime sources.

Gameplay and timing evidence is retained under private
`.local/units/WIN-RESIDENT-022/` and `C:\acr\units\WIN-RESIDENT-022\`.
This remains an **opt-in experimental subset**, not a completed 60-fps or full
correctness gate. Final measured results and gate status follow below.

### Iteration 1 diagnostic A/B results

All runs are windowed `dynamic-60-cap` on the same VM, with identical generated
main/SDK archives and private timer observers. Pre-launch checks require zero
other game processes, the exclusive lease and 15 seconds below 15% background
CPU / 10% GPU. Accepted ROIs require every complete two-second watchdog bucket
to remain at or below 15% **other-process CPU**. Rejected windows remain in the
raw evidence. These are single-run estimates; wall-clock routes can reach
different authored shots and simulation phases, so not every FPS difference is
an isolated same-workload speedup.

The early V1 binary (`2f0bbe67…`) also deduplicated index inputs while residency
was disabled. V2 (`e293f324…`) restored the original disabled index path and
introduced the 4 KB read cutoff. V3 adds the graphics-writer safety fallback.
Do not combine these binaries as one A/B pair.

The six V1 switch runs isolate the dominant input-copy source. Values below are
average / 1% low fps. Lab uses the early 165-second shot, unlike the later
175-second shot in the long runs.

| V1 switch configuration | Title | Early lab | Chase | Acceptance note |
| --- | ---: | ---: | ---: | --- |
| Resident off | 41.098 / 26.682 | 20.061 / 14.681 | 13.144 / 8.031 | All three idle checks pass |
| Full cache, tiny reads included | 57.802 / 31.556 | 24.343 / 18.973 | 17.118 / 10.925 | All three idle checks pass |
| Read persistence off | 59.529 / 31.831 | 24.600 / 18.758 | 18.931 / 11.453 | chase rejected |
| Writable-storage persistence off | 39.773 / 26.902 | 20.762 / 17.467 | 12.759 / 7.542 | All three idle checks pass |
| Write-watch off | 41.010 / 25.717 | 20.193 / 17.153 | 12.410 / 8.586 | All three idle checks pass |
| Resident off + scalar merge + SDL gamepad retained | 39.921 / 26.189 | 19.977 / 15.742 | 13.139 / 5.860 | cutscene rejected |

The rejected storage-only chase had 21.97% other-process CPU; the legacy lab also
exceeded 15%. They are not accepted speedup evidence. Writable-storage/snapshot
reuse accounts for most of the gain: read-only persistence alone leaves the
large copies. `NX_WRITE_WATCH=0` has zero cache hits and restores full copying.
The legacy combined switch is not an independent attribution of SIMD versus SDL;
its SDL joystick thread again consumes approximately one core.

V2's tiny-read ablation (`min0-H`) passes all three idle checks: title
58.679 / 31.273, early lab 24.348 / 19.092, chase 17.097 / 10.776 fps. Chase
write-watch query time is 3.218 ms/frame. The default cutoff's later chase
window needs 0.393 ms/frame. The scenes differ in phase/GPU time, so the query
counter is stronger attribution than their FPS difference.

For the long V2 off/on pair, the lab and chase GPU times closely agree at the
selected ROIs. The on-title window is **rejected** (22.67% other-process CPU).
All other rows below pass the idle check.

| V2 run / scene | Frames | Average / 1% low fps | p50 / p95 / p99 ms | Guest/replay thread CPU ms/frame | GPU busy ms/frame |
| --- | ---: | ---: | --- | ---: | ---: |
| Off / title | 823 | 41.209 / 26.646 | 24.923 / 29.340 / 36.004 | 15.545 | 3.790 |
| Off / cutscene | 358 | 17.967 / 14.708 | 55.378 / 63.996 / 66.141 | 41.004 | 9.578 |
| Off / chase | 249 | 12.469 / 11.250 | 80.003 / 83.475 / 84.450 | 56.136 | 15.403 |
| Off / late route | 261 | 13.108 / 11.166 | 76.178 / 79.799 / 86.770 | 52.447 | 15.773 |
| On / title (rejected) | 1065 | 53.341 / 28.006 | 18.244 / 27.436 / 31.476 | 9.314 | 3.770 |
| On / cutscene | 451 | 22.600 / 15.385 | 44.063 / 57.600 / 60.262 | 27.688 | 9.568 |
| On / chase | 355 | 17.865 / 15.040 | 55.621 / 58.979 / 63.642 | 32.755 | 15.436 |
| On / late route (scene not captured at ROI) | 466 | 23.335 / 18.690 | 42.917 / 45.693 / 48.071 | 26.014 | 10.560 |

The V2 matched chase reduces copied buffer input from 53.976 to 0.724 MB/frame
and snapshots from 33.224 to 0.138 MB/frame. It still scans 33.224 MB/frame for
writeback, merging 0.0577 MB of changed bytes. Its Vulkan busy time stays about
15.4 ms. This removes the measured input-copy bottleneck without removing the
completion/writeback dependency. The remaining 32.755 CPU ms/frame exceeds the
16.667 ms 60-fps budget by 1.97× even before counting freeable waits. Input copies
alone therefore cannot satisfy the overall target; the next iteration needs a
separate, correctness-tested visibility/lifetime design. The on-run's late-route
sample has a different GPU
phase (10.56 versus 15.77 ms), so its larger FPS ratio is not an isolated cache
speedup claim. Its 900- and 970-second captures show an autosave/tutorial overlay
following the chase; the off-run still shows the bike. The late rows are diagnostic
route samples, not a matched chase pair or proof of continuous combat.

The on-chase stack profile attributes about 25.27% of wall samples to a Vulkan /
NVIDIA wait stack and 14.07% to changed-word writeback; 12.01% includes guest
kernel condition-variable waiting. These inclusive stack observations overlap
and are not exclusive CPU timers. The next design step is to narrow or lazily
materialize GPU-written results with explicit CPU-read visibility, then bound
frames in flight. Write-watch identifies CPU writes; it cannot prove that an
unchanged CPU page no longer needs a GPU result. Do not remove the merge/fence
or copy whole GPU ranges over concurrent CPU writes to obtain an apparent gain.

### Final guarded build (V3)

The measured guarded executable is SHA-256
`449e71063e0704e39f1ab12fbcfa68018b49b861c03897e71a7f072db3706664`.
Its resident patch is `1ab0dd81…`; the perf patch is `ee19d268…`.
`build-v3-receipt.json`, `v3-vm-source-verification.json` and
`source-v3-verification.json` in the private unit root record exact hashes.
The VM source matches the committed patches. All 142 non-generated runtime files
also match a fresh reconstruction of the complete Windows series; the private
control-context header separately matches the prior build input. Generated input
file hashes and main/SDK library hashes are unchanged. This is a fresh native
build and gameplay measurement, not a source-only inference from V2.

Both title windows and the lab/chase ROIs pass the idle policy. No graphics-writer
fallback is reported through the measured chase. The 392-second pre-ROI frame
confirms the rear-bike rapid-fire chase/tutorial scene. V2's resident-off rows
above provide the instrumented before data; the V2 off/on pair supplies the
same-binary residency ablation. V3 adds the safety check and is reported separately.

| V3 scene / window | Frames | Average / 1% low fps | p50 / p95 / p99 ms | CPU ms/frame | GPU busy ms/frame | Peak other CPU |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| title | 1080 | 54.045 / 26.423 | 17.921 / 26.925 / 31.969 | 9.410 | 3.817 | 11.04% |
| title-repeat-2 | 1122 | 56.185 / 30.253 | 17.441 / 25.557 / 30.886 | 8.524 | 3.747 | 12.69% |
| cutscene | 457 | 22.936 / 16.678 | 43.946 / 56.726 / 59.607 | 27.691 | 9.570 | 6.69% |
| chase | 351 | 17.593 / 15.349 | 56.556 / 59.588 / 63.464 | 33.570 | 15.408 | 2.83% |
| Late side-view chase | 457 | 22.928 / 18.679 | 43.798 / 46.687 / 48.561 | 26.032 | 10.471 | 5.18% |

The 740-second frame confirms the late side-view bike/truck tutorial scene.
Its lower GPU workload prevents treating it as an isolated speedup over the
resident-off late sample.

Counter means below use decimal MB; the arena column is occupied address space,
not the fixed backing allocation's committed size. Timing counters can cover
slightly different complete-frame/bucket boundaries than the CPU sampler.

| V3 window | Copied / snapshot MB | Dirty page reports | Hits / misses / bypasses | Writeback scanned / changed MB | Query / synchronous fence ms | Arena MB |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| title | 0.039974 / 0.003068 | 2.429 | 4.000 / 0.000 / 152.345 | 10.041084 / 0.000000 | 0.079 / 5.463 | 11.159 |
| title-repeat-2 | 0.039980 / 0.003068 | 2.428 | 4.000 / 0.000 / 152.383 | 10.041084 / 0.000000 | 0.077 / 5.398 | 11.159 |
| cutscene | 0.388927 / 0.003068 | 2.430 | 115.000 / 0.000 / 773.878 | 10.041084 / 0.000000 | 0.293 / 10.834 | 31.604 |
| chase | 0.728108 / 0.137509 | 40.151 | 87.168 / 0.290 / 1369.438 | 33.223594 / 0.057281 | 0.403 / 16.956 | 124.302 |
| Late side-view chase | 0.575892 / 0.114649 | 33.910 | 87.308 / 0.000 / 1059.465 | 33.223506 / 0.037896 | 0.438 / 11.267 | 134.244 |

The final chase input-copy reduction is 98.65% versus V2 resident-off; snapshot
copying falls by 99.59%. This is still **17.593 fps**, not 60. The measured
33.570 CPU ms/frame requires another 2.01× reduction to fit a 16.667 ms budget,
even before accounting for serialized GPU work and waits.

The V3 chase PC profile has 2,845 samples on the busiest guest/replay thread:
30.26% wait-for-multiple-objects, 12.13% alert/condition waiting, 7.77% directly
in changed-word writeback, and 1.16% directly in dedup. A separate 1,744-sample
stack trace attributes its largest stacks to the Vulkan/NVIDIA fence wait
(24.77%), guest-kernel condition-variable blocking (15.02%), and writeback via
`draw_end_submit` (11.07%). These observations use the exact V3 link map;
DLL names use module offsets/nearby exports. They are wall samples and inclusive
call paths, not exclusive CPU-time percentages. Writeback visibility and safe
submission overlap remain the next bottleneck to address.

### Correctness, stability and review gates

**The complete acceptance gate is not passed; the feature stays opt-in.**
The native Windows resident suite passes all six tests; the native perf suite
passes seven tests with only its optional pinned-reference apply check skipped.
The actual SDL lifecycle fixture executes there. Mac checks pass six resident
cases (one native-Windows skip), seven perf cases (Windows SDL skip; an extra
run with the private pinned reference executes series application), 55 builder
cases and eight Windows-overlay cases (two native-Windows skips). The required
three command invocations also pass after rebasing; their plain local perf run
has two skips because its optional default reference path is absent. Source
reconstruction independently verifies the complete V3 Windows series.
A supplemental native probe observes dirty pages after buffered `ReadFile`,
`WriteProcessMemory` and `ReadProcessMemory`; it is evidence for this Windows
write-watch contract, not a proof for every external-memory producer.

The V3 process remains alive until the planned bounded stop at 976.419 seconds.
Its 392-, 600- and 740-second frames show chase/tutorial rendering; its 900- and
970-second frames show an autosave/tutorial overlay after the chase. This does
**not** establish ten minutes of continuous active chase/combat. The same scene
transition appears in V2-on; the resident-off run progresses more slowly.
No fatal/device-loss strings appear in the guest/stderr logs of the four long
runs (excluding the static boot message that unsupported instructions are fatal).
The validation SDK/layer was unavailable and **no validation-layer run passed**.
Ordinary logs cannot substitute for that gate.

Full-size burst dumps finish before the selected FPS windows. V3 clearance is
4.70 seconds at title, 10.26 at lab and 36.17 at chase; the other three long runs
also have positive clearance. Raw timestamps, all source PPMs and the selection
metadata are retained. Pose comparison results are recorded separately below;
scene/pose inspection is required before interpreting pixel error as fidelity.

Memory uses process private bytes, excludes shutdown samples, and compares
complete two-second observations in 400–970 seconds. First/last means cover the
first and last 60 seconds of that interval; MB is decimal.

| Run | Early-chase growth, 400–600 s MB | Peak private MB, 400–970 s | First / last 60 s mean MB | Mean increase MB |
| --- | ---: | ---: | ---: | ---: |
| Original baseline | 116.058 | 8786.964 | 6817.224 / 7442.463 | 625.239 |
| V2 resident off | 123.235 | 8648.663 | 6818.512 / 7433.374 | 614.862 |
| V2 resident on | 80.125 | 9093.755 | 7150.225 / 8638.287 | 1488.062 |
| V3 guarded resident | 93.168 | 8949.858 | 7133.166 / 8632.875 | 1499.708 |

The early chase does not show excess growth over baseline. V3's full-window peak
is 301.195 MB above resident-off, but its late mean grows more while it reaches
a new map/overlay earlier. This trajectory does not establish a leak or satisfy
the requested matched-workload memory gate. The fixed arena and bounded entries
are unit-tested; process growth still needs a longer controlled active-combat
comparison. Capture elapsed time and a bounded cache are not substitutes.

The burst-run device recordings do not pass the coarse A/V sync check in original
baseline, resident-off, V2-on or V3. The 12-second lab recordings contain real 48 kHz stereo WASAPI
loopback and desktop video. In V3, speech advances through the particle-gun/ready
exchange by 9.68 seconds while the eight-second frame still displays the earlier
researcher/chimeric-transformation subtitle. The original and other candidate
clips show a similar ordering mismatch. The capture helper has no shared
video/audio QPC calibration, so no exact lip-sync offset is claimed; the coarse
mismatch remains unresolved. Non-silent audio and world-clock counters alone
cannot pass this gate. Because full-size dumps can disturb dynamic timing,
a separate no-frame-dump recording is needed before assigning the cause; the
clean control results are reported below.

Independent other-model/different-effort review belongs to the parent for the
exact final committed head. No nested review was started and no review or
correctness gate is silently waived. This iteration provides measured opt-in
code and evidence; it is not an approval to enable, land publicly or release it.

### No-frame-dump control and retained comparison evidence

Three additional short runs omit every game frame dump. They retain the same
physical/scripted route, title CPU-only sampling and a 12-second desktop/WASAPI
lab recording. All three title windows pass the idle policy. The V3 off/on rows
are from the exact same `449e7106…` executable.

| No-dump title control | Frames | Average / 1% low fps | p50 / p95 / p99 ms | CPU ms/frame | GPU busy ms/frame |
| --- | ---: | ---: | --- | ---: | ---: |
| original-clean-M | 824 | 41.257 / 25.529 | 24.714 / 29.984 / 36.612 | 16.038 | Unavailable |
| clean-off-K | 827 | 41.436 / 26.418 | 24.644 / 29.120 / 35.642 | 15.460 | 3.784 |
| clean-on-L | 1181 | 59.130 / 32.429 | 16.788 / 23.617 / 27.569 | 7.769 | 3.715 |

The clean V3 title off/on pair copies 10.077992 / 0.039973 MB and snapshots
10.041084 / 0.003068 MB per frame. On has four resident hits/frame and
0.0735 ms query time; both still scan 10.041084 MB/frame for writeback and change
zero bytes. Fence means are 5.342 / 5.379 ms. The no-dump title reaches 59.130
average fps with a 32.429 fps 1% low; it still does not hold 60.

The no-dump recordings retain the coarse subtitle/speech mismatch: at eight
seconds original and V3-off show an earlier prime-core line; V3-on shows the
researcher/chimeric-transformation line, while their recorded speech is already
in the later particle-gun/ready exchange. Speech ends at approximately 8.56,
10.00 and 8.40 seconds respectively. Dumps are therefore not a sufficient
explanation. Capture-start skew versus runtime drift still needs a common-clock
A/V check; these clips do not prove precise lip-sync or pass the A/V gate.

Nearest-pose candidates use fixed captured bursts only. Candidate selection
samples pixels, but `tools/render_compare.py` compares the original complete
1600×900 RGB PPMs without scaling, alignment or masking. Visual inspection gives:

| Before / V3 | Scene | Full-frame MAE / 255 | Before / after wall seconds | Interpretation |
| --- | --- | ---: | --- | --- |
| original-I | title-burst | 0.104906 | 39.180 / 39.201 | same bracelet/room view; tiny dynamic differences. Wall times nearly match. |
| original-I | lab-burst | 0.000000 | 164.610 / 151.714 | nonblank lab actor/camera/subtitle image is pixel-identical. Wall times differ by 12.896 s, so same-timestamp gate remains open. |
| original-I | closeup-burst | 13.056800 | 251.880 / 243.850 | different zoom/animation phase and subtitles; not pose-matched. |
| original-I | chase-burst | 11.337267 | 369.732 / 341.985 | differing camera/road position and subtitle phase; not a full pose match. |
| final-off | title-burst | 0.114105 | 39.952 / 40.897 | visually matching bracelet/room view; slight phase difference. |
| final-off | lab-burst | 15.302534 | 152.544 / 162.818 | different camera/actor framing and subtitle phase; not pose-matched. |
| final-off | closeup-burst | 9.145603 | 253.214 / 244.210 | zoom/pose and subtitle differences; not pose-matched. |
| final-off | chase-burst | 6.346880 | 370.286 / 341.778 | road/camera and subtitle differences; not pose-matched. |

The zero-error lab pair is a real actor/camera image, not a black/fade match.
However, the wall-time shift and unmatched close-up/chase views leave the full
same-timestamp pose gate open. Use a common save and game-time/camera phase for
follow-up controls. Similar appearance or a nearest-pixel score alone does not
prove absence of a cache regression. Timer observers report approximately 1.0
world-time ratio in V3's accepted windows; that is not physical A/V proof.

All evidence remains in private `.local/units/WIN-RESIDENT-022/` on the Mac:
`measurements-all.json`, `measurements-clean-av.json`, `gate-analysis.json`,
`world-ratios-all.json`, `pose-pairs/*/report.json`, `av-checks/`, native test
logs and build/source receipts. `evidence.zip` contains 3,315 verified files,
13,817,820,178 uncompressed bytes; its 5,781,350,047-byte ZIP has SHA-256
`3e1bf72a587940c5086d20e340f521cf797509c0537a1c29f6d54650573dd51e`.
The clean A/V supplement contains 120 verified files, 201,091,216 uncompressed
bytes; its 111,892,668-byte ZIP has SHA-256
`2e08b87bde6870785a24bf2c87d1925d276ee2de9cd26287ff6cc1f0d3fffb7f`.
Both manifests and every extracted file hash match. Windows originals remain
under `C:\acr\units\WIN-RESIDENT-022\`; no game-derived evidence enters Git.

This is a measured first subset, with **60 fps, full pose/A/V, continuous active
combat, matched memory growth and validation-layer acceptance still open**.
The next iteration must preserve ordered changed-word visibility while narrowing
GPU-result materialization, then reassess bounded overlap and remaining CPU work.
The pending independent review must assess this exact head before landing.

## WIN-RESIDENT-023: changed-block materialization and bounded overlap (iteration 2)

`astral-windows-writeback.patch` follows the resident overlay in `series.windows`.
All new optimization switches default **off**. Residency still requires its own
`NX_RESIDENT=1` switch. This is an opt-in measured subset; it does not establish
60 fps or close the iteration 1 visual, audio or sustained-combat gates.

### Materialization and lifetime policy

`NX_NARROW_WRITEBACK=1` retains a second, GPU-readable original snapshot for
eligible disjoint resident storage ranges. The snapshot and result occupy the
same bounded 256 MiB arena; this reduces its effective cache capacity rather
than adding an unbounded allocation. CPU-dirty pages refresh both snapshots
from the actual uploaded input. Same-submit replacements get fresh allocations.
Merged, overlapping, separate, small, missing-snapshot and exhausted allocations
retain the original eager CPU scan.

An original compute shader compares complete words against that snapshot and
writes one flag per 4 KB block. Its full GLSL source and compiled SPIR-V are in
the patch. A shader-write-to-host-read barrier and the owning submission fence
precede CPU access to flags. Only flagged blocks undergo the existing changed
32-bit-word merge; unchanged guest words keep concurrent CPU writes. Partial
final words always undergo the CPU tail merge. No changed block is copied as a
whole page. `NX_WRITE_BACK_WHOLE` and incomplete CPU snapshots retain their
pre-existing full-copy fallback. A failed pipeline, descriptor or safe flag
allocation falls back to the eager scan. New flag allocations cannot wrap over
the current submission's live upload data.

This moves the broad comparison to the GPU; it does **not** eliminate that
comparison or all readback traffic. Counters report bytes considered, GPU bytes
compared, flag bytes, CPU bytes scanned/changed and the additional snapshot
copies separately. `NX_NARROW_WRITEBACK_ORACLE=1` independently checks skipped
complete words on the CPU, logs any missed block and recovers with the eager
merge. Its full scan is diagnostic overhead and is excluded from performance
comparisons.

`NX_FRAMES_IN_FLIGHT=1` requires residency and uses four shared submit/present
slots. It throttles replay count to two before returning; queuing before the
throttle can transiently put a third replay in flight. After the last compute
dispatch, the first part can compare and
materialize results while the later graphics part continues. This is allowed
only while later graphics shaders have zero conservative storage-write masks,
the exact write-back ranges/snapshots remain unchanged, and no CPU debug
observer requires completion. Unknown/nonzero graphics write masks, out-of-range
bindings, later writers/merges, separate-compute mode and CPU observers retain
the whole-submit wait. A graphics writer also retains iteration 1's sticky
read-cache fallback. The original pipelined mode's conservative read counting
is unchanged when the new flight switch is off.

Required write-backs finish before guest execution resumes. Whole-submit NVN
completion is published only after all queued parts retire and required merges
complete; early materialization does not advance that serial. Fence capture
also serializes with active replay. Descriptor/command pools, ring stretches,
images and snapshots retain their slot lifetimes. The next resident refresh or
arena recycle drains previous users. This permits bounded overlap with guest
recording; it does not implement lazy CPU faults or permit arbitrary pending
GPU results to remain invisible to raw guest reads.

`NX_VK_VALIDATION=1` additionally enables the Khronos layer and a persistent
host debug messenger on the active NVN Vulkan path. The pre-existing guest
Vulkan bridge switch alone did not cover this path. The pinned SDK installer
from `tools/win/install_vulkan_tools.ps1` was installed under this unit's private
VM directory; installer SHA-256 was checked by that script.

### Verification and measured results

The native L4 standalone oracle executes the exact embedded comparison shader:
144 unchanged, sparse, dense and partial-word/block boundary cases pass with
zero validation errors and warnings. Native Windows executes all nine write-back
tests, including shader source/SPIR-V reproducibility and concurrent fence capture.
Final exact verification
results are recorded below.
These fixtures use no game inputs. The merge oracle includes concurrent guest
changes, missing/short snapshots, unaligned buffers, guard pages, conservative
extra flags and sparse ranges spanning multiple blocks, in scalar and AVX2
modes. Flight tests cover bounded retirement, materialization before completion,
range identity, later-writer/observer fallback and concurrent fence capture.

Private evidence and build receipts remain in
`.local/units/WIN-RESIDENT-023/` and `C:\acr\units\WIN-RESIDENT-023\`.
Native runtime objects are rebuilt from the selected series. The dynamic-60-cap
main/SDK archives are reused byte-for-byte from iteration 1 and their hashes
are checked; the production CMake file and generated inputs are unchanged.
Windowed measurements use the same route, warm pipeline seed, audio backend,
resolution, GPU timestamps, CPU-only sampler and exclusive idle-VM policy.
Single scene-confirmation dumps precede each FPS window; no burst dumps run in
the timing windows. Matching route labels alone do not establish matched poses
or identical GPU workloads.

The final V3 executable is SHA-256 `b9d27b853b0fd39da9325693cfb6bff3a9a5f817b0d3f828b32614b9f0af05ca`.
`final-source-verification.json` checks all 143 non-generated runtime files
against a fresh complete-series reconstruction and the native build receipt.
The private control-context header and generated main/SDK archives match the
previous build inputs. Earlier V1/V2 binaries, maps, source reconstructions and
receipts are retained separately; their measurements are diagnostic history.

F/G/H and the chunk experiment below use this **same V3 executable**. All use
`NX_RESIDENT=1`, `NX_GPU_PROFILE=3` and the same SVC/copy/frame instrumentation.
F disables both new switches, G enables only narrowing, and H enables both.
The last configuration additionally sets the inherited
`NX_SUBMIT_CHUNK_DRAWS=150`; it remains off by default and is a separate
experiment. It queues work earlier during replay without changing guest clocks,
resolution, shaders or the generated archives. CPU is the busiest non-SDL
thread's measured CPU service, not whole-process CPU or wall-clock wait time.
GPU values are queried execution intervals, with zero unready query results in
accepted buckets. MB below is decimal.

| Configuration / scene | Average / 1% low fps | p50 / p95 / p99 ms | CPU ms | GPU ms | CPU scanned / changed MB | Fence ms |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Resident only / Title | 58.590 / 31.686 | 16.952 / 22.647 / 29.783 | 7.947 | 3.639 | 10.041084 / 0.000000 | 5.350 |
| Resident only / Lab | 24.885 / 18.869 | 41.251 / 44.439 / 46.934 | 27.627 | 5.936 | 10.041084 / 0.000000 | 6.707 |
| Resident only / Chase | 20.280 / 15.890 | 49.477 / 56.570 / 60.323 | 30.701 | 10.737 | 27.041599 / 0.039885 | 11.508 |
| Narrow / Title | 59.288 / 30.787 | 16.288 / 24.861 / 28.958 | 5.943 | 3.898 | 0.001084 / 0.000000 | 4.461 |
| Narrow / Lab | 24.689 / 19.532 | 41.526 / 44.469 / 46.987 | 25.758 | 7.906 | 0.001084 / 0.000000 | 8.686 |
| Narrow / Chase | 20.476 / 16.089 | 49.259 / 55.544 / 60.212 | 25.906 | 14.757 | 0.107950 / 0.038906 | 15.522 |
| Narrow + overlap / Title | 59.570 / 28.965 | 15.837 / 26.457 / 30.359 | 6.295 | 3.583 | 0.001084 / 0.000000 | 2.435 |
| Narrow + overlap / Lab | 25.476 / 20.393 | 40.116 / 43.648 / 45.580 | 28.120 | 7.154 | 0.001084 / 0.000000 | 5.298 |
| Narrow + overlap / Chase | 21.478 / 11.696 | 46.669 / 56.535 / 60.148 | 28.044 | 14.058 | 0.101894 / 0.035755 | 11.701 |
| Narrow + overlap + chunks / Title | 59.974 / 28.582 | 16.053 / 26.244 / 30.084 | 6.305 | 3.624 | 0.001084 / 0.000000 | 2.496 |
| Narrow + overlap + chunks / Lab | 26.479 / 20.398 | 38.366 / 41.462 / 44.244 | 28.825 | 7.902 | 0.001084 / 0.000000 | 3.248 |
| Narrow + overlap + chunks / Chase | 26.501 / 14.462 | 37.488 / 43.682 / 46.055 | 26.296 | 11.619 | 0.084993 / 0.027763 | 4.310 |

| Configuration / scene | Input / CPU snapshot / GPU snapshot MB | GPU compared MB | Flag KB | Arena MB |
| --- | ---: | ---: | ---: | ---: |
| Resident only / Title | 0.039963 / 0.003068 / 0.000000 | 0.000000 | 0.000 | 10.896 |
| Resident only / Lab | 0.389971 / 0.003068 / 0.000000 | 0.000000 | 0.000 | 31.088 |
| Resident only / Chase | 0.674040 / 0.108331 / 0.000000 | 0.000000 | 0.000 | 128.444 |
| Narrow / Title | 0.039985 / 0.003068 / 0.003068 | 10.040000 | 9.808 | 21.924 |
| Narrow / Lab | 0.387859 / 0.003068 / 0.003068 | 10.040000 | 9.808 | 42.348 |
| Narrow / Chase | 0.665997 / 0.106101 / 0.106101 | 26.587059 | 25.969 | 167.780 |
| Narrow + overlap / Title | 0.039993 / 0.003068 / 0.003068 | 10.040000 | 9.808 | 22.187 |
| Narrow + overlap / Lab | 0.393698 / 0.003068 / 0.003068 | 10.040000 | 9.808 | 39.453 |
| Narrow + overlap / Chase | 0.668440 / 0.101018 / 0.101018 | 26.264051 | 25.653 | 165.249 |
| Narrow + overlap + chunks / Title | 0.039985 / 0.003068 / 0.003068 | 10.040000 | 9.808 | 21.924 |
| Narrow + overlap + chunks / Lab | 0.390236 / 0.003068 / 0.003068 | 10.040000 | 9.808 | 39.130 |
| Narrow + overlap + chunks / Chase | 0.638968 / 0.083985 / 0.083985 | 22.086915 | 21.574 | 167.931 |

Every headline ROI passes the idle policy; the highest complete-bucket other-CPU
sample is 8.20%. Scene-confirmation dumps precede the measured windows;
`gate-analysis.json` records their positive timestamp clearance. A separate
post-ROI chunk-run image checks that route's later scene identity. Image captures
are outside the FPS windows. Camera, enemy and loading phases still differ:
these are controlled same-route observations, not matched-pose causal FPS gains.
The chunk run's post-ROI chase image also has unresolved bike/road occlusion and
red credit artifacts. Their origin is not established by matched poses, so that
run is not evidence of fidelity-clean rendering or equal rendered work.
In particular, GPU time differs between F and G; narrowing's lower CPU service
alone does not establish an isolated whole-frame speedup.

The flags reduce eager CPU scanning while preserving changed-word merging.
Overlap moves materialization to the first part when the guard succeeds, but
it cannot hide GPU work queued only near the end of replay. H's early chase
still falls far short of 60 fps and its 1% low is worse than F in this sample.
Its 179.404 ms outlier coincides with a 60-frame bucket reporting six ASTC
texture decodes totaling 116.9 ms and zero new PSOs. That frame reports only
0.567 MB of input copying and an 11.075 ms fence wait. This points to loading/
texture preparation as a tail concern; the bucket does not isolate per-frame
ASTC time. The outlier remains included in the reported quantiles and 1% low.
With the inherited 150-draw chunk option, the chase reaches 26.501 fps and its
fence wait falls to 4.310 ms, but CPU service is still 26.296 ms per frame against
a 16.667 ms target. The 1% low remains below the resident-only control.
No optimization is enabled by default from these measurements.

### Profiling, validation and open gates

The V2 long diagnostic run C survives its bounded 974.912-second route. Its
pre-ROI 375-second frame shows the rear-bike rapid-fire tutorial; 600 and 740
seconds show the side-view chase; 900 and 970 seconds show the subsequent
autosave/tutorial overlay. This does **not** pass ten minutes of continuous
active chase/combat. Its late ROI is 23.898 fps / 19.372 fps 1% low, p50/p95/p99
42.189/44.923/46.238 ms, CPU 23.733 ms and GPU 13.890 ms. This is V2 diagnostic
history, not a final-V3 sustained-combat result.

C's 1,744 primary-thread stacks put 27.69% of wall samples in the first-part
Vulkan fence wait and 15.25% in guest kernel blocking. Writeback no longer leads
the profile. A separate 1,314-stack sample of host thread 8608 shows 61.26% in
a guest synchronization wait and 12.94% in the condition-variable path. The SVC
profiler identifies `WaitProcessWideKeyAtomic` (0x1c) at SDK+0x370ebc as the
presenting thread's main blocked call. The nearest-export label printed for that
address is not evidence of SSL work. The final diagnostic mapping identifies
presenting guest thread 80 / host thread 6332 in validation run D, while its
busiest sampled thread is 7408. Presenter blocked time must not be added to that
other thread's CPU service. Final V3 profiles provide the post-change view: H's 1,748
primary stacks contain 27.06% first-part fence wait, 15.33% guest kernel blocking
and 18.48% command recording including allocator/copy callees. In I's 1,743
primary stacks those groups are 16.06%, 16.93% and 21.69%, respectively. Resident
upload's environment lookup appears in 7.40% of I's stacks. These are wall
samples, not CPU-time attribution; kernel waits do not dominate active replay.
No guest SVC result, timeout, required job dependency or scheduler semantics
were bypassed. Further work should separate remaining first-part GPU
latency, active command recording/replay and loading-time texture work.

The pinned SDK installation succeeds. Native Windows runs **nine new tests with
no skips**, and the L4 standalone bitmap oracle passes 144 cases with zero
validation errors/warnings. Local execution runs nine tests: eight pass and the
optional GLSL compiler check is skipped. The native resident suite executes its real
`MEM_WRITE_WATCH`/recommit fixture successfully. The lead-approved series-order
assertion update allows the successor patch; all six native resident tests pass
and local execution passes five with one Windows-only skip. Builder tests pass
all 55 cases.

The final-V3 validation session D reaches title, lab and the chase with both new
switches and the skipped-block CPU oracle enabled. The persistent messenger is
confirmed active; no oracle mismatch, fatal error or device loss is observed.
It emits **45 error diagnostics plus five duplicate-suppression notices** and
**nine unused-fragment-output warnings plus one suppression notice**. The errors
cover missing draw-parameter/interlock feature or extension enablement, an
8-clip-plus-1-cull array exceeding the device's combined limit of 8, and null
color attachments paired with defined pipeline formats. The V3 title control E
with both new switches off reproduces the exact same normalized error messages
and counts. Its short title-only scope does not classify the chase warnings.
The new compute shader's standalone validation passes; full-game **zero-error
validation remains open**. D's heavy validation/oracle timings are diagnostic,
not included in the headline performance comparison. The chunk configuration
has ordinary gameplay/error checks; D does not establish its validation coverage.

The long C process reaches 9,103.962 MB private bytes in 400–970 seconds; its
first/last 60-second means are 7,200.284/8,665.896 MB. The later new-map/overlay
phase confounds the 1,465.612 MB increase. No matched final-V3 long memory/leak
comparison passes. Full pose/pixel parity, calibrated device A/V, continuous
active combat, broad scene/save/reload coverage and 60 fps remain open as well.
Raw logs/captures and all ordinary-run fatal/device-loss scans are retained.

The lead approved the narrow `test_astral_windows_resident.py` scope extension
in decision `LEAD-RESIDENT023-SCOPE` at 2026-10-20T23:21:41Z. Only that test's
series-order assertion was changed, requiring perf → resident → writeback.
The initial terminal-order assertion failures remain in the historical evidence;
the final required commands are rerun against the committed head.

Independent other-model/different-effort review belongs to the parent for the
exact final head. No nested review was started, claimed or silently waived.
The source remains opt-in and is not a public/release/default-enable approval.

Private evidence: `build-receipt.json`, `final-source-verification.json`,
`historical-source-verification.json`, `native-v3-ssh.log`, `gpu-oracle.log`,
`measurements.json`, `summary-numbers.json`, `gate-analysis.json`,
`tail-frame-diagnostics.json`, final H/I `*-analysis.json` profiles,
`verify-final.json`, `final-vm-state.json`, the two `*-validation.json` reports,
`evidence-manifest.json`, `evidence-receipt.json`, `evidence-validation.json`
and `vm-evidence/` under `.local/units/WIN-RESIDENT-023/` on the Mac. Source,
executables, maps, generated inputs, saves, driver logs and captures stay private.

## WIN-REPLAY-024: G4 control and command replay (iteration 3)

The unchanged iteration-2 executable is remeasured first on the replacement G4:
AMD EPYC 9B45 (24 cores / 48 logical processors), NVIDIA RTX PRO 6000 Blackwell
Server Edition (97,887 MiB), driver 596.86. This separates the machine change
from the new code. These are windowed dynamic-60-cap runs, not a Windows 11
or physical gaming-PC result. The generated main/SDK archives, imported control
header, warm-cache seed, route, 1600×900 render output, audio backend, CPU sampler
and Vulkan timing queries are held constant. Captures precede measured windows.
Every launch checks all `astral*` processes and acquires the shared exclusive
marker; the runner requires 15 seconds of low CPU/GPU activity and records
other-process CPU throughout. No build overlaps the FPS runs.

`astral-depth-fidelity.patch` is now active immediately after the render fix in
all three platform series. Windows defaults to exact EQUAL without synthetic
EQUAL slack; the other three fidelity experiments remain individually opt-in.
See [render fidelity](ASTRAL_RENDER_FIDELITY.md). Performance comparisons of the
new switches use the same new binary and the same depth policy, so depth's
correctness change is separate from replay attribution.

`astral-windows-replay.patch` follows perf → resident → writeback. All five new
switches default **off** and are enabled only for strict Astral on Windows:

| Switch | Opt-in behavior |
| --- | --- |
| `NX_REPLAY_ENV=1` | Freeze resident enabled/read/storage flags on the first recording/startup use. The off control retains the original per-call environment queries. Runtime async/failure/graphics-writer and size guards remain live. |
| `NX_REPLAY_POOL=1` | Copy command payloads into one aligned, indexed arena per immutable command list. Recycle command/vector/arena capacities only after the final shared owner releases the list. The free pool holds at most 256 list objects and 32 MiB of retained vector/arena capacity; larger/excess lists are freed. Guest handles, command-memory overlap eviction, queue ownership and replay order are unchanged. |
| `NX_REPLAY_SCRATCH=1` | Reuse per-thread shader-selection vectors, separately for draw and dispatch. Selection and shader-debug overrides remain effective. |
| `NX_REPLAY_KEYS=1` | Canonicalize unused vertex attributes/streams, inactive blend state and unused color slots before graphics-key lookup. Effective vertex, blend, depth, polygon and attachment state remains in the key. This does not require extended dynamic-state extensions. |
| `NX_REPLAY_DYNAMIC=1` | Split the existing raster-state filter into independent stencil-reference, compare-mask, write-mask and depth-bias groups. Existing command-buffer, submit and helper-pass resets force all groups again. |

The runtime already reuses Vulkan command buffers and caches descriptor sets
within a submit. This unit preserves those GPU-resource lifetimes; it does not
reuse descriptor contents across unfinished frames. The new pool recycles CPU
command storage, including payload allocations that previously occurred for
each decoded state object. A list still referenced by a recorded handle or
queued replay cannot be recycled. Cumulative `replay storage` counters report
created, reused and released lists for the pool experiment.

The source-only fixtures execute production recording, payload access, pool
ownership/reset/bounds under concurrent owners, frozen flag behavior,
canonical-key hits/misses, and raster calls across state and reset boundaries.
Full-series source reconstruction and native Windows compilation are distinct
from game/GPU checks. The new native executable is SHA-256
`62eeb029be7ea75e3cb33679aeedb0ef33c404c4caea68534cd1de6d865d82be`.
All 147 composed public runtime files match its build receipt; its imported
control header and both generated libraries match iteration 2. Private evidence
is under `.local/units/WIN-REPLAY-024/` and `C:\acr\units\WIN-REPLAY-024\`.

<!-- WIN-REPLAY-024-MEASUREMENTS -->

### Measured G4 results

A/B use the unchanged iteration-2 executable. C2–H2 use the one final V2 binary above, with exact EQUAL and the other three fidelity candidates off. C2 disables all five new replay switches; D2 enables environment caching; E2 adds pooling; F2 adds scratch reuse; G2 adds canonical keys; H2 adds the finer state filter. Every C2–H2 run holds residency, narrowing, flight overlap and 150-draw chunks on. Each neighboring pair changes one replay switch. These are controlled same-route observations; camera/enemy/loading phases are not locked.

Every headline CPU-only sampling window is 20 seconds. Average fps is 1000 divided by the mean complete present interval; 1% low is 1000 divided by the mean of the slowest ceiling(1% of intervals). Quantiles use linear interpolation. CPU is the busiest non-SDL thread’s GetThreadTimes service per frame. GPU uses the existing Vulkan query intervals. All headline ROIs pass the exclusive/idle check with zero unready GPU query results. Captures finish before the windows; detailed clearance, thread IDs and raw timing buckets are in private evidence.

| Configuration / scene | Average / 1% low fps | p50 / p95 / p99 ms | CPU ms | GPU ms | Fence ms |
| --- | ---: | --- | ---: | ---: | ---: |
| Iteration 2 off / A / Title | 59.713 / 27.615 | 16.341 / 21.787 / 26.813 | 4.644 | 1.927 | 2.129 |
| Iteration 2 off / A / Lab | 42.232 / 24.934 | 25.152 / 28.466 / 30.721 | 14.022 | 3.635 | 3.817 |
| Iteration 2 off / A / Chase | 38.986 / 18.922 | 25.942 / 30.841 / 33.420 | 16.031 | 3.563 | 3.747 |
| Iteration 2 on / B / Title | 59.966 / 31.626 | 16.522 / 20.971 / 23.483 | 2.488 | 2.354 | 2.136 |
| Iteration 2 on / B / Lab | 58.124 / 27.595 | 17.147 / 23.694 / 28.450 | 9.018 | 4.025 | 1.924 |
| Iteration 2 on / B / Chase | 53.344 / 25.568 | 18.459 / 21.515 / 29.281 | 10.823 | 4.068 | 1.001 |
| New replay off / C2 / Title | 59.796 / 28.580 | 16.424 / 21.129 / 26.213 | 2.143 | 2.403 | 2.197 |
| New replay off / C2 / Lab | 56.237 / 22.855 | 17.713 / 25.135 / 36.665 | 8.905 | 3.940 | 1.906 |
| New replay off / C2 / Chase | 57.980 / 27.950 | 16.880 / 19.406 / 28.080 | 10.402 | 4.183 | 1.212 |
| Environment / D2 / Title | 59.797 / 28.737 | 16.547 / 21.474 / 26.778 | 2.182 | 2.293 | 2.177 |
| Environment / D2 / Lab | 58.722 / 25.830 | 16.890 / 24.634 / 31.537 | 7.929 | 4.050 | 2.731 |
| Environment / D2 / Chase | 58.733 / 27.975 | 16.735 / 18.798 / 27.921 | 8.712 | 4.163 | 2.163 |
| + Pool / E2 / Title | 59.921 / 31.457 | 16.409 / 21.163 / 25.670 | 2.099 | 2.335 | 2.207 |
| + Pool / E2 / Lab | 59.770 / 30.103 | 16.695 / 25.429 / 28.435 | 6.849 | 3.983 | 2.736 |
| + Pool / E2 / Chase | 58.992 / 27.313 | 16.664 / 19.514 / 24.248 | 6.926 | 4.163 | 2.171 |
| + Scratch / F2 / Title | 59.925 / 30.306 | 16.481 / 21.116 / 25.641 | 2.216 | 2.298 | 2.181 |
| + Scratch / F2 / Lab | 59.595 / 30.406 | 16.815 / 24.872 / 27.275 | 6.568 | 3.972 | 2.757 |
| + Scratch / F2 / Chase | 59.623 / 27.764 | 16.628 / 18.897 / 22.775 | 6.630 | 4.278 | 2.392 |
| + Keys / G2 / Title | 60.007 / 34.092 | 16.592 / 21.023 / 24.732 | 1.784 | 2.278 | 2.205 |
| + Keys / G2 / Lab | 59.577 / 28.552 | 16.798 / 24.695 / 27.851 | 6.661 | 3.929 | 2.757 |
| + Keys / G2 / Chase | 59.725 / 30.422 | 16.606 / 18.888 / 22.299 | 6.671 | 4.155 | 2.297 |
| + Dynamic / H2 / Title | 59.590 / 26.095 | 16.623 / 21.326 / 25.909 | 1.993 | 2.311 | 2.197 |
| + Dynamic / H2 / Lab | 59.343 / 27.287 | 16.804 / 24.662 / 27.424 | 6.859 | 3.936 | 2.723 |
| + Dynamic / H2 / Chase | 59.334 / 28.387 | 16.673 / 18.798 / 23.749 | 6.807 | 4.086 | 2.155 |

MB below is decimal. The counter table preserves both CPU scanning and the work moved to the GPU. Arena capacity is bounded independently of the new free command-list pool.

| Configuration / scene | Input / CPU snapshot MB | CPU scanned / changed MB | GPU compared MB | Flag KB | Arena MB |
| --- | ---: | ---: | ---: | ---: | ---: |
| Iteration 2 off / A / Title | 10.078013 / 10.041084 | 10.041084 / 0.000000 | 0.000000 | 0.000 | 0.000 |
| Iteration 2 off / A / Lab | 25.713362 / 10.041084 | 10.041084 / 0.000000 | 0.000000 | 0.000 | 0.000 |
| Iteration 2 off / A / Chase | 42.399800 / 21.796004 | 21.796004 / 0.024442 | 0.000000 | 0.000 | 0.000 |
| Iteration 2 on / B / Title | 0.039985 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 21.924 |
| Iteration 2 on / B / Lab | 0.418377 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 42.322 |
| Iteration 2 on / B / Chase | 0.596708 / 0.036322 | 0.035577 / 0.005097 | 12.646622 | 12.354 | 207.823 |
| New replay off / C2 / Title | 0.039996 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 21.792 |
| New replay off / C2 / Lab | 0.414397 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 42.023 |
| New replay off / C2 / Chase | 0.582289 / 0.041581 | 0.041250 / 0.008203 | 14.235875 | 13.906 | 203.804 |
| Environment / D2 / Title | 0.039999 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 21.792 |
| Environment / D2 / Lab | 0.418821 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 41.305 |
| Environment / D2 / Chase | 0.587489 / 0.039505 | 0.039013 / 0.007108 | 13.630003 | 13.314 | 210.500 |
| + Pool / E2 / Title | 0.039953 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 21.792 |
| + Pool / E2 / Lab | 0.416168 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 41.907 |
| + Pool / E2 / Chase | 0.594505 / 0.037420 | 0.036808 / 0.006100 | 12.888048 | 12.590 | 215.684 |
| + Scratch / F2 / Title | 0.039994 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 21.924 |
| + Scratch / F2 / Lab | 0.416460 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 42.665 |
| + Scratch / F2 / Chase | 0.588077 / 0.038976 | 0.038565 / 0.006996 | 13.614692 | 13.299 | 213.038 |
| + Keys / G2 / Title | 0.039997 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 22.055 |
| + Keys / G2 / Lab | 0.416259 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 42.297 |
| + Keys / G2 / Chase | 0.591887 / 0.037720 | 0.037104 / 0.006100 | 13.068179 | 12.765 | 216.598 |
| + Dynamic / H2 / Title | 0.039989 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 21.924 |
| + Dynamic / H2 / Lab | 0.415853 / 0.003068 | 0.001084 / 0.000000 | 10.040000 | 9.808 | 42.492 |
| + Dynamic / H2 / Chase | 0.594743 / 0.035801 | 0.035056 / 0.005194 | 12.656468 | 12.363 | 212.922 |

The pool makes zero new list objects and reuses two lists per frame in the measured title, lab and chase windows. Retaining their command/payload capacities removes repeated payload allocations. Native synthetic fixtures verify byte preservation, alignment, queued ownership, reuse, concurrent owners and capacity limits; real-game counters establish that reuse actually occurs.

After pooling, another guest thread becomes the busiest. The following table identifies the NVN-calling thread from resolved adjacent instruction samples and matches its host TID to the independent CPU-only ROI. This keeps replay CPU attribution separate from that change in thread ranking.

| Configuration / chase | NVN-calling CPU ms | Busiest CPU ms | NVN / busiest / presenter host TID |
| --- | ---: | ---: | --- |
| Iteration 2 on / B | 10.823 | 10.823 | 11760 / 11760 / 5156 |
| New replay off / C2 | 10.402 | 10.402 | 10764 / 10764 / 13996 |
| Environment / D2 | 8.712 | 8.712 | 6060 / 6060 / 6532 |
| + Pool / E2 | 6.317 | 6.926 | 3304 / 3244 / 8624 |
| + Scratch / F2 | 5.988 | 6.630 | 3436 / 2416 / 9112 |
| + Keys / G2 | 5.965 | 6.671 | 7876 / 13608 / 14252 |
| + Dynamic / H2 | 6.149 | 6.807 | 6064 / 4972 / 12068 |

Environment caching and pooled storage provide the clear CPU reductions. Scratch reuse adds a smaller change; the key/dynamic experiments do not establish a robust whole-frame gain in this short, near-cap sample. GPU work and game phase vary between runs, so the fps differences are not a matched-pose causal speedup. No new performance switch is made default-on.

The initial V1 C/D diagnostic runs are retained separately. Source review found that V1’s off-path guard order skipped an environment lookup for tiny reads. V2 restores the original query order; an executable fixture counts all 17 uncached bypass queries and zero after cached initialization. Only the corrected same-binary C2–H2 controls are headline replay comparisons. V1 binary, map, receipts and logs remain private history.

Private `summary-numbers.json`, `measurements.json`, `profile-summary.json`, `gate-analysis.json`, `tail-frame-diagnostics.json`, build receipts, raw profiles and `RESUME.md` retain exact values and provenance. The first unchanged-build G4 results were checkpointed before candidate measurements. The Windows dependency `f4b9380` was already on main at start. Independent exact-head review and landing belong to the parent.

<!-- WIN-REPLAY-024-MEASUREMENTS-END -->

### Remaining cost, hitches and acceptance limits

Adjacent wall-stack samples of the actual NVN-calling thread show the resident
CRT path falling from 5.59% in C2 to zero in D2. Command recording falls from
11.07% in C2 to 2.32% in F2. These are wall-sample fractions, including waits,
not CPU-time percentages. F2 still spends 43.50% in guest kernel blocking and
22.57% in the first-part Vulkan fence. After pooling, the busiest guest logic
thread differs from this replay caller; its stacks cannot substitute for the
replay profile. The presenter is another host thread again. The observed guest
wait is `WaitProcessWideKeyAtomic` (SVC 0x1c); the nearest SDK export name is not
proof of the internal caller's function. This unit does not establish an
unnecessary wait or change any SVC semantics.

The headline runs leave `NX_REPLAY_THREAD` unset. In that configuration,
`nvn_worker.cpp` executes jobs inline and returns serial zero; `worker_wait(0)`
returns immediately. There is no dedicated worker-completion wait on the
presenting guest thread in this path. The NVN-calling guest thread's observed
kernel wait is distinct from the worker's host condition variable. Removing it
would require identifying the guest condition-variable key and its signaler,
not bypassing `WaitProcessWideKeyAtomic`'s atomic unlock/wait/relock behavior.

A separate diagnostic J enables the existing `NX_REPLAY_THREAD=1` with all five
new switches on: chase average/1% low 59.844/28.759 fps, busiest CPU 6.358 ms,
NVN-caller CPU 3.903 ms, Vulkan GPU 4.283 ms. It redistributes work without
establishing a reliable whole-frame gain or broad fidelity acceptance. It stays
opt-in. The next steady-state investigation is the dependency chain between
guest work, replay and the first fence, with host thread roles kept separate.

The fixed-workload native recording benchmark alternates three off/on process
pairs, each measuring 256 frames after 32 warm-up frames, two lists and 4,096
commands per frame (half with 96-byte payloads). It executes the extracted
production recording/storage code with stub object lookup and counts heap
allocations: off 2,126 allocations/frame and 120.437–130.192 ns/command; pool
2 allocations/frame and 23.281–23.335 ns/command. This isolates allocation cost;
it is not a game-fps result. `record-benchmark.cpp`, its native build log and
`record-benchmark.json` retain the workload and all six observations privately.

Long frames remain. C2's 66.454 ms maximum and D2's 68.926 ms maximum coincide
with nearby 60-frame reporting buckets containing six ASTC decodes taking
45.8/47.2 ms and zero new pipelines. Their ordinary fence averages are only
2.198/1.463 ms in those buckets. The E2 maximum has no matching creation bucket,
so it is not attributed to ASTC. These are coarse bucket correlations, not
per-frame attribution. During C2 loading, 114 ASTC decodes total 1,138 ms versus
50 pipeline creations totaling 51.5 ms; the next bucket has 51 decodes/378.6 ms
versus 42 pipelines/13.9 ms. P5 loading-time texture preparation with immutable,
generation-checked inputs is the next hitch target. No ASTC worker or P4 Windows
recipe warm-up is implemented in this measured subset.

The installed SDK's validation layer is explicitly active in K (all old/new
performance switches off) and L (all on), with the same 16 GB diagnostic memory
guard. Both reach the chase. The complete observed message multisets match:
45 errors across five VUIDs and nine unused-fragment-output warnings, plus five
error and one warning duplicate-suppression notices. There are no new observed
VUIDs or messages. The inherited errors concern SPIR-V capabilities/extensions,
clip/cull limits and dynamic-rendering attachment formats
(`pCode-08740`, `pCode-08742`, `maxCombinedClipAndCullDistances-00710`, and
`dynamicRenderingUnusedAttachments-08912` for indexed and non-indexed draws).
Suppression prevents treating these runs as proof of zero validation errors.
L enables the narrow-writeback CPU oracle and reports no `ORACLE_MISMATCH`.
Validation timings are diagnostic and excluded from the ordinary FPS table.

Short chase memory windows (375–470 seconds) are also retained: C2 first/last
20-second means 7,162.767/7,249.050 MB, E2 7,163.589/7,252.619 MB. Their growth
is 86.283/89.031 MB and their peaks 7,253.098/7,252.619 MB. These do not establish
the requested matched ten-minute memory gate. There is no ten-minute continuous
active chase/combat acceptance or matched-pose title/lab/close-up/chase parity
pass. All iteration-1/2 and new replay performance switches therefore remain
opt-in. Exact EQUAL is the separately verified fidelity default. Near-60 average
fps does not close the low-percentile or broad gameplay gates.

Local executable/source fixtures and native game evidence are separate. The
Windows replay fixture run executes six tests and skips the local TU-syntax
test, covered separately by the complete native runtime build. The other three
fidelity experiments are still unverified. Parent-owned independent review of
the exact committed head remains pending; no nested review is started or waived.


### Independent presentation cross-check

A final same-binary M/N/O series uses the official standalone
[PresentMon 2.6.0 release](https://github.com/GameTechDev/PresentMon/releases/tag/v2.6.0)
and its [console interface](https://github.com/GameTechDev/PresentMon/blob/main/README-ConsoleApplication.md).
The download matches the release API SHA-256
`b2a706bc6ad475749e3b7e3409263aa1e6906d45bdcf993f6dbc0f660188f1af`;
no installer or service is used. Unique, timed ETW sessions track only the owned
game PID with input tracking disabled. Each 26-second capture brackets the same
20-second CPU-only ROI by QPC timestamps. Analysis selects the dominant
swapchain and complete application present intervals inside that ROI. All nine
observer processes exit zero with normal start/stop logs, and every ROI passes
the same idle check. Raw CSVs and exact commands are private.

M holds all old/new performance switches on with the original heavy diagnostic
settings. N holds the same switches on but unsets frame/resident/SVC/GPU logs,
input recording and audio dumping. O keeps the old four settings on and disables
only the five new replay switches, with the same quiet diagnostics as N. Actual
effective-process receipts confirm the null diagnostic variables; route,
resolution, audio playback, caps and fidelity defaults are unchanged. Captures
and stack sampling remain outside each timing ROI.

The table uses application `msBetweenPresents`; CPU remains busiest non-SDL
GetThreadTimes service per observed frame. GPU is **ETW `msGPUActive`**, a
different scope from the Vulkan query intervals in the main table. Events are
labeled DXGI / Composed:Flip by the host observer; the game renderer remains
Vulkan. Dropped application presents are retained in the application interval
statistics and reported separately.

| Configuration / scene | Average / 1% low fps | p50 / p95 / p99 ms | CPU ms | ETW GPU-active ms | Dropped presents |
| --- | ---: | --- | ---: | ---: | ---: |
| All on, instrumented / M / Title | 59.883 / 33.284 | 16.568 / 20.839 / 25.049 | 2.100 | 2.836 | 0 |
| All on, instrumented / M / Lab | 58.961 / 26.539 | 17.289 / 24.099 / 28.222 | 6.771 | 4.570 | 1 |
| All on, instrumented / M / Chase | 59.686 / 29.474 | 16.641 / 18.129 / 24.612 | 6.714 | 4.895 | 1 |
| All on, quiet / N / Title | 59.992 / 36.580 | 17.069 / 20.535 / 22.398 | 1.849 | 2.703 | 0 |
| All on, quiet / N / Lab | 59.877 / 30.500 | 16.333 / 26.220 / 27.398 | 6.524 | 4.504 | 1 |
| All on, quiet / N / Chase | 59.567 / 29.524 | 16.674 / 18.928 / 21.707 | 6.649 | 4.736 | 0 |
| New replay off, quiet / O / Title | 60.008 / 37.228 | 16.881 / 20.707 / 22.399 | 2.461 | 2.805 | 0 |
| New replay off, quiet / O / Lab | 60.010 / 36.577 | 17.028 / 25.647 / 26.294 | 8.813 | 4.520 | 1 |
| New replay off, quiet / O / Chase | 59.801 / 32.837 | 16.638 / 18.359 / 20.135 | 10.451 | 4.729 | 1 |

The quiet off/on chase pair has NVN-calling CPU 10.451/5.928 ms per
frame, independently selected from adjacent resolved instruction profiles and
matched to the ROI host TID. The observer reproduces M's runtime-log averages
within 0.004 fps at all three scenes, while individual tails differ between
host presentation and the runtime frame hook. Quiet O is already near the cap:
new replay off/on gives 59.801/59.567 fps and 32.837/29.524 fps 1% lows. The
observed CPU reduction does **not** demonstrate an FPS or tail improvement;
the off control has the better tails in this sample. Quiet N still has slow
frames, so removing diagnostic logging does not establish sustained 60 fps. N/O remain
same-route observations with unlocked game/camera phase, not matched-pose causal
FPS proof. Compositor displayed-interval statistics are retained separately in
`presentmon-measurements.json` and are not substituted for app intervals.

Private `presentmon-receipt.json`, `presentmon-measurements.json`,
`presentmon-runtime-crosscheck.json`, M/N/O effective-switch receipts, CSVs,
CPU-only windows and adjacent profiles provide the observer provenance.
`validation-comparison.json`, `worker-wait-investigation.json` and
`record-benchmark.json` support the separate acceptance/profile findings. The
final executable and a hash-verified raw evidence archive are retained on the
Mac; `evidence-manifest.json`, `evidence-receipt.json`, `evidence-validation.json`
and `final-vm-state.json` record owned-process/task cleanup and archive checks.
The exact required local VERIFY commands and native-versus-local coverage are
recorded in `verify-final.json` and the structured worker report. No branch is
pushed by this worker.

## WIN-STUTTER-025: per-frame hitches on G4

This unit measures windowed `dynamic-60-cap` on the same G4/driver and fresh-game
route as WIN-REPLAY-024. It holds that unit's quiet-O settings:
`NX_RESIDENT=1`, `NX_NARROW_WRITEBACK=1`, `NX_FRAMES_IN_FLIGHT=1`,
`NX_SUBMIT_CHUNK_DRAWS=150`; all five replay switches remain unset/off.
These four older options are explicit benchmark inputs, not newly enabled defaults.
The five new performance switches below default **off**. The 1600×900 render output, generated
main/SDK archives, legacy cache input seed, XAudio2 and PresentMon method remain
constant. The inherited seed is `pipelines_10de_27b8.bin` (L4); the active G4
path is `pipelines_10de_2bb5.bin` and logs **0 bytes loaded** at each fresh run.
These are initially empty application Vulkan caches, with OS/driver caches not
purged. The same seed is retained to match WIN-REPLAY-024; it is not mislabeled
as an effective warm G4 driver-cache blob. Each launch checks `astral*`, owns the exclusive marker and passes
the idle gate; no build overlaps game measurements. Captures precede the ROIs.

Private evidence is `.local/units/WIN-STUTTER-025/` on the Mac and the matching
`C:\acr\units\WIN-STUTTER-025\` directory. No game-derived cache, capture,
shader, source, save or executable is tracked. The console/pacing matrix executable is SHA-256
`24680fd8c0ac8ce0ffae1ef8dc6ac30ba58e1621c32a52d2345792546ec1b856`;
the 4 GiB disk-cache matrix uses
`4a48956978ef5390591ece19b40899ba8503f5bea01b0ee422079f69c3df9418`;
the preparation matrix uses
`d750febe0c2b81c5d8859f333c13b6419ab2d5e08ed25602b44f910c9f8df0b8`.
The continuation WIN-STUTTER-025B persistence matrix, final warm confirmation
and SDK/oracle routes use
`f1d412c3dd2d78107ad852a6bc8ef966a705f6f2443964a0892c570d2f85b040`.
Each control/treatment comparison stays within its own executable. No performance
claim merges controls from different binaries.
All 151 public runtime files in the final build match a fresh complete-series
reconstruction (150 for the preceding matrices); the
three native-only files are the unchanged private control header and two metadata
files. Generated archives match the prior unit byte for byte.

### Attribution before optimization

`astral-windows-stutter.patch` is last in `series.windows`. Setting
`NX_STUTTER_TRACE=<private filename>` writes a QPC-aligned binary span trace,
`ACST0001` followed by 32-byte little-endian records:
`begin_ns:u64, end_ns:u64, argument:u64, host_tid:u32, kind:u32`.
It records individual module/graphics/compute creation, ASTC/texture preparation,
untiling/upload, fences, blocking guest SVCs, pacing sleeps, GPU ownership,
slot begin, queue submit, acquire/present, periodic diagnostics and console/file
writes. Frame markers connect these spans to independent PresentMon timestamps.
The bounded 65,536-event backlog is written by a separate thread every 100 ms;
kind zero explicitly reports lost records. All accepted attribution traces have
zero loss and cover every ROI end. Tracing is disabled in the ordinary A/B matrix.

Step 1 was checkpointed in private `RESUME.md` before performance edits. Three
full diagnostic routes distinguish app production from compositor output.
The final diagnostic C classifies every complete app interval >25 ms below;
A/B independently reproduce the console/ASTC patterns. These diagnostic numbers
are attribution data, not the quiet performance headline. The categories are
observed primary/mixed stages; inclusive spans across threads must not be added.
The exact guest condition-variable signaler and all guest CPU work remain
unresolved. No guest wait/result, draw or required fence is bypassed.

| ROI | App >25 / >50 ms | App max ms | Displayed >25 / >50 ms | Displayed max ms |
| --- | ---: | ---: | ---: | ---: |
| title | 10 / 0 | 31.317 | 0 / 0 | 18.897 |
| cutscene | 156 / 2 | 55.932 | 7 / 1 | 50.194 |
| chase | 5 / 1 | 66.834 | 4 / 0 | 49.687 |

| ROI / primary measured category | Count | Total interval ms | Excess above 16.667 ms |
| --- | ---: | ---: | ---: |
| title / console writes >5 ms | 4 | 119.773 | 53.106 |
| title / guest dependency / pacing / caller work | 6 | 154.180 | 54.180 |
| cutscene / console writes >5 ms | 8 | 325.105 | 191.771 |
| cutscene / guest/pacing with 0.5–5 ms console overlap | 10 | 289.181 | 122.514 |
| cutscene / guest dependency / pacing / caller work | 138 | 3527.161 | 1227.161 |
| chase / ASTC texture demand | 1 | 66.834 | 50.167 |
| chase / console writes >5 ms | 4 | 152.630 | 85.964 |

All C spikes have zero overlapping shader-module or pipeline creation. The title's
four largest intervals have 61.364 ms of console writes versus 0.382 ms of primary
log-file writes in total. Every one occurs on a 300-present statistics boundary.
The worst title interval is 31.317 ms: statistics 16.469 ms, console 16.378 ms,
log file 0.112 ms. GPU ownership, acquire, slot begin, queue submit and the actual
present call are short. A native redirected-pipe fixture measures 1,000 diagnostic
lines at 938–1,107 ms with `fprintf`; a single `fwrite` per line is no faster
(984–1,281 ms). The expensive path is synchronous console mirroring through this
Windows launch harness, not missing graphics precompilation.

The 66.834 ms chase interval contains 49.367 ms of texture preparation, including
46.825 ms of ASTC work; the presenter's 58.969 ms guest wait overlaps that replay
work and is not a separate cost to add. The other four chase spikes contain
84.923 ms of console writing in total, versus 0.447 ms of primary-file writes.
A/B's independent worst chase frames likewise contain about 46–47 ms of ASTC.

Displayed gaps remain separate. C title has none despite ten slow app intervals.
Six of the seven lab display gaps correspond to app intervals >25 ms (215.532 ms
of displayed intervals); the remaining gap is 33.301 ms. Three of four chase gaps
correspond to such app intervals (116.314 ms); the other is 33.897 ms. Those latter
cases can include compositor pacing or earlier buffered/dropped app work; they
are not proof of a slow Vulkan present call. No FIFO, timer-resolution or DXGI
waitable-object change is justified by this evidence. P4 Windows recipe/cache
prewarm was not ported in WIN-STUTTER-025: it does not explain these measured steady ROI spikes.
The later PC-SHADER-027 port is measured separately below.

### Opt-in changes

- `NX_WIN_ASYNC_CONSOLE=1` moves console mirroring to one worker. A 256-line FIFO
  owns copied messages, preserves order and applies backpressure instead of
  dropping lines. The main `NX_LOG` file is still written/flushed synchronously;
  calls through `plat::exit_process`, including fatal exits, drain console output.
  The existing direct window-close and forced-termination paths may interrupt
  the final console backlog, while already-written primary log lines
  remain available. This avoids this harness's pipe stalls without removing logs.
- `NX_WIN_PACE_BEFORE=1` moves the existing deadline limiter before inline
  presentation. It retains the same period, late-frame policy and shortest-step
  clamp. With `NX_REPLAY_THREAD=1` it retains the original placement. This tests
  whether pacing after presentation amplifies variable guest-work intervals.
- `NX_WIN_ASTC_CACHE=1` reuses checked decoded RGBA results. Its key covers SHA-256
  of the entire executable, format/sRGB, dimensions, layer/block/level layout and
  all owned compressed input bytes. The versioned file checks key, size and a
  SHA-256 of header plus complete output before publishing it. Failed/corrupt
  loads leave the zero-initialized destination untouched and use the original
  decoder. Windows UTF-8 paths and atomic replacement are supported. The cache
  limits entries to 64 MiB, 4,096 files and 4 GiB, plus one bounded temporary file;
  unavailable CNG, failed I/O or exhausted limits retain decoding. It does not
  move guest pointers to a background thread or skip first-use draws.
  `NX_WIN_ASTC_CACHE_ROOT` overrides the default private
  `<NX_DATA_ROOT>/decoded_astc_v1`; benchmark runs share a unit-owned warm seed.
  `NX_WIN_ASTC_CACHE_VERIFY=1` recomputes every hit, compares bytes/invalid-block
  counts and uses fresh decoded data on mismatch. Verification is diagnostic,
  excluded from performance windows. Cold decoding and cache writes still cost
  time; warm-cache results must not be presented as a cold-launch solution.


- `NX_WIN_ASTC_PREPARE=1`, together with the cache switch, validates the most
  recent cached entries once at the first texture-loading barrier and retains
  up to 192 MiB of owned RGBA snapshots. Subsequent matching requests still
  hash the full compressed input and metadata, then copy the checked snapshot.
  They avoid repeated output checksums, allocation and disk reads. A new process
  rejects corrupt entries; mutations of a disk file cannot change an already
  checked snapshot. This is bounded synchronous preparation at a loading
  barrier, not background guest-memory decoding or a solution to cold misses.
  Entries outside that working set retain ordinary checked disk loads. The
  trace separately records preparation and input-key time; `ready=` counts
  prepared hits and remains a subset of total hits.

- `NX_WIN_ASTC_ASYNC_STORE=1`, together with the cache switch, moves output
  hashing and atomic disk persistence to one worker. Jobs own the key, decoded
  RGBA bytes and invalid-block count; no guest pointer or GPU object crosses
  threads. The queue and in-flight job together are capped at 128 MiB and 16
  jobs, with the existing 64 MiB per-entry limit. A full queue skips optional
  persistence without waiting for disk or changing the decoded texture. Saves
  remain serialized; concurrent loads see checked published files or immutable
  prepared snapshots. Cumulative queued/skipped/saved/failed counters expose
  incomplete persistence. Forced process exit can discard pending cache writes;
  a partially written temporary file is never accepted as a cache entry.

The extra preparation switch follows measured cache cost. With no game running,
a native benchmark loads the six newest chase entries (5,592,416 bytes each)
three times: total load time is 36.2–37.1 ms per six, including about 16.6 ms
of SHA-256. The first warm disk-only pair still has 59.757/60.740 ms app frames;
its last chase bucket is six hits and zero misses. The same-binary O2/Q2/P/R
comparison tests moving that checked work to the loading barrier. Cold training
G reaches a 109.881 ms chase app interval: actual ASTC decode 42.195 ms and
cache store 44.799 ms inside 95.108 ms of texture preparation. Disk-cache cold
writes regress this first encounter and are not omitted from the tradeoff.

The continuation starts from that regression, rather than repeating the finished
console/pacing/cache matrices. A later cold trace S independently records a
102.749 ms chase app interval: ASTC decode 42.213 ms and synchronous persistence
37.514 ms inside 87.873 ms of texture preparation. This observation was written
to `RESUME.md` before adding the asynchronous persistence worker. The full
RGBA copy is still on the producer and has its own `cache_enqueue` span;
`cache_store` spans on the worker must not be charged as frame-thread work.

The parent restarted the VM at 08:32:01Z. The first following preparation-off
route Q reached substantially earlier camera phases (title present 1501 rather
than 2161, lab 7081 rather than about 8941). It was designated a restart diagnostic
before its chase result was known; the entire run is retained, and Q2 replaces
it in the repeated preparation control. No individual slow frame is trimmed.
Preparation-on R remains in the treatment spread despite its failed chase
result: 98.255 ms app / 101.050 ms displayed, with PresentMon reporting
90.151 ms GPU active and 0.245 ms inside Present for the worst interval. Its six
late texture requests were all prepared hits; quiet bucket logs do not establish
the exact cause of that GPU/driver outlier. P alone therefore does not establish
reliable preparation success.

<!-- WIN-STUTTER-025-RESULTS -->
Each value below is first / second run, preserving the measured spread.
The quiet A/C→B/D comparison isolates asynchronous console output; B/D→E/F
isolates limiter placement. H/J→I/K isolates the decoded disk cache with both
earlier switches held on. O2/Q2→P/R isolates bounded preparation with all three
earlier switches on. T/V versus U/W isolates persistence scheduling, each with a fresh
decoded cache. X/Y repeats the final warm configuration and is not a cross-binary
control. G and S seed routes, ZB tracing and SDK/byte-oracle routes
are excluded from these performance tables. Each pair uses the same executable,
route, seed and observer. Results remain same-route observations with unlocked
game/camera phase; they are not matched-pose pixel proof.

App-present intervals (includes dropped presents):

| Case | ROI | Avg fps | 1% low fps | p99 ms | Max ms | >25 ms | >50 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A/C off | title | 60.026 / 59.956 | 32.436 / 33.252 | 24.627 / 24.573 | 41.565 / 42.616 | 12 / 12 | 0 / 0 |
| A/C off | cutscene | 60.005 / 59.807 | 35.185 / 31.153 | 26.564 / 26.455 | 33.434 / 49.570 | 124 / 166 | 0 / 0 |
| A/C off | chase | 59.748 / 59.676 | 35.116 / 33.803 | 19.598 / 19.835 | 65.965 / 68.297 | 5 / 5 | 1 / 1 |
| B/D console | title | 59.989 / 60.004 | 40.609 / 41.121 | 22.277 / 22.194 | 26.296 / 26.147 | 7 / 7 | 0 / 0 |
| B/D console | cutscene | 60.019 / 59.976 | 36.708 / 37.236 | 26.343 / 26.026 | 29.084 / 29.070 | 198 / 148 | 0 / 0 |
| B/D console | chase | 59.849 / 59.851 | 41.914 / 43.228 | 18.922 / 18.149 | 70.422 / 70.459 | 1 / 1 | 1 / 1 |
| E/F +pacing | title | 60.000 / 60.000 | 57.791 / 57.897 | 17.169 / 17.118 | 17.931 / 17.898 | 0 / 0 | 0 / 0 |
| E/F +pacing | cutscene | 59.999 / 59.996 | 52.366 / 51.327 | 18.656 / 18.718 | 20.920 / 22.123 | 0 / 0 | 0 / 0 |
| E/F +pacing | chase | 59.855 / 59.854 | 45.653 / 46.669 | 17.297 / 17.151 | 65.022 / 64.904 | 1 / 1 | 1 / 1 |
| H/J cache off | title | 60.000 / 60.000 | 58.273 / 57.973 | 17.121 / 17.136 | 17.259 / 17.498 | 0 / 0 | 0 / 0 |
| H/J cache off | cutscene | 60.000 / 59.999 | 52.076 / 52.749 | 18.588 / 18.402 | 21.475 / 21.851 | 0 / 0 | 0 / 0 |
| H/J cache off | chase | 59.852 / 59.849 | 45.990 / 45.851 | 17.167 / 17.244 | 65.783 / 66.806 | 1 / 1 | 1 / 1 |
| I/K cache on | title | 60.000 / 59.999 | 57.425 / 57.884 | 17.085 / 17.108 | 18.647 / 18.160 | 0 / 0 | 0 / 0 |
| I/K cache on | cutscene | 60.000 / 59.999 | 52.408 / 53.526 | 18.616 / 18.497 | 20.438 / 19.333 | 0 / 0 | 0 / 0 |
| I/K cache on | chase | 59.869 / 59.867 | 47.392 / 47.384 | 17.207 / 17.100 | 59.757 / 60.740 | 1 / 1 | 1 / 1 |
| O2/Q2 preparation off | title | 60.001 / 60.000 | 58.190 / 57.978 | 17.083 / 17.141 | 17.980 / 17.720 | 0 / 0 | 0 / 0 |
| O2/Q2 preparation off | cutscene | 59.999 / 60.002 | 52.673 / 54.660 | 18.728 / 18.083 | 19.845 / 18.981 | 0 / 0 | 0 / 0 |
| O2/Q2 preparation off | chase | 59.867 / 59.859 | 45.421 / 46.540 | 17.124 / 17.105 | 60.535 / 61.698 | 2 / 1 | 1 / 1 |
| P/R preparation on | title | 60.001 / 60.000 | 58.229 / 57.841 | 17.096 / 17.116 | 17.344 / 18.006 | 0 / 0 | 0 / 0 |
| P/R preparation on | cutscene | 59.999 / 59.999 | 52.539 / 52.418 | 18.642 / 18.241 | 19.720 / 20.762 | 0 / 0 | 0 / 0 |
| P/R preparation on | chase | 59.999 / 59.687 | 53.786 / 37.034 | 17.089 / 17.127 | 31.121 / 98.255 | 1 / 3 | 0 / 1 |
| T/V cold sync store | title | 60.001 / 60.000 | 58.242 / 58.237 | 17.088 / 17.113 | 17.294 / 17.402 | 0 / 0 | 0 / 0 |
| T/V cold sync store | cutscene | 60.001 / 59.999 | 54.789 / 54.651 | 18.042 / 18.082 | 18.913 / 18.941 | 0 / 0 | 0 / 0 |
| T/V cold sync store | chase | 59.637 / 59.741 | 36.239 / 38.925 | 17.283 / 17.486 | 103.457 / 102.824 | 2 / 1 | 1 / 1 |
| U/W cold async store | title | 59.999 / 60.001 | 58.410 / 58.238 | 17.079 / 17.123 | 17.197 / 17.272 | 0 / 0 | 0 / 0 |
| U/W cold async store | cutscene | 60.001 / 60.000 | 53.697 / 52.825 | 18.233 / 18.037 | 20.181 / 21.785 | 0 / 0 | 0 / 0 |
| U/W cold async store | chase | 59.838 / 59.838 | 43.737 / 45.345 | 17.154 / 17.149 | 69.816 / 70.193 | 2 / 1 | 1 / 1 |
| X/Y warm all on | title | 60.001 / 59.999 | 57.462 / 58.102 | 17.141 / 17.157 | 19.013 / 17.272 | 0 / 0 | 0 / 0 |
| X/Y warm all on | cutscene | 60.000 / 60.001 | 53.564 / 53.526 | 18.309 / 18.095 | 19.713 / 23.383 | 0 / 0 | 0 / 0 |
| X/Y warm all on | chase | 59.999 / 59.999 | 53.901 / 53.196 | 17.092 / 17.106 | 30.359 / 32.876 | 1 / 1 | 0 / 0 |

Displayed intervals (separate compositor output):

| Case | ROI | Avg fps | 1% low fps | p99 ms | Max ms | >25 ms | >50 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A/C off | title | 59.949 / 59.950 | 52.473 / 52.510 | 17.708 / 17.682 | 33.523 / 33.409 | 1 / 1 | 0 / 0 |
| A/C off | cutscene | 60.000 / 59.751 | 56.304 / 41.284 | 17.691 / 17.725 | 17.841 / 33.860 | 0 / 5 | 0 / 0 |
| A/C off | chase | 59.752 / 59.649 | 40.937 / 37.058 | 17.708 / 17.715 | 66.677 / 66.314 | 3 / 4 | 1 / 1 |
| B/D console | title | 60.000 / 59.999 | 56.445 / 56.643 | 17.668 / 17.363 | 17.807 / 17.810 | 0 / 0 | 0 / 0 |
| B/D console | cutscene | 60.000 / 59.950 | 56.461 / 52.254 | 17.691 / 17.712 | 17.768 / 34.375 | 0 / 1 | 0 / 0 |
| B/D console | chase | 59.799 / 59.850 | 43.325 / 45.779 | 17.705 / 17.725 | 66.215 / 66.806 | 2 / 1 | 1 / 1 |
| E/F +pacing | title | 60.000 / 60.002 | 56.416 / 56.398 | 17.691 / 17.691 | 17.762 / 17.781 | 0 / 0 | 0 / 0 |
| E/F +pacing | cutscene | 60.000 / 60.000 | 56.263 / 56.337 | 17.711 / 17.715 | 18.125 / 17.811 | 0 / 0 | 0 / 0 |
| E/F +pacing | chase | 59.849 / 59.801 | 45.928 / 43.363 | 17.706 / 17.725 | 66.212 / 66.719 | 1 / 2 | 1 / 1 |
| H/J cache off | title | 60.000 / 60.001 | 56.418 / 56.352 | 17.691 / 17.697 | 17.767 / 17.807 | 0 / 0 | 0 / 0 |
| H/J cache off | cutscene | 59.949 / 60.000 | 52.419 / 56.374 | 17.679 / 17.700 | 34.007 / 17.830 | 1 / 0 | 0 / 0 |
| H/J cache off | chase | 59.851 / 59.899 | 45.898 / 48.768 | 17.701 / 17.714 | 66.414 / 50.532 | 1 / 1 | 1 / 1 |
| I/K cache on | title | 60.000 / 59.952 | 56.339 / 52.540 | 17.687 / 17.656 | 17.847 / 33.502 | 0 / 1 | 0 / 0 |
| I/K cache on | cutscene | 60.003 / 60.001 | 56.386 / 56.413 | 17.694 / 17.684 | 17.840 / 17.858 | 0 / 0 | 0 / 0 |
| I/K cache on | chase | 59.899 / 59.849 | 49.000 / 45.128 | 17.720 / 17.787 | 49.499 / 50.258 | 1 / 2 | 0 / 1 |
| O2/Q2 preparation off | title | 59.998 / 59.998 | 56.348 / 56.120 | 17.674 / 17.694 | 17.925 / 18.203 | 0 / 0 | 0 / 0 |
| O2/Q2 preparation off | cutscene | 59.949 / 60.000 | 52.649 / 56.087 | 17.683 / 17.690 | 32.820 / 18.140 | 1 / 0 | 0 / 0 |
| O2/Q2 preparation off | chase | 59.800 / 59.902 | 43.464 / 48.944 | 17.717 / 17.742 | 50.009 / 49.645 | 3 / 1 | 1 / 0 |
| P/R preparation on | title | 60.000 / 60.001 | 56.138 / 56.285 | 17.701 / 17.694 | 18.430 / 18.134 | 0 / 0 | 0 / 0 |
| P/R preparation on | cutscene | 60.003 / 59.998 | 56.391 / 56.117 | 17.689 / 17.701 | 17.779 / 18.231 | 0 / 0 | 0 / 0 |
| P/R preparation on | chase | 60.000 / 59.699 | 56.269 / 38.415 | 17.700 / 17.715 | 17.862 / 101.050 | 0 / 2 | 0 / 1 |
| T/V cold sync store | title | 60.002 / 60.001 | 56.460 / 56.000 | 17.683 / 17.717 | 17.776 / 18.216 | 0 / 0 | 0 / 0 |
| T/V cold sync store | cutscene | 59.998 / 60.001 | 56.428 / 55.734 | 17.690 / 17.735 | 17.766 / 18.235 | 0 / 0 | 0 / 0 |
| T/V cold sync store | chase | 59.652 / 59.748 | 36.684 / 40.381 | 17.708 / 17.719 | 83.519 / 99.843 | 3 / 1 | 2 / 1 |
| U/W cold async store | title | 59.999 / 60.000 | 56.509 / 56.084 | 17.666 / 17.699 | 17.753 / 18.734 | 0 / 0 | 0 / 0 |
| U/W cold async store | cutscene | 59.951 / 59.998 | 52.754 / 55.768 | 17.705 / 17.725 | 32.266 / 19.235 | 1 / 0 | 0 / 0 |
| U/W cold async store | chase | 59.850 / 59.851 | 45.698 / 45.869 | 17.690 / 17.729 | 67.178 / 66.238 | 1 / 1 | 1 / 1 |
| X/Y warm all on | title | 59.950 / 60.000 | 52.118 / 56.403 | 17.732 / 17.688 | 32.951 / 17.834 | 1 / 0 | 0 / 0 |
| X/Y warm all on | cutscene | 60.000 / 59.949 | 55.657 / 52.114 | 17.756 / 17.730 | 18.284 / 34.337 | 0 / 1 | 0 / 0 |
| X/Y warm all on | chase | 59.950 / 59.950 | 52.334 / 52.476 | 17.713 / 17.724 | 33.841 / 33.364 | 1 / 1 | 0 / 0 |

All accepted ROIs pass the same exclusive-game and other-process CPU idle
gate. The PresentMon observer exits zero. The observer starts before each CPU
ROI and stops after it; only complete intervals inside the measured window
are used. The 1% low is 1,000 divided by the mean of the slowest ceil(N/100)
intervals; p99 is the linearly interpolated 99th percentile. App and displayed
statistics are never substituted for one another. Full precision, CPU receipts
and observer provenance are retained in `measurements.json` and each run directory.
<!-- WIN-STUTTER-025-RESULTS-END -->

The final cold diagnostic ZB records 5,712,561 events, zero loss and complete
coverage through every ROI end. It has no app interval >25 ms in title or lab.
The chase has two: a 70.707 ms ASTC-demand interval and a 25.238 ms guest
dependency/caller-work interval whose exact signaler remains unresolved. In
the former, GPU-owner thread 3028 spends 43.188 ms decoding and 3.828 ms
copying/enqueuing, inside 54.920 ms of texture preparation. Persistence overlaps
for 38.283 ms on worker thread 6292; it is not producer time to add. The
present call is 0.071 ms, fences total 0.624 ms, and no shader-module or pipeline
creation overlaps either app spike. One lab displayed gap is 32.904 ms despite
its associated app interval being 19.633 ms; the sole chase displayed gap is
66.175 ms and corresponds to the 70.707 ms decode interval. All 383 requests
are cache misses, including the same five oversized outputs. These observations
confirm the moved persistence cost and remaining first-use decode cost;
ZB is diagnostic, excluded from the quiet A/B tables. Full per-frame and
per-thread evidence is in `trace-cold-ZB-trace-analysis.json` and
`final-trace-attribution-B.json`.

On the final executable, both cold synchronous controls T/V have 383 cache
misses and zero hits. Their worst chase app intervals are 103.457/102.824 ms;
with asynchronous persistence U/W they fall to 69.816/70.193 ms. Displayed 1%
lows rise from 36.684/40.381 to 45.698/45.869 fps. Average chase app production
remains 59.637/59.741 versus 59.838/59.838 fps. Title and cutscene app intervals
stay below 25 ms in all four routes; U has one 32.266 ms displayed-only lab gap.
The async routes save all 361/372 accepted jobs, skip 22/11 optional saves at
the queue bound, and report zero write failures. They improve the cold cost,
but do not meet the chase >=50 displayed 1% low / <=50 ms maximum target.

Final warm confirmations X/Y enable all five switches and use W's private
cache on the final executable. Both meet the numeric target in these bounded
ROIs: chase displayed 1% lows are 52.334/52.476 fps, maxima 33.841/33.364 ms;
app lows are 53.901/53.196 fps and maxima 30.359/32.876 ms. No app or displayed
interval exceeds 50 ms in any of the six ROIs. X has one displayed title gap
and Y one displayed lab gap despite no app interval >25 ms there. The cache
records 372/378 hits, 11/5 misses and 81/87 prepared hits over the full routes;
the six late chase requests are prepared hits in both. These are successful
warm confirmations, not new cold controls or proof against R's retained GPU
outlier. Remaining first-use decoding, occasional display pacing gaps and
unresolved GPU/driver stalls prevent a universal hitch-free claim.

On the final executable, SDK/oracle routes LB/MB both explicitly activate
`VK_LAYER_KHRONOS_validation`, retain the same 16 GiB diagnostic guard and reach
the opening lab and File 01 chase in inspected captures. With the five new
switches off/on, the complete observed message multisets match: 45 errors
across the same five inherited VUIDs, nine unused-output warnings, five error
and one warning suppression notice. There are no new observed messages or
VUIDs. Suppression still prevents a zero-error validation claim. MB recomputes
all 378 decoded-cache hits with zero byte/invalid-block mismatches; no
`ORACLE_MISMATCH` or device-loss message is observed.

The MB trace has zero lost events. It measures one 340.761 ms cache-construction
and preparation span at the first texture-loading barrier, including executable
identity hashing. The five persistent misses are four 89,478,496-byte outputs
and one 178,956,992-byte output, all beyond the 64 MiB entry limit; they retain
the original decoder. This startup cost and incomplete caching are intentional
tradeoffs, not removed work.

Inspected off/on title, lab and chase captures retain the expected scene content,
but their animation/camera phases differ; they do not establish matched-pose
pixel parity. The decoded-texture oracle is stronger evidence for the cache's
observed outputs, but does not replace that whole-frame gate. All five switches
remain opt-in: numerical warm success and no new observed validation messages
are not default-promotion approval. `visual-observations-B.json`,
`validation-B-comparison.json`, `acceptance-B.json` and the raw run directories
preserve these separate gates.

The four required unittest commands pass locally with the explicit pinned
`NVN_REFERENCE`: stutter 7 tests (one native CNG skip), shader cache 9, Windows 8
(two native-only skips), builder 55. Native Windows executes six stutter fixtures
including CNG known vectors, executable identity,
Unicode cache I/O/atomic replacement, trace concurrency and console ownership,
FIFO/backpressure/drain, and retained-input asynchronous cache publication with
independent in-flight byte/job bounds and I/O failure; only full-series application
is skipped there and is
checked independently on the Mac. The runtime itself is built natively.
Independent exact-head review and landing belong to the parent; this worker
starts no nested review and makes no public/default/release approval claim.

The supplemental `ReplayTests.test_series_scope_and_opt_in_defaults` still
asserts that the preceding replay overlay is the final Windows entry. It fails
solely on that order after this required append. `tests/test_astral_windows_replay.py`
is outside this unit's exact scope and is left unchanged; the parent must update
that assertion to test relative order before claiming a complete suite pass.
Private `replay-order-scope-check.json` and `proposed-replay-order-test.patch`
retain the failure and a separately executed passing relative-order proposal.
This does not change the four required VERIFY results.

## PC-SHADER-027: versioned cache, recorded prewarm and file-only diagnostics

The strict Windows player now enables the shared versioned Vulkan cache and
recorded-pipeline boot prewarm described in [ASTRAL_SHADER_STUTTER.md](ASTRAL_SHADER_STUTTER.md#pc-shader-027-desktop-portability-and-console-defaults).
The old Windows legacy cache is not an effective warm seed for the new envelope.
The sequence below starts with no application cache or records, then seeds each
fresh data/save root with the immediately preceding run's versioned cache and
records. OS/NVIDIA caches are not purged. Thus "cold" means application-cold,
not a clean driver installation or a new GPU.

All headline routes use the same G4 executable, SHA256
`28a8ebf3800b99d583036b6d5caca613ccbb2be6dd6a9ed847b26feb89589d50`,
`dynamic-60-cap`, 1600×900, and the WIN-REPLAY-024/025 fresh-game input route.
Generated main/SDK archives remain byte-identical to WIN-STUTTER-025B. The old
quiet-O inputs remain explicit: resident=1, narrow writeback=1, flights=1,
chunk draws=150; the five replay switches are unset. ASTC cache and pacing
experiments are off. `NX_WIN_ASYNC_CONSOLE=0` leaves the new shared logger at its
file-only default. `NX_FRAME_LOG=1` records creation spans for attribution in
all runs. Primary `guest.log` retains periodic statistics. Existing generated
`FPS007` diagnostics and SDL messages write directly to stderr; this change
controls shared logger mirroring, rather than deleting those retained diagnostics.

The Windows driver checks `Get-Process astral*`, acquires the exclusive busy
marker, passes the CPU/GPU idle gate, and verifies only its game throughout each
run. No build overlaps a game measurement. The title, lab cutscene and chase
captures precede their ROIs. PresentMon uses the existing primary-swapchain,
QPC/v1 method and 20-second CPU-sampler windows near 45, 175 and 400 seconds.
Only complete intervals inside each window count. Average FPS is reciprocal
mean interval; 1% low is reciprocal mean of the slowest ceiling(1%) intervals;
p99 uses linear interpolation. Displayed intervals exclude dropped presents and
are independently windowed at their display time. App/displayed values remain
separate. A later traced route is diagnostic, excluded from headline comparisons.

Private evidence is `.local/units/PC-SHADER-027/`
and `C:\acr\units\PC-SHADER-027\`. Earlier key-audit/pilot runs are retained and
excluded; the accepted runs have the `pc-` prefix. Cache envelopes are checked
again after collection, and each build has source/generated-archive hash receipts.

### PC-SHADER-027 measured cache sequence

| Run / ROI | App avg / 1% low fps | App p99 / max ms | Displayed avg / 1% low fps | Displayed p99 / max ms | M / G / C calls; overlap ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| pc-cold / title | 60.006 / 39.426 | 21.636 / 31.086 | 59.951 / 52.318 | 17.705 / 32.837 | 0 / 0 / 0; 0.000 |
| pc-cold / cutscene | 60.023 / 37.333 | 26.323 / 27.446 | 60.001 / 56.297 | 17.701 / 18.162 | 0 / 0 / 0; 0.000 |
| pc-cold / chase | 59.864 / 41.154 | 18.903 / 66.506 | 59.850 / 46.012 | 17.702 / 49.009 | 0 / 1 / 0; 0.042 |
| pc-warm1 / title | 60.008 / 40.758 | 21.711 / 26.118 | 60.000 / 56.283 | 17.723 / 17.807 | 0 / 0 / 0; 0.000 |
| pc-warm1 / cutscene | 60.022 / 37.761 | 26.202 / 26.875 | 60.001 / 56.411 | 17.690 / 17.763 | 0 / 0 / 0; 0.000 |
| pc-warm1 / chase | 59.854 / 43.214 | 18.473 / 67.949 | 59.853 / 45.760 | 17.727 / 66.859 | 0 / 0 / 0; 0.000 |
| pc-warm2 / title | 60.010 / 40.362 | 22.121 / 27.290 | 60.000 / 55.925 | 17.709 / 18.700 | 0 / 0 / 0; 0.000 |
| pc-warm2 / cutscene | 60.021 / 37.112 | 26.286 / 27.909 | 59.997 / 56.163 | 17.684 / 18.269 | 0 / 0 / 0; 0.000 |
| pc-warm2 / chase | 59.864 / 43.297 | 18.585 / 66.132 | 59.798 / 43.211 | 17.684 / 66.540 | 0 / 0 / 0; 0.000 |

M/G/C are module/graphics/compute creation API calls intersecting the ROI;
overlap time is clipped to its boundaries. Both warm runs have zero in all ROIs.
The cold title/cutscene were already creation-free, so no shader speedup is
attributed to their steady-state frame timing.

| Run | Warmed / skipped pipelines | Boot prewarm loop ms | Process creation → first present ms | Whole-route runtime M / G / C | Runtime API time ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| pc-cold | 0 / 0 | n/a (no records) | 797.271 | 160 / 419 / 13 | 205.236 |
| pc-warm1 | 432 / 0 | 135.131 | 961.128 | 7 / 4 / 0 | 0.254 |
| pc-warm2 | 436 / 0 | 133.749 | 953.034 | 4 / 2 / 0 | 0.160 |

The timed prewarm loop excludes executable hashing and record-file parsing;
process creation to first present includes that startup work. Cold boot has no
recorded compile loop. Windows process creation time is read from GetProcessTimes,
rather than treating the post-launch harness receipt as the start of the process.

The driver payload is **4,189,052 bytes**. Recipe counts grow **432 → 436 → 438**,
with **160 shader identities** throughout. The four and two remaining whole-route
graphics creations add exactly four and two full-state records, respectively;
their shaders were already known. Module creation uses the existing per-process
shader-pointer/variant cache, so an unseen full-state recipe can also recreate
an already-known shader variant. This is recorded-route coverage, not a promise
to prewarm every future material, animation state or chapter.

Private per-run `cache-analysis.json`, `windows-record-delta.json`, raw PresentMon
CSVs/marks and hash-checked envelopes contain the complete values. All twelve
headline captures show the expected title, lab, character close-up and motorcycle
chase. Animation phases vary; this is a bounded visual check, not pixel equality.

### Prewarm-off control and default decision

`pc-off1` uses the same executable, effective warm driver cache, route and quiet
settings, with only `NX_SHADER_PREWARM=0`. It leaves versioned caching enabled.
Its title/cutscene/chase results are:

| ROI | App avg / 1% low fps | App p99 / max ms | Displayed avg / 1% low fps | Displayed p99 / max ms | M / G / C calls; overlap ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| title | 60.010 / 40.583 | 22.340 / 26.125 | 60.001 / 56.428 | 17.697 / 17.759 | 0 / 0 / 0; 0.000 |
| cutscene | 60.021 / 37.214 | 26.271 / 27.922 | 60.001 / 56.362 | 17.705 / 17.794 | 0 / 0 / 0; 0.000 |
| chase | 59.860 / 41.242 | 18.624 / 68.050 | 59.849 / 45.995 | 17.706 / 50.045 | 0 / 1 / 0; 0.043 |

With prewarm off, whole-route creation returns to 416 graphics / 13 compute / 160 module calls,
taking 57.950 ms inside the creation APIs. The warm prewarm runs
do not show a repeatable frame-time regression against this control, so Windows
keeps prewarm enabled by default. This is a bounded route/control comparison,
not proof of a universal frame-rate improvement. The residual chase hitch and
app-side cutscene pacing remain; pipeline prewarm does not eliminate them.

### Periodic console-cost gate and remaining hitches

The separate `pc-trace` route records **5,714,263 events, zero loss**, and covers
all three ROI ends. It observes **zero shared-logger console spans** and
**29,343 primary-file spans**. Maximum periodic-statistics span is **0.438 ms**
in title, **0.068 ms** in the lab cutscene, and **0.135 ms** in chase. Maximum
cache-save span is **0.0036 / 0.0027 / 0.0031 ms** respectively: normal warm windows
skip serialization. File logging remains present; its maximum individual write
is **0.692 / 0.179 / 1.890 ms** respectively. These diagnostic measurements confirm
removal of the synchronous ~16 ms console-mirroring component found by
WIN-STUTTER-025. Traced frame times are not mixed into the untraced headline table.

This does not remove every >25 ms app interval. The trace has **8 title, 206
cutscene and 1 chase** app intervals above 25 ms, with **0 / 1 / 1 displayed**
intervals above that threshold. Every such app interval has zero overlapping
module/graphics/compute creation. The largest title interval is 26.031 ms,
with guest blocking/pacing and only 0.050 ms of primary-file writes; the largest
cutscene interval is 28.086 ms, also dominated by guest dependency/pacing.
The 67.055 ms chase interval includes **48.469 ms texture preparation, of which
46.000 ms is ASTC work**, while the actual present call is 0.062 ms. The guest
wait overlaps the replay work and must not be added to it. These remaining
bottlenecks are separate from pipeline creation and console mirroring; no draws,
waits or cache validation are bypassed.

Private evidence: `trace-statistics.json`, `pc-trace-trace-analysis.json`,
`runs/pc-trace/trace.bin`, `windows-run-gates.json`,
`windows-final-policy-source-verification.json` and
`windows-desktop-guard-equivalence.json`. Four native Windows translation-unit
comparisons prove that the final Linux-only telemetry/policy and desktop guard
changes preprocess identically to the measured Windows code, including the cache
header. The other 147 public runtime files match the fresh series byte for byte.
Native Windows cache/logging fixtures cover Unicode paths, actual executable
identity, corruption/driver rejection and console opt-in; changing a real driver
or corrupting the live game cache was not part of the performance sequence.

Final G4 observation: AMD EPYC 9B45, 48 logical CPUs, RTX PRO 6000 Blackwell Server
Edition, NVIDIA 596.86, Windows Server 2025 build 26100. After the game routes,
post-run checks find zero games, busy marker, PresentMon processes and owned
scheduled tasks. The exact measured executable is retained and SHA256-verified
on the Mac. Independent review and cloud-resource cleanup remain the lead's work;
this worker does not push, land, publish or remove cloud resources.

## WIN-DEFAULTS-032: default-promotion gate remains open

**No defaults are promoted.** `NX_WIN_PACE_BEFORE`, `NX_WIN_ASTC_CACHE`,
`NX_WIN_ASTC_PREPARE` and `NX_WIN_ASTC_ASYNC_STORE` still require explicit `1`;
unset and explicit `0` remain off. All other experimental switches are unchanged.
The existing versioned pipeline cache, Windows pipeline prewarm and file-only
shared logger keep PC-SHADER-027's policy. This unit does not include PC-ASYNC-PSO-029.
The historical approximately 52 fps warm displayed chase low is not established
for a player using actual defaults.

Enabling only the requested stutter family with the older experimental inputs
unset records warm displayed chase 1% lows of **28.075 / 29.297 fps**. It does
not reproduce the faster quiet-O result. Performance, drawing parity and disk
eviction therefore remain separate unmet promotion gates.

Current main `4678bdb46959890a41314cc0a0eec04605024a07` was rebuilt on the G4.
All 151 public runtime files match a fresh complete Windows-series reconstruction.
The unchanged generated main/SDK archives have SHA256
`08f82b2c2bfe78d0f3dce35cbbd55be3590542ef348507ef0f414fc4d2f5f789` /
`1f19cf2adbc83e897fe54d550bc44b2488645117d5f00e43605ad3f04a61676f`.
The uninstrumented player is SHA256
`6768da410b23a1752bff3ad8d480fc99ceeb7edbb10b461faa974d3238cc7ea5`.
Private evidence is `.local/units/WIN-DEFAULTS-032/`
and `C:\acr\units\WIN-DEFAULTS-032\`. Diagnostic changes, generated overrides,
executables, fresh-save roots, cache contents and captures remain private.

### Guest-update capture controls and their limits

The private observer counts completed guest timer-update calls at the existing
end-of-call diagnostic in `main_00907A10`. Inputs use that count divided by 60,
including the initial title-confirmation presses; captures trigger at counts
2,160 / 9,000 / 14,520 / 22,500. These select the title prompt, opening lab
cutscene, character close-up and File 01 chase. Each run starts without a save.
Full-resolution 1600×900 RGB PPMs are compared directly, with zero tolerance,
no resizing, alignment, exposure adjustment or excluded pixels. The observer
records every guest delta and its cumulative sum as well as capture/update and
present indices. A matching presentation filename alone is not the control.

The first observer leaves guest clocks and memory unchanged. Its executable is
SHA256 `68093da0412a35b6564b3e80e4f73a90772b962ca1dd4368e809944b663f4b3d`.
The off/off repeat reaches each exact capture index, but **none of its four
frames is identical**. The measured dynamic timestep accumulates different
simulated time despite equal call counts:

| Off/off scene / update | Changed pixels of 1,440,000 | RGB MAE | Maximum channel error | Second minus first cumulative guest ticks |
| --- | ---: | ---: | ---: | ---: |
| title / 2,160 | 248,589 | 0.862465 | 250 | -6.896944 |
| opening cutscene / 9,000 | 1,099,963 | 5.453521 | 241 | -5.586214 |
| character / 14,520 | 74,831 | 0.281945 | 215 | -10.205283 |
| chase / 22,500 | 1,401,086 | 25.123890 | 244 | -16.802347 |

Guest ticks here are units of 1/30 second; the chase discrepancy is approximately
0.560 seconds. This demonstrates a control problem, not a rendering regression
caused by a switch. It explains why update-index matching alone cannot establish
matched-pose parity; it does not prove that every differing pixel is timing-only.
`natural-repeatability.json` retains all frame paths, indices, deltas and metrics.

A second private diagnostic controls the timer outputs after each update:
delta=0.5, fractional carry alternates 0.5/0, integer ticks alternate 0/1 and
measured milliseconds=1000/60. Inputs and captures retain the same guest-update
counter. Its executable is SHA256
`8acdec57a7ffe9950e64260c37a9f0800939648d6b5990e50c22bc3282291d64`.
This deliberately changes guest timer state for a diagnostic; it is not a player
build or a performance result. Even its clean off/off title repeat differs in
**11,678 pixels (0.810972%)**, RGB MAE **0.103101**, maximum channel error **195**.
Both captures are at update 2,160 with controlled 0.5-step advancement. Residual
differences remain unexplained. After these two attempts the premise of a
deterministic whole-frame capture is not established, so neither optimization
passes the promotion gate. `fixed-off-off-title-diff.json`, the two
`runs/pilot-fixed-off*/` directories and `parity-fixed-build-receipt.json` retain
the exact limitation; the diagnostic is not treated as proof for live clocks.

The initial handoff between capture drivers briefly overlapped two diagnostic
games. Both were stopped, excluded and retained as
`diagnostic-contended-cache-train` / `diagnostic-contended-pilot-fixed-off1`;
their cache seed was quarantined too. Earlier off/off controls finished before
that overlap. An atomic run-start guard now serializes launches in addition to
the shared busy marker and game-process checks. Accepted subsequent routes use
one driver and one game. `contamination.json` and the two stop receipts document
the error rather than silently admitting these runs into a comparison.

### Switch-by-switch whole-frame differences

All pairs below use the first natural-clock off run as their reference and hit
the exact requested guest-update index. The cache group includes preparation
and background persistence; verification is off so cache hits supply the rendered
texels. Only the pacing-only opening-cutscene pair is pixel-identical. The other
11 pairs remain insufficiently explained for promotion, alongside the failed
off/off controls above. These are not claimed as switch-caused rendering defects.

| Switch / scene / update | Changed pixels | RGB MAE | Max channel error | Cumulative guest-step difference |
| --- | ---: | ---: | ---: | ---: |
| cache / title / 2,160 | 248,939 | 0.888367 | 250 | -6.771023 |
| cache / opening-cutscene / 9,000 | 992,594 | 3.402069 | 184 | -6.787647 |
| cache / character / 14,520 | 338,960 | 1.797843 | 234 | -11.575879 |
| cache / chase / 22,500 | 1,401,015 | 28.006880 | 241 | -24.200455 |
| pace / title / 2,160 | 244,720 | 0.870339 | 243 | -7.214271 |
| pace / opening-cutscene / 9,000 | 0 | 0.000000 | 0 | -7.635292 |
| pace / character / 14,520 | 174,125 | 0.489167 | 234 | -11.512802 |
| pace / chase / 22,500 | 1,414,352 | 28.264514 | 241 | -21.901062 |
| both / title / 2,160 | 244,880 | 0.874868 | 243 | -7.160338 |
| both / opening-cutscene / 9,000 | 992,594 | 3.402069 | 184 | -7.027383 |
| both / character / 14,520 | 331,712 | 1.659980 | 234 | -11.260590 |
| both / chase / 22,500 | 1,409,427 | 26.528795 | 244 | -24.718506 |

`parity-report.json` contains all 20 per-frame comparisons, including the
off/off repeat and cold training route, exact PPM paths and SHA256 values,
guest deltas, integrated steps and presentation indices. A separate determinism
unit must first establish off/off whole-frame repeatability before a further
default-promotion attempt.

Native Windows runs the eight-test stutter suite: seven pass and the full-series
reference integration is skipped; the latter passes locally against the pinned
reference. Actual CNG vectors/executable hashing, Unicode cache I/O, atomic
publication, queue bounds and the new sparse 4 GiB/file-cap fixture pass.
The three required local commands pass: stutter 8 tests/1 native-CNG skip,
Windows 8 tests/2 native-platform skips, builder 55 tests/0 skips.

The capture-route decoded cache contains **341 files / 1,560,832,840 bytes**,
with **zero pending temporary bytes**, below both configured caps. This is
the diagnostic executable’s private cache, not a portable player cache.
Private receipts: `parity-astc-disk.json`, `native-stutter.log`,
`verify-final.json` and `result-audit.json`.

### Decoded-cache disk policy

The production cache has **no eviction implementation**. Its configured bounds
are 64 MiB decoded payload per entry, 4,096 published files and 4 GiB published
bytes, plus one bounded temporary file. Preparation owns at most 192 MiB;
queued and in-flight persistence together own at most 128 MiB and 16 jobs.
At the file or byte cap, new persistence is refused. An over-cap directory at
startup disables cache keys and persistence; it is not pruned automatically.
This falls back to decoding but cannot satisfy an eviction acceptance claim.
Keys include the whole executable, so entries from obsolete builds also consume
this shared disk budget and are not removed automatically.

The added executable fixture uses synthetic files and the real production
limits: 4,096 existing entries refuse another save; a sparse file leaving one
byte too little capacity refuses a save; a directory one byte above 4 GiB
disables key creation and saving. Existing files remain intact and no temporary
file is created on these refusals. The pacing fixture also explicitly tests an
environment with the pacing/replay variables absent, rather than substituting
an empty string for an unset variable. No default-promotion tests are claimed
because the promotion gate did not pass.

<!-- WIN-DEFAULTS-032-PERF -->
### Exact-main PresentMon results with defaults unchanged

These windowed 1600×900 dynamic-60-cap routes use the exact main executable and the
WIN-STUTTER-025 QPC/v1 primary-swapchain method. Each ROI is the complete app
and independently windowed displayed intervals inside the 20-second CPU-only
sampler window near 45 / 175 / 400 seconds. The 1% low is the reciprocal mean
of the slowest ceiling(1%) intervals, not the reciprocal p99. Captures precede
ROIs. Every accepted ROI passes the idle/process and observer-output checks.

`perf-*` retains the historical explicit quiet-O inputs: resident=1, narrow
writeback=1, flights=1, chunk draws=150. `perf-cold/warm1/warm2` additionally
enable pacing, decoded caching, preparation and background persistence;
`perf-off1` explicitly disables those four switches with the warm shader seed.
`default-*` leaves all of those experimental variables unset. It therefore
measures the current player defaults rather than relabeling quiet-O as defaults.
Supplementary candidate-warm runs, if listed, enable only the four requested
stutter switches with the older experimental inputs absent. They are explicit
opt-in proxy measurements of the proposed combination, not a changed-default
build. No corresponding candidate-cold run is claimed.
The shared logger remains file-only; common route/measurement diagnostic
settings are retained across these runs. No build or second game overlaps an accepted ROI.

Cold means empty application caches; NVIDIA/OS caches are not purged. Warm
runs copy the preceding performance run’s versioned driver cache and pipeline
records and reuse the same executable’s decoded cache where enabled.

| Run / ROI | App avg / 1% low fps | App p99 / max ms | Displayed avg / 1% low fps | Displayed p99 / max ms |
| --- | ---: | ---: | ---: | ---: |
| perf-cold / title | 60.001 / 55.994 | 17.540 / 18.150 | 60.000 / 55.980 | 17.672 / 18.311 |
| perf-cold / cutscene | 60.005 / 54.178 | 18.085 / 19.288 | 59.999 / 55.881 | 17.700 / 19.421 |
| perf-cold / chase | 59.836 / 40.015 | 17.037 / 70.725 | 59.798 / 43.466 | 17.741 / 65.796 |
| perf-warm1 / title | 60.000 / 56.291 | 17.133 / 19.769 | 60.001 / 56.216 | 17.645 / 18.209 |
| perf-warm1 / cutscene | 60.004 / 54.706 | 17.968 / 18.718 | 60.001 / 56.406 | 17.686 / 17.823 |
| perf-warm1 / chase | 60.001 / 54.212 | 17.046 / 32.102 | 60.001 / 56.139 | 17.744 / 18.102 |
| perf-warm2 / title | 60.000 / 58.368 | 17.052 / 17.262 | 59.999 / 56.172 | 17.665 / 18.158 |
| perf-warm2 / cutscene | 60.001 / 53.950 | 18.323 / 18.831 | 60.000 / 56.075 | 17.716 / 18.177 |
| perf-warm2 / chase | 59.999 / 53.433 | 17.277 / 32.387 | 60.001 / 55.935 | 17.746 / 18.294 |
| perf-off1 / title | 60.008 / 39.851 | 22.266 / 28.253 | 59.999 / 56.907 | 17.399 / 17.742 |
| perf-off1 / cutscene | 59.975 / 36.987 | 26.344 / 28.901 | 59.951 / 52.416 | 17.749 / 33.297 |
| perf-off1 / chase | 59.857 / 42.710 | 18.817 / 67.703 | 59.851 / 45.819 | 17.726 / 66.423 |
| default-cold / title | 60.007 / 41.080 | 22.221 / 25.923 | 60.000 / 56.040 | 17.726 / 18.492 |
| default-cold / cutscene | 55.971 / 37.392 | 26.445 / 27.417 | 55.947 / 29.452 | 33.855 / 34.169 |
| default-cold / chase | 51.776 / 31.345 | 25.275 / 70.431 | 51.792 / 25.823 | 33.977 / 83.581 |
| default-warm1 / title | 59.995 / 40.573 | 22.494 / 25.801 | 60.000 / 56.045 | 17.688 / 18.208 |
| default-warm1 / cutscene | 56.024 / 36.970 | 26.852 / 27.519 | 55.997 / 29.501 | 33.744 / 34.288 |
| default-warm1 / chase | 51.711 / 33.347 | 25.315 / 71.010 | 51.692 / 26.706 | 34.184 / 66.786 |
| default-warm2 / title | 59.993 / 39.714 | 22.751 / 27.663 | 60.000 / 56.224 | 17.699 / 18.157 |
| default-warm2 / cutscene | 56.522 / 36.734 | 26.678 / 28.658 | 56.495 / 29.425 | 33.824 / 34.382 |
| default-warm2 / chase | 51.791 / 33.401 | 25.117 / 72.468 | 51.793 / 26.984 | 33.939 / 66.842 |
| candidate-warm1 / title | 60.000 / 56.864 | 17.128 / 18.221 | 60.003 / 56.581 | 17.416 / 17.768 |
| candidate-warm1 / cutscene | 55.713 / 41.759 | 23.496 / 24.807 | 55.696 / 29.359 | 33.863 / 34.533 |
| candidate-warm1 / chase | 51.626 / 37.433 | 25.047 / 39.760 | 51.636 / 28.075 | 34.037 / 49.817 |
| candidate-warm2 / title | 60.001 / 58.090 | 17.098 / 17.458 | 60.000 / 56.377 | 17.668 / 17.885 |
| candidate-warm2 / cutscene | 55.815 / 41.216 | 23.937 / 25.786 | 55.848 / 29.384 | 33.820 / 34.721 |
| candidate-warm2 / chase | 50.587 / 36.550 | 25.476 / 41.572 | 50.592 / 29.297 | 33.952 / 34.453 |

With only the requested stutter family enabled, the supplementary warm chase
displayed 1% lows are **28.075 / 29.297 fps** (averages **51.636 / 50.592 fps**).
This combination does not reproduce the approximately 52 fps low with the older
experimental inputs left at defaults. The faster quiet-O cohort retains those
older inputs; its result cannot be attributed to changing only the requested
defaults. This is an additional performance limitation alongside the open
drawing-parity and eviction gates.

Peak other-process CPU in these ROIs is **1.567%**
of total machine capacity. `measurements.json`, per-run PresentMon CSVs, CPU
marks, effective switches, cache-seed hashes and process logs retain the values.
The cold first-decode hitch is reported separately from warm behavior and is
not repaired by this unit. Numeric warm success does not close the drawing
parity or eviction gates, and no default is promoted.

### Vulkan validation and disk closeout

Both SDK routes explicitly activate VK_LAYER_KHRONOS_validation. Off/on record
**45 / 45 errors** and **9 / 9 warnings**.
Observed error-message multisets match: **True**;
warning-message multisets match: **True**.
New error VUIDs / error messages / warning messages: **0 / 0 / 0**.
These are observed messages under the layer’s duplicate suppression, not a
zero-error validation claim. The same 16 GiB diagnostic guard and writeback
oracle apply to both; these diagnostic runs are excluded from performance rows.

The on route recomputes **378** decoded-cache hits; byte/invalid-block
mismatches are **0**. Private `validation-comparison.json` and
the full per-run logs preserve the activation, message multisets, suppression
notices and decoder/oracle counters.

After the full player route and SDK confirmation, the player-executable ASTC
cache holds **378 files / 1,605,223,232 bytes**, with **0 pending bytes**.
It is below the **4,096-file / 4,294,967,296-byte** published-cache caps.
The production eviction policy is still absent, as tested/documented above.
This is explicit opt-in disk use; the current defaults do not enable this cache.
Private `main-astc-disk.json` records every member’s size and SHA256.

Independent exact-head review and landing remain the lead’s responsibility.
No nested reviewer, branch push, public change, release or cloud-resource change
is performed by this unit. Private ignored evidence is retained.

Final closeout at **2026-10-21T19:51:14Z** finds zero games, no busy marker,
zero PresentMon processes and zero owned scheduled tasks. The **19 accepted
run lifetimes have no overlaps**, and all **27 performance ROIs** pass their
idle/process/observer checks. The two contaminated diagnostics remain excluded.
The retained **68,573,696-byte** player executable on the Mac matches the measured
SHA256 above. Evidence: `closeout.json`, `result-audit.json`, `hardware.log`,
`default-policy.json` and `visual-observations.json` in the private unit folder.
<!-- WIN-DEFAULTS-032-PERF-END -->

## WIN-GATE-034: practical gate failed; defaults remain opt-in

The owner dropped whole-frame pixel equality on 2026-10-21. Natural off/off
repeats in WIN-DEFAULTS-032 differ by 75k–1.4M pixels at the same guest-update
index. The replacement gate requires no new Vulkan messages, byte-exact
oracles, sampled visual review, ten minutes of chase/following combat or tutorial
play, and private-byte growth within 10% of off plus a bounded disk cache.

**No defaults are promoted by this unit.** The actual eight-default experimental
Windows build fails ordinary stability at its existing 8 GiB memory guard.
The final branch retains all eight existing opt-in policies; explicit `0`
still disables each setting. The proposed default diff is retained privately
for a follow-up after the memory failure is resolved.

| Variable | Tested experimental unset value | Final branch unset value |
| --- | ---: | ---: |
| `NX_RESIDENT` | `1` | `0` |
| `NX_NARROW_WRITEBACK` | `1` | `0` |
| `NX_FRAMES_IN_FLIGHT` | `1` | `0` |
| `NX_SUBMIT_CHUNK_DRAWS` | `150` | `0` |
| `NX_WIN_PACE_BEFORE` | `1` | `0` |
| `NX_WIN_ASTC_CACHE` | `1` | `0` |
| `NX_WIN_ASTC_PREPARE` | `1` | `0` |
| `NX_WIN_ASTC_ASYNC_STORE` | `1` | `0` |

### Actual experimental build and gate evidence

The G4 executable SHA256 is
`461fadd4c627eb3d9aa9e83cc9b0f10ef17a5b14c4270d718e4d28304ffa72ad`.
All eight variables are genuinely absent in its default-cold/warm1/warm2 and
validation/stability candidate receipts. The control is this same executable
with all eight explicitly zero. This tests compiled defaults, rather than an
opt-in proxy. Its complete public runtime reconstruction has 152 matching
files; the later rebase onto main `869090b` adds Linux-only staging. Of the
153 rebased public files, 151 are byte-identical, the changed Windows translation
unit has identical native clang-cl preprocessor tokens, and the additional Linux
header is unused on Windows. Generated main/SDK archives are unchanged.
The experimental source/diff and build are retained privately; the final branch
removes the promotions, so these performance rows are **candidate observations,
not measurements of a newly promoted shipping default**.

Private evidence is
`.local/units/WIN-GATE-034/` and
`C:\acr\units\WIN-GATE-034\`. Every game launch checks `astral*`, owns the
shared busy marker and atomic launch guard, passes the quiet gate, and records
continuous process/memory samples. Only this unit's VM directory is written.

1. **Vulkan validation: PASS for the measured route.** Both full SDK routes
   report the same 45 inherited errors and nine warnings. Error and warning
   message multisets match; no new VUIDs or message strings are observed.
2. **Byte oracles: PASS for that route.** All 365 reported ASTC cache hits are
   verified byte for byte, with zero mismatches and five misses. The candidate
   records 148,200 changed-word checks over 410,333,992 bytes with zero mismatches
   and 21,000 changed-block checks over 219,661,413,952 bytes with no mismatch
   messages. The off route records 57,000 changed-word checks with zero
   mismatches. Diagnostic SDK routes use a common 16 GiB guard.
3. **Sampled visual review: PASS.** Paired title, opening cutscene, character
   and chase captures, plus five 12-frame sequences per validation route, show
   no new missing/extra geometry, wrong textures, depth defect or flicker.
   Actor/camera/credit phase varies; credit bars also occur in off. This is
   sampled review, not whole-frame equality or an unseen full A/V claim.
4. **Ordinary stability: FAIL for the eight-switch candidate.** With the normal
   unset 8 GiB guard, it logs `8.31 GB ... over the 8.0 GB limit` during the
   chase-to-street transition and terminates near elapsed 681–683 seconds,
   roughly 307 seconds into the required 600-second window starting at 375.
   The process watcher observes 8,920,133,632 private bytes. This is a guard
   termination, not a completed stability run. An earlier all-eight-zero
   ordinary attempt also stops at 8.18 GiB, near 791 seconds; it does not pass.
5. **Memory-growth gate: INCOMPLETE.** The candidate exits before its final
   60-second sampling window, so no passing 600-second growth ratio exists.
   A reference-only off run uses a 16 GiB termination threshold to finish: its
   first/last 60-second private-byte means over elapsed 375–975 are
   6,869,077,196.8 / 7,597,568,546.1 bytes, growth 728,491,349.3 bytes, peak
   8,591,290,368 bytes, with 299 samples. The 10% growth allowance would be
   801,340,484.3 bytes. Raising that diagnostic reference threshold does not
   make either ordinary 8 GiB attempt pass.

The retained implementation adds only an **opt-in diagnostic**:
`NX_WIN_WRITEBACK_VERIFY=1` executes the production changed-word merge on owned
scratch copied from each real route range, checks an independent scalar
reference, then executes the real guest merge. Guest writes cannot race the
diagnostic destination. Existing `NX_NARROW_WRITEBACK_ORACLE=1` changed-block
checks now report cumulative counts. Randomized/guard-page scalar and AVX2
contracts and an injected unchanged-word clobber test exercise the checker.
Neither diagnostic is enabled in ordinary performance/stability measurements.
No macOS/Linux patch input or series changes; this overlay is Windows-only.

The private route driver was corrected after held/pulsed trigger pilots failed
to progress beyond the carrier Shoot encounter. A virtual Xbox pad supplies
analog lateral movement and short RT presses; the off reference clears the
carrier, reaches the street crash cinematic, then the on-foot Move/Dash/Camera
tutorial and Meet up with Akira objective. An image-condition handler closes
the blue tutorial panel with Plus on the owned foreground game window. It was
introduced at off elapsed 889 after the first guide appeared at 735; this late
dismissal limits phase matching of the off reference. The candidate handler
is already running, but the candidate exits before the guide. Earlier
SSH-interrupted, 25-second capture-timeout and traced diagnostic attempts are
retained separately and supply no headline stability/performance result.

The single-variable follow-up uses the same experimental executable with only
`NX_WIN_ASTC_CACHE=0` and the other seven variables absent. It also terminates
at the normal guard: **8.05 GiB**, between elapsed 677.4 and 679.4 seconds,
before the required 600-second window completes. Disabling the cache also
prevents its dependent preparation/store allocations; this is insufficient to
avoid the termination. No single failing switch has been isolated, and no
reduced set has passed the full practical gate or its required new-build
cold/two-warm matrix. A memory-peak/guard follow-up is required before promotion.

The retained decoded cache has **538 files / 2333561056 bytes**, below
its 4096-file / 4294967296-byte cap, with 0 pending bytes.
This disk-cap check passes; it does not override the failed stability gate.

### Candidate cold and warm performance

These pre-failure observations use WIN-DEFAULTS-032's fresh-save route, windowed
1600×900 `dynamic-60-cap`, primary-swapchain PresentMon QPC/v1 selection and
CPU-only 20-second windows near 45 / 175 / 400 seconds. All 12 ROIs pass the
quiet/PresentMon bracketing checks. Frame/resident/GPU/SVC telemetry, input
recording and audio dumping are absent in this quiet cohort. Those diagnostics
differ from the older WIN-DEFAULTS-032 cohort, so the fresh same-binary off-warm
control below is the direct comparison. Async console remains off.

Cold means empty application caches, without purging OS/NVIDIA caches. Warm
runs copy the preceding versioned Vulkan cache/pipeline records and share the
isolated decoded cache root. FPS is reciprocal mean interval; 1% low is the
reciprocal mean of the slowest ceiling(1%) intervals. App and displayed intervals
are selected independently; dropped app presents remain in app statistics.

| Experimental run / ROI | App avg / 1% low fps | App p99 / max ms | Displayed avg / 1% low fps | Displayed p99 / max ms |
| --- | ---: | ---: | ---: | ---: |
| default-cold / title | 60.000 / 57.681 | 17.090 / 18.768 | 59.999 / 56.916 | 17.400 / 17.776 |
| default-cold / cutscene | 60.000 / 53.948 | 18.069 / 20.019 | 60.000 / 56.186 | 17.699 / 18.353 |
| default-cold / chase | 59.838 / 43.132 | 17.036 / 70.435 | 59.847 / 45.910 | 17.742 / 49.769 |
| default-warm1 / title | 60.001 / 56.421 | 17.176 / 19.233 | 60.002 / 56.432 | 17.677 / 17.776 |
| default-warm1 / cutscene | 59.999 / 54.342 | 18.120 / 18.864 | 59.996 / 56.002 | 17.727 / 18.222 |
| default-warm1 / chase | 60.001 / 53.451 | 17.001 / 32.690 | 60.000 / 56.283 | 17.741 / 17.826 |
| default-warm2 / title | 60.001 / 57.625 | 17.081 / 18.631 | 59.999 / 57.006 | 17.395 / 17.904 |
| default-warm2 / cutscene | 60.000 / 52.928 | 18.407 / 20.614 | 59.999 / 56.433 | 17.675 / 17.788 |
| default-warm2 / chase | 59.998 / 53.164 | 17.322 / 32.126 | 60.001 / 56.356 | 17.715 / 17.797 |
| off-warm / title | 59.994 / 40.691 | 22.590 / 25.892 | 60.000 / 55.922 | 17.709 / 18.310 |
| off-warm / cutscene | 58.666 / 37.388 | 26.219 / 27.976 | 58.648 / 29.712 | 33.365 / 33.935 |
| off-warm / chase | 54.024 / 34.109 | 24.510 / 70.951 | 54.045 / 25.918 | 33.895 / 83.695 |

`validation-comparison.json`, `visual-observations.json`,
`candidate-stability-failure.log`, `memory-stability.json`, `measurements.json`,
`source-provenance.json`, `windows-rebase-equivalence.json`,
`other-platform-policy.json`, `verify.json` and per-route raw archives retain
the evidence under the private unit root. The eight-switch set is not eligible
for promotion from these results. A reduced set needs its own actual flipped
build, all practical gates and cold/two-warm measurements. Independent review
and landing remain the parent's responsibility; no nested review is started or
waived, and this unit makes no push, public release or cloud-resource change.

The final source passes all six required unittest commands (7 / 6 / 9 / 10 / 8 /
55 tests; platform skips are recorded in `verify.json`). Supplemental native
Windows perf, resident, writeback and stutter suites also pass, including the
real CNG fixture. `failure-audit.json` records the exact binary/switch receipts,
nine run lifetimes without overlap, the 12 quiet bracketed performance ROIs,
and both failed candidate lifetime bounds. The unit ends without promoting a
switch set; a passing test suite is not a passing product stability gate.
