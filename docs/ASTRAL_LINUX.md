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


Linux also needs `astral-texel-coalesce.patch`, which is in `series.macos` and so in `series.linux` too
(`docs/ASTRAL_TEXEL_COALESCE.md`). Without it the queue of pending texel writes for the title movie grew by about
1 GB every 30 s, and the memory guard stopped the game on the title menu after about 3.5 minutes.

## Dependencies (tested: Ubuntu 22.04, x86-64, NVIDIA A40, driver with Vulkan 1.4)

- clang 14 or newer (`clang`/`clang++`; the runtime compiles with `-march=x86-64-v3`, so an AVX2 CPU), CMake 3.24+,
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
