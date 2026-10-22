# Windows test VM helpers

These helpers prepare the owner-approved `acr-win` Windows Server 2025 / NVIDIA L4 VM.
They install tooling and test the real console desktop, audio and XInput. They do not
provision cloud resources, modify GCP rules, upload keys or launch the game. The parent
owns the VM lifetime and the upstream firewall's owner-IP restriction.

Run from an elevated PowerShell as local `admin`. Sources may be anywhere; all downloads,
probe builds, captures and generated secrets stay in `C:\acr\units\WIN-SETUP-001`.
Do not commit that directory or copy its credential files off the VM.

## Install and status

From the assigned Mac worktree, copy only the helper sources:

```sh
ssh acr-win 'New-Item -ItemType Directory -Force C:\acr\units\WIN-SETUP-001\src | Out-Null'
COPYFILE_DISABLE=1 tar --exclude='._*' -cf - tools/win | ssh acr-win 'cmd /c "tar -xf - -C C:\acr\units\WIN-SETUP-001\src"'
ssh acr-win 'powershell -NoProfile -ExecutionPolicy Bypass -File C:\acr\units\WIN-SETUP-001\src\tools\win\setup_vm.ps1 -ConfigureConsole'
```

`setup_vm.ps1` skips already installed packages, uses a private download cache, logs to
`C:\acr\setup.log`, and atomically replaces `C:\acr\setup-status.txt` after each capability.
Each line is `capability=OK detail`, `FAIL reason`, or `PENDING`. Any failed capability
makes the script return 1; all capabilities must be OK for exit 0. `OK` describes the
named setup probe; recording and reboot acceptance require the additional probes below.
A rerun still refreshes status and logs and checks services and devices; it does not
reinstall healthy packages, reset the password, or reboot automatically.

The setup installs Git for Windows, Python 3.12.10, VS 2022 Build Tools (C++ workload,
Windows SDK, clang-cl, CMake, Ninja), .NET SDK 8, ffmpeg, 7-Zip, VB-Audio Virtual Cable,
ViGEmBus, a private Python venv with vgamepad, and Sunshine. On Server editions that omit
the Xbox 360 function driver, it also stages the signed Microsoft Update Catalog XUSB21
package (update `4015a39c-7c66-46bb-a5bc-db6c33ca5114`, SHA-256 checked). The NVIDIA driver must be
provided first; setup checks the existing Vulkan runtime and `vulkaninfo` for the L4.
It enables Windows Audio and AudioEndpointBuilder, selects CABLE Input for all default
playback roles, and adds application-scoped Windows Firewall streaming rules for
TCP 47984–47990/48010 and UDP 47998–48000/48010. GCP's existing owner-IP rule is required.

Downloads use upstream HTTPS distribution endpoints. Git, 7-Zip, Sunshine and ViGEmBus
resolve the current upstream release on the first installation; the cached installer
is reused thereafter. VS is constrained to the 2022 channel. VB-Cable's catalog signature
is checked before trusting its publisher for unattended driver installation. The optional
LunarG SDK is pinned to 1.4.363.0 and its published SHA-256 is checked.

`-ConfigureConsole` changes only the local `admin` account to a fresh cryptographically
random password and stores it as the Winlogon **LSA secret**, with no plaintext password
file or `DefaultPassword` registry value. The private marker prevents rotation on reruns.
The helper neither retrieves nor exports the secret. SSH public-key access remains the
management path. With `-ConfigureConsole`, setup also calls `start_console.ps1`: it
queries the console user, refuses to log off any existing user, and resets an empty
logon screen to trigger autologon without interrupting session-0 SSH uploads. On this
VM that transitioned the empty session 1 to admin's active console session 2.
`start_console.ps1` is a no-op when admin is already logged in. Setup applies 1920×1080
inside that console. A full reboot remains a separate persistence check.
Reboot only when the parent upload has completed (`C:\acr\data\UPLOAD_OK`)
and the other workers are ready. If console bootstrap is unavailable, the first install reports a console failure until reboot:

