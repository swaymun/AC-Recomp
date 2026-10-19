# Astral in the iOS simulator (iPhone and iPad)

This brings the iOS simulator target to parity with the current macOS patch stack
(NVN fixes, shared fonts, swkbd, perf HUD, audio dump, launcher on desktop only)
and runs the game on an iPhone and an iPad simulator. Simulator only: no physical
device, IPA or App Store claim.

## Patch stack

On the Wonder pin `010ed7a5`, apply with `git apply`:

1. `runtime/patches/series.macos` in order; it now ends with `astral-launcher.patch`
   (desktop only; its CMake block excludes iOS) and `astral-touch.patch` (HID touch
   screen, desktop mouse-as-touch; `docs/ASTRAL_TOUCH.md`)
2. `ios-runtime.patch`, `ios-nvn-compile.patch`, `ios-vulkan.patch` (unchanged, reviewed earlier units)
3. `ios-astral-parity.patch` (this unit; named `ios-*` because it is part of the iOS
   stack, not the macOS series)

All of them apply cleanly with `git apply` on the pin (checked against the pinned
reference checkout).

The UIKit host is `ports/ios` (`App.mm`, `InputBridge.*`, `Info.plist`), passed as
`NX_IOS_HOST_DIR`.

`ios-astral-parity.patch`:

- **CMake (iOS branch)**: links `hle_fiber.cpp` + `fiber_context_mac.S` (the Astral
  fiber HLE the macOS target has; without it the guest's fiber imports are
  unresolved), AudioToolbox, and `nvn_spirv_subgroup.cpp`. Generated code is built
  at `NX_IOS_GAME_OPT` (default `-O2`, as macOS) instead of the old first-boundary
  `-O0`. `NX_IOS_PREBUILT_GAME_DIR` optionally links prebuilt `libgame_main.a` /
  `libgame_sdk.a`; `NX_OPUS_LIBRARY`/`NX_OPUS_INCLUDE` give hwopus a static libopus
  (pkg-config would find the macOS dylib). The Vulkan-header pin now names the
  runtime's own registry headers (`vulkan_core.h` SHA-256 `a7ac0d7e...edc6`, the
  RUNTIME-BOOTSTRAP-001 headers `vk_gen.cpp` was generated from and macOS uses)
  instead of MoltenVK 1.3.0's; MoltenVK is reached only through
  `vkGetInstanceProcAddr`. The pinned MoltenVK 1.3.0 simulator library check stays.
- **`platform_ios.mm`**: `NX_DATA_ROOT` override (the simulator reads host paths, so
  the 9.6 GB extract is used in place, never copied); `NX_HEADLESS`; real audio
  through one AudioQueue (s16 stereo 48 kHz, same queue contract as the SDL path;
  `NX_MUTE=1` falls back to silent self-pacing); D-pad and stick-click mapping;
  `input_script` (NX_INPUT_SCRIPT) for unattended runs; `read_touches`; and the
  macOS crash handler (signal, host pc, guest registers, backtrace to the log).
- **`perf_hud.cpp`**: the iOS SDK lacks `libkern/OSThermalNotification.h`; thermal
  reads "n/a" there. `NX_PERF_HUD=1` works on iOS (composited into the swapchain).
- **Subgroups at size 1 (`nvn_spirv_subgroup.cpp`, iOS simulator build only: compiled
  into the iOS target and hooked under `NX_ASTRAL_STRICT && NX_IOS_RUNTIME`)**: the simulator GPU has no
  SIMD-group functions. MoltenVK reports subgroup sizes 1..1 and its emulation
  compiles only `Elect`, so translated compute shaders using ballot/shuffle (e.g.
  `8cf5c6044fd81792`, 32x9 groups over the 1600x900 target) failed to build, their
  dispatches were skipped, and later passes timed the GPU out
  (`MTLCommandBufferErrorDomain` 1/2, `VK_ERROR_DEVICE_LOST`) right after ZL+ZR on
  the title screen. When the device's maximum subgroup size is 1, GroupNonUniform
  operations are rewritten to their exact one-invocation meaning (Ballot ->
  (pred,0,0,0), Elect/AllEqual -> true, All/Any -> pred, Broadcast/Shuffle* -> own
  value, SubgroupLocalInvocationId -> 0, Lt/Gt masks -> 0, Eq/Ge/Le -> (1,0,0,0) as
  Private variables). Modules with other subgroup operations are left alone. Only
  devices reporting size 1 are affected (not macOS/Windows/Linux/Android GPUs).
  Cross-lane shuffles from other lanes read the caller's own value, which is what a
  size-1 device returns; reductions built from such shuffles therefore compute
  per-invocation values and may differ from Maxwell results.
