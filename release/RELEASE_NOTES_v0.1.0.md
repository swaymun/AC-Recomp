# AC-Recomp v0.1.0 (macOS)

An early preview of AC-Recomp, a native static recompilation of **Astral Chain** for macOS on Apple silicon.

**This release contains no game code, data, shaders or fonts.** You need your own legally dumped Astral Chain 1.0.0
(NSP) and your console's keys. `tools/acr_build.py` imports your dump and recompiles the game on your own Mac.

## Download

- **`AC-Recomp-v0.1.0-macos.dmg`** (recommended): open it and run **AC-Recomp Setup**, which checks the prerequisites,
  asks for your NSP and keys and builds `AC-Recomp.app` on your Mac. SHA-256: `e71aa3922b8d96453c52606fa78f7ecfabaaee47d6b924dc8866b92b90a8884d`
- `AC-Recomp-v0.1.0-macos.zip`: the same build kit for the command line (`python3 tools/acr_build.py ...`).
  SHA-256: `891337ae4621fa544f04eb1a26cea8fac936d29deeb63428221aee4a46fb6942`

The setup app is not notarized. On macOS 15 and later, try to open it once, then choose **System Settings >
Privacy & Security > Open Anyway**. On macOS 13 and 14, right-click it and choose **Open**.

## Getting started

1. Open the DMG and run **AC-Recomp Setup** (or drag it to Applications first).
2. Follow the steps: it checks Xcode's command-line tools, Homebrew packages, Python 3.11+ and the .NET 10 SDK and
   offers the install command for anything missing; then pick your Astral Chain 1.0.0 NSP and your keys.
3. Press Build (about 5 to 10 minutes on an M-series Mac). When it finishes, open AC-Recomp or move it to
   Applications. Your saves live in the build folder (`~/AC-Recomp/build/data/user`), not inside the app.

Prefer the command line? See `docs/BUILDING.md` (`python3 tools/acr_build.py --nsp ... --keys ... --out ...`).

## What works

Observed on the developer's Mac with the development build:

- Boots through the opening sequence and character creation (with the firmware's shared fonts).
- The File 01 motorcycle chase runs at a stable 30 fps on an Apple M5 Pro.
- Audio.
- A launcher (start screen) with a controller-style remapping screen for gamepad and keyboard, save profiles
  (pick or create one when you press Play; existing saves are "Default"), and settings: performance HUD,
  upscaling (Bilinear / FSR 1), frame rate (30 / 60, experimental), fullscreen, window size (labelled against the
  native 1600x900) and mute.
- A performance HUD, switched on in the launcher's Settings (or `NX_PERF_HUD=1`): Apple's Metal Performance HUD on macOS, MangoHud on Linux when installed, and a built-in HUD otherwise (F3 toggles MangoHud and the built-in HUD).

With a build made by `tools/acr_build.py` from the developer's own dump:

- The whole pipeline (import, control metadata, lift, shader translation, all runtime patches, build, data root,
  app) completes. The lifted code and all 1,332 translated shaders are byte-identical to the development build's.
- A 60-second headless run of the built app (with mouse touch) reaches the start screen ("ZL + ZR") with steady frame output and no fatal error.

Also included:

- FSR 1 upscaling (AMD FidelityFX, MIT): choose "Upscaling: FSR 1" in the launcher's Settings (or
  `NX_UPSCALE=fsr`); the picture keeps its 16:9 shape.
- Touch: the game's touch screen follows the mouse (hold the left button).
- A one-click setup app (in the DMG) that guides you through prerequisites, file selection and the build.

## Experimental

Both options below patch a private copy of your `main` before the lift. Every original instruction is checked first,
and only Astral Chain 1.0.0 is accepted. They can be combined. Changing either one relifts `main` and reruns the
later build stages.

- `--render-res WxH` makes the game render docked at WxH instead of 1600x900 (for example `2560x1440`). The
  graphics memory budget scales automatically (`--graphics-memory-mib` overrides it). Tested headless at 1920x1080
  and 2560x1440 through the opening only. Dynamic resolution is turned off. See docs/ASTRAL_RENDER_RES.md.
- **60 fps is an in-app setting:** the launcher's Settings > Frame rate, 30 or 60 (experimental), saved as
  `fps` in `settings.ini`. The build makes both binaries by default (`astral` and `astral-60fps`, sharing all but two
  recompiled files); `--fps 30` or `--fps 60` builds one only. See docs/ASTRAL_60FPS.md. Briefly smoke-tested on the developer's Mac: the game switched itself to 60 fps and held a steady 60.0 fps through the opening for 60 s, and the opening cutscene kept normal speed (same scene at the same wall time as a 30 fps run). Battle, gameplay timing and audio sync are not yet checked.

## Known issues

- The game is **not** complete or playable end to end. Expect crashes and rendering bugs.
- Saving and reloading are untested.
- Only Astral Chain 1.0.0 (base game, no update) is supported; other versions are refused when the data root is
  laid out.
- macOS on Apple silicon only in this release. Linux (x86-64, NVIDIA) boots through character creation in headless tests (not part of this release); Windows (x64, NVIDIA) boots through the opening cutscene in headless tests (not part of this release); iOS builds are in progress.
- Without your firmware's shared fonts, open-licensed replacement fonts (Noto Sans) are installed and
  format-checked, but their in-game appearance is not yet verified. Button icons and Chinese, Japanese and Korean
  text do not display with them.
- The first boot cutscene cannot be skipped and lasts about five minutes.
- The first build takes a while. It runs at low priority, sizes its parallel compiles from your performance cores
  and available memory, and backs off automatically under memory pressure; `--jobs 4` is a safe explicit choice.

## Pins

- SuperMarioWonderRecomp `010ed7a596a621c15d3a8dfa5795ca8c3668b066` (runtime, importer, recompiler, shader harness)
- Shader translator (see THIRD_PARTY_NOTICES.md) `a82350bb774f70fcbd41c9987bf67a3775409963`
- Recompiler packages: capstone 5.0.6, lz4 4.4.4, zstandard 0.24.0
- Runtime patches: `runtime/patches/series.macos`, 27 patches
- Replacement font: Noto Sans Regular from notofonts commit `28b15b4b43b7bed62b5cf6e6b0b5ff5846270535`,
  downloaded at build time

## Legal

Not affiliated with, endorsed by or sponsored by Nintendo or PlatinumGames. Do not post game files, keys,
firmware, generated code or translated shaders in issues.
