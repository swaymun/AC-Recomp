# NVN indirect draws, command fences and raster state

NVN-GAPS-014 adds `runtime/patches/astral-nvn-gaps.patch` to the pinned
SuperMarioWonderRecomp runtime (`010ed7a596a621c15d3a8dfa5795ca8c3668b066`).
Private audit details and game-derived evidence remain under
`.local/units/COVERAGE-008/` and `.local/units/NVN-GAPS-014/`.

## Implementation

`nvnCommandBufferDrawElementsIndirect` records the primitive, index type,
index-buffer base address and indirect-record address. It reads the packed
20-byte `{count, instanceCount, firstIndex, baseVertex, baseInstance}` record
**during replay**. Prior submissions have already applied their compute write-backs
at replay begin. A checkpoint submits and waits only when an earlier dispatch in
the current replay wrote the 20-byte argument record. CPU widening of GPU-written
8-bit indices also requires a checkpoint; 16/32-bit indices keep using the
existing GPU-ordered `written_read` path. A fresh host command buffer continues
the same NVN replay state and render targets when a checkpoint is necessary. The draw then uses the existing indexed
Vulkan draw path, adding `firstIndex * indexSize` to the index-buffer address.
Signed base vertex, base instance, all three index sizes, unaligned argument
loads and zero-count/zero-instance draws are covered. The single-draw API has
no stride argument; multi-draw/count APIs are outside this patch.

This conditional CPU readback avoids guessing the index upload range before a
GPU-generated count is known and supports CPU widening of 8-bit indices.
CPU-produced arguments with ordinary indices no longer synchronize the GPU.
`NX_COMPUTE_SEPARATE` retains the conservative checkpoint because that diagnostic
mode does not track written ranges. A later
optimization can keep arguments and a bounded index range on the GPU and use
`vkCmdDrawIndexedIndirect`; it must preserve compute-write ordering. The patch
also preserves zero instance counts in the existing direct Vulkan draw call.

`nvnCommandBufferFenceSync` records a retained completion object. Submission
arms fences recursively through called lists and captures a separate completion
for every execution. A reused list or sync cannot be released by an older
execution's signal. Submissions with command fences wait for their Vulkan fence
and apply write-backs before publishing completion, including in pipelined mode.
Both NVN conditions conservatively wait for all work in that submission; signaling
at the end of the submission can be later than the recorded marker. This favors
correctness over overlap. Invalid fence conditions/syncs and GPU submission or
completion failures fail visibly.

Command-fence `nvnSyncWait` returns ALREADY_SIGNALED (0), CONDITION_SATISFIED (1)
or TIMEOUT_EXPIRED (2), honors zero and finite nanosecond timeouts and an infinite
`UINT64_MAX` timeout, and retains pending state safely across sync finalization.
The older queue-fence wait implementation is otherwise unchanged; this patch
does not claim to repair its pre-existing timeout policy or add multiple host queues.
NVN requires submitted command lists to remain immutable until completion.

`SetAlphaRef` reads AArch64 `s0`, records the float and preserves it in replay.
The offline translator's `StaticGpuAccessor` hard-codes `AlphaTestOp.Always`;
`SupportBuffer::alpha_test` is declared but unused. It is therefore unsafe to
assume the translated shaders already honor NVN color-state alpha tests.
The patch instruments translated fragment SPIR-V at normal entry-point exits:
NEVER kills the fragment; LESS, EQUAL, LEQUAL, GREATER, NOTEQUAL and GEQUAL compare
location-zero output alpha against a float specialization constant and discard
failed fragments. ALWAYS/default leaves the module unchanged. NOTEQUAL uses an
unordered comparison, preserving the NaN inequality case. EarlyFragmentTests is
removed for active alpha tests so discarded fragments do not write depth/stencil.
Helper-function returns are not modified. An active unsupported output layout or
conflicting specialization identifier fails visibly. The pipeline/module cache
keys and Mac pipeline-recipe serializer include the required state.

`SetLineWidth` also reads `s0` and records the value. Pipeline width is clamped
to the device's advertised range when `wideLines` is enabled; devices without
that feature use one pixel. Invalid/nonfinite widths fail visibly. NVN's observed
upper-left window-origin mode (1) now has explicit Set/Get handlers preserving
the existing viewport, winding and presentation convention. Lower-left mode
fails visibly: implementing it also requires coordinated scissor, copy and
presentation changes and is a follow-up.

