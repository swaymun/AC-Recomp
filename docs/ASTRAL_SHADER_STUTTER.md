# Mac shader compilation stutter — MAC-STUTTER-005

The Mac overlay adds a versioned Vulkan cache and a recorded-pipeline boot prewarm.
It moves compilation of previously observed pipelines to an initial loading barrier;
it does not claim to serialize Metal machine code or eliminate cold compilation.
**The overall warm-spike reduction gate is not met on the measured route.** The
existing Vulkan cache was already effective, and its remaining warm spikes did
not overlap pipeline/shader creation. The new code moves creation before
presentation, but is not evidence that the owner's reported warm stutter is fixed.
Treat this branch as measured implementation/progress, not a performance pass.
PC-SHADER-027 extends it to Windows and Linux below. Independent exact-head review remains the parent's
responsibility; this worker does not land or spawn a nested reviewer.

## What was already cached

The owner's read-only `data/pipelines_106b_1a060209.bin` is **5,796,351 bytes**,
with Vulkan header size 32, header version 1, vendor `0x106b`, device `0x1a060209`
and UUID `49b97f261a0602090000000100000000`. Its SHA-256 is
`43f6d5075f7b758c837d9b77702bb06c48e11c8c6788365ed700e3a17ee9fc95`.
It is an existing `VkPipelineCache`, not an inventory of complete pipeline states.
The old runtime loads it lazily at the first pipeline creation and saves growth
every 600 presents. Shader modules, pipeline layouts and pipeline objects are
otherwise cached only within that process and created on demand in GPU replay.

