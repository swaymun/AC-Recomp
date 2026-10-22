# Astral Chain on Linux (x86-64)

`runtime/patches/astral-linux.patch` makes the macOS runtime series build and run on Linux. It applies after the
whole of `runtime/patches/series.macos`; `runtime/patches/series.linux` is that series plus this overlay, and
`tests/test_astral_linux.py` keeps the two lists in step. The macOS build is unchanged: `series.macos` does not list
the overlay, and every change in it is inside a Linux-only branch or behaves identically on macOS (below).

## What the overlay changes

| file | change |
|---|---|
| `runtime/src/fiber_context_linux.S` (new) | The host stack switch of the fiber bridge (`docs/ASTRAL_FIBER_CONTEXT.md`) for ELF hosts. **x86-64 System V:** `nx_fiber_swap(from, to)` pushes `rbp rbx r12-r15`, the x87 control word and MXCSR on the outgoing stack, stores `rsp` in `*from`, loads `to`'s `rsp` and pops the same frame. `nx_fiber_enter` is reached by `ret` with a 16-byte aligned `rsp` and calls `entry(arg)` from `r12`/`rbx`. **arm64 (Linux):** the macOS `fiber_context_mac.S` instructions and layout with ELF symbol names and directives. |
| `runtime/src/hle_fiber.cpp` | Accepts Linux x86-64 and arm64 besides Apple arm64. `HostContext` on x86-64 is the saved stack pointer only; `prepare_entry()` lays out a fresh host stack (`[fpcw][mxcsr][r15][r14][r13][r12=enter][rbx=0][rbp][ret=nx_fiber_enter]`, the FP control state copied from the creating thread). On arm64 `prepare_entry()` sets the same fields the macOS code set inline. Dispatch, finalization and thread retirement are unchanged. |
| `runtime/src/kernel.cpp` | `fiber_retire_thread()` is the real one on Linux (not Android) too, so a thread that exits while a fiber is active switches back to its root continuation first, as on macOS. |
| `CMakeLists.txt` | The Linux (`elseif(UNIX)`) branch enables ASM and adds `hle_fiber.cpp` and `fiber_context_linux.S`. Without them `nn::os::SwitchToFiber` ran the lifted dispatcher and crashed right after the hwopus probes (the SIGSEGV after `InitializeFiber`). |
| `runtime/src/nvn/nvn_vk.cpp` | With `NX_HEADLESS` a missing window surface is no longer fatal: SDL's `offscreen` video driver (a server without a display) wants `VK_EXT_headless_surface`, which Ubuntu 22.04's loader does not offer, and `init()` gave up, so nothing was ever replayed. Headless runs only read frames back, so any graphics queue is taken. On macOS the surface is always created, so this path is not taken there. |
| `runtime/src/nvn/nvn_caps.cpp` | On Linux the upload ring defaults to host-cached coherent memory (`NX_RING_CACHED=1`; `NX_RING_CACHED=0` restores the plain type). Compute results are read back from the ring by the CPU (`apply_write_back`, about 35 MB a frame on the title screen); from write-combined memory on a discrete NVIDIA GPU that took ~450 ms a frame and held the title at **1.5 fps**. Host-cached: **30 fps**. Other hosts keep the opt-in. |
| `runtime/src/nvn/nvn_frames.cpp`, `nvn_linux_staging.h` | LINUX-PERF-031: cached/coherent dedicated staging with fallback and a bounded submission-retired free pool; see policy and A40 gates below. |



Linux also needs `astral-texel-coalesce.patch`, which is in `series.macos` and so in `series.linux` too
(`docs/ASTRAL_TEXEL_COALESCE.md`). Without it the queue of pending texel writes for the title movie grew by about
1 GB every 30 s, and the memory guard stopped the game on the title menu after about 3.5 minutes.

## Dependencies (tested: Ubuntu 22.04, x86-64, NVIDIA A40, driver with Vulkan 1.4)

- clang 14 or newer (`clang`/`clang++`; the runtime compiles with `-march=x86-64-v3`, so an AVX2 CPU), CMake 3.25+,
  Ninja, pkg-config.
- SDL3 (not packaged in 22.04: build it from source and pass its prefix in `CMAKE_PREFIX_PATH`).
- `libopus-dev` (the build uses `-DNX_HWOPUS=ON`), the Vulkan loader (`libvulkan1`) and a Vulkan 1.3+ driver.
- Vulkan headers at the pin `tools/acr_build.py` uses (`VULKAN_HEADERS_PIN`), e.g. `-DNX_VULKAN_INCLUDE=<Vulkan-Headers>/include`.

`tools/acr_build.py` is macOS-only. Its import, control, lift and shader stages produce platform-independent output
(the lifted C++ in `<out>/work/gen`, the data root with `analysis`, `exefs`, `extract` and `spirv`), which can be
copied to the Linux machine. Keep that output private: it is derived from your game.

## Build

```sh
git clone https://github.com/BelmanteGu/SuperMarioWonderRecomp runtime-src
git -C runtime-src checkout --detach 010ed7a596a621c15d3a8dfa5795ca8c3668b066   # dependencies.lock pin
for p in $(sed 's/#.*//' runtime/patches/series.linux); do git -C runtime-src apply "$PWD/runtime/patches/$p"; done
cp <mac build>/work/runtime/source/runtime/src/astral_control_context.h runtime-src/runtime/src/   # control stage output
CC=clang CXX=clang++ cmake -S runtime-src -B build -G Ninja -DNX_GAME=astral -DNX_GEN_DIR=<gen> \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=<sdl3 prefix> -DNX_VULKAN_INCLUDE=<vulkan include> -DNX_HWOPUS=ON
cmake --build build --target astral
```

The whole series applies cleanly to the pin and this builds with no errors (406 steps, about 13 minutes on 7.6
CPUs).

## Run

```sh
NX_DATA_ROOT=<data root> NX_NVN_REAL=1 NX_NVN_FORMAT_PROFILE=<astral.profile> NX_SHARED_FONT_DIR=<fonts> ./build/astral
```

Headless (a server without a display): add `NX_HEADLESS=1 SDL_VIDEODRIVER=offscreen`, and `NX_DUMP_FRAMES=<n>` to
write every n-th presented frame to `<data root>/frames/NNNNN.ppm`. `NX_SAMPLE=997` turns on the runtime's SIGPROF
profiler (Linux x86-64 only), which logs the hottest code per thread every 20 s.

## Status (2026-10-19, RunPod A40, headless)

- Boots through `nn::init`, the vi layer, the NVN device on the A40, RomFS and hwopus, then past the fiber switch.
- Renders the boot sequence, the title screen, the title menu, LOAD DATA and its dialogs, and then, after loading
  a File 01 save, the in-engine opening cutscene (the Legion sequence) and the character creation screen (the
  POLICE officer screen with the 3D model, Name / Hair Style / Eye/Skin Color, then Given Name). The images look
  correct when checked by eye.
  The input was scripted: ZL+ZR at 6/9/12/15/40/45 s, then LEFT and A every 5 s. The macOS state-normalising script
  (A from 305 s, then B/DOWN) did not line up with the Linux timings: it left the game at the "press ZL+ZR" title.
