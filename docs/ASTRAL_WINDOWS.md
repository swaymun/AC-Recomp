# Astral Chain on Windows (x64)

`runtime/patches/astral-windows.patch` makes the Linux runtime series build and run on Windows x64 with clang-cl. It
applies after the whole of `runtime/patches/series.linux` and `windows-native.patch` (the clang-cl policy);
`runtime/patches/series.windows` is that list, and `tests/test_astral_windows.py` keeps them in step. macOS is
unchanged (`series.macos` lists neither patch) and so is Linux: every change is in the Windows-only CMake branch,
`platform_win.cpp` (built only on Windows), a `_WIN32` branch, or a condition extended by `|| defined(_WIN32)`.

## What the overlay changes

| file | change |
|---|---|
| `runtime/src/hle_fiber.cpp` | The fiber bridge (`docs/ASTRAL_FIBER_CONTEXT.md`) on Windows x64 uses Win32 fibers instead of an assembly stack switch. Each guest fiber continuation is `CreateFiberEx(64 KiB commit, 8 MiB reserve, FIBER_FLAG_FLOAT_SWITCH)`; the thread itself becomes the root continuation on its first switch (`ConvertThreadToFiberEx`, or `GetCurrentFiber` if it already is a fiber). `SwitchToFiber` saves the MS x64 callee-saved state (rbx rbp rdi rsi r12-r15, xmm6-xmm15, MXCSR, the x87 control word) and keeps the TEB stack base/limit, the SEH chain and fiber-local storage right, so stack probes and exceptions work on fiber stacks. Retired continuations are freed with `DeleteFiber` (never the running fiber or the root). Dispatch, validation and finalisation are unchanged. |
| `runtime/src/kernel.cpp` | `fiber_retire_thread()` is the real one on Windows too (a thread that exits on a fiber switches back to its root first). |
| `CMakeLists.txt` | The Windows branch builds `hle_fiber.cpp` (without it, `nn::os::SwitchToFiber` runs the lifted dispatcher, as on Linux before its overlay). With `-DNX_HWOPUS=ON`, Windows takes libopus from its own CMake package (`find_package(Opus CONFIG)`, target `Opus::opus`) instead of pkg-config. |
| `runtime/src/nvn/nvn_caps.cpp` | The upload ring defaults to host-cached memory on Windows as on Linux (discrete GPUs; `NX_RING_CACHED=0` restores the plain type). |
| `runtime/src/platform_win.cpp` | `sleep_ns` waits on a high-resolution waitable timer (`CREATE_WAITABLE_TIMER_HIGH_RESOLUTION`). `std::this_thread::sleep_for` rounds up to the 15.6 ms system tick, which would stretch the 60 Hz vsync thread (`hle_vi.cpp`) to about 31 ms. |

The headless path without a window surface, the host-cached ring and texel-write coalescing come from the Linux overlay
and `astral-texel-coalesce.patch` and apply unchanged.

## Dependencies (tested: Windows Server 2025, x64, NVIDIA L4)

