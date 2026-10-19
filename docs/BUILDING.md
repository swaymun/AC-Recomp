# Building AC-Recomp from your own game files (macOS)

AC-Recomp releases contain **none of Astral Chain's code or data**. A release is a set of tools, runtime patches,
launcher art and documentation. You supply your own legally dumped game and keys, and `tools/acr_build.py`
recompiles the game on your Mac. Everything it produces is derived from your dump: keep it to yourself.

This works like [LASRecomp](https://github.com/peiikai/LASRecomp)'s "bring your own game files" setup, except that
the game's code is lifted and compiled locally instead of being shipped.

## What you need

- A Mac with Apple silicon, macOS 13 or newer, and about **25 GB** of free disk space.
- Your own **Astral Chain** dump as an **NSP** (cartridge or eShop, base game 1.0.0).
- Your console's **keys**, and **title keys** if your dump needs them. The tools pass these files to the
  importer by path. They never print, copy or upload them.
- Optional: the six **shared system fonts** from your own console's firmware (see [Fonts](#fonts)).
- The Xcode command-line tools: `xcode-select --install`
- [Homebrew](https://brew.sh) packages:

  ```sh
  brew install cmake ninja pkg-config sdl3 opus molten-vk vulkan-headers spirv-tools zstd
  ```

- The **.NET 10 SDK**, for the offline shader translator: `brew install --cask dotnet-sdk`, or the macOS Arm64
  installer from <https://dotnet.microsoft.com/download/dotnet/10.0>. Open a new terminal afterwards.
- Python 3.11 or newer (`python3 --version`); if yours is older, `brew install python`.
- An internet connection for the first run. It clones the pinned
  [SuperMarioWonderRecomp](https://github.com/BelmanteGu/SuperMarioWonderRecomp) runtime and the pinned shader
  translator (see THIRD_PARTY_NOTICES.md) source, installs three Python packages for the recompiler (`capstone`, `lz4`, `zstandard`),
  and restores the translator's NuGet packages. If you give no fonts, it also downloads Noto Sans.

`cmake` and `ninja` are optional: without them the script installs both into its own Python environment. Without
`vulkan-headers` it fetches the pinned Vulkan-Headers.

## Build

From the unpacked release (or a checkout of the repository):

```sh
python3 tools/acr_build.py \
  --nsp "/path/to/Astral Chain.nsp" \
  --keys /path/to/keys \
  --title-keys /path/to/title-keys \
  --fonts /path/to/shared-fonts \
  --out ~/AC-Recomp-build
```

`--title-keys` and `--fonts` are optional. The script prints each stage as it runs:

| stage | what it does | time on an M-series Mac |
|---|---|---|
| preflight | checks tools and inputs, and lists every missing piece with its install command | seconds |
| workspace | creates `--out` as a private Git workspace that ignores everything | seconds |
| upstream | clones SuperMarioWonderRecomp at the pinned revision | under a minute |
| toolchain | creates a Python venv with the recompiler's packages | under a minute |
| import | imports your NSP: program modules, metadata and RomFS (about 10 GB) | a few minutes |
| control | reads the game's control metadata (age ratings, parental flags) | under a minute |
| lift | recompiles `main` and `sdk` to C++ | one to two minutes |
| shaders | finds every shader in the RomFS and translates it to SPIR-V | a few minutes |
| runtime | prepares the pinned runtime and applies `runtime/patches/series.macos` | seconds |
| build | compiles the runtime and the lifted game code | minutes to an hour, depending on the Mac and `--jobs` |
| fonts | installs your fonts, or open-licensed replacements | seconds |
| data | lays out the data root: game files, SPIR-V, fonts and saves | seconds |
| app | writes `AC-Recomp.app` (its icon made from `assets/launcher/AC-Recomp.png` with `sips` and `iconutil`, skipped without them) and `run-ac-recomp.sh` | seconds |

When it finishes, open `~/AC-Recomp-build/AC-Recomp.app`, or run `~/AC-Recomp-build/run-ac-recomp.sh`. The
launcher comes up first. **PLAY** starts the game.

### Resuming and rerunning

Each finished stage is recorded in `<out>/acr-state.json`, with what it was built from. If a pinned revision or a
patch changes (a new release), the affected stage and everything after it are rebuilt automatically. `--out` must be
a new or empty directory, or an earlier AC-Recomp build directory. If something fails, fix what the error message says
and run **the same command again**: finished stages are skipped and the compile continues where it stopped.

- `--from-stage NAME` reruns that stage and everything after it, for example `--from-stage fonts --fonts <dir>`
  to switch to your own fonts later.
- `--only NAME` runs a single stage. `--to-stage NAME` stops after it.
- `--dry-run` prints every command and file operation without changing anything.
- `--list-stages` lists the stages.
- `--jobs N` sets the number of parallel compiles. By default it adapts to your Mac: half the performance cores,
  at most one per 6 GiB of currently available memory, and never more than 8. The compile runs at low priority
  (`nice 10`), and a watchdog checks memory pressure every few seconds: under warning or critical pressure, or
  with less than 4 GiB available, it stops the compile and resumes it with half the jobs, noting this in the
  output and in `logs/build.log`. Nothing finished is recompiled. `--jobs 4` is a safe explicit choice.
- **Experimental:** `--render-res WxH` makes the game render docked at WxH instead of 1600x900, e.g. `2560x1440`,
  by patching a dozen instructions of `main` (each original word checked first) before the lift. The game's
  graphics memory budget is scaled with the size automatically; `--graphics-memory-mib` overrides it. Tested
  headless at 1920x1080 and 2560x1440 through the opening only. Changing it relifts `main`; only the two changed
  C++ files recompile. See [ASTRAL_RENDER_RES.md](ASTRAL_RENDER_RES.md).
- **Experimental 60 fps:** by default the build makes both frame rates: `AC-Recomp.app/Contents/MacOS/astral`
  (30 fps, the game as shipped) and `astral-60fps`, whose `main` is lifted a second time with five instructions
  patched, after a check of each original word (docs/ASTRAL_60FPS.md). Only the generated files that differ (two of
  about 200) compile again; the runtime and everything else are shared, so this adds about 25 s of lifting, a few
  seconds of compiling and 56 MB to the app. The launcher's **Settings > Frame rate** (`settings.ini` `fps = 30|60`,
  or `NX_FPS` at run time) picks the binary. `--fps 30` or `--fps 60` (or `NX_FPS` in the build's environment) builds
  only that one, as before; changing it relifts `main`. Only Astral Chain 1.0.0 is supported for 60 fps: with
  another version the default build prints a note and makes the 30 fps binary only.
  `--render-res` applies to both binaries.

Other options: `--prefix` (SDL3/opus install prefix, default Homebrew), `--vulkan-include`, `--moltenvk`,
`--dotnet`, `--cmake`, `--ninja`, `--reference` (a local SuperMarioWonderRecomp clone, for offline rebuilds),
`--nvn-format-profile`, `--skip-shaders` and `--no-shader-validation`. Run `python3 tools/acr_build.py --help` for the full
list.

## Texture-format profile

The strict runtime reads texture-format records straight from the game's SDK, using a small profile named by
`NX_NVN_FORMAT_PROFILE` (`NX_FORMAT_PROFILE_V1` and nine hexadecimal values; see `docs/MAC_NVN_TEXTURE.md`). The
build installs it for you: it checks the built-in profile for Astral Chain 1.0.0 against your own SDK, writes
`<data root>/astral.profile`, and the app sets `NX_NVN_FORMAT_PROFILE` itself. If your dump is a different version,
the data stage stops with "this game version is not supported". `--nvn-format-profile <file>` overrides the built-in
profile; it gets the same check.

## Fonts

The game draws its text with the Switch's shared system fonts. You have two choices.

**Your console's fonts (optional).** Switch fonts are Nintendo IP; you may provide them from your own hardware.
Put the six font files in one directory and pass `--fonts <dir>`:

```
nintendo_udsg-r_std_003.bfttf        standard (Japanese, US and European)
nintendo_udsg-r_org_zh-cn_003.bfttf  Chinese (simplified)
nintendo_udsg-r_ext_zh-cn_003.bfttf  Chinese (simplified) extension
nintendo_udjxh-db_zh-tw_003.bfttf    Chinese (traditional)
nintendo_udsg-r_ko_003.bfttf         Korean
nintendo_ext_003.bfttf               Nintendo extended (button icons)
```

The script accepts the firmware's `.bfttf` files unchanged, or already-decoded `.ttf`/`.otf` files with the same
names. It checks every font before installing it.

**Open-licensed replacements (default).** Without `--fonts`, the script downloads Noto Sans Regular
(SIL Open Font License, pinned by checksum; downloaded at build time, not redistributed) and installs it in all
six slots, so you can build without firmware. The fonts are installed and format-checked; their in-game appearance
is not yet verified. **Button icons from the Nintendo extended font and Chinese, Japanese
and Korean text will not display.** `--replacement-font <file.ttf>` uses another TrueType font instead. To switch
to your own fonts later:

```sh
python3 tools/acr_build.py --out ~/AC-Recomp-build --from-stage fonts --fonts /path/to/shared-fonts
```

## What ends up where

```
<out>/
  AC-Recomp.app            the game: launcher script, astral and astral-60fps, MoltenVK, launcher art, icon
  run-ac-recomp.sh         the same, from a terminal
  data/                    the data root (NX_DATA_ROOT)
    analysis exefs extract   links to your imported game files
    spirv/                 translated shaders
    astral.profile         the texture-format profile, checked against your SDK
    shared-fonts/          the six fonts
    settings.ini controls.ini   the launcher's settings and controls (kept by the script)
    user/save/             your saves (never deleted by the script; see "Saves")
  .local/game-private/     the imported dump (about 10 GB)
  work/                    upstream sources, lifted C++, shader tools, the runtime build
  logs/                    one log per command
  acr-state.json           finished stages
```

Once the game runs you can delete `work/` to save space. The next run of the script rebuilds what it needs.

The app reads `NX_DATA_ROOT` and `SDL_VULKAN_LIBRARY` from the environment when they are set. Other settings, such
as `NX_PERF_HUD=1` and `NX_PLAYER_NAME`, work as described in the README.

## Saves

The game's save data lives in `<out>/data/user/save/` (`GameData.dat`, `SlotData_0.dat`, `SlotData_1.dat`, ...), next
to the launcher's `settings.ini` and `controls.ini` in `<out>/data/`. With another `NX_DATA_ROOT`, they are under that
root instead. Save profiles chosen in the launcher's PLAY picker other than Default live in
`<out>/data/user/profiles/<name>/save/` (`docs/ASTRAL_LAUNCHER.md`, "Save profiles").

Rerunning `tools/acr_build.py` with the same `--out` (any stage, `--from-stage`, or after changing the patches) keeps
them: the `data` stage only replaces `spirv/`, the game-file links and `astral.profile`, the `app` stage only replaces
`AC-Recomp.app`, and the script refuses to delete `data/user` or anything inside it (`tests/test_acr_build.py` checks
both). Deleting `work/` is safe too.

Back them up anyway before updating or deleting a build: quit the game, then copy the whole `<out>/data/user/` folder
(and `settings.ini`/`controls.ini` if you want your settings). To restore, quit the game and copy the folder back. Do
not delete `<out>` itself or point `--out` at a new directory expecting your saves to follow: a new `--out` starts with
no saves until you copy `data/user/` into it.

## Troubleshooting

- **The preflight check lists missing tools.** Install them with the commands it prints, then rerun.
- **`import failed (importer_failed_resume_same_command)`.** Your keys probably do not match the dump's
  key generation. Use keys from your own console that match the dump, add `--title-keys` if your dump needs it,
  and rerun.
- **`import failed (title_mismatch)`.** This is not an Astral Chain base-game NSP.
- **The build fails.** The error shows the last lines of `<out>/logs/build.log`. Check that the Homebrew packages
  are installed, and rerun with `--jobs 2` if the machine ran out of memory.
- **The game stops with a missing shared font.** Rerun `--from-stage fonts`.
- **`this game version is not supported`.** Only Astral Chain 1.0.0 (base game, no update) is supported.

## Sharing

Do not share `<out>` or anything in it: it contains game code, data and shaders derived from your dump. Bug reports
should include `logs/` excerpts and `acr-state.json`, never game files.
