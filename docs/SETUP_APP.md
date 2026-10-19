# AC-Recomp Setup (macOS installer app)

`AC-Recomp Setup.app` is a small native SwiftUI wizard that builds AC-Recomp on the player's own Mac without a
terminal. It ships in `AC-Recomp-<version>-macos.dmg` next to an Applications link and `Read Me First.txt`. It is a
front end for `tools/acr_build.py`: the build itself, its stages, resuming and every check are the same as in
[BUILDING.md](BUILDING.md).

## What the player does

1. Open the disk image, drag **AC-Recomp Setup** to Applications (optional) and open it.
2. **Welcome**: the legal note. Nothing from the game is included; the player brings their own legally dumped
   *Astral Chain* 1.0.0 NSP and their own console's keys, and is responsible for them. A checkbox confirms it.
3. **Prerequisites**: one row per requirement with its status:
   Xcode Command Line Tools, Homebrew, Python 3.11 or newer, the Homebrew build libraries
   (`cmake ninja pkg-config sdl3 opus molten-vk vulkan-headers spirv-tools zstd`, the list in `acr_build.py`'s
   preflight) and the .NET 10 SDK. **Install** for the command-line tools opens Apple's installer dialog; every
   other **Install** shows the exact command and, on confirmation, opens it in Terminal (or copies it), so the
   player sees and approves what runs. The .NET SDK is installed with Microsoft's `dotnet-install.sh` into
   `~/.dotnet` (`curl -sSL https://dot.net/v1/dotnet-install.sh | bash -s -- --channel 10.0 --install-dir
   ~/.dotnet`), which needs no administrator password, unlike the Homebrew cask. **Check again** re-reads the state.
4. **Game files**: file pickers for the NSP, your keys, optional title keys and an optional folder with the six
   shared-font `.bfttf` files. Only the paths are stored (in the app's preferences) and passed on; the app never
   opens, copies, hashes or prints key files.
5. **Options**: the build folder (default `~/AC-Recomp/build`, about 25 GB; the default has no spaces in its path,
   and the native build is only tested without them) and the experimental `--render-res` choice. The folder may not
   be, contain or sit inside the kit copy (`~/AC-Recomp/kit`, replaced when the kit changes) or the bundled kit; the
   page and the helper both refuse that. Both frame rates are always built; 30 or 60 fps is chosen later in
   AC-Recomp's own Settings, so there is no frame-rate option here. `AC-Recomp.app` refers to the build folder's
   `data/` by absolute path and keeps saves there, so the folder must stay.
6. **Build**: runs the build with a live log, a progress bar and one marker per stage (from the `[n/13] stage:`
   lines). **Cancel** sends SIGINT to the whole build process group; finished stages are kept, and **Resume**
   reruns the same command, which skips them. Every run is appended to `~/AC-Recomp/setup-build.log`. Quitting
   mid-build asks first and then stops the build (it resumes next time); closing the window keeps it running.
7. **Done**: **Open AC-Recomp**, **Move to Applications** (`/Applications` when writable, else `~/Applications`)
   and **Show build folder**.

## How it works

- `ports/macos-setup/SetupApp.swift` is the whole app (SwiftUI, macOS 13+). It is compiled with
  `swiftc -parse-as-library`; there is no Xcode project. Its look follows the launcher: dark, the Baloo 2 font and
  `title-bg.jpg` (dimmed) from `assets/launcher`, and the `AC-Recomp.png` icon converted to `.icns` with `sips`
  and `iconutil` at build time.
- `Contents/Resources/kit` holds exactly the release kit that `scripts/package_release.py` puts in the zip, plus a
  `KIT_VERSION` stamp (version and content digest).
- `tools/acr_setup_cmd.py` (standard library, runs on the command-line tools' Python 3.9) does the work the app
  should not hard-code: `check` reports the prerequisite rows as JSON with their fix commands, `command` prints the
  exact `acr_build.py` argv, and `run` copies the kit to `~/AC-Recomp/kit` (the app can
  run read-only from the disk image or a translocated path), puts Homebrew and the .NET SDK on `PATH` (apps start
  with a bare one), makes itself a process group and execs `acr_build.py` with the Python 3.11+ it found.
  `tests/test_acr_setup_cmd.py` covers the command assembly and the checks.

## Making the disk image

```sh
python3 scripts/make_dmg.py --version v0.1.0 --out dist            # dist/AC-Recomp-v0.1.0-macos.dmg
python3 scripts/make_dmg.py --app-only --out .local/setup          # just the .app, for testing
python3 scripts/package_release.py --version v0.1.0 --dmg          # the zip and the disk image together
```

`make_dmg.py` stages the kit from the committed tree (through `package_release.stage_release`, so the same
allowlist and public-export scan apply), compiles the app, signs it ad hoc (`codesign --sign -`) and runs
`hdiutil create -format UDZO`. Built apps and images are never committed (`dist/` and `.local/` are ignored).

For development, `ACR_SETUP_KIT=<checkout>` makes the app use a checkout instead of its bundled kit, and
`ACR_SETUP_PAGE=<0-5>` opens it on a given page, `ACR_SETUP_DRY_RUN=1` passes `--dry-run` to the build (nothing is
changed) and `ACR_SETUP_AUTOSTART=1` starts the build at launch. Saved choices can be overridden for one launch with
user-defaults arguments, for example `-nsp <file> -keys <file> -out <dir>`.

If a prerequisite is installed somewhere the check does not look, **Skip (advanced)** continues anyway; the build's
own preflight still stops with a precise message on anything really missing.

## Not notarized

The app is signed ad hoc only, not with a Developer ID, and is not notarized. The first launch of a downloaded copy
is blocked by Gatekeeper:

- **macOS 15 and later:** try to open it once, then go to **System Settings > Privacy & Security** and click
  **Open Anyway** (right-click > Open no longer bypasses Gatekeeper there);
- **macOS 13 and 14:** right-click (Control-click) **AC-Recomp Setup** and choose **Open**, then **Open** again;
- or, only after dragging the app to Applications, remove the quarantine flag in Terminal:

  ```sh
  xattr -dr com.apple.quarantine "/Applications/AC-Recomp Setup.app"
  ```

`AC-Recomp.app`, which the build writes on the player's Mac, is not downloaded and needs none of this.

## Limits

- Apple silicon and macOS 13 or newer only, like the build.
- The Homebrew and .NET installs run in Terminal; the app does not install them silently.
- Cancelling stops the current stage; that stage reruns from its start on Resume.