- Visual Studio 2022 Build Tools with the C++ workload and its clang-cl (19.1), CMake and Ninja; the Windows SDK.
- A Vulkan 1.3+ driver (`vulkan-1.dll` comes with it) and the Vulkan headers at the `tools/acr_build.py` pin.
- libopus 1.3+ built with CMake: `cmake -S opus -B opus-build -G Ninja -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_C_COMPILER=clang-cl -DOPUS_BUILD_SHARED_LIBRARY=OFF -DOPUS_DISABLE_INTRINSICS=ON` and `cmake --install`
  (clang-cl does not compile opus 1.5's SSE4.1 sources without per-file target flags, hence no intrinsics).

`tools/acr_build.py` now has a native Windows mode. With private inputs prepared
on the Mac, copy its platform-independent output (`<out>/work/gen`, the data root
with `analysis`, `exefs`, `extract`, `spirv`, `astral.profile`, `shared-fonts`) to
Windows and use its existing-input options. Keep keys on the Mac and all generated
outputs private. The desktop overlay adds an SDL3 dependency: supply `SDL3_DIR`
as described below. The builder's app-copy stage currently copies executables
and launcher assets but omits SDL3.dll; until that separate integration is fixed,
copy the DLL and its licence from the SDL archive into the private player folder.

## Build

From a "x64 Native Tools" prompt (`VsDevCmd.bat -arch=x64`), with the source prepared as on Linux but from
`series.windows`:

```bat
cmake -S runtime-src -B build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang-cl ^
  -DCMAKE_CXX_COMPILER=clang-cl -DNX_GAME=astral -DNX_GEN_DIR=<gen> -DNX_HWOPUS=ON ^
  -DOpus_DIR=<opus prefix>/lib/cmake/Opus -DNX_VULKAN_SDK=<dir with include/vulkan> ^
  -DSDL3_DIR=<SDL3 VC archive>/cmake
cmake --build build --target astral
```

406 steps, about 5 minutes on the test machine. Warnings only.

## Run

```bat
set NX_DATA_ROOT=<data root>
set NX_NVN_REAL=1
set NX_NVN_FORMAT_PROFILE=<data root>/astral.profile
set NX_SHARED_FONT_DIR=<data root>/shared-fonts
build\astral.exe
```

Headless: add `NX_HEADLESS=1` (a hidden window, no swapchain) and `NX_DUMP_FRAMES=<n>` to write every n-th frame to
`<data root>/frames/NNNNN.ppm`. Writing a frame takes about 0.6 s there, so a dumping run shows a lower frame rate.

## Status (2026-10-19, Windows Server 2025 cloud machine, NVIDIA L4, headless)

- Boots through `nn::init`, the NVN device, RomFS, hwopus and the fiber switch, with no fatal.
- Renders the boot sequence, the title screen (the title movie with the ZL+ZR prompt) and, after a scripted ZL+ZR
  press, the save check, the loading screen and the **opening cutscene** (characters, subtitles, effects). Frames were
  compared by eye with the macOS build. 110 s runs ended by the time limit, not a crash.
- **30 fps** (the game's cap) on the title screen without frame dumping: replay ~7 ms, fence wait ~5 ms, other ~5 ms
  per frame, about 34 MB of uploads a frame. Working set steady at about 1.0-1.1 GB.
- The whole RomFS is needed past the title: with `pl/` not yet copied, the game crashed on a null player object right
  after ZL+ZR (a guest null dereference, not a runtime fault); with it present the opening plays.
- Not yet done: a windowed run with a swapchain on a desktop session; audio (headless runs are muted); real gamepad
  input (XInput is wired but only `NX_INPUT_SCRIPT` was exercised); an `acr_build.py` Windows mode.

## Desktop validation overlay

`astral-windows-desktop.patch` is last in `series.windows`. For Astral it builds the
existing SDL3 launcher and shared binding/settings code on Windows. The game retains
its Win32 window, Win32 Vulkan surface, XInput polling and XAudio2 output. The host
converts the first active XInput slot to the shared positional-button/axis frame
(first connected when every pad is neutral),
so `controls.ini` affects gameplay as well as launcher navigation. Keyboard sampling
is restricted to the game window. SDL is initialised before the launcher; PLAY
destroys the launcher before the game window is created.
The Windows audio host treats an unset, empty or `0` `NX_MUTE` as audio enabled;
`1` still mutes, and headless runs still use the timer without a device. Previously
any present `NX_MUTE`, including `0`, suppressed the device despite the launcher
showing that override as Off. The CPU fixture covers these flag combinations.

Windows uses a CRT environment adapter for the launcher's settings, discovers its
executable with `GetModuleFileNameW`, recognises `astral-60fps.exe`, and starts the
selected sibling with `_wspawnv(_P_NOWAIT)`. The parent waits on the returned
process handle and forwards the full DWORD exit status; a child exit of
`0xFFFFFFFF` is distinguished from a spawn failure. Install paths remain UTF-8
through sibling discovery, then become UTF-16 for process creation; arguments
are quoted using the Windows CRT rules (including quotes and trailing slashes).
This is a parent/child transition; measure the directly launched game
binary for working-set measurements. The optimized CMake variant-object target is
still disabled on Windows: build both generated trees separately and place the
second executable beside `astral.exe` as `astral-60fps.exe`.

`tools/win_validate.py stop` tracks the waiting launcher and its direct FPS child.
New launch receipts persist the original PID, executable, console session and UTC
creation ticks, including after helper-publication recovery. Stop compares that
saved identity before terminating anything. Legacy receipts without creation time
are refused; do not fill it from a current process snapshot, which could belong to
a later launch with the same PID, path and session.
It matches parent PID, console session, creation time and the exact sibling
executable path inside this unit's directory. It stops the launcher first, then
inventories again to catch a child spawned during shutdown. Each termination
rechecks identity while holding a process handle; it waits for exit and verifies
that no matched game remains before removing the scheduled task. Other launches,
other unit paths and helper executables are preserved. If the launcher is already
absent but a possible orphan remains, ancestry cannot be verified from the old
receipt: the command fails and retains the task rather than claiming cleanup.
PID reuse, denied termination and surviving children also fail without removing
the task. The WIN-VALIDATE-003B regression run passed 29 offline driver tests,
including fake-SSH subprocess execution, shutdown races and peer isolation.
This follow-up did not rerun the game or execute the new stop path on Windows;
the desktop measurements below remain the earlier retained evidence.

Manual source preparation must also install the generated, verified
`runtime/src/astral_control_context.h` from the private control receipt, as
`acr_build.py` does. Applying patches alone omits this input and boots to
`FATAL: logger: missing live process`. When adding it to an existing manual build,
force `kernel.cpp` to recompile: an earlier negative `__has_include` check does not
create a Ninja dependency on the missing file. Never invent control metadata.

Add SDL3 to the dependencies above. The validation build uses the official
[SDL 3.4.18 VC development archive](https://github.com/libsdl-org/SDL/releases/tag/release-3.4.18),
`SDL3-devel-3.4.18-VC.zip`, SHA256
`78d84602ae616cfe26b33a73b7d3b9b6b56e8a6650e53d92c9c6ca938f747acd`.
Extract it privately and add `-DSDL3_DIR=<SDL3-3.4.18>/cmake` to the CMake command
(or set the `SDL3_DIR` environment variable). The post-build step copies SDL3.dll
beside the executable; distribute that DLL and its licence with private player
packages. Copy `assets/launcher` beside the player, or set `NX_ASSET_DIR`.

### Mac-driven VM workflow

`tools/win_validate.py` uses only Python's standard library and SSH. It never
provisions a VM, reads credentials, invokes `NX_INPUT_SCRIPT`, or launches a game
on the Mac. Its default output is the ignored owner-checkout directory
`.local/units/WIN-VALIDATE-003/`. Remote writes and executable launches are restricted
to `C:\acr\units\WIN-VALIDATE-003`. `prepare` creates junctions to read-only inputs;
settings, logs and fresh profile saves remain in this unit's own data root.

```sh
python3 tools/win_validate.py preflight
# Require complete private input uploads before gameplay; UPLOAD_OK is the parent's marker.
python3 tools/win_validate.py prepare
python3 tools/win_validate.py launch --exe 'C:\acr\units\WIN-VALIDATE-003\build\astral.exe' --launcher
python3 tools/win_validate.py capture --seconds 5 --name launcher-proof
python3 tools/win_validate.py status launcher-proof
python3 tools/win_validate.py pad /private/path/one-observed-menu-step.jsonl --name menu-step
python3 tools/win_validate.py status menu-step
python3 tools/win_validate.py capture --seconds 45 --name chase
python3 tools/win_validate.py sample --seconds 600 --interval 10
python3 tools/win_validate.py collect 'C:\acr\units\WIN-VALIDATE-003\chase'
python3 tools/win_validate.py collect 'C:\acr\units\WIN-VALIDATE-003\nx.log'
python3 tools/win_validate.py audio /private/path/chase/audio.wav
python3 tools/win_validate.py logs /private/path/nx.log
python3 tools/win_validate.py stop game
```

The helpers in [ASTRAL_WINDOWS_VM.md](ASTRAL_WINDOWS_VM.md) must already be installed.
Capture and controller jobs run in the console session. The driver parks the mouse
outside the game before restoring focus, and sets the SDL background-controller
hint for launcher validation because scheduled tasks can steal focus. Allow at
least 15 seconds after connecting a new virtual pad for SDL hot-plug discovery
(the default `pad --settle-ms 15000`; direct in-game XInput needs only 1000). Each command creates a
local JSON receipt with the actual child PID, console session, stdout/stderr and
exit-code file. `status` preserves nonzero application exit codes; a successful
SSH command is not a successful recorder. Check recorder completion before collecting
media. Large script writes use bounded byte chunks because Windows OpenSSH rejects
oversized encoded commands before PowerShell starts. For a static menu use `still --name menu`: it records one Desktop Duplication
PNG without waiting for new desktop frames. `stop` checks executable path and session before stopping the returned PID
and unregistering its own scheduled task. Launch refuses while another desktop `astral`
process is running. Record other headless runs/builds when interpreting timings. Retain evidence before restarting; the runtime rotates `nx.log`.

Pad files are JSON lines of complete Xbox states, built in Python rather than
shell-quoted ad hoc. For example, after visually confirming the title prompt:

```python
import json
states = [dict(ms=1000), dict(left_trigger=255, right_trigger=255, ms=500), dict(ms=2000)]
with open('title.jsonl', 'w') as f:
    f.writelines(json.dumps(s) + '\n' for s in states)
```

Default Nintendo layout: Xbox **B** confirms (Switch A), Xbox **A** backs out
(Switch B). `pad --normalise` waits for pad enumeration, then sends three back/release pairs for an already
identified nested menu. It is not safe to treat that as scene recognition. Observe
a capture between route stages; wall-clock input sequences can desynchronise during
asset loading. Drive ZL+ZR, save check, name entry, intro and File 01 separately.
The software keyboard currently supplies `NX_PLAYER_NAME`, not a Windows text-entry UI.

The audio analyzer reads PCM16 and WASAPI float32/extensible WAV directly, reporting
RMS, dBFS, peak, individual full-scale sample count and longest all-channel silence
at −60 dBFS. Listen to establish music/SFX identity. `logs` retains individual
300-present FPS windows, swapchain creation and fatal/audio-device lines. Frame
counts without a successful swapchain or an inspected scene do not establish
windowed gameplay. Working-set output reports regression slope, range and duration;
a trend by itself cannot prove the absence of a leak. Starting a new soak removes
the previous summary; an interrupted run retains its samples without a stale
success summary.
The log analyzer reports memory-guard terminations separately from fatal/exception
lines; a guarded exit must not disappear behind a zero fatal-line count.

Offline checks:

```sh
python3 -m unittest discover -s tests -p 'test_astral_windows.py'
python3 -m unittest discover -s tests -p 'test_win_validate.py'
```

The overlay test composes the complete pinned series and executes a CPU fixture for
nonzero-slot XInput conversion, all buttons, stick extremes/polarity, triggers,
remapping and repeated save/reload. Native Windows fixture coverage requires
`NVN_REFERENCE`, `NX_SDL3_INCLUDE` (the directory containing `SDL3`),
`NX_SDL3_LIB` (containing SDL3.lib), SDL3.dll on PATH and clang-cl in its developer
environment. Skips are explicit; these fixtures do not accept desktop gameplay.
Independent review of this unit belongs to the parent; the brief forbids nested
reviews. It has not been waived.

### Desktop validation observations, 2026-10-20

These are partial acceptance results from `acr-win` (Windows Server 2025,
NVIDIA L4, GRID 596.86 WDDM, licensed RTX Virtual Workstation), not release
acceptance. Evidence stays private under `.local/units/WIN-VALIDATE-003/` on the
Mac and `C:\acr\units\WIN-VALIDATE-003` on the VM. No owner saves were used.

The native Win32 game created a 1600×900, three-image MAILBOX Vulkan swapchain.
Before gameplay, all 8,701 private RomFS files (10,309,045,725 bytes) matched the
Mac input snapshot by SHA256; `input-hash-receipt.json` records zero mismatches.
The ViGEm Xbox controller drove title ZL+ZR, the initial save, character/name
entry and File 01's motorcycle chase. XInput receipts include nonzero slots;
`NX_INPUT_SCRIPT` was never set. The software-keyboard fallback supplied the
seven-character name `Windows`. Launcher settings (windowed, 1600×900, HUD,
audio enabled) and a controller remap were inspected after restart. The fresh
profile's Slot A reappeared as File 01 Startup, Casual, play time 1:08; choosing
Load resumed the opening sequence. A later updated save is recorded below.

`chase-30fps/desktop.mp4` records 45 seconds (1920×1080 desktop capture,
674 frames at approximately 15 capture fps). This is capture rate, not game FPS.
Its 48 kHz stereo loopback `audio.wav` contains 2,160,000 frames: RMS
0.126023 (−17.991 dBFS), peak 0.916504, zero clipped samples, longest
all-channel silence 0.028354 seconds at −60 dBFS. The runtime opened its real
48 kHz stereo XAudio2 device through VB-Cable. Music/SFX identity still requires
listening; non-silence alone does not establish that gate. The agent could inspect
the video but could not audition audio in this harness.

The clip ran from 07:52:06Z to 07:52:51Z and belongs to this unit's PID 4028;
that process crashed later, at 07:56:01Z. `chase-provenance.json` separates it
from a peer that acquired the desktop after the crash. `excluded-peer-window.png`
is deliberately excluded from acceptance. The clip predates the subsequent
audio/cache-series synchronization and launcher exit/path fixes; preserve its
binary identity instead of calling it a capture of the final source.

Open defect: after fresh-profile chase play (rapid fire, alternating left/right
movement and evade), continuing the run threw C++ exception `e06d7363`.
`chase-30fps-crash.log` was symbolized during that run; the resolved stack passes through
`__scrt_throw_std_bad_alloc`, `operator new`, `nvn::replay::written_bind`,
`build_sets`, `dispatch_call`, `replay_list` and `gpu_submit`. The reported
private commit was approximately 6.5 GB, below the 8 GB guard. The allocation
size and system commit at the exception were not recorded, so neither a leak
nor Windows-specific causation is established. Reproduce with the retained
fresh-profile route and chase pad script; investigate that allocation before
accepting a long gameplay soak. Do not conceal it with a dropped dispatch.
The original map was overwritten by a later collection. The preserved
`package-active-pad-astral.map` belongs to the later build, not this old exception;
do not use it to resymbolize the old addresses. The resolved stack above was
recorded before that overwrite.

The legacy 60 fps sibling did launch in the window, with interval 2 changed to
1 and zero subsequent interval-2 requests over 600 presents. Street-title
performance was approximately 16.5–18.2 fps at the default renderer settings;
`NX_PIPELINED=1` also remained around 18 fps. This fails the about-60-fps gate.
Peer headless gameplay and compilation overlapped; the VM reached 100% CPU.
These observations establish actual slow presentation, not an isolated GPU
benchmark. Do not infer 60 fps from the selected binary or interval alone.

The second diagnostic (`NX_PIPELINED=1 NX_REPLAY_THREAD=1`) also failed the
60 fps target. Its title run recorded 225 60-frame windows, median 21.6 fps;
the final 20 averaged 23.57 fps. Neither diagnostic changes the Windows default.
The title soak ran 601.751 seconds with 49 working-set observations,
1,597,329,408 bytes first and 422,420,480 last, no crash. A parallel private-byte
sample spanned 597.725 seconds: range 4,448,710,656–4,490,866,688 bytes,
regression −0.456 MiB/min. This is evidence of a stable title scene, not a
replacement for the failed chase soak. Files use the `async60-` prefix.

A subsequent desktop run reproduced ignored input with an idle XInput slot 0
and this unit's virtual pad in slot 1. The overlay now prefers the first pad
with buttons, triggers or stick activity outside the deadzone; neutral pads
fall back to the first connected slot. The CPU fixture exercises an idle slot 0
alongside all slot-2 button, trigger and stick cases. No other unit's controller
or service is disconnected to obtain a test slot. The native desktop regression
then held an owned neutral controller in slot 0 and drove ZL+ZR through slot 1;
`active-second-controller-menu.png` shows the resulting Load menu, with matching
two-controller XInput receipts. `package-active-launcher.png` shows the launcher
loading its font/background from the private player's own assets folder.

`pipeline-memory-summary.json` records 50 working-set observations over
602.205 seconds while traversing title, save-load menus and the opening:
942,170,112 bytes first, 557,367,296 last, range 493,928,448–1,907,580,928,
regression +27.581 MiB/min. Scene loading makes this a mixed-workload trend;
it does not pass a stable gameplay/no-leak soak. The contemporaneous system
snapshot recorded 24.80 GB committed of a 35.43 GB limit and a full 1 GB
pagefile. Preserve private-commit and system context rather than reading a
falling resident working set as proof that allocations were freed.

The updated private player repeated the full route and cleared **File 01 Hot
Pursuit**, score 1,800 (`package-chase-soak-end.png`). The 45-second repeat is
`package-chase/desktop.mp4` (657 captured frames, nominal 15 fps, 1920×1080)
with `package-chase/audio.wav` (48 kHz stereo, 2,160,000 frames). Its RMS is
0.108032 / −19.329 dBFS, peak 0.750824, zero clipped samples, longest silence
0.401375 seconds at −60 dBFS. Inspected frames at 5, 20 and 35 seconds show the
bike moving/evading and the Rapid Fire/Move/Evade prompts responding. The game
itself was only about 6–7 fps during capture, later 10–11 fps, with peer games
and compilation overlapping. This is controlled gameplay evidence, not a
playable-frame-rate acceptance claim.

`package-chase-provenance.json` ties that repeat to console-session-2 PID 4744
and executable SHA256
`afa41d6c337171188b8dbfd14e411d3ef10d99e7b25bf6c4458740d3c6c5ede5`.
The repeat includes the synchronized audio/cache overlays and active-pad fix;
it predates only the final `NX_MUTE=0` host fix. That flag was unset during the
repeat. `active-pad-source-equality.json` records 472 matching runtime files.

The chase working-set sample completed 601.706 seconds with 50 observations:
789,393,408 bytes first, 503,025,664 last, range 477,753,344–789,393,408,
regression −21.201 MiB/min. **The no-leak/stability gate still fails.** Shortly
after the CLEAR screen, private bytes rose and the unchanged 8 GiB guard
terminated the player with exit 3. Last live samples: 8,233,504,768 and
8,211,378,176 private bytes; system commit 23.25–23.53 GB of a 35.43 GB limit.
The next observation at 10:06:13Z found the game gone. The log says
`memory: 8.00 GB is over the 8.0 GB limit (NX_MEM_LIMIT_GB): stopping`.
Reproduce by loading the retained fresh profile, completing Hot Pursuit using
the 600-second XInput pad file, and leaving the CLEAR screen open. Inspect
allocation/resource lifetime across that transition rather than increasing the
guard. `package-memory-guard-exit.log`, `package-chase-late-memory.json` and
`package-memory-context.json` retain the distinction between resident memory,
private commit, system commit and process exit. This differs from the earlier
`std::bad_alloc` exception; neither defect is claimed fixed.

WIN-MEM-036 found that the memory overlay was never in `series.windows`. Its
[rebased integration and allocation/commit counters](ASTRAL_WINDOWS_MEM.md#win-mem-036-integration-and-attribution-follow-up)
are now included after the desktop overlay, with the memory repairs opt-in
until the normal-guard chase/combat gates pass. The guard still defaults to
8 GiB. The historical stop above remains a failed stability gate; patch
composition and portable lifetime tests do not replace native memory measurements.
WIN-MEM-036B reproduces the stop on the fresh L4 default and eight-switch candidate.
Streamed uploads reduce staging but do not alone pass the guard: live decoded
images still grow through the transition. The opt-in cold ASTC image-cache trim
has survived six 600-second normal-guard memory windows on the L4 (three per
build), but a candidate peak of
7.930 GiB leaves only 72 MiB below the guard. Complete following-combat coverage
and comfortable headroom remain unproven. No default-on memory or performance
promotion is claimed; see the [continuation's measurements and limits](ASTRAL_WINDOWS_MEM.md#frozen-head-route-measurements).


The game wrote `GameData.dat` and a new rotating `SlotData_1.dat` at 10:05:19Z,
before that guarded exit. Restart displayed **UI Slot A**, File 01 Startup,
name Windows, play time 25:46 and the 10:05 timestamp (`final-save-slots.png`).
`SlotData_1.dat` is a backing file, not UI Slot B; the latter remains empty.
The saved files and hashes are retained under `save-after-chase/` and
`save-after-chase-metadata.json`.
Loading that updated Slot A restored the on-foot scene after the chase, objective
“Meet up with Akira,” 600/600 health and the Medicine reward
(`final-restored-on-foot.png`). This verifies progress reload rather than only
recognition of a save-file header.

The final host build also exercised `NX_MUTE=0` against the real VB-Cable sink:
`mute-zero-audio/audio.wav`, 10 seconds, RMS −30.100 dBFS, peak 0.508362,
zero clipped samples, longest silence 0.185917 seconds. Its log reports device
output rather than timer-only pacing. Both variants linked successfully;
that prepared/native runtime comparison matched all 472 files.
These recordings still need a human music/SFX and glitch audition.

Closeout rebased onto main's later Windows audio callback/completion changes.
The desktop overlay was recomposed around those changes, retaining its active-pad
and mute-flag behavior. The recordings and guard failure above predate that later
callback baseline: they are retained evidence, not a full chase/soak acceptance
of the final rebased audio stack. Repeat those gates after integration.
Both variants rebuilt after that rebase. All 473 final runtime files matched
the prepared source. Native fixtures again passed 8 tests with one skip. A
five-second final-stack desktop smoke (`closeout-window.png`, `closeout-smoke/`)
showed the windowed title, a successful swapchain and real device audio with
`NX_MUTE=0`: RMS −32.567 dBFS, peak 0.294617, zero clipped samples, longest
silence 0.048438 seconds. This short smoke does not replace the chase/soak gates.

The exact Mac verification commands passed (8 Windows-overlay tests, two
native-only skips; 19 driver tests). The supplemental native Windows run passed
8 tests with one portable-fixture skip, including real Win32 fiber continuation,
settings/remap rewrite and reload, Unicode/spaced install paths, argument
quoting and full child-exit forwarding. Those are CPU/native fixtures rather
than substitutes for the recorded desktop route.