```powershell
Test-Path C:\acr\data\UPLOAD_OK
powershell -NoProfile -ExecutionPolicy Bypass -File C:\acr\units\WIN-SETUP-001\src\tools\win\verify_reboot.ps1 -Reboot
# Reconnect over SSH, then:
powershell -NoProfile -ExecutionPolicy Bypass -File C:\acr\units\WIN-SETUP-001\src\tools\win\verify_reboot.ps1
query user
Get-Process explorer | Select-Object Id,SessionId
powershell -NoProfile -ExecutionPolicy Bypass -File C:\acr\units\WIN-SETUP-001\src\tools\win\setup_vm.ps1
```

Do not delete the autologon marker or rerun console bootstrap to fix an unrelated issue.
The parent deletes the VM and its disk at closeout, which removes the VM-only secrets.

## Build environment

New shells receive the installed tools on PATH. For MSVC headers, libraries and linker
settings, dot-source the developer environment before a clang-cl build:

```powershell
. C:\acr\units\WIN-SETUP-001\src\tools\win\build_env.ps1
clang-cl --version
cmake --version
ninja --version
dotnet --list-sdks
```

`common.ps1` refreshes PATH in a shell opened before installation. See
[ASTRAL_WINDOWS.md](ASTRAL_WINDOWS.md) for runtime build flags. Build and run each unit
in its own directory; the shared private inputs are under `C:\acr\data` and
`C:\acr\work\gen{,-60fps}`. Never delete another unit's files.

## Launch in the console

`run_interactive.ps1` requires `admin` to be logged in. It registers a uniquely named
interactive-token scheduled task, launches the executable, and returns a PowerShell
object with `PID`, `SessionId`, `TaskName`, `JobDirectory`, `Stdout`, `Stderr`, and
`ExitCodeFile`. It refuses session-0-only operation and waits up to 30 seconds for a PID.

```powershell
$helpers='C:\acr\units\WIN-SETUP-001\src\tools\win'
$job=& "$helpers\run_interactive.ps1" `
  -FilePath 'C:\acr\units\MY-UNIT\build\astral.exe' `
  -WorkingDirectory 'C:\acr\units\MY-UNIT' `
  -Environment @{ NX_DATA_ROOT='C:\acr\data'; NX_NVN_REAL='1' } `
  -LogDirectory 'C:\acr\units\MY-UNIT\logs'
$job | ConvertTo-Json
Get-Content $job.Stderr -Wait
```

`Arguments` is a Windows command-line string; quote paths containing spaces. The helper
sets environment variables only in the task's process tree. Requests are stored as JSON:
**never pass passwords, keys or tokens** in arguments or environment. The PID is the
actual child executable, not the scheduled-task wrapper. `ExitCodeFile` appears after
exit and retains a nonzero application exit code. For commands run under PowerShell,
use `-File` and have that script explicitly return the application's exit code.

Stop only your returned PID and remove only your completed task:

```powershell
Stop-Process -Id $job.PID
# Wait for ExitCodeFile, then:
Unregister-ScheduledTask -TaskName $job.TaskName -Confirm:$false
```

## Desktop and audio capture

