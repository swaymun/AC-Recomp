# Astral launcher and input remapping

`runtime/patches/astral-launcher.patch` adds a launcher (start screen) to Astral (strict) builds on the SDL3 desktop
hosts, macOS and Linux. It works like the start screens of other PC recompilations such as LASRecomp: a menu comes up
before the game boots, with a controls remapping screen and a few settings.

The look:

- full-window background art, darkened towards the left
- a large warm-gradient title, "AC Recomp", at the top left, with the subtitle "Astral Chain · unofficial native recompilation"
- PLAY / CONTROLS / SETTINGS / QUIT left-aligned below it, with a soft highlight band on the selected item
- at the bottom left: a green check and "Game files ready." (or a red cross and "Game files missing", with what is
  needed), then "Nintendo Switch · v1.0.0" and the controller name
- a "Preview" tag at the bottom right
- the CONTROLS and SETTINGS screens in the same style over the dimmed art

All layout, drawing and input code is original. Text uses Baloo 2 Bold (SIL OFL) through stb_truetype, and the art
is an original AI-generated picture (no game assets, characters or logos) decoded with stb_image. Provenance is in
`runtime/patches/astral-launcher.NOTICE`.

## Overlay order

Apply it last, after the whole native stack:

1. `NATIVE_ORDER` (`tests/test_nvn_window_depth.py`)
2. `astral-nvn-window-depth.patch`, `astral-nvn-bc-zero-fill.patch`, `astral-nvn-cube-storage.patch`
3. `astral-shared-font.patch`, `astral-swkbd.patch`
4. `astral-perf-hud.patch`, `astral-audio-dump.patch`
5. **`astral-launcher.patch`**

The `CMakeLists.txt` hunk and the `#include "perf_hud.h"` context lines come from `astral-perf-hud.patch`, so this
patch must come after it. `windows-native.patch` still applies after this overlay. The save picker is a separate
overlay, `astral-save-profiles.patch`, listed in `series.macos` after `astral-upscale.patch`
(`tests/test_astral_save_profiles.py`). The CONTROLS screen's panel layout and drawn controller are another,
`astral-controls-ui.patch`, listed last (`tests/test_astral_controls_ui.py`).

New files:

- `runtime/src/input_map.{h,cpp}`: bindings, `controls.ini`, `settings.ini`.
- `runtime/src/launcher.{h,cpp}`: menu state machine, drawing, assets, window.
- `runtime/src/third_party/stb_truetype.h` (v1.26) and `stb_image.h` (v2.30), unmodified. They are public domain
  (or MIT).

Changed files: `platform_mac.cpp`, `platform_linux.cpp` and `CMakeLists.txt`. The new TUs are listed for Astral on
non-Android, non-iOS and non-Windows hosts. Every addition is inside `#if defined(NX_ASTRAL_STRICT)`, so the default
profile preprocesses exactly as before.

## Assets

The art and font live in the repository at `assets/launcher/`, outside the patch, because they are binary files:

| file | size | what |
|---|---|---|
| `title-bg.jpg` | 1600x900, about 300 KB | background art, scaled to cover the window (cropped to its aspect) |
| `Baloo2-Bold.ttf` | about 35 KB | Baloo 2, instanced at weight 700 and subset to Latin |
| `OFL.txt` | | the font's licence |

The runtime looks in these directories, in this order. It takes the first one that holds both the font and a
background; if none does, it takes the first that holds either:

1. `NX_ASSET_DIR`
2. `<executable dir>/assets/launcher`
3. `<executable dir>/../assets/launcher`
4. `<executable dir>/../Resources/assets/launcher` (an app bundle)
5. `./assets/launcher`

To use them, copy or symlink `assets/launcher` beside the built binary, or set
`NX_ASSET_DIR=<repo>/assets/launcher`. Reads are capped at 16 MiB and images at 8192 pixels a side. Without the font, text falls back to SDL's built-in 8x8 debug font, scaled.
Without the art, a drawn night-sky gradient with neon lines is used. Either way the launcher still works.

Layout uses a 1280x720 space, scaled uniformly to the window's real pixels (HiDPI aware) and centred. The art always
covers the whole window. Text is rasterised at the output pixel size, so it stays sharp at 2x.

## When it shows

`main()` calls `nx::launcher::start()` right after `SDL_Init`, before the memory guard and the game thread exist. On
Linux it then calls `nx::hud::prepare_native_overlay()`, which sets MangoHud's environment from the exported
`NX_PERF_HUD` while the process is still single-threaded (`docs/ASTRAL_PERF_HUD.md`).

