# Current native Mac measurement — MAC-CURRENT-MEASUREMENT-069

This is a **new current measurement**, using source revision
`4f696a616d2f7ee148fd8d41a1b7a3025b34a815` and independently landed VI-CORE-068.
It preserves VI063's two failed rounds and every prior receipt. It does not
reconstruct historical compiler equivalence or reinterpret failed tests.

The unit inspected the original task-owned Mac057 and VI063 native-1 directories
read only. Mac057 has 395 objects and a completed executable; VI063 has 285
objects and no executable. A fresh composition from pinned Wonder runtime
`010ed7a596a621c15d3a8dfa5795ca8c3668b066` and the twelve current ordered overlays
differs from Mac057 source only in `runtime/src/hle_vi.cpp`. The generated
control-context header matches. An isolated source directory changes all compiler
include paths, so a normal dependency rebuild was selected rather than editing
Ninja command hashes or old build metadata. No old worktree was modified.

Private evidence is retained in this worktree's `.local/mac-current-069/`:
`measure.py`, `measurement.json`, `tool-observation.json`, fresh `source/` and
`build/`, configure/build/startup receipts and logs as available. The private
short driver uses existing `service_batch_startup.run_stage` process-group bounds.
Generated/canonical inputs are reused read only and fingerprinted before build;
source, external headers and inputs must also match after the launch.

The pre-build receipt contains current source/overlay/control/input/generated
identities, 402 relevant header hashes and compiler path/hash/version.
Compiler: Apple Clang 21.0.0 (`clang-2100.3.34.2`), native arm64, Release.
All 395 compile commands, including actual generated main/sdk translation units,
have exactly `NX_APPLE_HIGH_MEMORY=1` and `NX_ASTRAL_STRICT=1`.
The build uses two jobs and a total 720-second configure/build bound, followed
by at most 90 seconds of actual guest startup. Owned child groups are stopped
at stage exit/bounds; no unrelated processes or simulators are targeted.

## Measured result

The original command was:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .local/mac-current-069/measure.py > .local/mac-current-069/driver.log 2>&1
```

The driver recorded exact absolute argv, bounds, timestamps and exit codes in
`configure.json`, `build.json` and `startup.json`. It invoked CMake with
`-G Ninja -DNX_GAME=astral -DCMAKE_BUILD_TYPE=Release
-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`, the frozen generated-source directory,
Homebrew prefix and the pinned private Vulkan include directory. The native
build command was the configured private `cmake --build
<unit-worktree>/.local/mac-current-069/build --parallel 2 --target astral`.
The launch argv was the resulting `<unit-worktree>/.local/mac-current-069/build/astral`,
with `NX_TRACE=1`, canonical `NX_DATA_ROOT` and a new unit-owned `NX_LOG`.

| Stage | UTC start | UTC finish | Exit | Elapsed |
|---|---|---|---:|---:|
| configure | 2026-10-18T20:30:11.099159+00:00 | 2026-10-18T20:30:17.130734+00:00 | 0 | 6.032s |
| build | 2026-10-18T20:30:22.229481+00:00 | 2026-10-18T20:40:17.287146+00:00 | 0 | 595.066s |
| startup | 2026-10-18T20:40:21.523805+00:00 | 2026-10-18T20:40:24.022959+00:00 | -11 | 2.499s |

**Native build passed; real guest startup faulted.** All 395 objects were built.
Configure plus build took approximately 601.097s,
within the 720-second total bound. The executable SHA-256 is
`bb4461a89ba75630b3a7030a295bb23ca1f89fbd5c97f95dbd5ba074206fe459`.

**VI scaling was passed in the actual guest.** The trace records the scaling
HLE followed by `vi: FitToLayer uses host full-extent blit`, then further NVN
procedure lookups and two `nvnDeviceGetInteger` HLE calls. The first complete
observed fault is signal 11 at executable-relative PC `0x1c2d69c`, data address
`0x8`, with guest LR `main+0x3df980` (`nnMain+0x780`). Current executable
symbolization with `atos -o .local/mac-current-069/build/astral -l 0x100000000
0x101c2d69c` (exit 0) resolves to `main_009AAB00(nx::CPU&) + 264`.
This records the successor fault; its root cause is unverified and no fix was
attempted. The strict-IPC-only parser returned null, which is **not** an assertion
that startup had no fault. `observed-result.json` records this distinction.

No game visuals were observed or captured. The guest exited after 2.499 seconds;
there is no screenshot, five-second clip, inspected advancing-frame/audio sample
or input/gameplay acceptance. The UI inventory checks did not find a persistent
Astral app. Rendered-frame count remains unverified, rather than asserted zero.
No visual-update image/clip was announced.

Post-launch hashes confirm unchanged generated/canonical input identities,
prepared source and all recorded headers. All three process receipts have empty
cleanup-group sets: the owned children had exited, with no live groups requiring
termination. The private driver exited 0 after retaining the fault evidence;
that driver exit does not turn the guest's -11 exit into success.

Focused verification: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover
-s tests -p test_vi_runtime.py -v` exited 0: one test, five policy/dispatch
executions, 5.213 seconds. The fresh synthetic receipt is
`.local/vi-core-068/verify-0a6c07b23f8b49eea00fafe487a7d2b3/receipt.json`.
`git diff --check main HEAD` is required again against the final committed head.


macOS gameplay remains unverified. Windows, Linux, iPhone simulator and iPad
simulator retain separate partial/blocked acceptance; 26.5 tested / 26.0 minimum
target is the mobile project status, not a new simulator test here. Physical
mobile acceptance and semantic correctness percentages remain unknown;
cross-ISA byte match is N/A. No diagnostic output establishes gameplay.

Independent Astra/medium review of the final exact head and concrete native
result is required through the parent before `scripts/land`; no review is waived
and this worker does not launch nested reviewers or land itself.