Run capture in the interactive session, not the SSH session. It uses ffmpeg `ddagrab` (DXGI Desktop Duplication) with NVIDIA H.264 encoding for video,
and a small .NET 8 helper with [NAudio.Wasapi 2.2.1](https://github.com/naudio/NAudio/blob/master/Docs/WasapiLoopbackCapture.md)
for loopback audio from the default VB-Cable playback endpoint. The source is in
`tools/win/audio_capture`; `build_audio_capture.ps1` publishes it into the private unit
directory and rebuilds only when its sources change. WASAPI omits idle audio buffers;
the helper fills those wall-clock gaps with silence to retain the requested duration,
and reports captured PCM bytes separately from padded timeline bytes.

```powershell
$job=& "$helpers\run_interactive.ps1" -FilePath powershell.exe `
  -Arguments "-NoProfile -ExecutionPolicy Bypass -File `"$helpers\capture.ps1`" -Seconds 5 -OutputDirectory C:\acr\units\MY-UNIT\capture" `
  -LogDirectory C:\acr\units\MY-UNIT\logs
```

`capture.ps1` writes `desktop.mp4`, `audio.wav`, and individual recorder logs, waits for
both recorders and fails if either process fails. `-Mode Desktop|Audio|Both` and `-FrameRate 15` are supported.
`-DesktopBackend Gdigrab` and `-AudioBackend Dshow` are optional compatibility modes;
`-AudioDevice` selects the DirectShow endpoint only. On this Server 2025 VM, DirectShow
found no usable audio output pin and GDI stalled with a visible Vulkan window; the
verified path uses Desktop Duplication/NVENC and WASAPI. `install_ffmpeg.ps1` pins
Gyan's ffmpeg 8.0.1 (SHA-256 checked) for NVENC API 13.0 compatibility with the supplied
GRID 596.86 driver. ffmpeg 9.0.2 requires driver 610.00/API 13.1; it is not the configured
capture binary. The approved driver is retained. Do not invoke it concurrently against the same output directory. This records
the entire console: keep unrelated personal content off this disposable test desktop.

`audio_default.ps1` uses [SoundVolumeView](https://www.nirsoft.net/utils/sound_volume_view.html)
to select and unmute the cable and verify the default playback role. The private
`audio-endpoints.csv` preserves device details. `test_tone.ps1` creates a 1 kHz WAV with
ffmpeg and plays it synchronously through the default device with .NET SoundPlayer.
Launch it interactively while capturing to verify the complete playback-to-cable path.

`display.ps1` applies a supported 1920×1080 primary-desktop mode (override with `-Width`
and `-Height`) using Win32 display settings. Run it through `run_interactive.ps1`, inspect
its exit code, and confirm the NVIDIA controller's reported resolution. It does not
install or substitute a software display adapter.

## Scripted Xbox 360 controller

ViGEmBus is installed independently of vgamepad so setup is unattended. The Python
client is pinned to upstream commit `3f910aa8bbde49a576683db74ad5e4a0879f8a80`
(version 0.1.3), SHA-256 checked, with `VGAMEPAD_SKIP_VIGEMBUS_INSTALL=true`.
Do not substitute PyPI 0.1.0: its wheel build runs an older bundled ViGEm installer,
which created a failed duplicate bus during this unit's initial VM testing.
`install_xinput_driver.ps1` handles the separately required Microsoft Xbox driver;
it verifies the referenced catalog and leaves signature enforcement enabled. Run the private
venv's Python and `gamepad.py`. Input is JSON lines from a file or stdin. Each line
resets the pad and applies the complete specified state, holds it for `ms`, then advances.
The pad disconnects at EOF, so use a final held state if the target needs time to observe it.

```powershell
'{"buttons":["A","LEFT_SHOULDER"],"left_trigger":255,"ms":500}
{"buttons":[],"ms":100}' | Set-Content C:\acr\units\MY-UNIT\input.jsonl
& C:\acr\units\WIN-SETUP-001\pad-venv\Scripts\python.exe `
  "$helpers\gamepad.py" C:\acr\units\MY-UNIT\input.jsonl
```

`buttons` uses vgamepad's Xbox names without `XUSB_GAMEPAD_` (A/B/X/Y, START, BACK,
DPAD_UP/DOWN/LEFT/RIGHT, LEFT/RIGHT_SHOULDER, LEFT/RIGHT_THUMB, GUIDE). Triggers accept
0–255; `lx`, `ly`, `rx`, `ry` accept signed 16-bit axes. Each output line includes the
observed `XInputGetState` slots. `--self-test` requires one newly connected slot and
asserts A (`0x1000`) and release (`0`); it fails rather than occupying an existing pad.

## Sunshine and Moonlight

Sunshine runs as `SunshineService`. The setup restricts the management UI to localhost,
sets the advertised name to `ACR Windows L4`, and selects VB-Cable for audio. Fresh UI
credentials are created on the VM and stored with machine-scope Windows DPAPI in a directory ACL-limited to admin
and SYSTEM. They are never copied back or included in reports.

From the owner's Moonlight, add the VM address allowed by GCP and request pairing.
Use its four-digit PIN from the VM's SSH session:

```powershell
& "$helpers\sunshine_pair.ps1" -Pin 1234 -Name 'Owner Moonlight'
& "$helpers\sunshine_pair.ps1" -Check # authenticated localhost API probe, no pairing
Get-Service SunshineService
Get-NetTCPConnection -State Listen | Where-Object LocalPort -in 47984,47989,47990,48010
```