| condition | behaviour |
|---|---|
| `NX_HEADLESS` or `NX_INPUT_SCRIPT` set (non-empty), or `NX_DUMP_FRAMES` / `NX_AUDIO_DUMP` set to anything but empty or `0` | No launcher: headless and scripted runs (for example `tools/run_mac_prepo_native.py`, which sets `NX_DUMP_FRAMES`) never wait at it. |
| `NX_SKIP_LAUNCHER` set to anything except empty or `0` | No launcher. |
| `NX_INPUT_RECORD` | Does **not** skip it: that is a player's own recorded session. |
| otherwise | The launcher window opens. **PLAY** closes it and boots. **QUIT**, or closing the window, exits with status 0. |

When the launcher is skipped, `settings.ini` and `controls.ini` are still read if they exist. Scripted runs use
fresh data roots and are unaffected.

The launcher has its own window and an SDL_Renderer (Metal on macOS). On PLAY, its textures, renderer and window are
destroyed and the leftover events are flushed. The game then creates its own window, Metal layer and Vulkan surface,
exactly as before. In addition, the game's event loop now ignores minimise, hide, show and pixel-size events from any
window other than the game's own (`SDL_GetWindowID(g_window)`).

This was checked on this Mac (Apple M5 Pro, SDL 3.4.18): the Metal renderer is drawn and destroyed, then a
`SDL_WINDOW_METAL` window, its `CAMetalLayer` and `vkCreateMetalSurfaceEXT` through MoltenVK all succeed. A pushed
Down, Up, Enter sequence also went through the real loop and returned PLAY with no events left over.

## Screens and navigation

| input | action |
|---|---|
| Up/Down, W/S, d-pad, left stick | move |
| Left/Right, A/D, d-pad, left stick | change a setting |
| Enter, keypad Enter, Space; the gamepad button bound to Switch **A** (default: east) | select |
| Esc, Backspace; the gamepad button bound to Switch **B** (default: south) | back |
| mouse | hover to highlight, left click to select |

CONTROLS (`astral-controls-ui.patch`) shows every Switch control at once, without scrolling, laid out like a
controller settings page: panels for **Buttons** (A, B, X, Y, Plus, Minus), **Left Stick** and **Right Stick** (click
and the four directions), **D-pad** and **Triggers** (L, R, ZL, ZR). Each row reads "control → binding" for the
selected tab, **Gamepad** or **Keyboard** (the two tabs at the top). Beside the panels, a drawn controller (original
shapes, no artwork) lights up the control under the cursor (a stick direction as an arrow, a click as a ring) and
names its binding.

- Arrows, W/A/S/D, the d-pad or the left stick move to the nearest item in that direction; the mouse hovers and clicks.
- To rebind a row, select it and then, within 5 s, use the selected tab's device: on **Gamepad**, press a button or
  push an axis past 24000 (a trigger or a stick direction); on **Keyboard**, press a key (any key, Esc included).
- Input from the other device, a mouse click or the 5 s timeout cancels.
- **Reset to defaults** restores the table below (both devices).
- Every change is written to `controls.ini` at once; its format and the bindings model are unchanged.
- The gamepad bindings show the controller's own labels when they are known, for example `east (B)` on an Xbox pad,
  `east (A)` on a Switch Pro Controller and `south (Cross)` on a PlayStation pad.

SETTINGS, written to `settings.ini` at once:

| row | key | exported as | notes |
|---|---|---|---|
| Performance HUD (F3) | `perf_hud` | `NX_PERF_HUD=1` | `docs/ASTRAL_PERF_HUD.md`: the platform's own overlay where there is one (macOS: Apple's Metal Performance HUD; Linux: MangoHud when installed), else the built-in HUD (headless and capture runs: always the built-in HUD). Linux sets MangoHud up right after the launcher returns. F3 toggles it in game, except Apple's HUD, which Metal loads only at process start: macOS restarts the game when PLAY is pressed with a changed setting (`docs/ASTRAL_PERF_HUD.md`). |
| Fullscreen (F11) | `fullscreen` | `NX_FULLSCREEN=1` | Linux already read it; this overlay makes macOS read it too (`create_window`). F11 still toggles. |
| Window size | `resolution` | `NX_RESOLUTION=WxH` | 1280x720 (default), 1600x900, 1920x1080, 2560x1440, 3200x1800, 3840x2160. This is the window's size in points. Each is labelled relative to the game's render size, 1600x900: `1600x900 (Native)`, `1280x720 (0.8x)`, `3200x1800 (2x)`. A `--render-res` build exports its size as `NX_NATIVE_RES` from the .app wrapper, and the labels follow it. |
| Mute audio | `mute` | `NX_MUTE=1` | no audio device, as `NX_MUTE` |
| Frame rate | `fps` | `NX_FPS=60` | 30 (default) or 60 (experimental): which binary runs (`docs/ASTRAL_60FPS.md`, `astral-fps-variant.patch`). The .app wrapper starts `astral-60fps` for 60. When it is changed in the launcher, PLAY re-executes the other binary with `NX_SKIP_LAUNCHER=1` (`launcher::reexec`). A build made with `--fps` has one binary; the row then says so instead of changing. |

