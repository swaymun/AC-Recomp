# Windows setup

The Windows zip is a source kit. Nothing from the game is included. Setup builds a private
copy from your own NSP dump and console keys, generates the original app icon locally, and adds
**AC-Recomp** to your Start menu and desktop. The import and control-metadata extraction run on
Windows; no Mac is needed. Keep your `prod.keys` and optional `title.keys` in a private local folder.
Only the native importer reads the keys; setup does not copy or upload them.

On Windows with an AVX2-capable x64 CPU:

1. Install your GPU manufacturer's Vulkan 1.3+ graphics driver. Allow at least 25 GB of free space
   and an internet connection for the first build.
2. **Extract All** from the Windows zip to a permanent folder. Do not run setup inside the zip viewer.
3. Double-click **AC-Recomp Setup.cmd** in that folder. The preview scripts are unsigned:
   review the source and only run a download you trust. No system execution policy is changed.
4. Enter your NSP dump and `prod.keys` paths, plus `title.keys` if required. You can paste paths containing spaces;
   outer quotes are accepted. Optionally provide translated shaders and shared fonts from your own build.
5. Setup checks Python 3.11+, Git, and Visual Studio 2022 Build Tools with C++, Clang, CMake and the Windows SDK.
   It shows each missing tool and asks before running its WinGet installer. Installers may request administrator
   permission. Without WinGet, use the official links printed by setup. If an existing VS installation lacks a
   component, open Visual Studio Installer, **Modify**, and select the C++ workload and C++ Clang tools.
6. For shader translation on Windows, install the .NET 10 SDK, SPIRV-Tools (`spirv-val`) and `zstd.dll` on PATH.
   Setup offers the .NET installer; the other two tools require manual installation.
   Reusing your own translated shader folder skips all three requirements.
7. Choose a separate install folder and confirm **Start building**. The default is
   `%LOCALAPPDATA%\AC-Recomp\build`. Setup builds both frame rates and creates the launcher and shortcuts.
8. Open **AC-Recomp** from Start or the desktop. Choose 30 fps or experimental 60 fps, then **Play**.

The Windows launcher is a small native Windows form; it does not include the Mac launcher's remapping UI.
Use [controller documentation](../../docs/CONTROLLER_SUPPORT.md) for controls and configuration.
Keep the install folder in place. Choose a folder restricted to your account; Windows inherits the parent ACLs.
Prefer a short path such as `C:\ACR\player` because compiler/dependency tools can have path limits.
Native import handles Unicode paths and 64-bit file sizes, including NSPs larger than 4 GiB.
Setup enables Python UTF-8 mode and decodes its output as UTF-8 automatically, including on
systems using cp1252 by default. You do not need to set encoding environment variables.
Saves live in `<install>\data\user`. Do not share the install or its generated files.

If setup stops, read the last error and rerun with the same paths. Finished stages are reused.
Build logs are in `<install>\logs`; runtime errors are in `<install>\game.log`.
Setup uses one compiler job by default to limit memory use. `-Jobs 2` or higher can shorten the build
on machines with enough available memory. For compiler out-of-memory errors, close memory-heavy programs
and rerun setup with `-Jobs 1`.
Close both the game and launcher before rerunning setup. To remove the install, first back up your saves,
then remove its folder and the two shortcuts yourself. Setup does not delete saves.

For repeatable local setup (no installers or prompts):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ports\windows\Setup.ps1 `
  -Nsp "C:\Games\Astral Chain.nsp" -Keys C:\Private\prod.keys `
  -TitleKeys C:\Private\title.keys -Fonts C:\Private\shared-fonts `
  -InstallDir C:\Games\AC-Recomp -Jobs 1 -NonInteractive
```

`-CheckOnly` checks prerequisites. `-NoDesktopShortcut` creates only the Start-menu shortcut.
`-Fps 30` or `-Fps 60` builds only that rate; the launcher offers only installed rates.
Use `-ToStage control` to stop after importing and verifying control metadata, before lifting,
compilation or shortcut creation. Rerun without it to continue the build.

To reuse an existing Mac or Windows import, supply `-ImportDir` and `-ControlReceipt` instead of
`-Nsp`/`-Keys`/`-TitleKeys`. See [BUILDING.md](../../docs/BUILDING.md) for the required layout.
Keep that imported folder in place: the build links to its game files. Never transfer your real keys
for maintainer testing. The Python helper accepts `run --windows --nsp ... --keys ... --out ...`
and the optional `--to-stage control`; `--import-dir ... --control-receipt ...` remains available.

Maintainers build the zip offline with `python3 scripts/package_release.py --windows`.
It packages committed source only; it does not download dependencies or compile any executable.
The installed launcher is compiled locally with the Windows SDK resource compiler and the .NET Framework
C# compiler included with supported Windows installations. No launcher binary is distributed.

Installer references: [VS component IDs](https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-build-tools?view=vs-2022),
[.NET on Windows](https://learn.microsoft.com/en-us/dotnet/core/install/windows),
[Python WinGet manifest](https://github.com/microsoft/winget-pkgs/tree/master/manifests/p/Python/Python/3/12).