MoltenVK **1.3.0**, bundled with the owner's player, serializes shader conversion configuration,
conversion results and compressed MSL through `MVKPipelineCache::writeData`.
Its graphics/compute pipeline compilers still request Metal pipeline states.
That explains why an existing Vulkan cache can avoid conversion work while a
new process still spends time in Metal library/pipeline creation. This is source
analysis, with runtime call durations measured separately below. See the
[versioned MoltenVK implementation](https://github.com/KhronosGroup/MoltenVK/blob/v1.3.0/MoltenVK/MoltenVK/GPUObjects/MVKPipeline.mm).

The [1.3.0 configuration list](https://github.com/KhronosGroup/MoltenVK/blob/v1.3.0/Docs/MoltenVK_Configuration_Parameters.md)
has no binary-archive switch, and that pipeline implementation contains no
`MTLBinaryArchive` use. Enabling a hypothetical environment setting would not
provide persistent Metal pipeline binaries. Adding archive integration inside
MoltenVK itself is a separate dependency change.

## Runtime change

`astral-shader-cache.patch` changes the four cache translation units plus the
shared loader's console policy, and adds `nvn_shader_cache.h` inside the prepared
upstream tree. Cache integration is enabled for strict Apple, Windows and Linux
builds; non-strict cache translation units remain unchanged. The existing Apple
cache code has identical minimized preprocessor output before/after PC-SHADER-027.
The shared loader intentionally changes console defaults on every strict platform.

- `pipelines_v1_<key>.bin` contains a checked envelope around the driver's opaque
  Vulkan cache. `pipeline_records_v1_<key>.bin` contains pipeline descriptions,
  shader identities and parameters. These are private, game-derived data under
  the player's data root and must never be distributed or committed.
- The key covers the entire executable digest (runtime and lifted game build),
  vendor/device, driver/API version, Vulkan pipeline-cache UUID, OS build,
  shader transformation/layout options, and, on Apple only, every `MVK_CONFIG_*` environment
  setting, sorted independently of environment order. A build/driver/options
  change gets another filename. The legacy cache is left intact; the first run
  with this overlay populates a new cache.
- Envelope `ACSC0001`: little-endian key length and payload length, a 40-character
  SHA-1 corruption checksum over key+payload, then key and payload. Limits are
  4 KiB for keys and 64 MiB for payloads. This checksum detects accidental
  corruption; it is not authentication of untrusted caches. Bad lengths, version,
  key, checksum or Vulkan header/UUID are ignored. Driver rejection retries with
  empty initial data. Temporary-file replacement preserves the last good
  versioned cache when a write fails, and same-size changes are saved too.
- Recorded graphics state omits pointers and zeroes ABI padding. Shader identity
  includes the owned SPIR-V file digest, stage, local size and shared-memory size.
  Prewarm checks each SPIR-V file against that digest; missing/changed files are
  skipped. A changed record format is invalidated by the executable digest.
- Vulkan initialization, under GPU ownership after the device is ready, starts
  a compiler thread and joins it before the first present. The worker uses SPIR-V and recorded state,
  never guest pointers or guest constants. It exclusively borrows the layout,
  module and pipeline maps while the GPU owner waits. The game's other threads
  can continue loading/recording. Compatible descriptor layouts let subsequent
  guest shader objects reuse the warmed pipelines through stable content keys.
- There is no asynchronous first-use draw omission or fallback pipeline. Unknown
  pipelines compile normally and become records for the next run. This deliberately
  bounded form of background compilation preserves rendering correctness and
  moves known work to boot. Mid-game loading-screen detection and progressive
  prewarming are not implemented.
- The boot barrier flushes its cache changes before the first present. Subsequent
  dirty records/cache are saved at a 60-present timing boundary. Unchanged Vulkan
  caches are not repeatedly serialized. The existing process uses `_exit`, so
  periodic saving matters; the last incomplete window may be lost on termination.

`NX_SHADER_CACHE=0` selects the legacy persistent-cache path and disables recorded
prewarming. `NX_SHADER_PREWARM=0` disables only prewarming. External diagnostic
shader tools (`NX_SPIRV_OPT` / `NX_SPIRV_TOOL`) disable the new cache because their
output can change independently of the executable. `NX_PIPELINE_CACHE=0` retains
its existing meaning: no driver Vulkan cache.

## Measuring a route

`NX_FRAME_LOG=1` emits each present's monotonic timestamp and interval, plus the
start/end timestamps of shader-module, graphics-pipeline and compute-pipeline
creation. Compilation events identify `runtime` versus `prewarm`. The first
present has no preceding interval and is excluded from statistics. Boot/prewarm
compilation is still included in whole-log compile totals.

```sh
python3 tools/frame_spikes.py /private/run/nx.log --fps 30
python3 tools/frame_spikes.py /private/run/nx.log --fps 30 --start-frame 1 --end-frame 3600
```

The JSON reports measured intervals, strict `> 2 × budget` and `> 100 ms` counts,
longest frame, percentiles, whole-log creation-call time by kind/phase, creation
time within the selected interval span, and compilation overlap for each spike.
Correlation uses timestamp overlap, not adjacent log lines. It does not prove
causation: CPU work, streaming, frame readback and scheduling can also cause
spikes. Histograms alone are rejected because they cannot supply these numbers.
Reported compile time measures Vulkan creation calls, not independently isolated
Metal compiler CPU time. Module and pipeline calls are measured without nesting. The first pipeline
event also includes initial Vulkan-cache loading, because the cache getter is
evaluated as a creation-call argument.

## Hardware measurement

Evidence is private under
`.local/units/MAC-STUTTER-005/` in the main workspace. Host: Apple M5 Pro,
18 CPU cores, 64 GB RAM, macOS 26.6.2 (25G83), the owner's copied MoltenVK 1.3.0 (Vulkan 1.3.313).
The current Homebrew driver is 1.4.2, a different binary; it is excluded from
the final measurement matrix to keep the driver identical to the installed app.
The isolated player reuses copied, unchanged owner-generated 30 fps archives and
source, compiles all 88 runtime objects at `nice -n 10`, and relinks locally.
Assets are read through symlinks; each run gets its own empty `user/` save root.
The owner's build, settings, logs and saves are not modified. The telemetry-only
baseline was independently rebuilt from the pinned Mac series and the retained
timing hooks: every loadable Mach-O code/data/constant section, including zero-fill
sizes, matches the measured baseline. Whole-file hashes differ because of linker
and signing metadata. Reconstructed source, build commands and section hashes are
retained in `baseline-source/`, `reproduce_baseline.py` and
`baseline-section-comparison.json`.

Baseline contains only frame/creation telemetry over the Mac series before this
overlay. The changed player includes the cache overlay. Both load the same private
copy of the owner's driver and use headless 30 fps at the game's 1600×900 render
resolution, muted audio, HUD off and a fresh profile. Dumps are every ten seconds
of wall time (`NX_DUMP_EVERY_S=10`), with present numbers logged for comparison.

The route was calibrated in a separate windowed, input-recorded player. The
unskippable fresh-profile opening leads to character creation. The fixed script
uses B at 10/11/12 s and ZL+ZR at 16/20 s, A at 24/28/32/36/40 s, then:

- A at 340 s chooses the default male character.
- A at 345 s opens Name; A at 350 s opens Given Name, answered deterministically
  as `Player` by the existing software-keyboard HLE.
- Down at 355/357/359 s selects Confirm; A at 362 s completes setup.
- ZR at 450 s fires for two seconds in the motorcycle chase.

All ordinary presses last 0.25 s (B 0.2 s; triggers at title 0.4 s). Times are from
the first pad read. Every comparison run is bounded at **500 seconds** and ended
by its own runner. The script is retained as `route.txt`; each receipt records the
exact environment, executable hash, input-cache hashes and the timeout outcome.
Cold means no application cache in that run's data root; Apple's OS/driver caches
are **not** purged. Warm copies only the preceding cold player's cache files into
another empty save root. Each launch is inside the shared `mac-game-lock` command.
The full route is checked in captures rather than inferred from process exit.

The first 160-second opening-only experiment is retained separately in
`opening-first-use-summary.json`. It exposed a warm-frame regression: prewarming
at the first layout request reduced counts but increased the longest interval
from 146.3 to 286.3 ms. That version is not the final implementation. The barrier
and its initial persistence now run during device initialization, before any
present. Earlier missing-profile and missing-headless-telemetry attempts are
retained and excluded from acceptance numbers.

Measurements are single traces on a shared workstation, not isolated laboratory
benchmarks. In particular, cold-before versus cold-after can benefit from Apple's
already-populated compiler caches; do not attribute that entire difference to
this patch. Whole-log creation time and prewarm time remain reported separately
from frame intervals. The benchmark does not cover a windowed swapchain,
upscaling, a 60 fps build, other chapters or changes of driver/configuration on
real hardware. Key changes and corrupt inputs have additional synthetic coverage.

Measured tables and frame-comparison observations below come from retained logs,
not from unit-test fixtures.

### Final title-to-chase results

All four runs lasted 500 seconds, exited 0 after the runner's time limit, and
reached the motorcycle chase. Thresholds use the 30 fps budget: strictly greater
than 66.667 ms and 100 ms. Times below are milliseconds.

| Run | Intervals | >2× budget | >100 ms | Longest | Creation total | During presented intervals | Boot to first present |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Before, cold | 14,928 | 20 | 12 | 710.767 | 2,557.455 | 2,557.455 | 339.445 |
| Before, warm | 14,988 | 2 | 1 | 100.696 | 140.853 | 140.853 | 337.961 |
| After, cold | 14,937 | 4 | 2 | 135.640 | 299.655 | 299.655 | 1,955.011 |
| After, warm | 14,970 | 5 | 1 | 102.727 | 98.622 | 5.257 | 836.132 |

Restricting all four logs to the same frame range, 1–14,928, leaves every spike
count and longest interval in this table unchanged. Before-cold has 18 spikes
overlapping creation calls; after-cold has two. Both warm runs have **zero**
spikes overlapping those calls. The existing Vulkan cache therefore already
removes most cold creation stalls on this route. The new warm run creates 372
recorded pipelines at boot (`warmed=372 skipped=0 elapsed_ms=179.726`); creation
calls themselves take 93.365 ms in prewarm and 5.257 ms later at runtime.
The later calls reflect additional state encountered in a time-scripted,
animated scene; a recorded run does not guarantee complete future coverage.

This is a failed overall warm-spike gate: 2 → 5 spikes, with longest frame
100.696 → 102.727 ms. Presented-interval creation time decreases about 96%, but
that does not establish a perceptible stutter improvement. Boot also costs more:
338 → 836 ms warm, and 339 → 1,955 ms cold in these single traces. Executable
hashing, record loading and prewarm add startup work; their individual costs were
not isolated. The cold improvement is confounded by OS compiler-cache warming.
After two implementation rounds (first-use barrier, then boot barrier), further
speculative cache changes are stopped. Investigate the remaining warm spikes
with broader CPU/GPU/upload/pacing telemetry and repeated windowed traces before
accepting this as the owner's stutter fix. Optimize build identity/startup cost
before enabling this by default in a landed player.

The additional 45-second `route-after-corrupt` run flips the final byte of both
versioned files before launch. Its log says `no valid recorded pipelines; cold
boot` and `(0 bytes loaded)`. It renders 1,326 measured intervals, exits 0 at the
runner's limit, and has no fatal/crash lines. The ordinary after-cold run proves
a full title-to-chase cold-cache boot. Driver rejection and changed build/driver
keys are unit-tested rather than exercised by changing the real driver.

Inspected before/after cold/warm captures at 300 s show the same opening close-up
with dialogue; at 490 s all show the motorcycle chase, rider, road, van, effects
and tutorial HUD. No new missing scene or pipeline is apparent in those samples.
The captures differ in animation/camera phase, so this is a bounded visual check,
not a pixel-equivalence test. A small red credit-text artifact and distorted rider
materials also appear in baseline captures; this unit does not fix those existing
rendering issues. Headless rendering uses the real Mac GPU but does not verify
windowed presentation or the whole game's visual correctness.

Evidence under `.local/units/MAC-STUTTER-005/`:

- `route-measurement-summary.json` and `runs/route-*/stats{,-common}.json` contain
  complete numbers and timestamp-based spike correlations.
- `runs/route-*/nx.log`, `receipt.json`, `frame300.png`, `frame490.png` and
  `data/frames/` retain logs, launch/cache hashes and private captures.
- `runs/route-after-corrupt/corrupt-inputs/` retains the rejected private inputs.
- `run.py`, `route.txt`, `summarize.py` and `frame-comparison-paths.json` reproduce
  the route, analysis and capture selection. No private evidence is in Git.

Measured baseline SHA-256:
`c2eb5a285b67757c743eefaec0d3c607e8f18774db004018e2a9a3ed25a5bf3f`.
Measured changed player SHA-256:
`d269486f1b226da90fc8297015fc1b1ef12ee837b5ea5e505143d0e41ed8f69e`.
Both use the copied owner MoltenVK SHA-256
`ad54a6a33e9b82592403f928d8d74bad98a6caf4df6151a50c762aaf7acf6735`.
Hardware traces precede the final rebase onto the parent's audio-diagnostic main
changes; the two required suites check final-head overlay composition. No combined
audio/shader hardware regression pass is claimed.

## Automated verification and remaining gates

```sh
python3 -m unittest discover -s tests -p 'test_astral_shader_cache.py'
python3 -m unittest discover -s tests -p 'test_frame_spikes.py'
```

The cache suite applies the complete Mac series to the pinned public runtime,
executes the production codec and record/key functions, compiles the complete
cache translation unit against a fake Vulkan driver (cold, warm, checksum/header
corruption and driver rejection), checks dirty-only serialization and same-size
updates, syntax-checks all changed translation units in the Mac profile, and
compares real default-profile preprocessor output before/after. No game, GPU,
credentials, downloads or cloud resources are used by tests.

Windows/Linux could adopt the portable envelope and pipeline-record logic after
providing platform-specific executable/OS identity, UTF-8 file I/O and atomic
replacement (Windows needs replacement semantics beyond `std::rename`), and validating the worker
barrier and descriptor-layout compatibility on their drivers. Their series are
unchanged and they have no validation claim from this unit. Mobile is out of scope.

Three legacy full-suite assumptions need a separately scoped parent update:
`test_astral_texel_coalesce` hard-codes its overlay as the final Mac entry;
`test_acr_build.SeriesTest.test_series_matches_the_overlay_tests` imports that
older order; and `test_series_covers_every_native_patch` assumes every native
patch is in the Windows series. The brief explicitly requires this overlay in
Mac only and forbids edits to those test files. Their helper/composition checks
are unaffected. Full-suite success is not inferred from this unit's two required
verification commands.

## PC-SHADER-027: desktop portability and console defaults

Strict Windows and desktop Linux builds now use default-on `ACSC0001` Vulkan/recipe
envelopes. Recorded prewarm is default-on on Windows; Linux requires
`NX_SHADER_PREWARM=1` after its warm-frame gate did not pass (see the Linux
measurements). The Apple cache code and its prewarm policy remain unchanged.
`NX_SHADER_CACHE=0` restores
the legacy cache path and disables recording/prewarm; `NX_SHADER_PREWARM=0` keeps
the versioned driver cache and recording while disabling the boot replay.
On Linux this is also the default; opt-in affects scheduling, not the cache key.
`NX_FRAME_LOG=1` enables module/graphics/compute creation spans and frame timestamps
on Windows and headless Linux. These are creation API durations, not a measure
of internal driver compilation, and do not include SPIR-V file reading/reflection
or all module patch preparation.

Windows obtains the executable with `GetModuleFileNameW`, reads it with `_wfopen`,
and reads `NX_DATA_ROOT` through `GetEnvironmentVariableW` before UTF-8 conversion.
Cache/SPIR-V files use `fopen_utf8`; successful closed temporary files replace the
previous version with `MoveFileExW(REPLACE_EXISTING | WRITE_THROUGH)`. Linux reads
`/proc/self/exe` and uses same-directory `rename`. Both key the full executable,
physical-device vendor/device, driver/API versions and pipeline-cache UUID plus
native OS version and effective shader/layout settings. Windows also keys its
six fidelity/replay settings (`NX_EXACT_EQUAL`, `NX_FRAG_OUTPUT_MASK`, `NX_HALF_BITS`,
`NX_VERTEX_PRECISE`, `NX_REPLAY_DYNAMIC`, `NX_REPLAY_KEYS`). `MVK_CONFIG_*` terms
remain Apple-only. A missing/unreadable executable disables the versioned path.
Both PC executable reads are bounded at 512 MiB; envelope limits remain unchanged.
Android is excluded from the desktop Linux guard: `/proc/self/exe` there names
the host process rather than the game shared library. No Android cache port is
claimed.

The existing joined `std::thread` owns compilation exclusively while the GPU
owner waits. No guest memory or concurrent Vulkan-cache access is introduced.
Boot and each GPU-owned 60-present timing window save dirty records and dirty
Vulkan data; there is no dependence on destructors or `atexit` in a player that
uses `_exit`/`ExitProcess`. Abrupt termination can still lose work since the last
checkpoint. Normal warm windows avoid driver serialization when no pipeline
has been created. The old `pipelines_<vendor>_<device>.bin` remains available for
explicit opt-out; it is not silently imported into the new envelope.

All strict platforms now keep diagnostic output, including periodic statistics,
in the primary log file without console mirroring by default. `NX_CONSOLE_LOG=1`
explicitly enables the console mirror. Windows `NX_WIN_ASYNC_CONSOLE=1` remains
an opt-in that both enables mirroring and chooses the existing bounded console
worker. File write/flush stays synchronous. A failed file open, write or flush
falls back to the console so diagnostics remain visible. Non-strict logging is
unchanged. This policy applies to all shared logger lines, including errors;
`NX_LOG` and its previous-session rotation remain the primary diagnostic record.

`mac-preprocessor-equivalence.json` privately compares the four original cache
translation units before/after with strict Apple configuration and
`clang -E -P -fminimize-whitespace`: all four outputs are byte-identical. The
loader intentionally changes only the requested logging policy on Apple. No Mac
game was run for this unit. Native synthetic tests exercise corruption, driver
rejection, same-size/Unicode replacement, executable/driver/UUID/option keys and
log-file retention/fallback; measured PC routes and their limits are recorded
in the platform documents below. Independent exact-head review belongs to the
lead; this unit does not start a nested review.