Environment variables win. If one of the four is already set, its row shows what the runtime will actually do, for
example `On (set by NX_MUTE)`, and the row cannot be changed. The runtime reads them as follows:

- `NX_MUTE` mutes whenever it exists, even as `0`.
- `NX_PERF_HUD` is on unless it is empty or starts with `0`. `NX_PERF_HUD=ac` always uses the built-in HUD.
- `NX_FULLSCREEN` is on only as `1`.

Settings left at their defaults are not exported, so a run without `settings.ini` behaves exactly as before.

### Save profiles

PLAY opens a small picker, **CHOOSE A SAVE PROFILE** (`astral-save-profiles.patch`, `runtime/src/save_profile.h`).
It lists every profile with the time its newest save file was written ("Last played 2026-10-19 15:44", or "No saves
yet"), then **New profile** and **Back**. The cursor starts on the profile used last. Up/Down (keys, D-pad, stick)
move, Enter / A or a click plays with the selected profile, Esc / B or Back returns to the main menu. New profile adds
"Profile 2", "Profile 3", ... to the list (its folder is created when the game mounts its save data at boot); choose it to start a new
save.

| profile | save folder |
|---|---|
| Default | `<data root>/user/save` (where saves have always been; never moved or deleted) |
| any other `<name>` | `<data root>/user/profiles/<name>/save` |

The choice is remembered in `settings.ini` as `save_profile = <name>` and reaches the runtime as `NX_SAVE_PROFILE`
(always exported, Default too, so a restart such as the macOS Metal HUD one boots the profile chosen even if
`settings.ini` could not be written; `hle_fs.cpp` `MountSaveData` maps it). Names are 1 to 32 ASCII
letters, digits, spaces, `-` or `_`, without a leading or trailing space; anything else, including `..` or a path
separator, is read as Default, and the mapped folder must still lie beneath the data root. Folders in
`user/profiles` that are symlinks or have other names are not listed. A valid `NX_SAVE_PROFILE` set in the environment skips
the picker and wins over `settings.ini`; an invalid one is logged, the picker shows with a warning, and the choice
replaces it (with the launcher skipped, the runtime logs it and uses Default); with the launcher skipped (`NX_SKIP_LAUNCHER=1`) the last choice in
`settings.ini` is used.

## Files

Both files live in the data root (`NX_DATA_ROOT`, default `private/astral`). Each is written to a `.tmp` file that is
then renamed over the original. Lines starting with `#` or `;` are comments. Keys and names are case-insensitive.
Unknown keys or names are ignored and logged (`input: controls.ini line N: ...`). An entry with no valid name keeps
its default.

`controls.ini`:

```
[gamepad]
A = east
ZL = +lefttrigger
LS_UP = -lefty
[keyboard]
A = Space
B = Left Shift | Right Shift
X = sc:158
LSTICK = none
```

- Gamepad names are SDL positional buttons: `south`, `east`, `west`, `north`, `back`, `guide`, `start`,
  `leftstick`, `rightstick`, `leftshoulder`, `rightshoulder`, `dpup`, `dpdown`, `dpleft`, `dpright`, `misc1`,
  paddles, and so on. An axis direction is written `+`/`-` followed by `leftx`, `lefty`, `rightx`, `righty`,
  `lefttrigger` or `righttrigger`. SDL's Y axes are positive downwards, so stick up is `-lefty`.
- Keyboard names are SDL scancode names, for example `Space`, `Return`, `Escape`, `Left Shift`, `A`, `Up` or
  `Keypad Enter`. A key whose name is empty, contains `|` (`Keypad |`, `Keypad ||`) or belongs to another key too
  (Return2 is also called "Return") is written `sc:<SDL scancode number>`.
- Separate several bindings with `|`. Write `none` (or leave the value empty) for no binding.
- Keys: `A B X Y L R ZL ZR PLUS MINUS LSTICK RSTICK DUP DDOWN DLEFT DRIGHT LS_UP LS_DOWN LS_LEFT LS_RIGHT RS_UP
  RS_DOWN RS_LEFT RS_RIGHT`.

`settings.ini`:

```
[settings]
perf_hud = 0
fullscreen = 0
resolution = 1280x720
mute = 0
```

Flags accept `1`, `on`, `true` and `yes`. A resolution must be `WxH` between 320x180 and 16384x16384, or it is
ignored.

## Default bindings (the former fixed mapping)

With no `controls.ini`, `nx::input::map` gives exactly the same `PadState` as the hosts' previous hard-coded
`sample_input`. The test compares the two on 50 000 random gamepad + keyboard frames. The gamepad uses the Nintendo
layout by position: Switch A is the **east** face button, so on an Xbox pad Switch A is the pad's B and Switch B is
the pad's A. Players who want the Xbox feel can swap A/B (and X/Y) on the CONTROLS screen.

| Switch | gamepad | keyboard |
|---|---|---|
| A / B / X / Y | east / south / north / west | Space / Left or Right Shift / J / K |
| L / R | leftshoulder / rightshoulder | Q / E |
| ZL / ZR | left / right trigger past 12000 | Z / C |
| Plus / Minus | start / back | Return / Escape |
| L / R stick click | leftstick / rightstick | none |
| d-pad | dpup / dpdown / dpleft / dpright | W or Up / S or Down / A or Left / D or Right |
| left stick | left stick (deadzone 7849) | W A S D and the arrows (full deflection) |
| right stick | right stick (deadzone 7849) | none |

Rules carried over from the old code:

- A key moves a stick to full deflection over the gamepad's value. Of two opposing keys, right wins over left and down
  wins over up.
- The keyboard is read only while the game window has focus.
- An axis bound to a button presses it above 12000.
- A button bound to a stick direction gives full deflection.

## Not covered

- Windows: its host uses XInput and Win32, not SDL3. The launcher and remapping are not built there, and
  `platform_win.cpp` is unchanged. `NX_FULLSCREEN` / `NX_RESOLUTION` / `NX_PERF_HUD` / `NX_MUTE` work there as before.
- Android and iOS keep their own input and settings paths.
- Only the first gamepad is used, as before. Bindings cannot be cleared from the UI (edit `controls.ini` and write
  `none`), and one input cannot be added beside an existing one there (use `|` in the file).
- The build does not copy `assets/launcher` beside the binary. Packaging (or `NX_ASSET_DIR`) does that.

## Public export

`scripts/export_public.py` publishes `assets/launcher/*.{jpg,png,ttf,otf}` of up to 1.5 MiB each, and requires an
`OFL.txt` or NOTICE beside every font. `title-bg.jpg` (about 300 KB), `Baloo2-Bold.ttf` (35 KB) and `OFL.txt` meet
those rules. The vendored stb headers travel inside `astral-launcher.patch` (about 570 KB, under the 1 MiB text
limit). The export of this branch verifies with no findings. Provenance and hashes are in `THIRD_PARTY_NOTICES.md`
("Launcher libraries, font and art").

## Verify

```
python3 -m unittest tests.test_astral_launcher -v
```

The test applies the stack to a fresh pinned runtime and links the production `input_map.cpp` and `launcher.cpp` into
a fixture with SDL3. It never calls `SDL_Init` and opens no window. It checks:

- file round trips and errors, including `sc:` key names
- the former-mapping identity and remaps
- synthetic SDL events and the menu state machine
- the truthful display of environment overrides
- `start()` and the skip rules for each variable
- that the shipped font measures sensibly through `NX_ASSET_DIR`, and that the art is a 1600x900 JPEG within 400 KB
- the window-ID filter
- strict Mac-profile syntax and default-profile preprocessing identity
- that the macOS and Linux additions are strict-only (checked textually)
- that `windows-native.patch` still applies

SDL3 headers come from `NX_SDL3_INCLUDE` or Homebrew, and the library from `NX_SDL3_LIB` or the include directory's
sibling `lib`. Without them the test is skipped.
