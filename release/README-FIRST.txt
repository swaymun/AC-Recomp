AC-Recomp - read this first
===========================

This download contains NO game code, data, shaders or fonts. It is a set of build tools, runtime patches,
launcher art and documentation. You need your own legally dumped copy of Astral Chain and your own console keys;
the game is then recompiled on your own Mac or Windows PC.

Windows x64 (AVX2-capable CPU, Vulkan 1.3+ graphics driver):

  1. Import your own dump on a Mac first (README.md, Windows section). Keys stay on the Mac.
     Copy only the imported exefs, analysis and extract folders plus the control receipt to Windows.
  2. Extract All from the Windows zip. Double-click AC-Recomp Setup.cmd in the extracted folder.
  3. Enter the import and receipt paths, optional shader/font folders, and a separate install folder.
     Setup checks Python, Git, Visual Studio C++ Build Tools and shader tools, with clear install prompts.
     Reuse your own translated shaders, or install .NET 10, SPIRV-Tools and zstd.dll to translate on Windows.
  4. Confirm the build. It needs internet and at least 25 GB free; allow an hour or more on the first run.
     When done, open AC-Recomp from Start or the desktop and click Play.

Keep the imported files and install folder in place. Saves live in <install>\data\user.
If setup stops, fix the printed error and rerun with the same paths to resume.
The scripts are unsigned; only run a download you trust. No game executables are shipped.
Full Windows instructions and command-line options: ports/windows/README.md.

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