- **Bounded GPU waits (Astral strict, every host)**: every fence wait and image
  acquire on the runtime's NVN path goes through `gpu_wait_fences` /
  `gpu_fence_timeout_ns()`: the submit waits (`nvn_vk.cpp`, `nvn_frames.cpp`), the
  frame/texture debug readbacks (`nvn_debug.cpp`, previously `UINT64_MAX`) and
  `vkAcquireNextImageKHR` (previously `UINT64_MAX`; a timeout or `VK_NOT_READY`
  now ends in `gpu_hung`). The limit is 2 s; `NX_GPU_TIMEOUT_S` may change it but
  is clamped to at most 5 s, with a log line when clamped (see "Host freeze
  incident" below). `tests/test_astral_default_profile.py` scans the fully patched
  tree (Astral profile) for `UINT64_MAX` in any wait/acquire call; only the
  guest-Vulkan pass-throughs (`vk_swapchain.cpp`, `vk_gen.cpp`, `vk_bridge.cpp`, used
  by Vulkan games such as Hades, never by Astral's NVN path) are allowlisted.
- **Default profile unchanged**: every shared-file change is inside
  `NX_ASTRAL_STRICT` conditionals; resolving it as undefined gives the original
  bytes (`tests/test_astral_default_profile.py`).

Not done here: `MVK_CONFIG_FULL_IMAGE_VIEW_SWIZZLE=1` (MoltenVK asks for it for RGB1
views) broke fragment shader compilation in MoltenVK 1.3.0 (`undeclared identifier
fp_t_tcb_8Smplr`) and hung the GPU, so it stays off; those views render without
the forced-one alpha.

## Touch controller overlay (`ports/ios/App.mm`)

Semi-transparent Switch-style controls drawn by UIKit over the CAMetalLayer: two
sticks (left high, right low, as the Joy-Con), D-pad, A/B/X/Y diamond, L/ZL and
R/ZR, -/+, LS/RS stick clicks and a HIDE/PAD toggle at the top centre. Layout is
relative to the safe area with a unit capped at 42 points so iPad thumbs stay
phone-sized; pressed controls brighten. `NX_IOS_OVERLAY=0` starts hidden. Touches
that start on no control, and every touch while hidden (except the toggle), become
touch-screen contacts (`acs_touch_*` -> `plat::read_touches` -> `TouchScreenState`).
The input bridge ABI stays v1 with additive controls (D-pad, stick clicks) and the
touch-point calls, so the original `ios-runtime.patch` mapping keeps working. The
old host captions are gone in runtime mode; nothing covers the game except the
controls.

## Host freeze incident (2026-10-19) and the rules it set

The owner's Mac hard-froze and restarted twice, at 13:29 and 13:52 EDT, while this
unit ran the game in the simulator with a raised GPU timeout:

- 13:29: one iPad Pro 13-inch (M5) simulator, the then-default 20 s simulator
  timeout, loading the save into the 3D scene; the guest log ends with
  `GPU hang (a submit did not finish in the GPU timeout)` at 54 s.
- 13:52: an iPhone 17 Pro and an iPad simulator at the same time, both with
  `NX_GPU_TIMEOUT_S=120`, on the same scene load.

The simulator GPU is not isolated: its Metal work runs on the host GPU. A submit
that does not finish (a runaway shader in the scene load, possibly from the
size-1 subgroup rewrite, or very large uploads: one load logged a 450 MB submit)
occupies the host GPU; the runtime's 2 s watchdog exists because waiting on a
stuck GPU had already frozen WindowServer and restarted a Mac (`nvn_vk.cpp`).
Raising it removed that protection. Earlier runs that also lost the Metal device
(`MTLCommandBufferErrorDomain` 1 and 2) but kept the 2 s watchdog did not freeze
the host. Rules now enforced:

- The GPU fence timeout is 2 s; `NX_GPU_TIMEOUT_S` is clamped to 5 s by the runtime
  and anything above 5 s is refused by `tools/ios_sim_run.py`.
- One game simulator at a time: `tools/ios_sim_run.py` refuses to start when any
  other simulator is booted or another game instance (`astral.app/astral`) runs.
- `tools/ios_sim_run.py` also refuses `NX_PIPELINED`/`NX_ASYNC_GPU` above 2 and the
  `NX_DUMP_TEXTURES`/`NX_DUMP_ON_TARGET`/`NX_DUMP_ON_FS` debug readbacks, drops
  inherited `SIMCTL_CHILD_*` variables so only the run's own `--env` reaches the
  app, and shuts down a `--udid` device whose boot failed or timed out.
- Do not run game simulators unattended while the owner uses the Mac until the
  scene-load hang is understood.

## Building

Private, ignored paths only. Example (see `.local/ios-parity/scripts/configure.sh`
in the worker's tree):

```sh
cmake -S <patched tree> -B <build> -G Ninja -DCMAKE_SYSTEM_NAME=iOS \
  -DCMAKE_OSX_SYSROOT=iphonesimulator -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=26.0 -DCMAKE_BUILD_TYPE=Release -DNX_GAME=astral \
  -DNX_GEN_DIR=<CPU-REGEN-020 gen> -DNX_VULKAN_INCLUDE=<runtime vulkan headers> \
  -DNX_IOS_HOST_DIR=<repo>/ports/ios \
  -DNX_IOS_MOLTENVK_LIBRARY=<MoltenVK 1.3.0 static xcframework>/ios-arm64_x86_64-simulator/libMoltenVK.a \
  -DNX_HWOPUS=ON -DNX_OPUS_LIBRARY=<arm64 simulator libopus.a> -DNX_OPUS_INCLUDE=<opus headers>
ninja -C <build>
```

The measured build used `NX_IOS_PREBUILT_GAME_DIR` with the macOS build's
`libgame_main.a`/`libgame_sdk.a` (and Homebrew's arm64 `libopus.a`) whose objects'
`LC_BUILD_VERSION` platform was rewritten MACOS -> IOSSIMULATOR (a private build
aid; the generated code calls nothing platform-specific and both are arm64
Darwin). That saved recompiling 315 generated translation units; a full native
`-O2` compile of the generated code is the clean alternative and needs no aid.

## Running: `tools/ios_sim_run.py`

```sh
tools/ios_sim_run.py --app <build>/astral.app --device-type "iPhone 17 Pro" --runtime 26.5 \
  --seconds 300 --screenshot-every 15 --data-root <private data root> \
  --env NX_NVN_REAL=1 --env NX_NVN_FORMAT_PROFILE=<private astral.profile> \
  --env NX_SHARED_FONT_DIR=<fonts> --env NX_PERF_HUD=1 --env NX_DUMP_FRAMES=600 \
  --env 'NX_INPUT_SCRIPT=20:ZL:0.5;20:ZR:0.5;35:A:0.2' --out <evidence dir>
```

It creates a fresh simulator of the device type (or uses `--udid`, which must be
Shutdown and is never deleted), boots it, installs a staged copy of the app
(CFBundleExecutable/identifier fixed in Info.plist, ad-hoc signed), launches with
`SIMCTL_CHILD_*` environment and `--stdout/--stderr` files, screenshots every N
seconds, and stops early at the first `FATAL`/`CRASH` in the guest log or when the
process exits. It then terminates the app, copies `guest.log`, `startup.jsonl`,
the input journals and dumped frames (moved out of `<data root>/frames`) into
`--out`, shuts the simulator down and deletes it if it created it. This also
happens on errors and SIGINT/SIGTERM. Every simctl call has a deadline and is
journaled in `simctl.jsonl`; `summary.json` has the status, runtime, UDID, PID,
elapsed time, screenshots, fatal line, log tail and last logged fps.

The data root is a private directory of symlinks (`analysis`, `exefs`, `extract`,
`spirv`, `shared-fonts`) plus its own writable `user/` (saves) and pipeline cache,
so the shared `t3-data` tree is never written.

`tests/test_ios_sim_run.py` drives the tool against a mock `xcrun simctl`,
`codesign` and `ps`: completed run, early FATAL stop, exited process, boot failure,
existing-device rules (including a failed boot), bad arguments, another booted
simulator or running game instance, NX_GPU_TIMEOUT_S above 5 s, GPU-heavy settings
and inherited SIMCTL_CHILD_* variables; cleanup always runs.
`tests/test_gpu_timeout_clamp.py` compiles the runtime's clamp from the patch.

## Measured results (2026-10-19, SDK 27.1, runtime iOS 26.5 build 23F77)

See the worker report for the evidence paths and numbers; summary:

| Device type | Result |
| --- | --- |
| iPhone 17 Pro (2622x1206) | Boots, renders the opening/title, 30 fps on the title, ZL+ZR accepted, Load menu and save dialogs at 15-22 fps; 300 s with no FATAL. |
| iPad Pro 13-inch (M5) (2752x2064) | Boots, title and Load menu render (12-15 fps); the app runs in portrait (iPadOS 26 ignores the landscape-only lock) with the picture letterboxed and the controls laid out below it. Loading the save into the 3D scene hangs the GPU (see the incident above). |

Both: touch overlay visible over the game, perf HUD visible, audio through
AudioQueue, `hid: touch screen polled` in the log, subgroup rewrite active.

Open issues:

- Loading the save into the 3D scene hangs the simulator GPU (both device types);
  neither reached the opening cutscene or gameplay. Investigate off the simulator
  first (compare rewritten shaders with the macOS build, log the shader of the
  stuck submit) before any further simulator run.
- Resident memory on the iPhone climbed to about 6.4 GB (perf HUD "RAM") after
  300 s idling on the Load menu, while the memory guard logged 1.4-1.5 GB earlier
  in the load; a possible leak in the iOS path (AudioQueue buffers, CAMetalLayer /
  MoltenVK drawables, upload buffers or the per-touch input journal) to investigate.
- Simulator GPU throughput limits menus to 12-22 fps.
- `simctl` cannot inject touches, so the overlay/touch path is exercised by unit
  tests and by hand in Simulator.app, not by the unattended runner.
