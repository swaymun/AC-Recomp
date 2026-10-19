# Astral performance HUD

`runtime/patches/astral-perf-hud.patch` adds an optional on-screen performance HUD to Astral (strict) builds. Where
the platform has its own overlay, that overlay is used instead:

| platform | `NX_PERF_HUD=1` / launcher "Performance HUD: On" shows | F3 in game |
|---|---|---|
| macOS | Apple's Metal Performance HUD (a launcher change restarts the game so it applies at once) | cannot switch it (see below); the HUD's own menu can |
| Linux | MangoHud, when its Vulkan layer is installed; otherwise the built-in HUD | toggles it (MangoHud's `toggle_hud=F3`) |
| Windows | the built-in HUD (Windows has no OS overlay for Vulkan) | toggles it |
| iOS / iPadOS | not an Astral target yet; see "iOS hook" | - |

`NX_PERF_HUD=ac` (any case) always uses the built-in HUD, on every platform. The built-in HUD draws in the top-right
corner of the presented image, the way emulators do, and is the only one that appears in dumped frames.

## Overlay order

Apply it after the whole native stack:

1. `NATIVE_ORDER` (`tests/test_nvn_window_depth.py`)
2. `astral-nvn-window-depth.patch`, `astral-nvn-bc-zero-fill.patch`, `astral-nvn-cube-storage.patch`
3. `astral-shared-font.patch`, `astral-swkbd.patch`
4. **`astral-perf-hud.patch`**
5. `astral-audio-dump.patch` (`docs/ASTRAL_AUDIO_DUMP.md`)

The `CMakeLists.txt` hunk uses `astral-swkbd.patch`'s lines as context, so this patch must come after it. The other
files do not depend on those two patches. `windows-native.patch` still applies after this overlay.

## Use

| control | effect |
|---|---|
| `NX_PERF_HUD=1` | The HUD is on from the start: the native overlay where there is one. Unset or `0`: off. |
| `NX_PERF_HUD=ac` | The built-in HUD, on from the start, on every platform. |
| F3 (macOS, Linux: SDL key; Windows: `WM_KEYDOWN`) | Turns the HUD in use on or off at runtime (not Apple's). Auto-repeat is ignored. |

With `NX_HEADLESS=1 NX_DUMP_FRAMES=<n>` (or the `dump_frames` file), the built-in HUD is drawn into every dumped
`.ppm` while it is on. Headless runs and capture runs never hand over to a native overlay: `NX_DUMP_FRAMES`,
`NX_INPUT_SCRIPT` or `NX_AUDIO_DUMP` set (not empty or `0`), or a `dump_frames` file in the data folder at start
(`hud::capture_run`). Native overlays are drawn when the frame is presented, after the read-back, so they are never
in dumped frames. A `dump_frames` file created later in a windowed run with a native overlay gets frames without HUD.

## Native overlays

### macOS: Apple's Metal Performance HUD

Metal loads its HUD library (`libMTLHud.dylib`) only when `MTL_HUD_ENABLED=1` is in the environment before the
process creates its first Metal device. The launcher's own window renders with Metal, so the decision is made at the
very start of `main`, before `SDL_Init` (`metal_hud::preload` in `platform_mac.cpp`):

- `NX_HEADLESS` or a capture run (above): nothing (dumps keep the built-in HUD).
- `MTL_HUD_ENABLED` already set by the player: used as given.
- Otherwise the HUD is wanted when `NX_PERF_HUD` is on (not `0`, not `ac`) or, without `NX_PERF_HUD`, when the
  launcher's `settings.ini` has `perf_hud = 1` (`hud::native_wanted_at_start`). Then `MTL_HUD_ENABLED=1` is set.

When the game window is made, Apple's HUD takes over the HUD's on/off state (`hud::use_native`); the built-in HUD is
then off and does no work. Once loaded, Apple's HUD is on every Metal layer of the process (the launcher window too)
and stays on. Checked on macOS 26 with a running game (`MTL_HUD_ALLOW_CAPTURE_HUD=1` lets `screencapture` see it):
the HUD showed GPU name, resolution, memory, game mode, FPS, GPU time and a frame-interval graph; setting
`CAMetalLayer.developerHUDProperties` to nil and posting the HUD's `com.apple.metal.hud.notify.ToggleEnabled`
notification both left it on. So F3 only logs a hint. To hide it during a run, use the HUD's own menu in the menu bar
(Metal HUD > Enable HUD); to drop it, turn the setting off and start again.

Settings changed in the launcher: when the player presses PLAY with a Performance HUD setting that differs from what
Metal loaded at start, the process restarts itself before any other thread exists (`metal_hud::after_launcher`,
`astral-launcher.patch`; the decision is `launcher::metal_hud_restart`). It `execv`s the same executable with the same
arguments and environment (so every `NX_*` setting the launcher exported carries over), plus `NX_SKIP_LAUNCHER=1`
(straight into the game), `NX_METAL_HUD_RESTARTED=1` (it never restarts twice) and `MTL_HUD_ENABLED=1` when the HUD
was turned on, or without `MTL_HUD_ENABLED` and with `NX_PERF_HUD=0` when it was turned off. The restarted process
appends to the same `nx.log` (no `.prev` rotation). A player-set `MTL_HUD_ENABLED` is never overridden.
So Apple's HUD shows exactly when the setting is on. The built-in HUD is never shown on macOS except with
`NX_PERF_HUD=ac`, headless runs and capture runs: Apple's HUD takes the HUD's state and F3 in every other windowed
run, loaded or not, and if the restart fails the HUD stays off for that run (logged) and shows from the next start.

### Linux: MangoHud

MangoHud is a Vulkan implicit layer, enabled by `MANGOHUD=1` when the loader creates the instance. In `main`, right
after the launcher exported the settings and before any other thread starts (`astral-launcher.patch`),
`hud::prepare_native_overlay` (Linux desktop, not headless, not a capture run) checks that the HUD is on, not `ac`,
`MANGOHUD` is not `0`, and a `MangoHud*.json` manifest is in one of the loader's implicit-layer
directories (`$XDG_CONFIG_HOME` or `~/.config`, `$XDG_CONFIG_DIRS` or `/etc/xdg`, `/etc`, `$XDG_DATA_HOME` or
`~/.local/share`, `$XDG_DATA_DIRS` or `/usr/local/share:/usr/share`, each with `/vulkan/implicit_layer.d`). Then it
sets `MANGOHUD=1` and, if the player set neither `MANGOHUD_CONFIG` nor `MANGOHUD_CONFIGFILE`,
`MANGOHUD_CONFIG=read_cfg,toggle_hud=F3,position=top-right,fps,frametime,frame_timing,cpu_stats,gpu_stats,gpu_name,ram,vram,resolution`.
`read_cfg` keeps the player's `MangoHud.conf`; only these keys override it.
MangoHud reads F3 itself; the runtime's F3 only keeps the state in step. HUD off at start: no layer is loaded and F3
toggles the built-in HUD.

Install: `sudo apt install mangohud` (Debian/Ubuntu), `sudo dnf install mangohud` (Fedora), `sudo pacman -S
mangohud` (Arch), or the Flatpak/Steam builds' own packaging. MangoHud's keyboard shortcuts need X11 or XWayland
focus.

### Windows

There is no OS overlay for Vulkan, so the built-in HUD is used. Vendor overlays work alongside it: NVIDIA App
(Alt+R), AMD Software (Ctrl+Shift+O), the Steam overlay's performance monitor, or RivaTuner Statistics Server.

### iOS hook

iOS cannot be an Astral target yet, and `platform_ios.mm` is not changed here. When it is: before the first Metal
device, call `setenv("MTL_HUD_ENABLED", "1", 1)` when `nx::hud::native_wanted_at_start(...)` says so, then after the
`CAMetalLayer` exists call `nx::hud::use_native(show, "Apple Metal HUD")` with a `show` that returns `on` (as
`metal_hud::show` on macOS). On a device, Settings > Developer > Graphics HUD also shows it.

## The built-in HUD

Lines, refreshed once per second (the first second shows `FPS 0.0`):

```
FPS 30.0
Frame 33.4 ms avg, 41.0 max
Speed 100% of 30 fps
CPU 245% (10 cores)
RAM 1234 MB
Thermal nominal
GPU Apple M3 Pro
1920x1080, game 1280x720
```

- **FPS:** presents over the last 1 s window.
- **Frame:** the average and the largest interval between presents in that window.
- **Speed:** FPS x the NVN window's present interval / 60. The present interval is read at `nvnQueuePresentTexture`
  (interval 2 = the game's 30 fps target). 100% means the game runs at full speed for the mode it asked for.
- **CPU:** process CPU time (user + system) over wall time. 100% equals one fully busy core, as in `top`.
- **RAM:** resident memory. macOS/iOS: `MACH_TASK_BASIC_INFO.resident_size`. Linux: `/proc/self/statm`. Windows:
  working set (`GetProcessMemoryInfo`, already linked through `psapi`).
- **Thermal:**
  - macOS/iOS: the system thermal pressure from `notify(3)` (`kOSThermalNotificationPressureLevelName`), the same
    state that `NSProcessInfo.thermalState` follows, without Objective-C. Values: nominal, moderate, heavy,
    trapping or sleeping; iOS can also report light.
  - Linux (and Android): the hottest `/sys/class/thermal/thermal_zone*/temp`.
  - Windows: `n/a`.
- **GPU:** `VkPhysicalDeviceProperties.deviceName` of the device in use, cut at 40 characters.
- **Last line:** the swapchain size and the game's presented texture size. Headless runs show `headless`.

## How it works

- `runtime/src/perf_hud.cpp` / `perf_hud.h` hold everything that is not Vulkan:
  - the 1 s statistics window;
  - the host probes;
  - the text;
  - the hand-over to a native overlay (`use_native`, `native_wanted_at_start`, MangoHud's `start_mangohud`);
  - the CPU rasteriser. White 8x8 glyphs on an opaque dark background (`#101018`), each font pixel scaled
    `scale x scale`. `scale = max(1, (height + 270) / 540)`: 1 at 720p, 2 at 1080p, 3 at 1440p, 4 at 2160p.
  The bitmap is cached and re-rasterised only when the text, scale or channel order changes, so at most once per
  second.
- `runtime/src/font8x8_basic.h` is Daniel Hepper's public domain `font8x8_basic` (U+0020..U+007E). Any other byte is
  drawn as `?`. See `runtime/patches/astral-perf-hud.NOTICE` and `THIRD_PARTY_NOTICES.md`.
- **On screen** (`runtime/src/nvn/nvn_hud.cpp`, called from `gpu_present` in `nvn_vk.cpp`): after the game's image
  is drawn by the present pass or blitted into the swapchain image (which is then in `PRESENT_SRC`), the bitmap is
  copied into that frame's upload memory (`upload_alloc`). That memory lives until the submit retires in both the
  synchronous and the asynchronous/pipelined modes, so no extra buffer lifetime is needed. Then:
  1. barrier `PRESENT_SRC` -> `TRANSFER_DST`;
  2. `vkCmdCopyBufferToImage` to `(width - bitmap - 4*scale, 4*scale)`;
  3. barrier back to `PRESENT_SRC`.

  All of this happens before the present's submit. The swapchain is already created with `TRANSFER_DST`. The copy
  supports only 4-byte BGRA/RGBA UNORM/SRGB swapchains, which is what `make_swapchain` picks. Other formats, or an
  image smaller than the HUD, are skipped.
- **Dumped frames** (`frame_dump_write` in `nvn_debug.cpp`): the bitmap is copied into the read-back pixels before the
  `.ppm` is written, scaled for the dumped image's height. `present_headless` counts presents for the statistics.
- `frame_stats.cpp` already logs present-interval histograms every 600 presents, and Android thermal headroom. Its
  state is file-local and covers longer periods, so the HUD keeps its own 1 s window.

**Off:**
- With a native overlay in use, the built-in HUD is off too and does nothing. On macOS with the HUD off at start,
  `MTL_HUD_ENABLED` is not set and Metal loads nothing; on Linux, `MANGOHUD` is not set.
- With `NX_PERF_HUD` unset, every hook returns at once. No statistics are taken, no commands are recorded and dumps
  are unchanged.
- In the default (non-Astral) profile, every change is under `#if defined(NX_ASTRAL_STRICT)`. The changed TUs
  preprocess identically, `perf_hud.cpp` and `nvn_hud.cpp` preprocess to nothing, and CMake lists them only for
  `NX_GAME=astral`.

## Tests

`tests/test_astral_perf_hud.py` applies the overlay at its place in the order on a fresh pinned runtime and checks:

| area | what is checked |
|---|---|
| Rasteriser | Glyph 'A' pixel-exact at scales 1 and 2 against the font README's documented bitmap. Also the border, BGRA order, line spacing, empty lines and the `?` fallback. |
| Placement | The scale rule, top-right placement with its margin, untouched surroundings, and skipping images that are too small. |
| Text and window | Every line. The 1 s window on a fake clock: FPS, average/max frame time, game speed from the present interval, the headless line and the bitmap cache. |
| Host probes | Live on macOS: CPU time, resident memory and a valid thermal name. |
| Dumps | Compositing into a synthetic 1920x1080 frame. |
| Swapchain copy | Recorded through fake `vkCmdPipelineBarrier` / `vkCmdCopyBufferToImage`: layouts, offset, extent and uploaded bytes. Unsupported formats and small images are skipped. |
| F3 toggle | Off records nothing, composites nothing and measures nothing. |
| Native overlays | The start decision from `NX_PERF_HUD` / `settings.ini` text, `NX_PERF_HUD=ac`, a failed hand-over keeping the built-in HUD, capture runs (`NX_DUMP_FRAMES`, `NX_INPUT_SCRIPT`, `NX_AUDIO_DUMP`, a `dump_frames` file) and headless runs skipping MangoHud, MangoHud manifest detection in temporary directories, the loader's directory list from `XDG_*`, `MANGOHUD=0`, the `MANGOHUD` / `MANGOHUD_CONFIG` (`read_cfg` first) it sets, F3 routed to the overlay, the built-in HUD idle (no commands, dump pixels or statistics) and a single owner. |
| Hook order | Where the hooks sit in `gpu_present`, `present_headless`, `frame_dump_write`, none in `nvn_vk.cpp`'s instance creation (Linux: `test_astral_launcher` checks the call after `launcher::start`); macOS: `metal_hud::preload` before `SDL_Init`, the hand-over after the game window's layer exists. |
| Build | Strict Mac-profile syntax of `perf_hud.cpp`, `nvn_hud.cpp`, `nvn_vk.cpp`, `nvn_debug.cpp`, `nvn_queue.cpp` and `platform_mac.cpp` (with SDL3 headers), plus `-Werror` on the new TUs. Identical default preprocessing, and that `windows-native.patch` still applies. |

## Limits

- **Built-in HUD: no game-run evidence.** Not yet seen on a real swapchain or MoltenVK. The copy is ordinary
  transfer work on a `TRANSFER_DST` swapchain image.
- **Apple's HUD:** seen once on this Mac (macOS 26, M5 Pro) in a 10 s windowed run of the game with
  `NX_PERF_HUD=1 NX_SKIP_LAUNCHER=1`; not seen with the launcher open. Not switchable at runtime (above). Neither
  run checked macOS 13-15.
- **MangoHud:** not run. The manifest search, the capture-run rule and the environment are tested on this Mac;
  the Linux branch of `prepare_native_overlay` (`plat::headless`, `plat::data_root`) was not compiled here. MangoHud's F3 needs
  X11/XWayland keyboard access.
- **Not compiled here:**
  - `platform_linux.cpp` and `platform_win.cpp` cannot be compiled on this Mac. The test checks that each block
    added there is a self-contained `#if defined(NX_ASTRAL_STRICT)` block.
  - The Linux and Windows branches of `perf_hud.cpp` (`/proc`, `/sys`, `GetProcessTimes`,
    `GetProcessMemoryInfo`) were not compiled here.
  - iOS cannot be an Astral target (CMake refuses it), so nothing changes there. The Apple branch of the probes is
    the same on iOS.
- **Thermal:** Windows shows `n/a`. Linux shows a zone temperature, not a throttling state.
- **Rotated swapchains:** with Android's pre-rotated swapchains the copy uses host-image coordinates, so on a rotated
  display the HUD would not sit at the top right. Astral does not target Android.
- **Cost:** the HUD's bitmap goes through the upload ring every frame while it is on, about 350 KB at 2x and 1.4 MB
  at 4x.