- **30 fps** (the game's cap; present interval 2) on the title and menus, with replay ~7 ms, fence wait ~3 ms and
  ~6 ms of other CPU work per frame. The cutscene runs at **23-30 fps**, mostly 25 (replay 6-14 ms). Resident memory
  stays at 1.5-3 GB once `astral-texel-coalesce.patch` is applied.
- The pod is limited to 7.65 CPUs (cgroup quota, although `nproc` reports 96). A build running alongside the game
  takes CPU time from it.
- Not yet done: a windowed run on a desktop (X11/Wayland surface and swapchain path); audio (the pod had no audio
  device, so timer pacing was used); gamepad input (only `NX_INPUT_SCRIPT` was exercised); an `acr_build.py` Linux
  mode; Linux arm64, which assembles but was not built or run.


## Status (2026-10-21, LINUX-BASE-026, RunPod A40, headless)

This is a new baseline of **main `b52bfa215fa1d130a0ed9644a17a845bc456434c`**, not a Linux port of the
Windows performance series. No runtime or generated game code was changed in this unit. Both executables use
that commit's complete `series.linux` on upstream `010ed7a596a621c15d3a8dfa5795ca8c3668b066`.
The runtime source's 474 non-Git files were hash-checked between Mac preparation and pod. All 10,715 private
input files (11,117,654,214 bytes) passed a content-hash check before the first game launch. Only this document
belongs in Git; inputs, binaries, captures and raw measurements remain private.

### Machine, builds and provenance

| Item | Measured configuration |
|---|---|
| Pod | One A40 pod, root over `acr-lnx`; Ubuntu 22.04, kernel 6.8.0-138-generic, driver 595.91.07, A40 46,068 MiB |
| CPU | Xeon Gold 6342, nominal 2.80 GHz; `nproc=96`, **7.65 CPUs available by cgroup quota** |
| Quota | This container uses **cgroup v1**: `cpu.cfs_quota_us=765000`, `cpu.cfs_period_us=100000`; `cpu.max` is absent. Memory limit 49,999,998,976 bytes |
| Toolchain | clang 14, CMake 3.31.6, Ninja, Release, `-march=x86-64-v3`, `-j8`, hwopus enabled |
| SDL | 3.4.18, commit `829a65d769d935c4852f8159e964312c0957260a`; private headless console build, X11/Wayland disabled |
| Vulkan headers | `e3b1eec08173d6b825cd3ac88c885a63b621504a` |
| `astral` | `NX_ASTRAL_FPS_MODE=30`; 406 build steps, **195.567 s** |
| `astral-60fps` | `NX_ASTRAL_FPS_MODE=dynamic-60-cap`; 406 build steps, **199.869 s**; renamed copy of the mode's `astral` target |
| SHA256, 30 | `09eaa146257c520814a0cb122572ed48bcb0df7111ba90a6d8ac8575900840ba` |
| SHA256, dynamic cap | `077923886856c1c45262dd8ceff5e2ff7af1ba74158ec96a8db4d7543567b47c` |

For the second build, the same CMake recipe above used `NX_ASTRAL_FPS_MODE=dynamic-60-cap`, the carry-mode main tree, the same SDK tree, and an empty `NX_MAIN_VARIANT_LIST`; both builds target `astral`. The measured `astral-60fps` is a byte-identical renamed copy, not another target. The pod's SDL configure used `SDL_UNIX_CONSOLE_BUILD=ON SDL_X11=OFF SDL_WAYLAND=OFF`; a desktop validation would need a different SDL build.

Build wall times include CMake configuration, all 406 Ninja steps and symbol-map extraction; dependency installation and input transfer are excluded.

The generated inputs came from the existing private FPS-007 build: `build-work/gen` for 30, and
`build-work/gen-dynamic-carry` for dynamic cap, with the same SDK tree. They contain **pre-existing unconditional
FPS-007 timer, input-window, camera and cut observers**. These are instrumented supplied inputs, not quiet
release builds. No observer was removed or added to generated code here. Against FPS-007's Windows-generated
archive, all 210 carry-mode files and 110 SDK files match byte-for-byte; 209 files of the 30 tree match, with
only `funcs.h` differing because the archive includes union variant declarations. The function bodies therefore
match that Windows reference input family. Both Linux SDK archives also have the same hash. This establishes
input provenance, not equivalence between A40/Linux and the later Windows GPU/CPU hardware.

### Route and measurement method

Two diagnostic runs (`pilot30`, `profile60`, both `NX_SAMPLE=997` with raw stacks) first established the route
and populated a common pipeline cache. The frozen 3,745,264-byte cache has SHA256
`622f9fa4ed79e5049109ff95d0371bb7532fab693eb7d00de1254f6aa33c1c10`. Every timing and switch run then starts
from its own **fresh user/save directory**, the identical frozen cache, and shared read-only game data.
The File 01 save copied for possible investigation was **not used**. The route follows the Windows fresh-profile
route, with two early B presses to normalize the Linux startup dialogs:

```text
NX_INPUT_SCRIPT=25:B:0.2;27:B:0.2;90:ZL:0.5;90:ZR:0.5;200:MINUS:0.5;202:PLUS:0.5;214:A:0.2;218:A:0.2;222:A:0.2;227:DOWN:0.12;228:DOWN:0.12;229:DOWN:0.12;231:A:0.2
```

Time zero is immediately before process creation. ROIs are **title 50-80 s**, **opening laboratory cutscene
170-195 s**, **File 01 chase 400-430 s**. Each process runs for 470 s and is deliberately stopped with SIGTERM;
the SDL path handles this as graceful exit 0. Captures are requested only at 35, 150, 242, 375 and 450 s,
outside the timing ROIs. Captures verify the bracelet title, in-engine researchers, officer close-up and
motorbike chase. Adjacent captures establish scene identity, not a locked camera/enemy pose across runs. The chase still has road/bike occlusion and red glyph artifacts in the stock Linux path;
this is **not visual-fidelity acceptance**, audio/gamepad acceptance, a windowed display result or a full playthrough.

Common settings are `NX_NVN_REAL=1 NX_HEADLESS=1 SDL_VIDEODRIVER=offscreen NX_SKIP_LAUNCHER=1
NX_PERF_HUD=0 NX_POWER_PROFILE=0 NX_GPU_PROFILE=3`, the private format/font/data paths, and the route above.
Inherited `NX_*` variables are cleared. Timing repeats have **no NX_SAMPLE**; mode3 GPU counters are diagnostic
only: this synchronous Linux submit path reports zero GPU timings because it does not implement those timestamps,
so zero **does not mean no GPU work**. Upload memory is already host-cached by Linux's default.
There is one game process at a time, no concurrent build or input transfer, and a 15 s quiet-launch gate
(cgroup background CPU below 15% of quota, GPU below 10%). Per-second process/thread CPU, RSS and cgroup
throttling are recorded; GPU telemetry is sampled every five seconds. No pod clock/power policy was changed.

The Linux guards do not enable the Windows/Apple individual-frame log. A private external `LD_PRELOAD`
observer therefore timestamps the existing headless `nx::hud::on_present` call, filtering a mutex wrapper by
its exact caller symbol range. It changes no runtime source or executable. A 10,000-event check recorded exactly
10,000 increasing timestamps; standalone overhead was about 1.2 microseconds per observed event and 1.8 ns per
nonmatching lock. Every run cross-checks the timestamps against the runtime's exact count of 60-frame buckets.
These are **headless present-cadence FPS**, not physical display refresh or CPU-only render throughput.

Average FPS is complete intervals divided by their summed duration inside each ROI; 1% low is the reciprocal
of the mean of the slowest `ceil(0.01*N)` intervals. Quantiles use linear interpolation. Stage values are means
of complete runtime 60-frame buckets lying inside the ROI. Replay/encode/fence/other/present are **elapsed
runtime counters**, not exclusive CPU service: fence contains waiting, other is the submit remainder, and
headless present is bookkeeping/readback. Do not add sampled CPU percentages to those counters. RSS uses decimal
MB, mean/maximum sampled each second. Repeat spread is observed variation with **N=2**, not a confidence interval.

### Two timing repeats per mode and scene

Mode `60` in these tables means `dynamic-60-cap`.

| Mode / run / ROI | Frames | Average / 1% low FPS | p50 / p95 / p99 / max ms |
|---|---:|---|---|
| 30 / `base30-A` / title | 899 | 30.015 / 15.855 | 33.699 / 42.878 / 61.118 / 67.369 |
| 30 / `base30-A` / cutscene | 703 | 28.173 / 18.219 | 35.493 / 40.243 / 49.662 / 58.090 |
| 30 / `base30-A` / chase | 680 | 22.726 / 17.285 | 42.579 / 52.949 / 54.615 / 70.055 |
| 60 / `base60-A` / title | 1753 | 58.469 / 24.363 | 16.608 / 27.530 / 32.449 / 50.826 |
| 60 / `base60-A` / cutscene | 704 | 28.219 / 22.685 | 35.568 / 40.307 / 41.511 / 46.491 |
| 60 / `base60-A` / chase | 767 | 25.609 / 11.266 | 40.090 / 56.095 / 59.336 / 277.110 |
| 30 / `base30-B` / title | 899 | 29.993 / 15.725 | 33.710 / 43.441 / 60.835 / 65.203 |
| 30 / `base30-B` / cutscene | 658 | 26.388 / 17.818 | 39.033 / 46.051 / 53.764 / 57.806 |
| 30 / `base30-B` / chase | 712 | 23.784 / 16.906 | 41.198 / 51.009 / 56.020 / 66.148 |
| 60 / `base60-B` / title | 1765 | 58.885 / 22.419 | 15.691 / 28.999 / 35.012 / 53.863 |
| 60 / `base60-B` / cutscene | 683 | 27.352 / 21.328 | 36.575 / 43.315 / 46.128 / 47.437 |
| 60 / `base60-B` / chase | 767 | 25.615 / 13.632 | 38.969 / 47.488 / 54.920 / 168.108 |

Elapsed runtime counters below are **replay / encode / fence / other / present**, ms/frame; RSS is mean / maximum decimal MB. Buckets are complete 60-frame buckets wholly inside the ROI.

| Run / ROI | Buckets | Stage ms | Upload MB/frame | RSS MB | Process CPU cores |
|---|---:|---|---:|---|---:|
| `base30-A` / title | 14 | 4.440 / 0.068 / 2.845 / 2.652 / 0.050 | 12.520 | 1991.565 / 1991.569 | 1.090 |
| `base30-A` / cutscene | 11 | 5.669 / 0.045 / 4.898 / 1.648 / 0.040 | 28.078 | 2110.136 / 2110.136 | 1.244 |
| `base30-A` / chase | 11 | 14.316 / 0.068 / 9.005 / 6.956 / 0.056 | 54.718 | 2474.595 / 2475.401 | 2.542 |
| `base60-A` / title | 28 | 3.587 / 0.054 / 2.723 / 2.336 / 0.046 | 11.471 | 1992.290 / 1992.290 | 1.360 |
| `base60-A` / cutscene | 10 | 5.731 / 0.040 / 4.927 / 1.627 / 0.059 | 28.098 | 2095.440 / 2095.440 | 1.264 |
| `base60-A` / chase | 12 | 13.402 / 0.076 / 7.619 / 5.188 / 0.156 | 44.355 | 2493.826 / 2493.981 | 2.588 |
| `base30-B` / title | 14 | 4.425 / 0.075 / 2.814 / 2.571 / 0.062 | 12.520 | 1990.983 / 1990.988 | 1.121 |
| `base30-B` / cutscene | 10 | 5.706 / 0.049 / 4.961 / 1.553 / 0.060 | 28.028 | 2108.297 / 2108.297 | 1.264 |
| `base30-B` / chase | 11 | 13.496 / 0.079 / 9.062 / 6.092 / 0.058 | 53.029 | 2496.628 / 2497.466 | 2.463 |
| `base60-B` / title | 29 | 2.707 / 0.044 / 2.641 / 2.008 / 0.047 | 11.463 | 1994.379 / 1994.379 | 1.224 |
| `base60-B` / cutscene | 10 | 5.435 / 0.044 / 5.020 / 1.581 / 0.059 | 28.053 | 2111.840 / 2111.840 | 1.232 |
| `base60-B` / chase | 12 | 12.623 / 0.072 / 8.707 / 3.868 / 0.085 | 43.232 | 2489.651 / 2499.912 | 2.539 |

Observed repeat spread (B minus A; two observations):

| Mode / ROI | Average FPS min-max | Delta average FPS | 1% low FPS min-max | p95 ms min-max |
|---|---|---:|---|---|
| 30 / title | 29.993-30.015 | -0.023 | 15.725-15.855 | 42.878-43.441 |
| 30 / cutscene | 26.388-28.173 | -1.785 | 17.818-18.219 | 40.243-46.051 |
| 30 / chase | 22.726-23.784 | 1.059 | 16.906-17.285 | 51.009-52.949 |
| 60 / title | 58.469-58.885 | 0.416 | 22.419-24.363 | 27.530-28.999 |
| 60 / cutscene | 27.352-28.219 | -0.867 | 21.328-22.685 | 40.307-43.315 |
| 60 / chase | 25.609-25.615 | 0.006 | 11.266-13.632 | 47.488-56.095 |

All baseline ROIs have 0.000 ms of cgroup throttling. Maximum sampled non-game CPU use is 1.629% of the 7.65-CPU quota. GPU utilization means span 8.2-22.2%, with SM-clock sample means 210-465 MHz. These sparse samples do not measure the duration of each GPU burst.

The inherited FPS-007 world-step observer is also retained. Its weighted `sum(steps)/(30*sum(dt))` ratio in complete one-second buckets is:

| Run | Title | Cutscene | Chase |
|---|---:|---:|---:|
| `base30-A` | 1.000 | 0.936 | 1.000 |
| `base60-A` | 1.000 | 1.000 | 0.993 |
| `base30-B` | 1.000 | 0.880 | 1.000 |
| `base60-B` | 1.000 | 1.000 | 0.997 |

This is the observer's world-step accounting, not proof of every animation/gameplay system or physical input parity.

The 30 cap is reached at title, while dynamic title averages 58.469-58.885 FPS. The opening cutscene remains
26.388-28.219 FPS across modes; removing the cap alone does not solve it. Chase is 22.726-23.784 FPS at 30 and
25.609-25.615 at dynamic cap, with dynamic 1% lows only 11.266/13.632 FPS. This is not sustained 60 FPS.

No measured baseline ROI is quota-throttled, and process CPU demand is well below 7.65 aggregate cores.
That does not measure single-core headroom or prove an idle physical host. In the cutscene, replay is only
5.435-5.731 ms/frame and fence 4.898-5.020 ms, alongside the guest vector/table profile entries; a large frame
interval is outside replay. In the chase, replay is 12.623-14.316 ms, fence 7.619-9.062 ms and other 3.868-6.956 ms,
with 43.232-54.718 MB/frame uploads. This makes writeback, recording and retained uploads concrete targets, but
neither upload bytes nor elapsed remainder can be called exclusive writeback CPU time. The existing Linux
texture watcher, cached upload ring and guest synchronization behavior must remain distinct from Windows
resident generations, narrowed scans and guarded overlap.

The largest dynamic chase intervals are **277.110 ms at 424.124 s** (A) and **168.108 ms at 422.067 s** (B).
Their containing runtime buckets each report six ASTC texture decodes, totaling **73.1/85.0 ms per 60-frame bucket**;
both report zero pipeline creations. These are nearby bucket aggregates, not a per-frame stack or proof that
decoding caused the full stall. Other chase buckets have pipeline creation totals around 1-2 ms and smaller
decode totals. Retain first-use texture preparation as a separate tail investigation from the Windows writeback
and replay ports; do not credit a smaller average writeback scan with solving these outliers.

### Existing portable switches (dynamic-cap binary, exploratory single runs)

These are already admitted by `series.linux`; no Windows patch or runtime edit was needed. Each uses the same fresh profile, frozen cache and ROIs as the repeats. A single optional run does not establish repeatability; retain the baseline A/B range as context.

| Run / switch | ROI | Average / 1% low FPS | p50 / p95 / p99 / max ms | Replay / encode / fence / other / present ms | RSS peak MB |
|---|---|---|---|---|---:|
| `pipe60` / `NX_PIPELINED=2` | title | 58.586 / 22.231 | 16.191 / 28.985 / 33.896 / 50.583 | 2.916 / 0.068 / 2.208 / 2.231 / 0.045 | 2081.108 |
| `pipe60` / `NX_PIPELINED=2` | cutscene | 27.957 / 21.562 | 36.157 / 40.976 / 42.004 / 54.350 | 5.645 / 0.066 / 4.675 / 1.869 / 0.056 | 2190.283 |
| `pipe60` / `NX_PIPELINED=2` | chase | 25.534 / 16.498 | 39.527 / 44.559 / 49.812 / 126.547 | 12.740 / 0.098 / 7.832 / 4.553 / 0.058 | 2573.263 |
| `chunks60` / `NX_PIPELINED=2 + NX_SUBMIT_CHUNK_DRAWS=150` | title | 58.411 / 22.057 | 16.717 / 28.633 / 38.145 / 49.289 | 2.840 / 0.067 / 2.185 / 2.243 / 0.051 | 2080.444 |
| `chunks60` / `NX_PIPELINED=2 + NX_SUBMIT_CHUNK_DRAWS=150` | cutscene | 31.692 / 22.608 | 33.091 / 38.528 / 43.793 / 45.037 | 5.478 / 0.082 / 2.938 / 1.591 / 0.057 | 2203.869 |
| `chunks60` / `NX_PIPELINED=2 + NX_SUBMIT_CHUNK_DRAWS=150` | chase | 33.074 / 20.320 | 29.638 / 35.370 / 39.211 / 112.620 | 10.199 / 0.244 / 3.771 / 3.337 / 0.054 | 2594.652 |
| `thread60` / `NX_REPLAY_THREAD=1` | title | 57.699 / 18.832 | 12.692 / 31.823 / 41.267 / 60.542 | 4.597 / 0.068 / 2.669 / 3.388 / 0.051 | 1994.179 |
| `thread60` / `NX_REPLAY_THREAD=1` | cutscene | 45.663 / 31.863 | 21.103 / 28.700 / 30.209 / 34.011 | 11.327 / 0.074 / 5.101 / 2.946 / 0.049 | 2121.785 |
| `thread60` / `NX_REPLAY_THREAD=1` | chase | 40.315 / 22.704 | 24.525 / 28.873 / 31.367 / 168.547 | 12.144 / 0.075 / 8.631 / 3.701 / 0.062 | 2524.582 |
| `watch-off60` / `NX_WRITE_WATCH=0` | title | 58.784 / 22.358 | 15.849 / 28.731 / 34.472 / 50.836 | 2.795 / 0.045 / 2.639 / 2.065 / 0.048 | 1991.713 |
| `watch-off60` / `NX_WRITE_WATCH=0` | cutscene | 29.678 / 24.699 | 34.581 / 39.472 / 40.077 / 41.444 | 5.104 / 0.043 / 4.915 / 1.379 / 0.059 | 2096.677 |
| `watch-off60` / `NX_WRITE_WATCH=0` | chase | 26.177 / 14.636 | 38.230 / 45.909 / 52.929 / 152.739 | 12.714 / 0.073 / 8.623 / 3.748 / 0.082 | 2481.517 |

`NX_WRITE_WATCH=0` here disables **Linux texture dirty tracking** and exercises its hash fallback; it is not the Windows resident heap-tracker control. Cached upload memory is already on (`NX_RING_CACHED=1`); forcing the known slow write-combined path is unnecessary. `NX_INVARIANT` is a fidelity option, not a demonstrated performance port.

Binary string/source guards confirm that this baseline does not admit `NX_WIN_SCALAR_WRITEBACK`, `NX_WIN_KEEP_SDL_GAMEPAD`, `NX_RESIDENT`/read/storage, `NX_NARROW_WRITEBACK`/oracle, `NX_FRAMES_IN_FLIGHT`, the five `NX_REPLAY_ENV/POOL/SCRATCH/KEYS/DYNAMIC` controls, or the native exact-EQUAL/MRT/half-bits/vertex-precise fidelity controls. Setting those names would not test the Windows implementation.


All four switch runs have zero measured ROI quota throttling; maximum non-game CPU is 1.526% of quota.
All five captures per run were inspected and confirm the route, with the stock occlusion/glyph defects still
present. The laboratory shots and chase phases differ between runs, particularly with the faster replay-thread
route. These are same-route exploratory results, not equal-workload causal speedups or fidelity acceptance.

`NX_PIPELINED=2` alone leaves the chase at 25.534 FPS, close to the 25.609-25.615 baseline. Adding 150-draw
chunks reaches **33.074 FPS**, with fence elapsed time falling to **3.771 ms**. `NX_REPLAY_THREAD=1` reaches
**45.663 FPS in the lab and 40.315 FPS in the chase**, while title is 57.699 FPS and its 1% low falls to 18.832.
This is the strongest immediately available scheduling lead. Replay stages move onto another host thread;
the table's elapsed stage counters must not be added as a serial critical path or treated as exclusive CPU work.
Neither option reaches 60 across the route. Disabling texture watch gives 26.177 chase FPS, an insufficient
single-run basis for changing that default. Replay-thread and chunking were not combined here.
The inherited world-step ratio is 1.000 in the title and lab ROIs of all four runs and 0.997-0.998 in the chase; this
supports approximately real-time accumulated steps, not full gameplay or device A/V acceptance.

**Next measurement unit:** repeat replay-thread off/on at least twice with scene/game-time alignment and
per-thread attribution, then separately repeat the chunked path. Test their combination only after each
individual result and fidelity check holds. Preserve exact baseline settings as the control; keep caps, generated
observers, warm cache and source identity fixed. This is higher immediate value than assuming every Windows
optimization must first be ported. New ports still require their own measured controls below.

### NX_SAMPLE=997 profiles (separate diagnostic runs)

Raw signal samples were resolved with each Linux executable's exact ELF address/size map. The following are
PC shares **within the identified NVN-calling host thread**, not percentages of a frame or the whole process.
The sampler uses process-wide `ITIMER_PROF`/`SIGPROF`; signal delivery and stack collection can bias thread sampling.
Each approximate report window is about 20 s plus stack-dump/report overhead and is scene-contained; it is not
an exact replay of the shorter timing ROI. The sampler's own host thread is excluded. A final raw window may
be incomplete at planned shutdown and is not used. CPU service is independently sampled from `/proc` in the
corresponding diagnostic ROI, not inferred by multiplying percentages into elapsed fence time.

| Mode / scene | Report end s / host TID / samples | Three leading PC entries (% of that thread) | NVN-caller CPU ms/frame in diagnostic ROI |
|---|---|---|---:|
| 30 / title | 63.353 / 13940 / 12310 | `main_00700360` 16.69; `main_00700740` 16.05; `apply_write_back` 12.35 | 21.149 |
| 30 / cutscene | 189.116 / 13940 / 16466 | `main_007024A0` 8.78; `main_00700740` 7.41; `main_006F2050` 7.09 | 27.662 |
| 30 / chase | 425.205 / 13940 / 10092 | `apply_write_back` 30.21; `nvn::record` 5.84; `libc.so.6+1af26a` 3.17 | 31.088 |
| 60 / title | 63.742 / 16075 / 13071 | `apply_write_back` 18.99; `main_00700360` 12.32; `main_00700740` 11.32 | 12.054 |
| 60 / cutscene | 190.418 / 16075 / 16715 | `main_007024A0` 8.79; `main_006F2050` 7.23; `main_00700740` 7.08 | 28.213 |
| 60 / chase | 428.613 / 16075 / 9709 | `apply_write_back` 29.53; `nvn::record` 5.78; `libc.so.6+1af1cc` 3.96 | 30.881 |

In the chase, `apply_write_back` is 30.21%/29.53% of NVN-caller PC samples in 30/dynamic mode; `nvn::record`
is 5.84%/5.78%. In the 30 chase window, `gpu_submit` appears inclusively in 71.45% of that thread's samples;
inclusive stacks overlap and are not additive. The title's `main_00700360`/`main_00700740` functions contain
guest vector/table loops; their semantic subsystem is not identified by a source symbol, so these addresses
are not labeled as a specific codec.

Another chase guest thread, host TID 13944/16079, spends 84.22%/78.25% of its PC samples in
`main_003DFC50`. Read-only generated-code inspection identifies a shared-word plain-load/backbranch poll and
exclusive acquisition/release, rather than an SDL joystick loop. Its CPU service can reflect polling while
another thread makes progress. Other guest threads and the presenter have distinct TIDs; ranking the busiest
thread cannot replace attribution to the NVN caller. No wait/poll semantics were changed or proposed for bypass.

### Ordered Windows-to-Linux port plan

The Windows G4 result is a technique reference, not an A40 target prediction. In the same Windows quiet
control, replay off/on changed NVN-calling CPU from 10.451 to 5.928 ms/frame while chase FPS stayed near the
60 cap; [the Windows report](ASTRAL_WINDOWS_PERF.md#win-replay-024-g4-control-and-command-replay-iteration-3)
explicitly leaves tails and broad gameplay open. Linux's supplied generated inputs retain diagnostic observers,
so even that quiet Windows control is not a matched cross-platform benchmark. Puddz's native resource/command
architecture remains a design reference only (gap analysis); no Puddz code was run.

The following expected gains are **planning estimates**, not measured Linux game speedups. They are non-additive,
can be zero when another thread/pacing path dominates, and require same-binary off/on A/Bs before promotion.
Use per-thread CPU, upload/snapshot/scan bytes, valid synchronous GPU queries and fidelity checks, not average
FPS alone. Keep all performance options opt-in until their own independent review and Linux validation.

| Order | Proposed unit / dependency | Linux cost addressed and evidence | Expected gain / decision gate |
|---|---|---|---|
| Before ports | Repeat the already-portable replay-thread and chunk options independently | `thread60` lab/chase **45.663/40.315 FPS**; `chunks60` chase **33.074**, versus dynamic baseline **27.352-28.219/25.609-25.615**. Single runs and unlocked scene phase limit causality. | Highest immediate measurement value; **no new speedup promised**. Require repeated same-phase controls, per-thread profiles and fidelity checks before selecting defaults or combining switches. |
| 0 | Diagnostic guard widening, byte counters and synchronous Vulkan timestamps | Individual frame logging is excluded by the current Linux guards; synchronous mode3 GPU timings are unavailable. This unit used an external observer. | **0 ms direct gain.** Establish valid CPU/GPU/byte attribution before making residency or overlap claims. Do not accidentally enable Apple pipeline warmup. |
| 1 | AVX2 changed-word writeback; widen the include/eligibility guard to Linux x86-64 | Chase `apply_write_back` is 29.53-30.21% of NVN-caller PC samples. Actual A40 cached/coherent Vulkan memory microbench, three scalar/SIMD pairs: difference of variant median CPU p50s **0.375/0.403 ms at 10.04 MB** unchanged/sparse; **0.837/0.272 ms at 33.22 MB**. Sizes are representative Windows scan ranges, not measured Linux scan bytes. Both native scalar/AVX2 contract fixtures pass 5,248 cases each. | Budget **0-1 ms/frame**, mostly scan-bound scenes; no whole-game gain yet. Preserve original-word comparison, changed-lane stores, scalar/full-copy paths and partial tails. Validate byte oracle and off/on route. |
| 2 | Command arena/final-owner pool, then selection scratch; widen replay option guard | Chase `nvn::record` is 5.78-5.84% of NVN-caller samples. Linux standalone production-storage fixture, 4,096 commands/frame: **60.36-64.30 to 35.21-36.09 ns/command**, **2,096 to 2 allocations/frame**, three pairs. This uses stub object lookup, not the game. | Budget **0-0.8 ms/frame** for pool, **0-0.2 ms** for scratch; test queued/shared ownership, overlap eviction, concurrency and 256-list/32 MiB free-pool bounds. No dependency on residency. |
| 3 | Linux write-generation backend, then bounded resident storage/read/index integration | Baseline replay/other plus tens of MB/frame uploads make retained buffers relevant. Linux's existing texture watch is only 16 protected ranges and a bounding dirty interval, **not** a GetWriteWatch heap-generation backend. UFFD probes fail `EPERM` and `/dev/userfaultfd` is absent on this pod. | Aim for **1-4 ms/frame net** in upload-heavy scenes, but **0 or a regression** until tracking is cheaper than removed work. Prototype targeted tracking before merging persistence. Retain uncached fallback, allocation identities, independent consumers, graphics-writer/overlap bypass and the 256 MiB arena bound. |
| 4 | GPU block-change flags plus eager changed-word narrowing, after retained snapshots | Chase writeback is the clearest sampled host hotspot. The current Linux baseline lacks Windows scan/snapshot counters, so upload MB cannot be relabeled as writeback scan MB. | Budget **1-5 ms/frame** on sparse writeback after residency; establish actual scan/changed-byte histograms first. Include GPU flag cost, barriers/fences, partial tails and CPU oracle. A GPU result must not become guest-visible before required merges. |
| 5 | Bounded frames in flight and early materialization, after tracker/narrowing | Fence elapsed time is material, but contains dependency waits; changing existing pipeline/thread switches alone is measured separately above. | Budget **0-3 ms/frame**, with regression possible. Do not simply delete waits. Preserve observer/later-writer/range-identity fallbacks, per-slot lifetimes and completion-after-merge ordering; prove scene fidelity and resident limits. |
| 6 | Frozen resident environment lookup | There is **no resident lookup path in the current Linux baseline**. Windows measured a useful reduction only after residency existed. | **0 ms today**; after porting residency, budget **0-1 ms/frame**, measured with cached/uncached bypass-query counts. Dynamic failure/async/writer checks stay live. |
| 7 | Canonical pipeline keys and finer dynamic-state filtering | No Linux profile here establishes pipeline-key or redundant-state traffic as a leading cost; Windows near-cap neighboring runs also do not establish a robust whole-frame gain. | Conservative budget **0-0.3 ms/frame each**. Count hits/misses/state calls first, retain all effective state and submit/helper/reset boundaries; defer behind writeback/pool/tracker. |
| Separate tail work | Loading-time texture preparation / first-use attribution, outside the named Windows hunk inventory | Dynamic chase maxima 277.110/168.108 ms occur in buckets with six ASTC decodes totaling 73.1/85.0 ms; zero pipelines in those containing buckets. Puddz gap P5 is an architectural lead, not a port already implemented by these Windows patches. | **0 steady-state FPS gain assumed**; potentially move some of the measured decode work out of play. Capture per-event attribution before estimating a frame-tail saving; do not equate the whole outlier with decode time. |
| Fidelity track | Admit exact EQUAL / MRT mask / precision options on Linux and compare captures | The depth-fidelity patch is already composed but its native options are Windows guarded. The stock chase captures have occlusion/red-glyph defects. | **No FPS gain assumed.** Correctness work before accepting the performance route. Do not use an approximate depth test or missing draw as an optimization. |

A Linux residency backend needs an explicit feasibility gate. [Linux soft-dirty](https://www.kernel.org/doc/html/latest/admin-guide/mm/soft-dirty.html)
uses pagemap bit 55 and `clear_refs=4`; reset and query are separate operations, with VMA renewal caveats.
This pod's preallocated-query probe correctly finds 656/2,622 sparse dirty pages in 256 MiB/1 GiB. Median reset
and pagemap read alone cost **0.879+1.334 ms / 2.703+5.949 ms** respectively (30 measured iterations after five
warmups); sparse Python-driven writes add 0.578/1.964 ms, including loop overhead. Whole-heap polling therefore
already consumes a substantial part of the proposed savings and is not a cheap atomic GetWriteWatch substitute.
The preserved first probe allocated its query buffer, reported all 1 GiB dirty and failed its sparse-page assertion;
the preallocated-query version passes. No failed result was silently discarded. The runtime reserves a 6 GiB
guest heap (`runtime/include/nx/runtime.h`), with commitment on demand; these 256 MiB/1 GiB probes do not measure
a scan of that entire reservation. Restrict any future query to justified committed/tracked ranges rather than
assuming the whole reserved span is a cheap per-frame query.

[Userfaultfd write protection](https://www.kernel.org/doc/html/latest/admin-guide/mm/userfaultfd.html) needs
feature negotiation and available permissions; it cannot be assumed on this RunPod container. No sysctl or
privilege policy was changed. A targeted [mprotect/SIGSEGV](https://man7.org/linux/man-pages/man2/mprotect.2.html)
backend is possible, but must handle concurrent writers, signal safety/chaining, pool alias/free/reuse and
kernel writes to protected pages (which the existing texture watcher warns can return EFAULT). A query/reset
race cannot be fixed by merely reading and clearing soft-dirty once per frame. Reuse the generation/consumer
algebra, then prove a backend's semantics under concurrent writes before enabling persistent buffers.

The measured dynamic baseline needs about **35.4-36.6 ms/frame in the lab and 39.0 ms/frame in the chase**,
against 16.667 ms for 60 FPS. The estimates above do not demonstrate removal of the roughly 19-22 ms gap,
and must not be summed into a 60-FPS forecast.

Guest work is a separate remaining cost: the title/cutscene vector/table loops and chase shared-word polling
helper described above are outside these Windows NVN hunks. A plain polling PC is not proof that equivalent productive
CPU work is irreducible. Do not bypass its synchronization, misidentify it as SDL, or promise 60 fps from the
listed budgets. The 30 and dynamic-cap modes still require CPU/game-thread and tail analysis after low-risk ports.

### Hunk-group classification

Portable as-is describes reusable algorithm/Vulkan hunks, not appending the raw Windows series. Linux option gates and dependencies are listed separately. No runtime change in this unit. The inventory covers every touched file of the eight named Windows patch families; shared files occur in more than one logical group. Each group maps to the measured cost and expected gain in the ordered plan; build/platform/diagnostic-only groups have no direct measured performance gain.

| Patch / logical hunk group | Classification | Cost/gain reference | Port constraint |
|---|---|---|---|
| `windows-native`: MSVC compilation policy | Windows-only | 0 gain (Win32 build policy) | Linux already builds runtime and lifted code with x86-64-v3 and contraction disabled. |
| `astral-windows`: Win32 fibers, retirement, Opus/build and timers | Windows-only | 0 gain (Win32 backend) | Keep Linux System V fiber assembly, ELF/CMake/Opus and POSIX clock paths; no Windows API transplant. |
| `astral-windows`: Cached upload memory default | Portable as-is | 0 gain (already Linux default) | Already selected by the Linux overlay. Re-enabling NX_RING_CACHED=1 is not a new gain. |
| `astral-windows-desktop`: Native launcher, environment, XInput, audio and process lifetime | Windows-only | 0 gain (Win32 desktop) | Linux uses SDL input/audio and POSIX executable discovery/reexec. Do not remove its gamepad subsystem using a Windows-specific lifetime fix. |
| `astral-windows-perf`: Changed-word AVX2 body | Portable as-is | Order 1 | The intrinsic loop runs in the standalone Linux fixture. Its include/eligibility guard must separately admit __x86_64__; retain scalar/tail/full-copy fallbacks and changed-lane stores. |
| `astral-windows-perf`: Compiler eligibility and scalar escape guard | Needs a Linux equivalent | Order 1 prerequisite; 0 direct | Use Linux x86-64 eligibility rather than _WIN32/_M_X64; -march=x86-64-v3 already supplies AVX2. The original Linux game ignores NX_WIN_SCALAR_WRITEBACK. |
| `astral-windows-perf`: Individual frame and headless frame logging | Needs a Linux equivalent | Order 0; 0 direct | Widen only the diagnostic guards to Linux. Avoid accidentally enabling Apple pipeline warmup. No direct FPS gain. |
| `astral-windows-perf`: GetThreadTimes and SDL launcher gamepad shutdown | Windows-only | 0 gain (Win32 APIs) | Linux already has CLOCK_THREAD_CPUTIME_ID, while SDL remains its real input backend. Benchmark source does not show the Windows joystick lock defect on Linux. |
| `astral-windows-resident`: Independent page/consumer generation algebra | Portable as-is | Order 3 prerequisite | Generic types and interface can be reused behind a platform-neutral name; one harvest owner and independent consumers are mandatory. |
| `astral-windows-resident`: Reserve, harvest/reset and allocation identity | Needs a Linux equivalent | Order 3 feasibility gate | GetWriteWatch atomic query/reset has no direct POSIX replacement. Probe/prototype targeted fault tracking or race-safe soft-dirty harvesting before enabling persistence; keep uncached fallback. |
| `astral-windows-resident`: Vulkan arena/cache and storage, read, index integration | Portable as-is | Order 3 | Requires the new tracker contract first. Retain bounded 256MiB backing, allocation/pool invalidation, independent consumers, overlap bypass, graphics-writer fallback and eager changed-word visibility. |
| `astral-windows-resident`: Copy/snapshot counters and synchronous GPU timestamps | Portable as-is | Order 0; 0 direct | Vulkan/counter-only hunks can be separated from residency for Linux attribution. Existing Linux mode3 does not time synchronous submits. |
| `astral-windows-writeback`: GPU block comparison, flags, CPU merge and oracle | Portable as-is | Order 4 | Depends on retained snapshots/residency. Preserve GPU-to-host barrier/fence, original-word comparison, partial tails and eager fallback. Oracle is diagnostic overhead. |
| `astral-windows-writeback`: Bounded slots, early materialization and fence capture | Portable as-is | Order 5 | Depends on residency and the guarded visibility design. Publish completion after required merges; keep observer/later-writer/range-identity fallbacks. This does not authorize removing guest waits. |
| `astral-windows-writeback`: NVN Vulkan validation messenger | Portable as-is | Fidelity diagnostics; 0 direct | Linux needs its own installed layer path; the Windows SDK installer is not a Linux prerequisite. No direct FPS gain. |
| `astral-windows-replay`: Command payload arena and final-owner pool | Portable as-is | Order 2 | Can port independently of residency after the separate switch gate. Retain queued shared ownership and 256-list/32MiB free-pool bounds; standalone Linux benchmark measures only recording. |
| `astral-windows-replay`: Draw/dispatch selection scratch | Portable as-is | Order 2 | Reuse thread-local vectors separately for draw and dispatch without freezing effective/debug selection. |
| `astral-windows-replay`: Canonical pipeline keys | Portable as-is | Order 7 | Keep all effective state; zero unused fields only. Near-cap Windows FPS does not establish a Linux gain. |
| `astral-windows-replay`: Finer dynamic-state filtering | Portable as-is | Order 7 | Retain command-buffer/submit/helper-pass resets and real guest state changes. |
| `astral-windows-replay`: Frozen resident environment options | Portable as-is | Order 6 | No corresponding resident query cost exists in the current Linux baseline. This helps only after a residency port; dynamic failure/async/writer checks stay live. |
| `astral-windows-replay`: Replay option eligibility | Needs a Linux equivalent | Orders 2/6/7 prerequisite; 0 direct | Explicitly add strict Linux x86-64 opt-in eligibility. Do not enable defaults or apply unrelated Win32 overlays wholesale. |
| `astral-depth-fidelity`: Native depth/MRT/precision option eligibility | Needs a Linux equivalent | Fidelity track; 0 assumed | Already composed by Linux but its exact-EQUAL, MRT mask, half-bits and vertex-precise options are Windows guarded. Validate Linux fidelity separately; no assumed FPS gain. |

### Verification and private evidence

The exact required command is `python3 -m unittest discover -s tests -p 'test_astral_linux.py'`.
On the Mac, with `NVN_REFERENCE` pointing at the retained pinned upstream clone, five tests run successfully
with one Linux-only execution skip; the whole Linux series applies and both ELF assembly targets compile.
The native pod run passes all five, including real fiber entry, resumption and preserved floating-point state.
These are source/platform checks, separate from the game measurements and visual acceptance.
Independent review of the final committed head belongs to the parent; it is pending, not waived. No nested
review, runtime change, public push or resource/billing operation was performed by this worker.

Private evidence root on the Mac is `$ACS_ROOT/.local/units/LINUX-BASE-026/`; the pod root is
`/root/acr/units/LINUX-BASE-026/`. Paths below are relative to the Mac root and are retained outside Git:

| Evidence | Contents |
|---|---|
| `build-receipts.json`, `source-receipt.json`, `source-validation.json`, `build30.log`, `build60.log` | Revision, exact source/build configuration, elapsed build time and executable identities |
| `inputs-manifest.json`, `input-validation.json`, `generated-observer-audit.json`, `windows-generated-comparison.json` | Private input hashes and inherited instrumentation provenance |
| `capabilities.json`, `hardware-snapshot.json`, `gpu-clock-policy.txt` | Actual cgroup quota, hardware and tracker feasibility probes |
| `run.py`, `timing-matrix.json`, `portable-matrix.json` | Recorded route, environment construction, sampling and sequential-launch policy |
| `runs/{pilot30,profile60,base30-A,base60-A,base30-B,base60-B,pipe60,chunks60,thread60,watch-off60}/` | Per-run `receipt.json`, `env.json`, `script.txt`, `quiet-gate.json`, `present.bin`, timestamped `stdout.jsonl`, `console.log`, `samples.jsonl`, `analysis.json`, saves and original frame dumps |
| Per-run `capture-manifest.json`, `gallery.png`; `scene-validation.json` | Capture hashes/timestamps, ROI clearance and visual scene inspection; no fidelity pass |
| `runs/{pilot30,profile60}/stacks.txt`, per-run `profile-summary.json`, `selected-profile-windows.json`, `build{30,60}.demangled.nm` | Raw and symbolized profiles with exact thread/window provenance |
| `observe.c`, `observer-validation.json`, `observer-check-v2.log`, `observer-v2-hashes.txt` | External observer implementation, event-count/overhead check and identity |
| `writeback-benchmark-summary.json`, `writeback-contract-tests.log`, `record-v2-*.json`, `softdirty-benchmark-v2.json` | Standalone measured feasibility fixtures, not Linux game optimization results; earlier failed probes are also retained |
| `port-groups.json`, `port-coverage-resume.json`, `switch-string-inventory.json`, `guest-hotloop-audit.json` | Full hunk/file inventory, actual option eligibility and sampled guest-loop inspection |
| `tail-frame-analysis.json`, per-run `world-summary.json` | Included long-frame correlations and actual stored world-step ratios |
| `native-tests.log`, `verify-resume-native.json`, `verify-resume-local.json`, `RESUME.md` | Native/local test coverage and resumable execution history |
| `raw-evidence-manifest.json`, `raw-evidence-validation.json`, `evidence-validation.json`, `final-input-validation.json`, `final-game-state.json`, `native-artifacts/` | Hash-verified local raw runs and exact executables/observer, independently recomputed interval statistics, final input recheck and game-free closeout |

All ten runs finish with planned graceful exit 0, ordered non-overlapping lifetimes and no forced kill.
Independent recomputation of the raw present intervals agrees with the tables; 930 telemetry inventories
observe only the owned game, and all 50 captures are outside their timing ROIs. Ordinary logs contain no
unexpected fatal, device-loss, memory-guard stop or oracle-mismatch lines; this is not a validation-layer pass.
The local raw-run manifest verifies **374 files / 828,409,010 bytes**, SHA256
`f17ba0a4110fc0b729cdeffb905e811f50a3b82b1f8e32f62c273087d097807c`.
The final input recheck again matches all **10,715 files / 11,117,654,214 bytes**. Exact native executables and
the observer are retained locally and verified against their build receipts. Closeout observes zero game/GPU
compute processes; no further pod work is required. The lead owns stopping the pod and billing cleanup.

## PC-SHADER-027: recorded-pipeline cache on the dynamic cap build

The strict Linux player now enables the versioned Vulkan cache and provides
opt-in (`NX_SHADER_PREWARM=1`) recorded pipeline prewarm from [ASTRAL_SHADER_STUTTER.md](ASTRAL_SHADER_STUTTER.md#pc-shader-027-desktop-portability-and-console-defaults).
This is a cache/logging port over the Linux series, rather than a port of the
Windows resident/replay/ASTC performance stack. The LINUX-BASE-026 runner,
headless observer, dynamic-60 generated main archive, SDK archive, data inputs,
fresh-save route and 7.65-CPU quota are retained. No build or native fixture runs
during an accepted game measurement. Per-run CPU/GPU quiet gates and `/proc`
inventories enforce one game; CPU quota/throttling and GPU clocks are sampled.

The warm-frame gate experiment below uses executable SHA256
`2f56d9342c753f42d0e26f1e300a142f80b4d7f2dae93b880a2d8351d4104900`.
The final opt-in policy and its separately rebuilt verification sequence follow.
All 139 public runtime files match a fresh complete-series preparation. The
optional Linux frame logger runs under GPU ownership after device initialization.
Native shader-cache tests execute the actual `/proc/self/exe` identity path,
codec, Unicode replacement, driver fallback and file-log failure behavior;
Apple SDK-specific tests are skipped explicitly. No display/swapchain or audio
hardware acceptance is inferred from headless rendering.

Each 470-second accepted run has a new save/data root. `pc-cold` has neither
application Vulkan cache nor pipeline records. Each subsequent warm root copies
both files from the immediately preceding completed run; the old legacy cache
is not copied. OS/driver caches are not purged. `NX_FRAME_LOG=1` uses the same
monotonic clock as the independent `hud::on_present` observer. ROIs remain
50–80 seconds (title), 170–195 (lab cutscene), and 400–430 (File 01 chase), with
captures at 35, 150, 242, 375 and 450 seconds. Only complete observer intervals
inside each ROI count. Average FPS, slowest-ceiling(1%) low and interpolated p99
use the same definitions as the Windows table. **Displayed FPS is unavailable**
on this headless pod and is never substituted with app FPS.

`guest.log` retains statistics without shared logger console mirroring by default;
the retained generated archives still emit direct `FPS007` diagnostics to stderr.
Private evidence is `.local/units/PC-SHADER-027/`
and `/root/acr/units/PC-SHADER-027/`. Pre-serialization pilot runs are retained
separately and excluded from the accepted `pc-` sequence. Raw archives, cache
payloads, captures and binaries remain private and ignored.

### PC-SHADER-027 measured cache sequence

| Run / ROI | Avg / 1% low fps | p99 / max ms | M / G / C calls; overlap ms |
| --- | ---: | ---: | ---: |
| pc-cold / title | 58.668 / 22.846 | 33.958 / 49.509 | 0 / 0 / 0; 0.000 |
| pc-cold / cutscene | 28.630 / 23.480 | 41.517 / 44.272 | 0 / 0 / 0; 0.000 |
| pc-cold / chase | 26.082 / 12.497 | 49.105 / 178.403 | 3 / 34 / 0; 8.020 |
| pc-warm1 / title | 58.836 / 22.718 | 33.336 / 49.949 | 0 / 0 / 0; 0.000 |
| pc-warm1 / cutscene | 27.952 / 23.463 | 41.765 / 45.508 | 0 / 0 / 0; 0.000 |
| pc-warm1 / chase | 23.885 / 11.864 | 57.553 / 182.796 | 6 / 3 / 0; 0.284 |
| pc-warm2 / title | 58.288 / 22.483 | 33.721 / 51.251 | 0 / 0 / 0; 0.000 |
| pc-warm2 / cutscene | 27.365 / 18.966 | 43.703 / 59.065 | 0 / 0 / 0; 0.000 |
| pc-warm2 / chase | 26.045 / 14.677 | 47.121 / 159.002 | 6 / 4 / 0; 0.375 |

M/G/C are module/graphics/compute creation calls intersecting the ROI, with
duration clipped to its boundaries. Title and cutscene were already creation-free
when cold. Chase creation overlap falls **8.020 → 0.284 → 0.375 ms**.

| Run | Warmed / skipped pipelines | Boot prewarm loop ms | Launch → first app marker ms | Whole-route runtime M / G / C | Runtime API time ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| pc-cold | 0 / 0 | n/a (no records) | 977.772 | 161 / 410 / 13 | 370.098 |
| pc-warm1 | 423 / 0 | 180.577 | 1209.371 | 9 / 6 / 0 | 0.581 |
| pc-warm2 | 429 / 0 | 184.816 | 1249.638 | 7 / 5 / 0 | 0.481 |

The prewarm loop timer excludes executable hashing and record-file parsing. The
launch-to-first-marker column includes that startup work. Driver payloads grow
**3,809,872 → 3,809,872 → 3,809,872 bytes**. Recipes grow **423 → 429 → 434**,
with **161 shader identities** throughout. All six and five remaining runtime
graphics creations add new full-state records; no shader identity was newly
encountered. Modules can be recreated through the existing pointer/variant cache
for an unseen full-state pipeline. This explains the remainder without claiming
coverage of unobserved future states.

### Linux warm-frame gate and opt-in decision

The same-binary `pc-off1` control uses the versioned warm driver cache with
`NX_SHADER_PREWARM=0`. Its result is:

| ROI | Avg / 1% low fps | p99 / max ms | M / G / C calls; overlap ms |
| --- | ---: | ---: | ---: |
| title | 58.651 / 22.759 | 34.921 / 49.519 | 0 / 0 / 0; 0.000 |
| cutscene | 28.252 / 22.883 | 43.185 / 44.568 | 0 / 0 / 0; 0.000 |
| chase | 25.762 / 12.399 | 55.969 / 173.456 | 3 / 32 / 0; 2.238 |

The ON chase averages **23.885 and 26.045 fps** straddle the OFF control at
**25.762 fps**; one ON run is materially slower. The other ON run has a worse
cutscene tail: **18.966 fps 1% low / 59.065 ms max**, versus the control's
**22.883 fps / 44.568 ms**. No quota throttling occurs in the headline ROIs, and
other pod CPU use stays below 1.74% of the quota. Five-shot galleries confirm
the same route, with animation/dialogue phase differences; these samples cannot
isolate every cause of variance or prove a universal causal regression.
They also do not clear a warm-frame acceptance gate. The conservative result
is therefore **Linux prewarm opt-in**, as allowed by the brief, with the
versioned driver cache and pipeline recording still enabled by default.
`NX_SHADER_PREWARM=1` enables the measured boot replay; omission or `0` leaves it
off on Linux. Windows keeps its independently measured default-on policy, and
the Apple preprocessed cache code remains unchanged.

Prewarm-disabled sessions still record the states observed during that session;
the opt-in prewarm path reloads and extends its seed recipe inventory. The
remaining Linux frame-time bottlenecks and inherited material/glyph/occlusion
defects are not fixed by this cache port. No Linux 60-fps or stutter-free claim
is made. A fresh build of the final policy is verified separately below.

### Final Linux opt-in policy verification

The final policy build is SHA256
`c2693e7bb8f5ac1529e3a6c862c5a441293933768a7ef954bb1e1eb0109c4968`.
A separate fresh three-run sequence verifies that exact binary: `gated-cold`
omits `NX_SHADER_PREWARM` (default off) and has no application cache or records;
`gated-warm1` and `gated-warm2` explicitly set `NX_SHADER_PREWARM=1` and seed
both envelopes from their immediate predecessor. Other route, observer,
ROI and statistical definitions are unchanged. These are new measurements,
not pooled with the preceding gate experiment.

| Run / ROI | Avg / 1% low fps | p99 / max ms | M / G / C calls; overlap ms |
| --- | ---: | ---: | ---: |
| gated-cold / title | 58.722 / 22.777 | 34.640 / 50.633 | 0 / 0 / 0; 0.000 |
| gated-cold / cutscene | 29.525 / 23.965 | 40.247 / 44.973 | 0 / 0 / 0; 0.000 |
| gated-cold / chase | 25.866 / 12.667 | 54.254 / 167.973 | 3 / 34 / 0; 8.126 |
| gated-warm1 / title | 58.710 / 22.401 | 36.619 / 49.354 | 0 / 0 / 0; 0.000 |
| gated-warm1 / cutscene | 28.864 / 23.094 | 41.708 / 50.801 | 0 / 0 / 0; 0.000 |
| gated-warm1 / chase | 25.828 / 13.110 | 47.865 / 186.463 | 6 / 7 / 0; 0.623 |
| gated-warm2 / title | 58.678 / 22.902 | 34.190 / 49.390 | 0 / 0 / 0; 0.000 |
| gated-warm2 / cutscene | 26.703 / 19.673 | 48.927 / 53.707 | 0 / 0 / 0; 0.000 |
| gated-warm2 / chase | 25.891 / 14.815 | 46.485 / 147.133 | 2 / 1 / 0; 0.129 |

| Run | Warmed / skipped pipelines | Boot prewarm loop ms | Launch → first app marker ms | Whole-route runtime M / G / C | Runtime API time ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| gated-cold | 0 / 0 | n/a (default off; no records) | 1040.926 | 160 / 397 / 13 | 344.729 |
| gated-warm1 | 410 / 0 | 174.929 | 1200.904 | 21 / 20 / 0 | 7.835 |
| gated-warm2 | 430 / 0 | 182.592 | 1303.148 | 2 / 1 / 0 | 0.129 |

The final opt-in chase creation overlap falls **8.126 → 0.623 → 0.129 ms**;
title/cutscene remain creation-free. The validated recipe inventories grow
**410 → 430 → 431**; graphics creations add **20 then 1** new full-state recipes,
with no lost records. Shader identities grow **160 → 161 → 161**, so warm1 also
encounters one previously unseen shader. The remaining module calls reflect
that shader and existing pointer/variant-cache recreation for new pipeline
states. No claim is made that replay covers unseen states. Driver payloads are
**3,745,264 → 3,809,872 → 3,809,872 bytes**. The final warm2 cutscene tail remains
worse than cold despite zero creation overlap, supporting the conservative
opt-in decision rather than a 60-fps acceptance claim.

All nine final ROIs have **zero cgroup throttling**; peak other-process CPU is
**1.829% of the 7.65-CPU quota**. Each of 279 process observations sees only the
owned game, with disjoint lifetimes. The five captures for each run show the
title, lab, character and chase route; existing glyph/material/occlusion defects
remain. Animated dialogue/camera phases differ between runs. No native builds
or synthetic fixtures overlap these measured game runs.

Native hardware: Intel Xeon Gold 6342, NVIDIA A40 (46,068 MiB), driver
595.91.07, kernel 6.8.0-138-generic, 49,999,998,976-byte memory limit. GPU samples
remain at low reported clocks/utilization (as in the baseline); this unit does
not change the pod configuration or infer desktop/display performance.
The final source has 135 public runtime files matching the measured build
byte-for-byte. The four files changed by final desktop guard qualification
(including the cache header) are covered by four byte-identical native
minimized-preprocessor translation-unit comparisons. Generated main/SDK
archives remain byte-identical to the baseline inputs. The native cache fixture
runs 13 tests with two Apple-SDK-only skips; the unchanged Linux overlay fixture
passed all five tests. Android is excluded from desktop executable identity;
only its preprocessor guard is tested here, not an NDK build or Android game.

Final-policy private evidence: `linux/runs/gated-{cold,warm1,warm2}/` contains
raw observer/CPU/GPU/log/capture/cache artifacts, per-member hash manifests and
`cache-analysis.json`/`analysis.json`; `linux-gated-record-delta.json`,
`linux-gated-run-gates.json`, `linux-desktop-guard-equivalence.json`,
`linux-final-policy-source-verification.json` and `visual-checks.json` record
validation under the private PC-SHADER-027 root given above. At
2026-10-21T12:10:58Z, `native-linux-final/final-linux-state.json` records zero games,
the unchanged 7.65-CPU quota and the matching final ELF/observer hashes. All unit
runs are finished; the lead owns cloud resource closeout and independent review.

## LINUX-MEASURE-030 — 2026-10-21: staging attribution and rejected switch-default gate

**The matched-rendered-phase acceptance gate did not pass. Keep the replay-thread,
chunked-submit and pipelined Linux defaults unchanged.** The repeated fixed-route
numbers below are measured cadence, but cannot establish equal-workload scene
speedups. The useful positive result is a loss-free decomposition of a reproduced
~614 ms texture-staging stall: it is primarily dedicated Vulkan allocation plus
copying, alongside a larger ASTC demand-decode cost. No runtime change is committed
by this unit. The next implementation should address those measured resource costs
and repair scene-state matching before promoting scheduling defaults.

### Source, route and measurement controls

The source basis is main `4678bdb46959890a41314cc0a0eec04605024a07`, prepared from the
complete `series.linux`: CMake plus all **139 public runtime files**. The dynamic-cap
runtime was rebuilt on `acr-lnx`, reusing LINUX-BASE-026's unchanged generated main
and SDK archives and its uploaded game inputs in place. Runtime compilation/linking
after configuration took **22.756 s**; this is not a fresh lift/archive build time.
The exact stock executable is SHA256
`c2693e7bb8f5ac1529e3a6c862c5a441293933768a7ef954bb1e1eb0109c4968`, identical to
PC-SHADER-027's final Linux policy build. Main/archive SHA256 is
`11027554b13220db12b9a7404b946efbc0827220ad35d0b4ec8b5951c4f34609`; SDK is
`b167d8739322037cbcab7ef5f452b7cf4736e836530b179faed88ba5ac41977a`.

Live hardware is **A40, NVIDIA 595.91.07, 46,068 MiB VRAM**, with an Intel Xeon Gold
6342 host. The container exposes affinity to 96 logical CPUs; the allocation's
advertised 9 vCPUs are constrained by the actual **7.65-CPU cgroup-v1 quota**
(765000/100000). Memory limit is 49,999,998,976 bytes. No affinity, clocks, power,
resource or billing policy was changed. Sparse GPU samples and container CPU
accounting do not measure activity by other tenants on the physical host.

An external `LD_PRELOAD` timing/input observer counts the existing headless
`hud::on_present` mutex call. Its SDL keyboard shim injects the original route's
buttons at fixed present numbers, with the offscreen window's input-focus bit set
for that harness. `NX_INPUT_SCRIPT=99999:A:0.2` leaves the original script idle.
Neither lifted code nor runtime code changes in the **stock timing executable**.
The fixed-frame route is:

```text
1366-1378:B;1479-1490:B;5114-5144:ZL+ZR;8305-8325:MINUS;8388-8408:PLUS;
8859-8867:A;9026-9037:A;9211-9219:A;9435-9439:DOWN;9478-9484:DOWN;
9526-9531:DOWN;9618-9628:A
```

These are half-open held-state ranges. Cadence windows use present boundaries
**title 2760–4500 (1740 intervals), nominal lab 7440–8100 (660), nominal chase
13920–14640 (720)**. Captures are at exact presents **1981, 6901, 8221, 10201,
13381, 13861, 14701 and 15181**, outside those windows. Every run stops after
present 15300, allowing the final one-second sampling loop to overshoot slightly.
The legacy wall-clock `roi_proposed` receipt field is unused; `route.rois` and
`analysis.json` contain the actual selection and its per-run wall-time exposure.

Private `matched-` run names identify the attempted alignment, not a passed gate.
The title, lab and chase remain the same route chapters, but fixed present numbers
are **not a verified rendered-scene clock**. A separate calibration using accumulated
guest world-step time also failed: at logical frame 9000, the off capture shows
SUPERVISION while replay-thread shows PRODUCER. In the stock fixed-present test,
present 6901 instead shows SUPERVISION off and the Researcher conversation with
replay-thread. At 8221 the CHARACTER DESIGNER credit appears in both, while the
camera/transition differs. The cause of this state mismatch remains unresolved.
Two clock-based phase adjustments were therefore rejected; phase identification
is split out as a prerequisite for default promotion, rather than treating the
higher cadence as proof of equivalent work. These failures are retained privately.

Each timing run has a new save/data root and exactly the same frozen, hash-checked
warm driver/recipe files, seeded from the completed stock pilot. Versioned caching
and recording remain enabled; **recorded prewarm remains omitted/default-off** as
in current Linux policy. OS/driver caches are not purged. Common settings retain
headless/offscreen rendering, `NX_GPU_PROFILE=3`, cached upload-ring default,
texture write-watch default and file-only shared logging. `NX_SAMPLE` is absent;
the supplied FPS-007 generated observers remain. There is one game at a time, no
build during a retained measured run, a 15-second CPU/GPU quiet gate, and one-second
process/thread/cgroup samples. Archiving happens after reaping the game and before
the next quiet gate. Frames are independently checked against the runtime's frame
logger. Headless cadence is **not displayed FPS**; synchronous mode3's zero GPU
counters are unavailable timings, not zero GPU work.

Average FPS is N/summed interval time; 1% low is the reciprocal of the mean of the
slowest ceil(1% × N) intervals; p99 is linearly interpolated. Counts use strict
>25 and >50 ms. A/B and their observed spread are two observations, not a confidence
interval. Fixed interval counts give different wall-time exposures between modes.

### Two repeats per configuration: nominal-route cadence, phase gate failed

Off sets all three controls to 0. Thread sets replay=1; chunks sets draws=150;
both sets those two; the final joint case adds pipeline=2. Chunking is **inactive
without the asynchronous frame path**: `frame_ring_size()` is zero and `frame_init`
does not initialize chunking when pipeline/async is off. Thus off/chunks and
thread/both are two effective-control equivalence classes; differences between
members are not evidence of a chunking effect. The fifth case exercises the replay
class with pipeline and chunking jointly active. The failed phase gate prevents
identifying a proven best equal-workload configuration or isolating pipeline from
the chunking it activates.

All paired cells below are **A / B**. The FPS range is the observed repeat spread.

| Configuration / nominal ROI | Avg FPS A / B [min–max] | 1% low FPS | p99 ms | Max ms | >25 / >50 counts A ; B |
| --- | --- | --- | --- | --- | --- |
| Off / title | 58.627 / 58.604 [58.604–58.627] | 23.282 / 22.821 | 33.409 / 35.670 | 53.242 / 48.923 | 281 / 1 ; 280 / 0 |
| Off / lab | 27.496 / 29.075 [27.496–29.075] | 22.819 / 24.624 | 42.420 / 40.218 | 50.582 / 41.201 | 627 / 1 ; 643 / 0 |
| Off / chase | 21.104 / 25.333 [21.104–25.333] | 9.393 / 16.330 | 82.403 / 46.707 | 194.582 / 103.569 | 720 / 239 ; 720 / 4 |
| Replay thread / title | 57.228 / 57.454 [57.228–57.454] | 18.592 / 18.608 | 41.438 / 41.948 | 65.155 / 64.456 | 307 / 12 ; 295 / 12 |
| Replay thread / lab | 46.046 / 47.828 [46.046–47.828] | 27.521 / 33.538 | 30.635 / 27.475 | 43.148 / 33.978 | 132 / 0 ; 75 / 0 |
| Replay thread / chase | 36.709 / 35.064 [35.064–36.709] | 19.217 / 23.298 | 43.418 / 37.412 | 92.549 / 56.273 | 720 / 2 ; 720 / 2 |
| 150-draw chunks / title | 58.414 / 58.771 [58.414–58.771] | 24.534 / 22.512 | 32.788 / 33.334 | 48.681 / 50.193 | 231 / 0 ; 273 / 1 |
| 150-draw chunks / lab | 27.089 / 28.855 [27.089–28.855] | 22.337 / 24.379 | 43.758 / 40.552 | 45.763 / 41.827 | 628 / 0 ; 647 / 0 |
| 150-draw chunks / chase | 24.608 / 24.768 [24.608–24.768] | 12.640 / 14.553 | 54.720 / 56.718 | 165.103 / 103.057 | 720 / 35 ; 720 / 21 |
| Thread + chunks / title | 57.240 / 57.510 [57.240–57.510] | 18.513 / 19.197 | 41.002 / 42.208 | 68.813 / 59.635 | 293 / 12 ; 316 / 11 |
| Thread + chunks / lab | 45.417 / 48.293 [45.417–48.293] | 30.460 / 33.356 | 29.709 / 27.317 | 36.087 / 34.703 | 163 / 0 ; 67 / 0 |
| Thread + chunks / chase | 38.289 / 37.379 [37.379–38.289] | 20.800 / 21.680 | 29.123 / 32.381 | 89.510 / 90.223 | 637 / 1 ; 720 / 1 |
| Thread + chunks + pipeline 2 / title | 57.380 / 57.102 [57.102–57.380] | 18.753 / 18.272 | 42.681 / 42.727 | 66.682 / 66.693 | 367 / 11 ; 367 / 12 |
| Thread + chunks + pipeline 2 / lab | 50.327 / 48.521 [48.521–50.327] | 32.637 / 32.281 | 27.887 / 28.576 | 35.008 / 36.239 | 79 / 0 ; 115 / 0 |
| Thread + chunks + pipeline 2 / chase | 51.533 / 51.136 [51.136–51.533] | 15.170 / 15.300 | 27.475 / 29.121 | 230.394 / 215.893 | 13 / 2 ; 16 / 2 |

### Host-stage counters, CPU service and visual checks

These **elapsed host-stage** counters are means of complete 60-present buckets
inside the selected slot, in replay / encode / fence / other / present order.
The shader logger starts at 0 while observer/capture presents start at 1; bucket
selection explicitly accounts for that offset. Independent logger-clock FPS checks
agree with observer-clock averages.
They are not exclusive CPU service. Fence contains waiting; replay-thread counters
run on another thread and are not a serial critical path. Actual **whole-process
CPU ms per present** comes separately from `/proc` ticks and includes other guest
threads and decoder workers. Per-thread values and sample granularity are retained
in `analysis.json`; a busy thread is not automatically the NVN caller.

| Configuration / ROI | Replay A / B | Encode A / B | Fence A / B | Other A / B | Present A / B | Process CPU ms/present A / B |
| --- | --- | --- | --- | --- | --- | --- |
| Off / title | 2.993 / 2.809 | 0.049 / 0.047 | 2.644 / 2.485 | 2.084 / 2.012 | 0.070 / 0.079 | 19.874 / 22.473 |
| Off / lab | 5.870 / 5.147 | 0.040 / 0.040 | 5.109 / 4.848 | 1.752 / 1.376 | 0.090 / 0.090 | 43.924 / 42.396 |
| Off / chase | 17.277 / 12.545 | 0.093 / 0.073 | 9.319 / 8.778 | 6.288 / 5.574 | 0.345 / 0.163 | 117.954 / 98.474 |
| Replay thread / title | 4.450 / 4.677 | 0.066 / 0.068 | 2.667 / 2.720 | 3.479 / 3.417 | 0.081 / 0.082 | 27.300 / 28.898 |
| Replay thread / lab | 11.262 / 10.821 | 0.071 / 0.072 | 5.050 / 5.003 | 2.921 / 2.844 | 0.078 / 0.072 | 45.518 / 42.680 |
| Replay thread / chase | 12.217 / 13.010 | 0.065 / 0.070 | 8.821 / 8.914 | 5.891 / 6.584 | 0.241 / 0.108 | 101.683 / 105.231 |
| 150-draw chunks / title | 3.326 / 2.770 | 0.056 / 0.043 | 2.702 / 2.614 | 2.306 / 2.038 | 0.076 / 0.077 | 22.179 / 21.394 |
| 150-draw chunks / lab | 5.777 / 5.285 | 0.040 / 0.040 | 5.122 / 4.876 | 1.765 / 1.440 | 0.088 / 0.090 | 45.494 / 42.274 |
| 150-draw chunks / chase | 13.466 / 13.279 | 0.067 / 0.074 | 8.871 / 8.863 | 5.578 / 5.444 | 0.228 / 0.246 | 104.259 / 103.553 |
| Thread + chunks / title | 4.643 / 4.400 | 0.073 / 0.065 | 2.617 / 2.661 | 3.732 / 3.361 | 0.084 / 0.076 | 28.174 / 25.823 |
| Thread + chunks / lab | 11.434 / 10.805 | 0.070 / 0.070 | 4.941 / 5.016 | 2.903 / 2.823 | 0.078 / 0.071 | 47.016 / 41.532 |
| Thread + chunks / chase | 12.017 / 11.953 | 0.065 / 0.064 | 8.700 / 8.727 | 5.087 / 5.845 | 0.235 / 0.166 | 97.014 / 99.585 |
| Thread + chunks + pipeline 2 / title | 4.296 / 4.347 | 0.098 / 0.099 | 1.893 / 1.929 | 3.462 / 3.453 | 0.083 / 0.082 | 28.878 / 27.262 |
| Thread + chunks + pipeline 2 / lab | 10.578 / 10.930 | 0.144 / 0.153 | 2.352 / 2.543 | 2.972 / 3.061 | 0.072 / 0.080 | 42.284 / 43.312 |
| Thread + chunks + pipeline 2 / chase | 11.563 / 11.283 | 0.174 / 0.171 | 2.335 / 2.529 | 4.046 / 4.301 | 0.179 / 0.180 | 78.597 / 79.102 |

Retained nominal timing-window cgroup throttling totals **0.000 ms**; maximum sampled non-game container CPU is **1.911% of quota**. GPU clocks and per-run shader/pipeline creation events remain in raw evidence. Those controls do not repair the rendered-phase mismatch.

| Configuration | Same-present capture comparison and decision |
| --- | --- |
| Off | A/B show the bracelet title but different bracelet orientations. At 6901 both retain SUPERVISION with different character/camera poses; at 13861 highway/camera/vehicle phase differs. Even the control repeat is not an identical rendered state. Red glyph and occlusion defects remain; no fidelity acceptance. |
| Replay thread | At 6901 both repeats show the Researcher conversation rather than the off SUPERVISION view. At 13861 A shows VISUAL EFFECTS DESIGN on a bend, B INTERFACE DESIGN on a straight section; car/camera/dialogue phase differs. Bracelet orientation also differs. Phase gate failed. |
| 150-draw chunks | At 6901 A/B retain SUPERVISION, but camera/character pose and glyphs vary; at 13861 they show a straight highway with different vehicle positions. The chunk path is inactive while pipeline=0, so those differences cannot demonstrate a chunk optimization. No new fidelity acceptance. |
| Thread + chunks | At 6901 both repeats show the Researcher conversation with different character poses. At 13861 the bend/credit/NPC state differs between A/B and from off; red glyph defects remain. This is the same effective replay class as thread while pipeline=0. Phase gate failed. |
| Thread + chunks + pipeline 2 | At 1981 A/B retain the bracelet title with different orientations. At 6901 both show the two-researcher conversation/chamber view, unlike the off SUPERVISION camera. At 13861 both have ANIMATION credits, explosions/debris and different enemy/dialogue state, unlike the off straight-road snapshots. A/B also vary in camera/object pose. Rendered-phase and broad fidelity gates remain failed. |

The inherited occlusion/glyph problems and bounded captures do not establish full
Linux fidelity, audio/gamepad acceptance, game-time parity or physical display
performance. **No scheduling default is promoted from this A40 matrix.**

### Texture-staging attribution: two loss-free diagnostic routes

The private measuring instrument is built from PC-UNTILE-028's Linux diagnostic
source with fine spans around Vulkan buffer/allocation/bind/map, copying,
conversion, ASTC decoder/output allocation, untiling, copy commands, queue submit
and fences. Original generated archives are unchanged; `NX_GPU_UNTILE` is **unset**.
This is a separate diagnostic executable, SHA256
`3e712ccd202a752655513fd8ac01c33c810b1b8d051480ff89e09591ba4f9db8`, excluded from
the timing matrix. Optional fine inner-untile instrumentation was split out after
two build failures; the retained outer untile span includes layout and linear-output
allocation, the latter measured separately. No production series is changed.

Cold has no application cache; warm seeds both versioned files from cold, with
prewarm still off. Both use fresh saves, the fixed route, no captures and the same
controls off. Binary `ACST0001` records and the observer use CLOCK_MONOTONIC. The
private additions also record **calling-thread** CLOCK_THREAD_CPUTIME_ID spans;
ASTC already uses up to six workers on large mip levels, so its caller CPU is not
total decoder CPU. CPU clock/trace overhead is included. Inclusive/nested spans
must not be added. Zero loss means no reported buffer overflow and full coverage
of the selected windows; the final unflushed `_exit` tail is outside those windows. Creation API spans are also read from the frame log.

Cold records **101,470 events**, warm **101,501**, both **zero loss**, with all ROI ends covered. Both make **318 dedicated staging allocations / 2187.234 MB** and select memory type **3** (host-visible/coherent, not host-cached). The existing upload ring uses type **4** (also host-cached). Recorded-route components, including boot and the flushed trace prefix, are:

| Component | Elapsed ms cold / warm | Calling-thread CPU ms cold / warm |
| --- | --- | --- |
| Texture preparation, inclusive | 5913.957 / 6475.434 | 5285.630 / 5306.276 |
| ASTC decoder calls (including worker setup/join) | 3806.041 / 3878.780 | 3217.763 / 3233.005 |
| RGBA output allocation/zero initialization | 417.217 / 390.715 | 417.255 / 390.721 |
| Dedicated staging allocation, inclusive | 1016.326 / 1650.920 | 976.373 / 1127.496 |
| vkAllocateMemory within staging | 1012.782 / 1647.471 | 973.022 / 1124.239 |
| Texture payload memcpy | 359.994 / 360.572 | 360.033 / 360.578 |
| Untile/layout/output allocation, inclusive | 258.299 / 142.510 | 258.089 / 142.369 |
| Linear output allocation within untile | 34.921 / 32.865 | 34.817 / 32.739 |
| vkCmdCopyBufferToImage recording | 6.357 / 6.474 | 6.124 / 6.226 |

The synchronous path reports `frame_ring_size()==0`. Consequently
`staging_wanted()` selects a separate buffer for every 1 MiB+ texture, and
`staging_alloc()` takes the first HOST_VISIBLE|HOST_COHERENT memory type, 3,
instead of the cached ring's selection. This explains why the cached-ring default
does not remove the measured dedicated-allocation cost.

The following are exact containing present intervals, with overlapping costs
reported separately. "Upload" is the original coarse staging span; allocation,
copy and command recording decompose it. ASTC and untile are outside that coarse
span and remain part of the longer frame.

| Run / event / end present | Interval ms | Upload ms | Staging allocation ms [vkAllocateMemory] | Memcpy ms | ASTC decoder / RGBA-init ms | Untile ms | Copy-command / queue-submit / fence ms | Staged MB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| staging-cold / lab_entry / 5215 | 3306.650 | 615.373 | 438.494 [437.315] | 173.517 | 1603.818 / 303.560 | 98.588 | 1.522 / 0.094 / 56.678 | 1111.534 |
| staging-cold / chase_entry / 10522 | 1041.429 | 200.988 | 149.617 [149.081] | 49.838 | 591.013 / 51.304 | 7.999 | 0.681 / 0.057 / 20.515 | 303.388 |
| staging-warm / lab_entry / 5189 | 3129.403 | 614.237 | 437.215 [436.097] | 173.753 | 1632.564 / 304.568 | 46.222 | 1.521 / 0.091 / 58.434 | 1111.534 |
| staging-warm / chase_entry / 11391 | 1205.302 | 650.742 | 626.100 [625.796] | 23.902 | 322.172 / 6.467 | 6.266 | 0.332 / 0.077 / 10.825 | 149.597 |

The cold/warm lab staging spans **615.373 / 614.237 ms** reproduce the earlier
613.8 ms lead. In the cold lab interval, **438.494 ms allocation + 173.517 ms copy**
account for almost all staging; the allocation API itself consumes **437.315 ms**.
That is not a 614 ms untile operation. The larger frame also contains **1603.818 ms
of ASTC decoder calls (including worker setup/join)** and **303.560 ms of RGBA output initialization**.

The biggest texture in both lab loads is **8192×4096 ASTC 8×8 sRGB (NVN 0x8e),
14 mips, one layer**: 11.190 MB tiled input expands to **178.957 MB** of staged
RGBA. The lab frame stages **1111.534 MB** in dedicated buffers. Other leading
resources are 4096×4096 ASTC 8×8 linear (0x80), 89.478 MB with mips, and
2048×2048 variants of both formats, 22.370 MB. Raw JSON assigns sizes and formats
to every parent texture span; these shape/byte observations are not a content-hash
oracle. The entire large load cannot safely be forced into the 256 MiB ring;
`NX_STAGING_RING=1` risks the known self-overwrite case and is not a fix.

Warm also contains a **5.592 MB allocation taking 444.674 ms elapsed but 15.006 ms
of caller CPU** inside `vkAllocateMemory`, in the 1205.302 ms chase-entry interval.
There is zero cgroup throttling across both diagnostic routes. This identifies an
allocation API stall with a large non-caller-CPU component; NVIDIA-internal
blocking versus host descheduling is unresolved. It is not measured as a Vulkan
fence wait. Texture-copy spans record only **1 / 4 minor faults and zero major
faults** over the entire cold/warm routes; metadata recording may itself contribute
minor faults. A memcpy page-fault storm is not supported by these traces.

Every selected >50 ms interval is retained in `spikes-gt50.csv` and expanded
`staging-analysis.json`, including intervals with zero texture work. The regions
are startup presents 0–1366, lab entry 5114–6900, chase entry 8305–13380, and the
three nominal timing slots above. The table sums **overlapping texture costs**,
not mutually exclusive frame time. Widening spans cover the instrumented block-linear
branch; other conversion/setup work remains in the parent texture residual. "Uncovered" is the interval portion outside
the union of texture, queue/fence and creation spans and remains unattributed.

| Region | >50 ms cold / warm | Max interval ms cold / warm | Texture ms in those intervals | Staging allocation ms | Memcpy ms | ASTC decoder ms |
| --- | --- | --- | --- | --- | --- | --- |
| startup | 12 / 13 | 231.734 / 227.585 | 29.455 / 13.987 | 11.139 / 4.408 | 2.951 / 1.548 | 0.000 / 0.000 |
| lab_entry | 5 / 7 | 3306.650 / 3129.403 | 2666.806 / 2648.838 | 443.878 / 451.649 | 175.121 / 175.416 | 1603.818 / 1632.564 |
| chase_entry | 102 / 88 | 1041.429 / 1205.302 | 2941.802 / 3529.671 | 512.153 / 1131.664 | 166.239 / 164.893 | 2049.742 / 2095.723 |
| title | 1 / 0 | 50.568 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 |
| cutscene | 4 / 0 | 65.375 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 |
| chase | 8 / 11 | 115.763 / 94.658 | 3.328 / 4.099 | 0.000 / 0.000 | 0.080 / 0.105 | 2.760 / 3.665 |

This accounts for **132 cold / 119 warm** selected intervals individually. The many zero-texture or mostly uncovered intervals remain a separate CPU/dependency/pacing investigation; staging fixes cannot be credited with solving them.


### Three fixable causes and expected gain bounds

These are implementation targets, not measured game speedups. Their gains overlap;
cache I/O, allocation lifetime, GPU transfer and other frame work remain.

| Priority / cause | Evidence and proposed change | Expected gain / required check |
| --- | --- | --- |
| 1 — fresh dedicated allocation policy | 318 calls / 2187.234 MB per route; 1016.326–1650.920 ms allocation spans, including the opaque warm allocation stall. Prefer cached/coherent memory on Linux, then a bounded staging arena/pool retired by the existing submission serial. Retain fresh-allocation fallback. | Isolated same-device five-repeat Vulkan fixture, 64 MiB: type-3 create/allocate median **23.301 ms** (22.522–24.071), type 4 **5.913 ms** (5.854–6.000). First memcpy is **10.276 / 10.260 ms**, so the measured gain is allocation, not faster copying. A cached preference targets the lab's 437 ms allocation slice; ~75% is observed only for the fixture sizes, not proven for all in-game allocations. Pooling removes reusable allocation calls after retirement; it cannot reuse all 1.1 GB while the initial submit still owns it. The 429 ms non-caller-CPU gap is not a guaranteed recoverable gain if it is host descheduling. |
| 2 — demand ASTC decoding | **3806.041–3878.780 ms** in decoder calls per route. Linux has no equivalent of the Windows validated decoded-output cache in this measured path. Port the bounded, content/dimensions/format/mip/layer/decoder-version keyed cache with corruption and fallback checks. | Warm-cache target: remove a substantial fraction of the **1.604–1.633 s lab decode slice**, bounded above by measured decoder time and reduced by hashing/read/decompression costs. Cold cache misses still decode. The decoder already creates up to six workers for large mip levels; adding "parallel decoding" is not a new technique. Measure a persistent worker pool separately before crediting thread reuse with a gain. |
| 3 — expanded RGBA intermediates | **390.715–417.217 ms** output initialization plus **359.994–360.572 ms** texture memcpy per route. Decode/read validated cached output directly into final mapped staging where safe. | At most roughly **0.75–0.78 s/route** of these measured components is addressed, not an additive promise alongside the decoded-output cache. The cold lab contains **303.560 + 173.517 ms** of these costs. Preserve defined invalid-block output, all mips/layers, partial edges and alignment/padding; require byte comparisons before removing zero initialization or copies. |

The standalone Vulkan fixture uses the actual A40 memory-type bits and validates
sampled written bytes outside its timed copies. Five pairs at each of 1, 8, 32 and
64 MiB distinguish fresh allocation from reused-copy passes. It is not a game
speedup or a complete GPU readback oracle. No policy was changed while measuring.
Untile, including layout/output allocation, totals only **142.510–258.299 ms/route**;
subtracting separately measured linear allocation leaves about **109.645–223.378 ms**
for the remaining untile/layout work. GPU untile is not the leading remedy for
these multi-second loads, and its CPU fallback remains the default.

### Concrete LINUX-PERF-031 plan

1. **Keep the tested discrete-Linux switch defaults unchanged/off and prewarm opt-in.** Preserve the existing integrated-GPU policy. Establish a real rendered-state
   anchor (camera/scene state or content signature), rather than another global
   timer guess. First make diagnostic readback prefer cached/coherent memory where
   available: current PPM capture can take ~200 ms and can perturb queues. Confirm
   capture overhead and align start/middle/end states before a new two-repeat
   scene benchmark. The present unit does not clear that prerequisite.
2. **Implement the Linux dedicated-staging cached-memory preference first**, with
   an escape/fallback and no change to other platforms. Measure off/on in the same
   binary using the actual large allocation sizes, identical resource-shape/byte
   batches and per-API CPU/wall spans. Run a real GPU upload/readback byte oracle,
   malformed/edge-format cases and visual checks. Promote this memory preference
   only after those gates; the already-default cached upload ring is not a new gain.
3. **Add bounded retired staging reuse as a separate change.** Preserve submission
   serial ownership, chunk/split lifetimes, buffer offsets and overflow allocations.
   Never wrap over live data. Record allocated/reused/peak bytes, allocation calls
   and wait reasons. A retained-byte cap is mandatory; first-load preallocation
   moves cost to boot and must be reported separately from eliminating it.
4. **Port the validated CPU ASTC output-cache technique**, then investigate direct
   decode/cache-read into mapped staging and persistent worker reuse independently.
   Keep GPU untile off. Report true misses/hits, cache I/O and decoder/output/copy
   spans; compare cold and two warm routes. Preserve decoder bytes and errors.
5. **Take the low-risk LINUX-BASE-026 ports next:** Linux x86-64 AVX2 changed-word
   writeback with scalar/tail/full-copy fallback and a byte oracle; command payload
   arena/final-owner pool, then selection scratch with concurrent/final-owner tests
   and the existing 256-list/32 MiB free-pool bounds. Earlier fixture budgets of
   0–1 ms/frame for writeback and 0–0.8 ms for recording remain estimates. Add real
   scan/changed/upload byte counters and valid synchronous GPU timestamps first.
6. **Defer heap residency, GPU narrowing and extra overlap** until a Linux
   write-generation backend passes concurrency/alias/free/reuse semantics. Whole-
   heap soft-dirty polling and unavailable userfaultfd remain feasibility gates;
   GetWriteWatch is not portable. Keep canonical keys/dynamic filtering behind
   measured traffic. Port exact depth/MRT/precision eligibility on a separate
   fidelity track, with no assumed FPS gain. Only then revisit replay/pipeline/
   chunk defaults with matched scenes, world/game-time checks and a windowed test.

Staging improvements principally target first-use/load tails. These measurements
do not demonstrate removal of the steady 60-FPS gap, and their estimates must not
be summed into a 60-FPS forecast. In particular the nominal replay-thread title
cadence/tails must pass their own non-regression gate, independently of lab/chase.

### Verification, review and retained evidence

The required command is `python3 -m unittest discover -s tests -p 'test_astral_linux.py'`.
Final output and exact-head scope checks are retained privately. The local run uses
the pinned upstream reference for complete-series application; native Linux fiber
execution is the explicit platform skip on the Mac. This is source/platform
verification, not a substitute for the failed rendered-phase acceptance gate.
Independent review of the committed documentation head belongs to the lead; it
is pending, not waived. No nested review, main/branch push, public change, Mac game,
Windows VM or resource/billing operation was performed.

Private Mac evidence root is `$ACS_ROOT/.local/units/LINUX-MEASURE-030/`; pod root
is `/root/acr/units/LINUX-MEASURE-030/`. All raw game-derived content stays ignored. The pod was marked **POD-FREE at
2026-10-21T17:34:58Z** after confirming zero games/builds and verifying all 17 run
archives plus the metadata archive locally; no resource was stopped or deleted.

| Private evidence | Contents |
| --- | --- |
| `source-receipt.json`, `build-receipt.json`, `source.tgz`, `metadata.tgz` | Exact main source, generated archive identity, build configuration and retained native executable |
| `route.json`, `route.tsv`, `observe-route.c`, `observe.so`, `run.py`, `pipeline-choice.json` | Fixed input/capture schedule, external observer and final joint-candidate selection |
| `runs/matched-{off,thread,chunk,both,pipe}-{A,B}/` | Hash-verified raw archive, env/receipt, input events, present timestamps, frame/creation logs, process/thread/cgroup samples, original captures and analysis |
| Per-run `capture-manifest.json`, `preview/`, `visual-review.json` | Exact capture numbers/hashes and observed phase/fidelity failures |
| `runs/{staging-cold,staging-warm}/{trace.bin,staging-analysis.json,spikes-gt50.csv}` | All fine spans, calling-thread CPU, sizes/formats and every selected >50 ms interval, including uncovered time |
| `diagnostic-source-receipt.json`, `diagnostic-source.tgz`, `build-diag-receipt.json` | Reproducible private 028-based measuring instrument and exact executable identity |
| `staging-bench.cpp`, `staging-bench.jsonl`, `staging-bench-summary.json` | Actual Vulkan type-3/type-4 allocation/copy fixture and five-repeat ranges |
| `runs/{pilot-off,phase-train,off-A,thread-A,fixed-thread-A}/`, `RESUME.md` | Rejected clock calibrations and invalid observer-installation pilot, explicitly excluded from the matrix |
| `collection-checkpoint.jsonl`, `raw-manifest.json`, `evidence-validation.json`, `verify.log`, `native-artifacts/final-state.json` | Archive SHA256 checks, scoped verification, zero-game closeout and POD-FREE handoff |


## LINUX-PERF-031: cached staging and bounded retired reuse (2026-10-21)

The LINUX-MEASURE-030 documentation above is included from the requested
`cfbdfbf5e7b1d7d7976734e14d532265b4a2f3e1` cherry-pick. Its switch
matrix remains **nominal/unaligned**, with no equal-workload FPS, scheduling
causality or scheduling-default promotion. Its staging measurements are historical
observations, not the controls for the new experiment below.

This unit implements the first item: Linux upload-staging memory preference and
retired-buffer reuse. The decoded ASTC cache, AVX2 writeback and command-storage
ports are **deferred under the shared-refactor restriction** described below.
They have no new Linux A/B results or default changes in this unit.

### Ownership, bounds and fallback

`astral-linux.patch` adds `nvn_linux_staging.h` and Linux-only blocks in
`nvn_frames.cpp`; the series files and Windows overlays are unchanged. Staging
still uses a separate transfer-source buffer for each live large upload, offset
zero. It does not put the 1.1 GB laboratory batch into the 256 MiB ring.

`NX_LINUX_STAGING_CACHED` first selects a compatible HOST_VISIBLE | HOST_COHERENT |
HOST_CACHED memory type. If none exists, it uses the original coherent selection.
A preferred-type allocation/bind/map failure disposes the partial allocation,
recreates the buffer and retries the original type. A failed allocation output
never transfers handle ownership. Final failure preserves the old ring fallback.

`NX_LINUX_STAGING_POOL` enables best-fit whole-buffer reuse, accepting capacity
from the requested size through twice that size. Buffers retain the old graveyard's
`g_submitted + 1` ownership and become reusable only at the existing completed
submission serial. The existing GPU lock serializes allocation and retirement;
chunk/split work keeps the same conservative whole-submit lifetime. No wait for
pool space or within-submit wrap is introduced. Free storage is capped at
**256 MiB of actual Vulkan allocation bytes and 32 buffers**; excess is freed.
Live uploads are separate from this free-storage cap. Storage is allocated on
first use, without boot preallocation; free pooled buffers remain until reuse or
process exit. This is a bounded retention tradeoff, not elimination of all memory.

### Linux policy after the byte and stage gates

- `NX_LINUX_STAGING_CACHED` defaults to **0**; explicit `0` disables it and `1` enables it.
- `NX_LINUX_STAGING_POOL` defaults to **0**; explicit `0` disables it and `1` enables it.

Set both to `0` to recover the old dedicated uncached path. The cached upload-ring
policy already present before 031 is unchanged. Replay-thread, pipeline, chunk,
integrated-GPU and recorded-prewarm policies are unchanged.

### Byte identity and visual checks

The A40 synthetic suite runs the original dedicated allocator, cached dedicated
allocator and cached pool through real buffer → image → readback transfers:
**72 images / 24 matching triples**, three data patterns per case, including
1×1, odd dimensions, mip chains, arrays, BC1/BC3, integer/half-float formats and
the 8192×4096/14-mip RGBA expansion. It compares every transferred byte and also
records FNV-1a-64 hashes. The retained suite explicitly enables supported BC
compression. It transfers **840,451,896 bytes per mode**, reuses 14 buffers and
keeps at most 101,193,728 free bytes. Earlier synthetic output without the explicit
BC feature enable is retained privately and excluded.

A separate full-route oracle reads each large uploaded image back from the GPU,
compares every transferred region with its CPU source, and records shape/format,
length and readback hash. The old path and exact timing candidate both cover
**all 318 staging requests / 2,187,234,256 requested bytes**. Their
**2,187,230,876 transferred texel bytes** (alignment gaps excluded), 235 unique
hashes and complete 318-entry multisets match, with zero byte mismatches and
zero lost trace events. The oracle includes mip levels/layers rather than only
rendered pixels. The pooled timing candidate's oracle has 144 fresh allocations / 174
reuses and a 218,146,096-byte free peak. A separate cached-only V2 route also
completes with exit 0, all 318 uploads / 2,187,230,876 texel bytes equal, and the
same complete old-path hash multiset. Oracle/hash/readback overhead is excluded
from performance measurements.

Title, laboratory researchers and the File 01 tunnel/bike chase are visually
checked. Camera, animation and dialogue phase still differ between captures.
Inherited red glyph/occlusion defects remain; these bounded checks are not full
fidelity or displayed-FPS acceptance. Two preliminary oracle runs accidentally
combined wall-clock and frame inputs and stopped at character creation. They are
retained as rejected `oracle-off` / `oracle-on`, not full-route or timing evidence.
The corrected runs explicitly set `NX_INPUT_SCRIPT=99999:A:0.2` so only the frozen
frame-input observer drives the route.

### Two repeats per staging setting on the A40

Settings below are `(NX_LINUX_STAGING_CACHED, NX_LINUX_STAGING_POOL)`:
`off=(0,0)`, `cached=(1,0)`, `pool=(1,1)`. Pooling is measured incrementally
against cached-only staging.

All six performance runs use one executable, SHA256
`04e8e626a7acd8eedde61b5de84587bea0187de93bf0a77621a45bfe17436d6d`, the same original generated archives, fresh saves,
identical frozen warm shader-cache seed and 030's fixed-present route through
present 15300. The runtime accepts the current executable's `755510...` seed
and loads 3,745,264 Vulkan payload bytes in each retained run. Stage totals stop
at present **15200**, leaving a common 100-present trace-flush guard before
execution stops at 15300; this preserves the route uploads and last requested
capture at 15181. Five runs have 318 requests; cached-B has 325 requests,
35 MB more traffic. Stage totals are clipped at that exact timestamp; raw
overshoot and shutdown tails remain retained. ASTC output is cold per process;
OS/driver caches are not purged.
Replay/pipeline/chunks are explicitly 0; GPU untile and prewarm are unset.
There is one game at a time, no concurrent build, a 15-second quiet-launch gate,
and process/thread/cgroup/GPU sampling. Off uses A40 memory type 3; cached and pooled fresh allocations use type 4.
The binary adds private stage/calling-thread
CPU probes, including staging retirement/freeing, plus optional byte-oracle code
that is disabled in these six runs. It has no guest-code or decoder changes.
The newly added cleanup probe initially hit Clang 14's structured-binding lambda
capture limitation; an explicit value capture fixed that measuring instrument.

These are per-frame load attributions and complete route-prefix stage totals with staging traffic
reported explicitly per run. They do not establish equal rendered
work or causal FPS gains. A private host-fault observer is identical across all
six runs; its normal-map and intentional-fault self-checks pass before launch. Elapsed spans include driver waiting; CPU spans measure
the caller, not all ASTC workers. Inclusive texture/ASTC/untile spans must not be
added to their children. The combined staging column adds only non-nested
allocation, retirement, memcpy, conversion and copy-command spans; it does not add
`vkAllocateMemory` or `vkFreeMemory` again.

| Run | Requests / MB | Fresh / reused | Free peak MiB | Allocation [vkAllocateMemory] ms | Retirement [vkFreeMemory] ms | Memcpy ms | Combined staging ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `verified-off-A` | 318 / 2187.234 | 318 / 0 | 0.000 | 947.097 [943.629] | 887.433 [695.580] | 354.071 | 2194.627 |
| `verified-off-B` | 318 / 2187.234 | 318 / 0 | 0.000 | 1040.599 [1037.057] | 915.748 [731.260] | 373.472 | 2335.967 |
| `verified-cached-A` | 318 / 2187.234 | 318 / 0 | 0.000 | 392.782 [389.270] | 558.171 [372.124] | 350.168 | 1307.040 |
| `verified-cached-B` | 325 / 2222.187 | 325 / 0 | 0.000 | 550.255 [545.657] | 614.497 [426.780] | 466.514 | 1638.493 |
| `verified-pool-A` | 318 / 2187.234 | 144 / 174 | 208.040 | 203.428 [201.344] | 302.647 [111.322] | 280.974 | 793.430 |
| `verified-pool-B` | 318 / 2187.234 | 144 / 174 | 208.040 | 699.686 [696.794] | 363.677 [173.750] | 518.186 | 1589.751 |

| Run | Texture inclusive ms | ASTC decode / RGBA-init ms | Untile inclusive ms | Copy-command ms |
| --- | ---: | ---: | ---: | ---: |
| `verified-off-A` | 5660.874 | 3771.312 / 409.695 | 129.664 | 6.027 |
| `verified-off-B` | 5870.178 | 3772.080 / 463.569 | 153.343 | 6.148 |
| `verified-cached-A` | 5196.248 | 3806.467 / 421.000 | 161.997 | 5.920 |
| `verified-cached-B` | 5760.118 | 3917.914 / 441.474 | 327.767 | 7.227 |
| `verified-pool-A` | 4897.346 | 3798.321 / 422.466 | 137.812 | 6.381 |
| `verified-pool-B` | 5978.909 | 3836.403 / 574.836 | 272.224 | 8.202 |

The laboratory table selects the containing interval with the largest staging
attribution in the lab-entry region. Each contains the same **1,111,533,824 bytes
of dedicated staging requests**. Other work remains in the longer interval;
these are direct attributions, not a subtraction of unmatched total frame times.

| Run / end present | Interval ms | Upload attribution ms | Allocation [vkAllocateMemory] ms | Memcpy ms | ASTC decode / RGBA-init ms | Retirement ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `verified-off-A` / 5175 | 2970.858 | 583.482 | 410.661 [409.504] | 171.360 | 1596.797 / 294.820 | 189.628 |
| `verified-off-B` / 5202 | 3229.476 | 688.623 | 494.505 [493.254] | 192.529 | 1619.248 / 350.830 | 192.771 |
| `verified-cached-A` / 5202 | 2714.156 | 331.079 | 159.977 [158.813] | 169.698 | 1651.175 / 307.741 | 94.953 |
| `verified-cached-B` / 5195 | 2833.471 | 348.272 | 167.182 [165.911] | 179.558 | 1596.983 / 308.352 | 172.615 |
| `verified-pool-A` / 5204 | 2674.291 | 334.259 | 160.514 [159.345] | 172.278 | 1602.910 / 310.548 | 63.877 |
| `verified-pool-B` / 5296 | 3885.998 | 949.009 | 625.716 [623.902] | 321.041 | 1656.472 / 417.969 | 123.532 |

`cached_vs_off` has an observed **34.99%** lower mean combined staging time; both
route and lab upload+retirement observations separate from the controls.
`pool_vs_cached` has an observed **19.09%** lower mean, but neither pair fully
separates: Pool-B has a 949.009 ms lab upload attribution. These two observations
do not establish a consistent incremental pooling improvement. Default promotion
requires the byte gate and both separations; otherwise the feature remains
opt-in. The additional runtime fault gate below is not cleared, so **both
features remain opt-in even if these stage separations pass**. Two observations
per setting are not a confidence interval.
ASTC decoding, guest/dependency waits and zero-texture tails remain separate work.
All selected >50 ms intervals, including the timing-window gaps and route tail with uncovered time, are retained per run.

Sampled route cgroup throttling A/B deltas are 0.000 ms, 0.000 ms, 0.000 ms, 0.000 ms, 0.000 ms, 0.000 ms; peak sampled non-game CPU is 2.071% of the 7.65-CPU quota. These controls do not repair the rendered-phase gate.

### Runtime fault gate and rejected setup runs

Before the retained matrix, `route-cached-A` exits with SIGSEGV at 199.407 s /
present 8410, in host `libstdc++::_Rb_tree_insert_and_rebalance`, accessing address
0x10. It has no native caller backtrace; the cause is unresolved and is not
attributed to staging or another subsystem. Its partial route is excluded from
performance averages and remains part of the correctness record. `route-off-A`
and `route-pool-A` complete, but all three initial runs use an executable-mismatched
030 shader seed and therefore are application-cache-cold, not the intended warm
controls. A further control named `warm-off-A` also rejects that copied key; its
legacy name does not establish cache warmth. These setup runs remain private.

The corrected seed is derived from the actual runtime cache path of the completed
V2 oracle, rather than from filenames merely present in its data directory. Its
current-key files are frozen and their positive runtime load is checked in every
retained run; all six complete with exit 0 and no lost trace events. The
host-fault probe delegates normal fault handling and records a native stack if
tree insertion faults again. Successful warm repeats do not
explain the earlier cold-run failure. No unrelated host-map fix is attempted, and
**no Linux default changes** while that gate remains uncleared.

### Explicit deferrals under the patch-ownership gate

- **Decoded ASTC cache:** `win_astc_cache.h` and `win_astc_store.h` are introduced
  by the later `astral-windows-stutter.patch`. Reintroducing their same paths from
  the earlier Linux overlay fails ordinary `git apply` with “already exists”.
  Reusing them without a second cache implementation requires moving shared
  ownership out of that Windows patch, plus a Linux SHA-256/executable-identity
  backend and its persistence/preparation tests. That shared refactor is forbidden
  in this unit. No cache is copied or Linux cache default promoted.
- **AVX2 writeback and command storage:** the AVX2 body is introduced by the later
  Windows performance overlay; command blobs/pool/options are introduced by the
  later Windows replay overlay. A shared portable implementation requires changing
  ownership/guards in those overlays. This unit stops at that reuse boundary.
  An independent Linux copy was not attempted within the remaining timebox and
  unchanged-Windows constraint; no claim is made that every possible separate
  implementation is impossible. Existing 026 fixture estimates are not new route
  measurements. Both ports and their Linux byte/A/B gates remain deferred.

### Verification and retained evidence

Both exact required unittest commands pass locally (8 and 23 tests, each with
one platform-specific skip) and on the A40 (8 and 23 tests, no skips):

```sh
python3 -m unittest discover -s tests -p 'test_astral_linux.py'
python3 -m unittest discover -s tests -p 'test_linux_runtime_startup.py'
```

Linux tests include allocator failure ownership, cached-type absence/incompatibility, fallback/retry, delayed/out-of-order
retirement, best-fit buffer-size checks, actual-allocation byte caps and count caps.
The pinned complete Linux and Windows series apply cleanly; no series or Windows
patch file changes. Linux-only additions preprocess away on Windows, macOS and
Android. Full `nvn_frames.cpp` preprocessing is byte-identical on the native Apple
SDK before/after; Windows target-body preprocessing is byte-identical with host
headers preloaded. This is a source guard proof, not a native Windows SDK/build
claim. No Windows VM or Mac game was used.

A separate public-series build, without private stage/oracle code, completes in
28.159 s while reusing the same 317 generated archive commands. Its executable
SHA256 is `0da835281d26d6d2d689ed378d2789e3d6b730ca5e7d3f70baf3b1e93f19799b`;
its runtime source hashes match the public-series manifest. With both new
switches omitted, the fixed route exits 0 after 15,318 observed presents.
Title prompt, laboratory and tunnel/bike captures are checked; inherited glyph
and occlusion issues remain. Original external route/fault observers remain
loaded. Its new shader-cache key loads zero bytes, so this is an application-cold
default smoke check, excluded from the six-run stage comparison and FPS claims.

The legacy startup supervisor has a pre-existing import mismatch: it expects
`prepare_runtime.inventory`, whose re-export was removed. Its offline test now
loads that supervisor in an isolated fixture with the historical exception-type
re-export supplied only during import. The existing real subprocess/Git checks
remain exercised. This test setup is not a repair of the standalone legacy tool;
production tooling is outside this unit's scope.

Independent review belongs to the lead and remains pending, not waived. The worker
commits only the four allowed files; no nested review, push, PR, tag, release,
resource/billing operation or owner-build access is performed.

The pod is marked **POD-FREE at 2026-10-21T20:30:40Z**, after all 17 raw run
archives and 131 native metadata files are exported and SHA256-verified locally.
The 20:29:58Z snapshot shows zero games/builds, GPU utilization and GPU memory
use. No cloud resource is stopped or changed.

Private evidence root is `$ACS_ROOT/.local/units/LINUX-PERF-031/`, with pod work at
`/root/acr/units/LINUX-PERF-031/`:

| Evidence | Contents |
| --- | --- |
| `full-route-oracle.json`, `full-route-cached-only-oracle.json`, `full-route-oracle-v1.json`, `synthetic-summary.json`, `synthetic-feature-correct.jsonl` | Complete byte comparisons, per-image readback hashes and synthetic cross-path triples |
| `runs/verified-{off,cached,pool}-{A,B}/` | SHA-verified raw archives, receipts/env, trace, frame/input logs, samples, captures, `staging-analysis.json` and every selected spike |
| `ab-summary.json`, `policy.json`, `crash-investigation.json`, `summarize.py` | Stage totals, incremental stage gates, blocked runtime acceptance and traffic/isolation checks |
| `visual-review.json`, per-run `preview/` | Observed chapters, phase differences and inherited fidelity limits |
| `native-artifacts/build-diag-v1-receipt.json`, `native-artifacts/build-diag-v2-receipt.json`, source archives and `native-artifacts/build-production-receipt.json` | Exact measuring code/binaries and unchanged main/SDK archive identities |
| `shared-port-deferrals.json`, `preprocessor-equivalence.json`, `series-apply.json`, verification logs | Patch-ownership blocker, other-platform guards and scoped checks |
| `production-validation.json`, `runs/production-default/`, `native-artifacts/verify-native-final.json` | Public source/build identity, default route and latest native test logs |
| `RESUME.md`, `metadata-validation.json`, `raw-manifest.json`, `native-artifacts/final-state.json` | Rejected pilots, verified exports, zero-game snapshot and POD-FREE handoff |
