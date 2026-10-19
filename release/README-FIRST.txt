AC-Recomp - read this first
===========================

This download contains NO game code, data, shaders or fonts. It is a set of build tools, runtime patches,
launcher art and documentation. You need your own legally dumped copy of Astral Chain and your own console keys;
the game is then recompiled on your own Mac.

Easiest (macOS, Apple silicon): download AC-Recomp-v0.1.0-macos.dmg instead, open AC-Recomp Setup and
follow the steps (docs/SETUP_APP.md). This zip is the same build kit for the command line.

Quick start (macOS, Apple silicon):

  1. Install the build tools:
       xcode-select --install
       brew install python            (if python3 --version is older than 3.11)
       brew install cmake ninja pkg-config sdl3 opus molten-vk vulkan-headers spirv-tools zstd
       brew install --cask dotnet-sdk

  2. Build (about 25 GB of free space; 30 to 90 minutes the first time):
       python3 tools/acr_build.py --nsp "/path/to/Astral Chain.nsp" --keys /path/to/keys \
           [--title-keys /path/to/title-keys] [--fonts /path/to/shared-fonts] --out ~/AC-Recomp-build \
           --jobs 4

  3. Play: open ~/AC-Recomp-build/AC-Recomp.app

If something is missing, the script says what and how to install it. Run the same command again after fixing it;
finished steps are skipped. By default the number of parallel compiles adapts to your
Mac and drops automatically under memory pressure; --jobs 4 is a safe explicit choice. Without --fonts, open-licensed replacement fonts (Noto Sans) are installed
and format-checked; their in-game appearance is not yet verified, and button icons and CJK text will not display. Full instructions: docs/BUILDING.md.

Supported: Astral Chain 1.0.0, base game, no update.

Everything the build produces comes from your dump. Do not share it.

This project is not affiliated with Nintendo or PlatinumGames. See README.md, LICENSE and THIRD_PARTY_NOTICES.md.