## Integration order

Activation remains deferred after NVN-PERF-015: see the measured performance
gate below. Once it clears, place `astral-nvn-gaps.patch` immediately after
`astral-shader-cache.patch` in macOS and Linux. Windows is lead-owned; its exact
line is also `astral-nvn-gaps.patch`, after the shader-cache prerequisite and
before `astral-linux.patch`. Proposed tails (retain all earlier entries):

macOS:

```text
astral-texel-coalesce.patch
astral-shader-cache.patch
astral-nvn-gaps.patch
```

Linux:

```text
astral-texel-coalesce.patch
astral-shader-cache.patch
astral-nvn-gaps.patch
astral-linux.patch
```

Windows:

```text
astral-texel-coalesce.patch
astral-shader-cache.patch
astral-nvn-gaps.patch
astral-linux.patch
windows-native.patch
astral-windows.patch
```

The shader-cache dependency supplies the Mac-only pipeline-recipe serializer
hunk; its runtime integration remains Apple-only. Other existing differences
between platform series, including audio overlays, are not changed by this unit.
The private Windows build also checks that applying the gap patch after the
Windows overlays composes successfully.

## Verification

```sh
python3 -m unittest discover -s tests -p 'test_astral_nvn_gaps.py'
```

The tests apply real patches to a fresh pinned public runtime with no downloads
or game data. They compile and execute the production recording/indirect replay
and command-fence paths with synthetic adapters, validate all eight alpha-test
functions plus default SPIR-V with `spirv-val`, syntax-check all eight changed
C++ translation units, and check Linux/Windows overlay composition. They require
an existing `NVN_REFERENCE` (default: the private build's clean upstream clone),
C++ compiler, Vulkan headers (`NVN_VULKAN_INCLUDE`) and SPIRV-Tools.

NVN-PERF-015 expands this to **seven tests**, including conditional checkpoint
selection and overflow/padding/upload-ring allocation boundaries. All seven pass. SPIR-V
validation covers all eight functions; the hardware route below exercises ALWAYS
and GREATER, not every comparison function. Tests do not contact the VM.

## Hardware evidence and visual limits

Fresh runtime builds compiled 88 Mac and 85 Windows runtime translation units,
reusing unchanged private generated-game archives. The route binaries use the
patch against main `d44c4bd`; the final rebase adds the concurrently landed Dynamic
FPS changes. Overlay application and compilation of the changed translation units
were rechecked against that newer main; the full route binaries precede that landing.

The real Apple-silicon Mac completed a **485.086-second**, headless, muted route
through character setup and the opening motorcycle chase. Its final binary SHA-256
is `76420e9ab19677d5f1b14bc945d89111a6dbf66a94b2586348ce2add759ed464`.
The private receipt reports exit 0, bounded termination and no remaining process
group. **118 frames** were captured. There are **zero FATAL/CRASH lines** and zero
first-call fallback witnesses for all five targeted APIs (indirect draw, command
fence, alpha reference, line width and window origin).

Eight capped positive indirect-draw witnesses include **54 indices × 50 instances**,
then **4 indices × 50 or 100 instances**. Eight capped command-fence witnesses report
completion after GPU submission. These are witnesses, not total call counts.
Alpha-test modes observed on draws are **8 (ALWAYS)** and **5 (GREATER)**, the latter
with reference **0.00392157 (1/255)**. The active alpha test is therefore required
on the measured route; treating the reference as advisory is not justified.

Private Mac evidence:

- `.local/units/NVN-GAPS-014/runs/mac-route-hwopus/{guest.log,receipt.json,config.json}`
- `.local/units/NVN-GAPS-014/mac-measurements.json`
- `.local/units/NVN-GAPS-014/mac-comparison.png` and `visual-comparison.json`

Compared this unit's frames **10200** (profile) and **13080** (chase) with
RENDER-009's `fixed-profile-02` captures, retained by COVERAGE-008 under
`reused-route/`. Character/profile UI, motorcycle, tunnel and tutorial are present.
The patched chase also visibly includes enemies, bullets, rock debris and explosions.
Material/decal artifacts remain. The captures have different camera/menu state
and chase timing, and the reference uses RENDER-009 rendering changes that are
not in this unit's baseline. This is a qualitative checkpoint comparison, **not
a pixel-aligned no-regression proof or an isolated attribution of a particular
new object to an indirect batch**. The positive indirect batches now reach Vulkan
where the fallback previously recorded no draw.

Both Mac game launches and the additional private integration probe used
`mac-game-lock`; the owner installation and saves were not modified. The integration
probe adds the separately owned RENDER-009 packaged-layout patch only in a private
binary, and does not change the shipped gap patch. Its seeded route remained in
the load UI, so it does not establish chase/material integration acceptance.

Initial private build-configuration probes stopped at missing control metadata
(Windows) or an omitted `NX_HWOPUS=ON` option (Mac). Installing the verified private
control header and enabling host Opus corrected those setup errors. The generated
header and generated-game archives remain private; no keys were read or transferred.

Windows startup and active GREATER alpha rendering were exercised on the NVIDIA L4
with driver 596.86. The first full attempt ended after **392.925 seconds** with
`std::bad_alloc` in the existing `written_bind` compute-buffer copy path, before the
new indirect path was reached. The symbolized stack is retained in
`C:\acr\units\NVN-GAPS-014\crash-symbols.json`. Other units were running multiple
concurrent game processes; contention is a possible explanation, not a proven cause.
The shared `event.pkz` also differed from the original. This unit used its own copy
of RENDER-009's restored archive, whose SHA-256 matched the Mac original, and left
shared inputs unchanged. Seeded Windows menu probes exercised command fences and
active alpha rendering but did not leave load confirmation; they do not count as
indexed-draw acceptance. A subsequent fresh route completed the profile and chase checks with the same
executable and did not reproduce the allocation failure.

The successful **NVIDIA L4 / Windows Server 2025** retry ran **859.161 seconds**
and captured **129 frames**. It has **zero FATAL/CRASH lines** and zero targeted
fallback witnesses. Eight capped positive indexed-indirect witnesses include
**54 indices × 50 instances** and **4 indices × 50 or 100 instances**; eight
command-fence witnesses complete after GPU submission. ALWAYS and GREATER with
reference 1/255 were observed again. The binary SHA-256 is
`aac16454f3c768946c0844d3abf8b625b8ffa65b1df016f726556ac90e45e53e`.
Windows frames **13080** (profile, Confirm selected) and **14880** (chase with
enemies and tutorial) were inspected and compared with the Mac/reference captures.
The same qualitative/material limitations above apply.

The VM started this retry with **19,898,068,992 bytes of free commit**. It was
stopped deliberately after the target witnesses and captures were obtained;
`targeted-stop.json` records the exact owned process/path and reason. The parent
reaped it, reporting Windows termination code `0xffffffff`, not an unhandled
runtime exception. This is a controlled test stop, not a clean in-game exit.

Durable Windows evidence was copied back to the Mac before VM cleanup:
`.local/units/NVN-GAPS-014/windows-evidence/evidence.zip`, its extracted `packet/`
(logs, configurations, receipts, build/input hashes and symbolized prior crash),
and `fresh-13080.png` / `fresh-chase.png`. The successful run's measurement file is
`windows-evidence/packet/windows-measurements.json`.

A **130.145-second pre-patch Mac control** using the same private seed also stayed
at load confirmation (`mac-before-load-control.png` and its run receipt). Thus the
seeded probes did not demonstrate a new command-fence regression; they also do not
establish save/reload acceptance.

These runs are not a performance acceptance: the last Mac 60-frame interval was
**26.4 fps**, and the last five Windows intervals ranged **9.1–13.2 fps**. Scene
complexity and concurrent VM work differ from the reference, so these are not a
controlled A/B regression measurement. CPU readback and end-of-submit fence waits
remain explicit performance costs; **60 fps is not established by this unit**.

Independent exact-head review belongs to the parent orchestrator. No nested review
is performed or silently waived. Linux receives patch-application coverage only;
no Linux hardware, physical controller or audio-device timing acceptance is claimed.

Open follow-ups: integrate the documented Windows series entry; review the exact head;
combine and visually accept the separately owned texture repair; optimize indirect
readback and marker-position fence completion; support lower-left origin and wide
lines on hosts without `wideLines`; cover remaining multi-draw/counter APIs. The
legacy queue-fence timeout behavior remains outside this patch.


## NVN-PERF-015 performance follow-through (2026-10-20)

The performance candidate removes unconditional per-indirect-draw checkpoints as
specified above. Synthetic production replay tests cover no written arguments,
GPU-written arguments, native GPU index reads, CPU 8-bit widening, and the
untracked diagnostic compute mode. Command fences retain their conservative
completion semantics; no signal is published before GPU work and write-backs
complete. Alpha SPIR-V modules remain cached by shader/function and graphics
pipelines by alpha reference; the measured route uses a stable reference of 1/255.

The previous Windows allocation exception was symbolized at `written_bind`,
which allocates a host snapshot of the merged compute-written range. The patch
now checks address overflow, input/padding sizes and the merged copy (including
alignment and zero tail) against the actual upload-ring capacity before pointer
arithmetic or allocation. A snapshot `std::bad_alloc` fails with requested size,
capacity, padding and overlapping-region count. These bounds prevent an oversized
copy from wrapping the upload ring or trying an impossible host snapshot; they do
not claim to diagnose or recover from every cause of system memory exhaustion.

Private build/run evidence is retained under `.local/units/NVN-PERF-015/` on the
Mac and `C:\acr\units\NVN-PERF-015\` on Windows. Both variants reuse identical
private generated-game archives, fonts, shaders, texture profile and fresh save
state. A is the native overlay prefix at `28eb85f` without NVN gaps; B adds this
unit's optimized patch. Windows adds identical Linux and Windows platform
overlays to both. All runtime translation units are rebuilt (88 Mac, 85 Windows),
with host Opus enabled. The shared private measurement change enables the
existing per-present `NX_FRAME_LOG` on Windows as well as Mac. The private Windows
benchmark also bypasses live XInput/keyboard when `NX_INPUT_SCRIPT` is set,
identically in A and B, so other units cannot steer this route through the shared
virtual controller. Neither measurement adaptation is shipped.

The Mac pair uses the same 650-second scripted fresh-game route in A and B,
headless and muted, with three on-demand captures. Its steady sample windows are
35–75, 382–400 and 555–645 seconds from the first present. The profile window
starts after the cold pipeline-compilation transition; that stall remains in the
raw log. Capture intervals within three seconds of a dumped present are excluded.
FPS is `1000 / mean(interval_ms)`; percentiles use linear interpolation. These
are real headless present intervals, not displayed swapchain latency. Muted
headless audio is timer-paced; no audio-device timing is claimed.

Windows calibration showed that fixed wall times and fixed cross-platform frame
positions could select a laboratory cutscene instead of the profile screen under
changing CPU load. Those calibration runs are not accepted performance evidence.
The subsequent private controller verifies the visible profile and chase tutorial
before sampling each stage, using the same input sequence in both variants. Inputs
are scheduled by present count; live hardware input is bypassed. The private file
input hook and frame counter are identical in A and B and are not shipped. Each
Windows run samples 900 title frames, then 600 profile and 600 chase frames after
warm-up. It records other game processes every ten seconds. Any contended run is
reported as such, rather than claimed as uncontended acceptance. Raw phase windows,
OCR results and captures are retained alongside receipts and logs.

### Mac confirmation

One completed A/B pair on the real Apple M5 Pro Mac (macOS 26.6.2) used
`mac-game-lock` for every launch. Both 650-second runs reached all three intended
checkpoints; their captured title, character/profile and chase frames were
inspected. Neither log contains a FATAL/CRASH line or allocation failure. Both
owned process groups are absent after bounded SIGTERM stops (exit -15), not
in-game exits. The owner installation and saves were read only.

| Stage | A / B fps | A / B p50 ms | A / B p95 ms | A / B p99 ms |
| --- | --- | --- | --- | --- |
| Title | 30.002 / 30.003 | 33.303 / 33.349 | 35.502 / 35.954 | 37.421 / 38.214 |
| Profile | 29.995 / 29.911 | 33.331 / 33.421 | 35.162 / 35.092 | 35.580 / 35.539 |
| Chase | 29.910 / 29.923 | 33.614 / 33.362 | 36.407 / 35.175 | 37.790 / 35.998 |

This pair has no meaningful fps regression at the tested 30 fps pace. It is one
Mac confirmation, not a three-run distribution. Existing per-60-frame timing logs
show a real cost in the chase: replay **4.13 → 4.97 ms/frame**, encode
**1.77 → 1.62 ms/frame**, and GPU fence waits **7.08 → 9.16 ms/frame**. Correct
indirect rendering and conservative completion still do work; stable capped fps
does not establish equal uncapped throughput. Upload-MB counters exclude earlier
checkpoint parts and must not be used as total-byte comparisons here.

Candidate witnesses include 54 indices × 50 instances and 4 indices × 50/100
instances, active GREATER alpha testing at 1/255, and command fences completed
after GPU submission. The chase includes the motorcycle, enemies and tutorial in
both variants. Existing material defects remain visible. Raw evidence:

- `.local/units/NVN-PERF-015/runs/mac-{A1,B1}/{guest.log,receipt.json,config.json,data/frames/}`
- `.local/units/NVN-PERF-015/{measurements.json,timing-costs.json,mac-cleanup.json,mac-source-comparison.json}`
- A binary SHA-256: `93033c224628c8e5e0c3a9fe13bf4f270922f72b01165f9bf7664803bebe8aaf`
- B binary SHA-256: `10099fea9aee69b2dff228e4fd65a101e1a36605674ca0fecf9506869b2218bd`

### Windows repeat results and acceptance limit

Six full NVIDIA L4 / Windows Server 2025 runs completed in order A1, B1, B2,
A2, A3, B3. This VM reports driver 596.86 and an Intel Xeon at 2.20 GHz with
4 cores / 8 logical processors. Both binaries use identical generated archives;
`windows-pair-provenance.json` verifies that only the 14 NVN-gap source files
vary. The shared private measurement/input adaptations are identical.

Each run starts from fresh save state. Title, the initial male/female profile
selector, and the motorcycle tutorial were verified from captured frames. The
controller samples 900 title and 600 profile/chase presents, after warm-up and
with capture-adjacent intervals excluded. Counts are one-based presented-frame
numbers; actual intervals remain monotonic wall time. During the chase, both
variants receive the same firing burst before the ROI, then a 12-frame right
input and a 60-frame firing burst at the same ROI-relative positions. The private
`phase-windows.json`, `menu-events.txt` and `tutorial-entry.json` retain the exact
input and sample boundaries. These are scripted inputs, not controller acceptance.

| Stage | Variant | FPS, repeats 1 / 2 / 3 | Pooled p50 / p95 / p99 interval (ms) |
| --- | --- | --- | --- |
| Title | A | 30.004 / 29.983 / 30.009 | 33.054 / 43.289 / 48.690 |
| Title | B | 29.995 / 30.008 / 30.001 | 33.135 / 42.386 / 48.164 |
| Profile | A | 25.325 / 27.970 / 27.086 | 35.945 / 49.023 / 56.003 |
| Profile | B | 23.336 / 26.871 / 29.397 | 36.023 / 50.912 / 58.534 |
| Chase | A | 11.909 / 13.927 / 12.865 | 76.535 / 104.079 / 124.319 |
| Chase | B | 10.318 / 12.288 / 10.921 | 89.955 / 123.825 / 142.051 |

Median FPS change B versus A: title -0.01%, profile -0.79%, chase -15.11%.

**These Windows runs do not establish neutral-performance acceptance.** Other
units continued running games throughout the samples, with changing process
counts and workloads. The captured chase encounter activity also differs; the
screens are phase-matched, not deterministic state or pixel matches. Neither a
slow B1 nor a faster B2 can therefore be assigned solely to this patch. All
repeats are reported, including the slower ones. An exclusive, state-controlled
repeat remains necessary before declaring the Windows performance gate passed.

The first Windows pair's chase logs show replay 37.10 → 56.04 ms/frame, GPU
fence wait 13.64 → 12.11 ms/frame, and other submit work 10.99 → 0.35 ms/frame.
Checkpoint write-back work moves between those categories; comparing replay
alone overstates its added cost. This pair does not support blaming a larger GPU
fence wait. The static profile windows log no new-pipeline work. Chase windows
do create pipelines and decode textures for new encounter content; the active
alpha reference remains 1/255, without evidence of a reference-driven per-draw
variant explosion. Preserving per-submit upload/descriptor caches around needed
readback and earlier marker completion remain bounded follow-ups if a clean
repeat confirms a CPU cost. Required ordering must not be bypassed for fps.

A durations (seconds): 894.906, 813.984, 848.734.
B durations (seconds): 976.390, 883.109, 798.859.

All six runs have zero FATAL/CRASH/allocation-failure matches. The three patched
runs therefore did not reproduce the earlier `written_bind` exception, including
under concurrent game load, and did not trigger the new bounds guard. This does
not prove the old exception's cause; malformed ranges and global memory pressure
remain distinguishable by the new diagnostics. Successful route runs were stopped
at their owned test boundary (Windows termination code 1), not exited in-game.
Patched logs include positive indexed-indirect and GPU-completed command-fence
witnesses and active GREATER alpha testing. Linux has application/syntax coverage
only, with no Linux hardware or performance claim.

Evidence retained on the Mac before VM cleanup:

- `.local/units/NVN-PERF-015/runs/win-phase2-{A1,A2,A3,B1,B2,B3}/`: raw logs, receipts, configurations, phase windows, OCR, controls and original captures.
- `.local/units/NVN-PERF-015/{measurements.json,windows-aggregate.json,timing-costs.json,creation-costs.json,background-context.json}`.
- `.local/units/NVN-PERF-015/{windows-pair-provenance.json,build-A-receipt.json,build-B-receipt.json,final-windows-sources.tgz}`.
- `.local/units/NVN-PERF-015/rejected-calibrations.json`: explicitly rejected wall/fixed-frame timing probes.

The candidate is deliberately absent from macOS/Linux default series because
the Windows performance gate is not cleared. The
hardware binaries isolate the patch on `28eb85f`; the rebased source is covered by
the required tests, rather than represented as a fresh combined hardware build.

Exact-head independent review belongs to the parent; no nested review is
performed by this worker.


### Integration gate still requiring lead follow-through

Default series activation is deferred. The Windows chase median is 15.11% lower
with the candidate under changing concurrent load; this cannot be declared neutral.
The conditional readback optimization removes unnecessary work, but does not
establish that the complete correctness patch is cheap enough. Reserve an exclusive
VM window and match encounter state before attributing and fixing the remaining
cost. Preserve required compute visibility and fence completion when doing so.

After that gate passes, insert the exact line `astral-nvn-gaps.patch` immediately
after `astral-shader-cache.patch` in macOS and Linux, before `astral-linux.patch`
on Linux. The same exact Windows line belongs after the shader-cache prerequisite
and before `astral-linux.patch`; Windows is lead-owned. Its missing shader-cache
and audio-fix prerequisites also need lead integration. Extend the enabled-series
checks in `test_acr_build.py` and `test_astral_texel_coalesce.py` at activation.
The candidate's NVN test already composes every earlier patch and tests its Linux
and Windows insertion order without default activation.

An attempted activation exposed exact-tail assertions in the out-of-scope
`test_astral_shader_cache.py`: its fixture setup and Linux assertion must allow
successor overlays. The earlier observed failure remains in
`.local/units/NVN-PERF-015/test-shader-cache-scope-blocker.log`. Deferring activation
avoids introducing that suite failure. The final unchanged shader-cache suite
passes all 9 tests; the required NVN-gap/build/texel suites pass 7/54/4 tests.
All 18 Windows stage captures and the 6 Mac captures were visually inspected.
The parent owns independent exact-head review; no nested review was performed
or waived.

The final main rebase added a deliberately unlisted `astral-render-fix.patch` and
native Windows NSP import. Within this unit's allowed `test_acr_build.py`, both
unlisted native overlays are recorded as specific pending gates (unknown unlisted
overlays still fail), and the parser test checks native import acceptance while
preserving the reused-import/key exclusion. No render overlay or Windows series
entry was enabled by this unit.
