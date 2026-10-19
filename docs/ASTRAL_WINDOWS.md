# Astral Chain on Windows (x64)

`runtime/patches/astral-windows.patch` makes the Linux runtime series build and run on Windows x64 with clang-cl. It
applies after the whole of `runtime/patches/series.linux` and `windows-native.patch` (the clang-cl policy);
`runtime/patches/series.windows` is that list, and `tests/test_astral_windows.py` keeps them in step. macOS is
unchanged (`series.macos` lists neither patch) and so is Linux: every change is in the Windows-only CMake branch,
`platform_win.cpp` (built only on Windows), a `_WIN32` branch, or a condition extended by `|| defined(_WIN32)`.

## What the overlay changes

| file | change |
|---|---|
| `runtime/src/hle_fiber.cpp` | The fiber bridge (`docs/ASTRAL_FIBER_CONTEXT.md`) on Windows x64 uses Win32 fibers instead of an assembly stack switch. Each guest fiber continuation is `CreateFiberEx(64 KiB commit, 8 MiB reserve, FIBER_FLAG_FLOAT_SWITCH)`; the thread itself becomes the root continuation on its first switch (`ConvertThreadToFiberEx`, or `GetCurrentFiber` if it already is a fiber). `SwitchToFiber` saves the MS x64 callee-saved state (rbx rbp rdi rsi r12-r15, xmm6-xmm15, MXCSR, the x87 control word) and keeps the TEB stack base/limit, the SEH chain and fiber-local storage right, so stack probes and exceptions work on fiber stacks. Retired continuations are freed with `DeleteFiber` (never the running fiber or the root). Dispatch, validation and finalisation are unchanged. |
| `runtime/src/kernel.cpp` | `fiber_retire_thread()` is the real one on Windows too (a thread that exits on a fiber switches back to its root first). |
| `CMakeLists.txt` | The Windows branch builds `hle_fiber.cpp` (without it, `nn::os::SwitchToFiber` runs the lifted dispatcher, as on Linux before its overlay). With `-DNX_HWOPUS=ON`, Windows takes libopus from its own CMake package (`find_package(Opus CONFIG)`, target `Opus::opus`) instead of pkg-config. |
| `runtime/src/nvn/nvn_caps.cpp` | The upload ring defaults to host-cached memory on Windows as on Linux (discrete GPUs; `NX_RING_CACHED=0` restores the plain type). |
| `runtime/src/platform_win.cpp` | `sleep_ns` waits on a high-resolution waitable timer (`CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`). `std::this_thread::sleep_for` rounds up to the 15.6 ms system tick, which would stretch the 60 Hz vsync thread (`hle_vi.cpp`) to about 31 ms. |

The headless path without a window surface, the host-cached ring and texel-write coalescing come from the Linux overlay
and `astral-texel-coalesce.patch` and apply unchanged.

## Dependencies (tested: Windows Server 2025, x64, NVIDIA L4)

- Visual Studio 2022 Build Tools with the C++ workload and its clang-cl (19.1), CMake and Ninja; the Windows SDK.
- A Vulkan 1.3+ driver (`vulkan-1.dll` comes with it) and the Vulkan headers at the `tools/acr_build.py` pin.
- libopus 1.3+ built with CMake: `cmake -S opus -B opus-build -G Ninja -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_C_COMPILER=clang-cl -DOPUS_BUILD_SHARED_LIBRARY=OFF -DOPUS_DISABLE_INTRINSICS=ON` and `cmake --install`
  (clang-cl does not compile opus 1.5's SSE4.1 sources without per-file target flags, hence no intrinsics).

`tools/acr_build.py` is macOS-only; copy its platform-independent output (`<out>/work/gen`, the data root with
`analysis`, `exefs`, `extract`, `spirv`, `astral.profile`, `shared-fonts`) to the Windows machine. Keep it private.

## Build

From a "x64 Native Tools" prompt (`VsDevCmd.bat -arch=x64`), with the source prepared as on Linux but from
`series.windows`:

```bat
cmake -S runtime-src -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang-cl ^
  -DCMAKE_CXX_COMPILER=clang-cl -DNX_GAME=astral -DNX_GEN_DIR=<gen> -DNX_HWOPUS=ON ^
  -DOpus_DIR=<opus prefix>/lib/cmake/Opus -DNX_VULKAN_SDK=<dir with include/vulkan>
cmake --build build --target astral
```

406 steps, about 5 minutes on the test machine. Warnings only.

## Run

```bat
set NX_DATA_ROOT=<data root>
set NX_NVN_REAL=1
set NX_NVN_FORMAT_PROFILE=<data root>/astral.profile
set NX_SHARED_FONT_DIR=<data root>/shared-fonts
build\astral.exe
```

Headless: add `NX_HEADLESS=1` (a hidden window, no swapchain) and `NX_DUMP_FRAMES=<n>` to write every n-th frame to
`<data root>/frames/NNNNN.ppm`. Writing a frame takes about 0.6 s there, so a dumping run shows a lower frame rate.

## Status (2026-10-19, Windows Server 2025 cloud machine, NVIDIA L4, headless)

- Boots through `nn::init`, the NVN device, RomFS, hwopus and the fiber switch, with no fatal.
- Renders the boot sequence, the title screen (the title movie with the ZL+ZR prompt) and, after a scripted ZL+ZR
  press, the save check, the loading screen and the **opening cutscene** (characters, subtitles, effects). Frames were
  compared by eye with the macOS build. 110 s runs ended by the time limit, not a crash.
- **30 fps** (the game's cap) on the title screen without frame dumping: replay ~7 ms, fence wait ~5 ms, other ~5 ms
  per frame, about 34 MB of uploads a frame. Working set steady at about 1.0-1.1 GB.
- The whole RomFS is needed past the title: with `pl/` not yet copied, the game crashed on a null player object right
  after ZL+ZR (a guest null dereference, not a runtime fault); with it present the opening plays.
- Not yet done: a windowed run with a swapchain on a desktop session; audio (headless runs are muted); real gamepad
  input (XInput is wired but only `NX_INPUT_SCRIPT` was exercised); an `acr_build.py` Windows mode.