The helper uses the VM-local DPAPI credentials against localhost HTTPS and reports only
whether Sunshine accepted the PIN. It does not initiate a client connection. To access
the local UI for owner troubleshooting, forward it with `ssh -L 47990:127.0.0.1:47990 acr-win`
and use `https://localhost:47990`; no additional public firewall rule is needed. Actual
Moonlight pairing and streaming require the owner's client and are a separate acceptance
step from a listening service. See the [Sunshine configuration reference](https://docs.lizardbyte.dev/projects/sunshine/master/md_docs_2configuration.html).

## Repeatable real-VM verification

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\acr\units\WIN-SETUP-001\src\tools\win\verify_vm.ps1
```

`verify_vm.ps1` writes a private timestamped evidence directory and fails on a failed
probe. It checks all script syntax and tool versions, compiles/links/runs a small Win32
program with clang-cl and the Windows SDK, tests the interactive launcher's PID/session,
environment, cwd, stdout/stderr and exit-code behavior, observes XInput A transitions
both directly and from a script, checks Sunshine listeners, runs LunarG vkcube in the
console, and captures eight seconds of desktop while a four-second default-device tone loops.
`capture_probe.ps1` starts playback and recording in the same interactive task, avoiding
scheduler delays between separate playback and recording tasks; it always stops the
synthetic tone in `finally`.
It requires at least 7.5 seconds of each recording and 90 video frames, extracts a PNG,
checks video luma is above black and checks cable audio peak above
−40 dBFS. Inspect the PNG/clip to confirm the Vulkan window; desktop luma alone cannot
identify that window. `-SkipCapture` runs the other probes only. `verify_reboot.ps1 -Reboot` refuses while `UPLOAD_OK` is absent, records the boot-time
baseline in the private unit directory, and restarts the VM. After SSH reconnects,
`verify_reboot.ps1` compares boot times and confirms console explorer, preserving
`reboot-proof.json`. Run this only after coordinating with other workers.


## WIN-SETUP-001 measured VM evidence (2026-10-20)

The real `acr-win` run at `05:44:26Z` passed `verify_vm.ps1` with driver 596.86 and
Vulkan 1.4.329 on NVIDIA L4. It compiled, linked and ran the Win32 SDK probe and verified
an interactive PID in console session 2 with the requested environment, cwd, separate
stdout/stderr and exit code 7. XInput slot 0 observed scripted A press `4096` (packet 2)
and release `0` (packet 3). A second self-test launched inside the real console
session 2 also passed (PID 2660, exit 0), so controller visibility was verified in both
SSH and desktop sessions; `console-pad-proof.json` retains the result.

The desktop clip is **1920×1080, 8.00 seconds, 119 frames (14.88 fps)**, encoded with
`h264_nvenc`. The extracted PNG was visually inspected and shows the rendered LunarG
Vulkan cube. Video luma YAVG ranged from 202.226 to 202.374. The default-device
VB-Cable loopback is **8.00 seconds**, stereo float PCM at 48 kHz, with mean −24.1 dBFS
and peak **−21.1 dBFS**. WASAPI delivered 3,053,768 PCM bytes; the timeline contains
3,072,000 bytes including idle-gap silence.

The VM evidence directory is `C:\acr\units\WIN-SETUP-001\evidence-20261020-054426`.
A private copy is retained under `.local/units/WIN-SETUP-001/evidence-20261020-054426`
in the owner's checkout, outside Git. Sunshine's service, TCP listeners
47984/47989/47990/48010, authenticated localhost API and H.264/HEVC/AV1 encoder probes
passed. Actual owner Moonlight pairing/streaming is still to be performed from the
owner's client; no client pairing is claimed by the localhost API probe.

A subsequent setup rerun returned **exit 0 in 9.045 seconds**, with **24/24 capabilities
OK** and an unchanged download-cache manifest. It invoked no package installers or
source rebuilds. The private `noop-proof.json` records that comparison.

Reboot persistence is pending completion of the parent upload; `UPLOAD_OK` was absent
at 06:45:17Z, with upload PID 9588 still active, so this unit preserved the transfer.
The VM last booted at 05:03:31.5Z; no full reboot was performed by this unit. The
private `reboot-gate-proof.json` records the final gate state. After the upload and
other worker activity finish, the parent must run `verify_reboot.ps1 -Reboot`, reconnect,
and run `verify_reboot.ps1` to complete this acceptance item. Autologon itself was proven by
resetting the empty console: it logged admin into session 2 without a password prompt.
Independent review remains the parent's responsibility under this brief's prohibition
on nested reviews; it has not been waived.
