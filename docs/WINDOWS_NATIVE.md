# Native Windows Astral startup

`tools/windows_native.py` stages a private Mac-built source package, detects the
Windows toolchain, builds the actual generated main + SDK and native Windows
runtime, and launches that executable with bounded tracing. A real guest startup
trace is required; compiler readiness or an unrelated GPU probe does not pass.
All outputs, source packages, game inputs and captures stay in ignored `.local`.
The worker never provisions, transfers inputs, signs into accounts, or changes
firewall policy. The parent handles the rented Windows cloud machine's lifecycle and transfers.

The reference is Wonder revision
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. Apply the current reviewed
`apple-memory.patch`, then `astral-bootstrap.patch`, then the isolated
`windows-native.patch`. The Windows patch selects clang-cl with the Windows SDK,
allows large generated object files, and disables floating-point contraction in
every translation unit. Shared bootstrap code is not edited by this lane.

On Mac, stage a fresh output with the current checkout, canonical imported
inputs, and accepted CPU-REGEN-020 regenerated directory:

```sh
scripts/check-windows-native stage \
  --repo "$PWD" --reference /absolute/pinned/Wonder \
  --inputs /absolute/private/astral --gen /absolute/private/regeneration/gen \
  --control-metadata /absolute/private/accepted-producer/receipt.json \
  --out "$PWD/.local/windows-native-025/stage-N"
```

The existing importer checks NSO/flat module hashes, boot metadata and NPDM.
For a reviewed runtime exposing the control validator, staging requires the
accepted producer receipt, reparses its metadata binding with the shared Mac
validator, and writes its validated private context header into the package.
Raw NSP, keys, NACP/CNMT and account context are not transferred. The pre-control
baseline revision can still be reproduced without the control option.
Staging hashes every runtime and generated file and records the wrapper/runtime
revision and patch hashes. The ZIP excludes `.git`, keys, NSP/NCA, account data
and authentication. It includes `data/analysis/main.bin` and `sdk.bin` for actual
startup. The small startup package omits the 9.6 GB RomFS; if guest execution
reaches asset loading, the parent must transfer only the required owned inputs
and verify their hashes. No substitute asset or success stub is introduced.

Give `transfer-request.json` to the parent. The parent verifies the ZIP SHA-256
and member manifest, extracts into a fresh task-owned directory, logs out old
remote account authentication, and announces SSH readiness and a hard stop.
Do not repeatedly probe a machine that is Off. No GitHub or Codex authentication
is needed by the remote build.

In an x64 Visual Studio developer environment on Windows:

```powershell
python C:/acs-units/WINDOWS-NATIVE-025/package/driver/windows_native.py probe
python C:/acs-units/WINDOWS-NATIVE-025/package/driver/windows_native.py run `
  --package C:/acs-units/WINDOWS-NATIVE-025/package `
  --out C:/acs-units/WINDOWS-NATIVE-025/run-N `
  --deadline 2026-10-18T16:32:04Z --seconds 1800 --jobs 3 --launch-seconds 30
```

Replace the example deadline with the parent's current observed paid-window
hard stop; the driver reserves 15 seconds before it. `probe` checks PATH for
Python, clang-cl/MSVC, CMake and Ninja, the Windows SDK developer environment,
and installed Vulkan SDK directories. It performs no installation or download.
Use the installed Visual Studio `VsDevCmd.bat -arch=x64 -host_arch=x64` before
running if the SDK/libraries are not on PATH. If missing, the parent/worker may
install only the explicitly authorized bounded official vendor tools; installations
and their result must be separately recorded. The native upstream Windows backend
uses Win32/XInput/XAudio2 and loads the GPU driver's Vulkan loader; it does not
need SDL3. Vulkan headers are still required for compilation.

The driver refuses empty or incomplete compile graphs, mixed strict/compiler
flags, objects outside the fresh build, and object reuse. It records every
object hash, the EXE SHA-256/size, tool executable hashes, compile graph hash,
exact stage arguments, selected launch environment, exit codes, timeouts and
log hashes. Post-run package identity is checked again. Configure, compile and
launch share a bounded time budget. Log output is bounded; the small polling
interval allows limited overshoot. On Windows, timeout cleanup invokes
`taskkill /PID <owned pid> /T /F`; it never kills by image name. Detached children
after a normally exiting process are not independently enumerated, so global
process absence is not claimed. A network disconnect does not itself cancel
the remote process; the remote driver and parent's deadline controls remain
necessary.

`guest_executed` means the actual boot trace reached SDK `nn::init::Start`.
It does not mean `nnMain`, a rendered frame or gameplay. A fatal strict service
request remains visible as the startup boundary and actual nonzero guest exit.
Presentation, input, audio and capture remain unverified until measured with
the actual guest. The receipt never turns a host probe into gameplay evidence.
Server 2025 results do not establish Windows 11 acceptance.

Offline verification uses only temporary synthetic files and actual local
subprocesses, including paths with spaces, timeout/log-limit intervention,
background-child cleanup on POSIX, compile-graph checks, and input tampering:

```sh
python3 -m unittest discover -s tests -p test_windows_native.py -v
git diff --check
```

Independent exact-head review and landing belong to the parent. The Windows
worker does not start a nested reviewer, push, or create a PR.

## Observed baseline on 2026-10-18

Actual Windows native compilation and guest execution passed at runtime revision
`038a6091b3f51c370c598a467635dc60bc93c596`, with the Windows patch SHA-256
`a10a948a55ddfdeb558d44fde0a6c68e69e5ea09c300b0d1ff2cde1389fb8b2c`.
This is a partial startup result, with no gameplay claim.

The initial parent-verified ZIP was 151,730,198 bytes, SHA-256
`a5cb25fb8858c38ed35d7436dd2b243aa4f01cd300050fb1a34650519bb6fccb`.
It held 449 prepared source files, 319 regenerated files, the two flat modules,
and the original helper. Its manifest SHA-256 was
`1f2c0edcf0e4ff3fc4d57b4a81a4555500737bc0b7f2a9414ad7dcf0529e4500`.
The helper in this baseline ZIP had SHA-256
`f2acf7f6cbec52aa500d202864718a6c20b850ed618b9ac95543fa23330544c1`;
the private command plan explicitly set `NX_LOG` to the owned run output.
The later helper sets this itself and adds PE architecture verification and
metadata-aware Mac staging. Baseline inputs were unchanged before/after launch.

The Server 2025 probe found only a WindowsApps Python alias, with no compiler,
CMake or Ninja on PATH and no standard Visual Studio, Windows SDK or Vulkan
SDK installation directories. A bounded official installation succeeded from
15:39:34Z to 15:41:34Z, without remote account authentication. Python 3.12.10's
[official embeddable package](https://www.python.org/downloads/release/python-31210/)
and the Microsoft bootstrapper passed Authenticode checks. The installed
[Microsoft components](https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-build-tools?view=vs-2022)
were x64 build tools, Clang, CMake and Windows SDK 26100. Vulkan-Headers came
from the dependency-lock commit's official Khronos archive; no full Vulkan SDK
or SDL installation was needed. The resulting tools were clang-cl 19.1.5
(target `x86_64-pc-windows-msvc`), CMake 3.31.6-msvc6 and Ninja 1.12.1.

| Actual stage (UTC) | Elapsed | Exit |
| --- | --- | --- |
| Configure 15:42:55.414–15:42:59.036 | 3.625 s | 0 |
| Fresh build 15:42:59.362–15:49:05.144 | 365.782 s | 0 |
| Guest 15:49:05.562–15:49:05.839 | 0.281 s | 1 |

All 395 target objects were compiled and hashed; no objects were reused.
The actual EXE is 67,761,664 bytes, SHA-256
`d9884d39fa9bd76d9335f87b6ca589675368b2d0370b38a209d04006c027bbe8`.
A fetched copy matched the remote identity and the current PE verifier confirmed
AMD64 / PE32+ with seven sections. No timeout or log-limit intervention occurred.
The actual trace entered SDK `nn::init::Start` and reached the strict boundary:
`FATAL: strict IPC missing command: service=IParentalControlService command=1`.
No renderer/presentation, input, audio, capture, save or gameplay is established.

Compact receipts, exact compile commands, logs and their checked member hashes
are retained in this worktree's ignored `.local/windows-native-025/remote/run-01/`.
The executable is retained separately in the ignored parent directory and on the
saved Windows machine. Receipt SHA-256 is
`429871453048b67b50604ab92e7173e4575453907df958699e7d99d06318ae72`;
guest trace SHA-256 is
`d9f355be9d75981526102edd3990341a3cfb07cb98bb2a059c6ee53d840fdacb`.
These are guest-startup evidence, not a host graphics probe. Parent still owns
independent exact-head review, refreshed input transfers and provider stop.

The current committed helper API was also executed on Windows at
15:56:13Z against the hash-verified baseline EXE. This was a launch repeat,
with no recompilation. Helper SHA-256
`89f4e5825f1b74bd2b7895f46d9706e8ad0e5c0e58dfbc8eb24b77f4d08d2f82`
belongs to `1cbdc17a50d930a85231a27411f68216cf56e323`. Its PE verification
returned AMD64/PE32+; the bounded launch exited 1 after 0.125 s at the same
parental-control command-1 boundary. Artifact and input hashes were unchanged,
and the repeat trace had the same SHA-256 as the first launch. This directly
checks the shipped PE and subprocess APIs without claiming another build.

## Reviewed control refresh

After independent review and landing of CONTROL-RUNTIME-024 at
`7ee38dabbefbecb75b3814103e6e13bb0babc27b`, this worker rebased and staged
runtime revision `143e234dae3026ddd0d1aa648184aafb4cfda590`. Mac preparation
validated producer receipt SHA-256
`f4421237f6365a6252834b6e64a00f575a1d28da515d8b53e8efbce4f92eac88`.
The package contains 450 prepared files, including the validated private control
header, and the same 319 regenerated files and two flat modules. No raw control
metadata or keys were transferred. The parent copied the baseline package to a
new directory and applied a 66,752-byte, eight-member delta, SHA-256
`89a00bfd22e5c7709a76d48db4b662f25dc1faadc57c33ae754877eec1d65cc9`.
The final package manifest SHA-256 is
`b5944f48427b9fb4842a18240a30f36097d98acd8feeb27a0142b0e5fd8b7b03`.
The parent explicitly granted a 16:20Z worker deadline inside the existing
16:32:04Z provider hard stop. The original package and outputs were preserved.

The shipped helper's complete `run` CLI performed a second fresh build, with
**395 hashed objects and zero object reuse**. Configure ran
16:01:07.303–16:01:10.649Z (3.344 s, exit 0); compile/link ran
16:01:10.984–16:07:16.842Z (365.844 s, exit 0). The EXE is **67,765,760 bytes**,
SHA-256 `47972ae70f4bd923e5a591a36878464142693e5989c50820d677b308f562492d`.
Both the driver and the fetched-copy verification identify AMD64/PE32+, seven
sections. Every package file was unchanged after execution.

The actual guest ran 16:07:17.255–16:07:17.477Z, exited **1** in **0.219 s**,
without timeout or log-limit intervention. It entered SDK `nn::init::Start`,
then logged authenticated parental Initialize for PID 1 and program
the game's title ID, with account policy explicitly unknown. The next boundary is
`FATAL: strict IPC missing command: service=ILogger command=0`.
SDK/main constructor completion, real game frames, presentation, input, audio,
capture and gameplay remain unverified. LOGGER-RUNTIME-029 is separate work;
this Windows unit does not add service success stubs.

Final receipt SHA-256:
`9e5fc35a01fe94f5d298b71940608661ca60f23d01c0d46d278e5aea87a8a99c`.
Final trace SHA-256:
`fd8e2598e6168aa4275458916654fcb59b0e519dfb7a4ab9bd2d547009a5fe83`.
The checked compact evidence ZIP is 85,604 bytes, SHA-256
`b5834c653a992ab7a1dbced805e89c43d334c2149ecee59978dcaf1366ec1ce8`.
Its verified contents are retained in `.local/windows-native-025/remote/run-02/`;
the actual EXE is retained as `remote/astral-run-02.exe` outside Git. At
16:08:43Z all six recorded stage PIDs were absent; this limited observation does
not enumerate detached descendants. Both EXEs and compact evidence were fetched
and hash-verified before notifying the parent to stop the saved machine. The
worker performs no provider stop or remote account action. Exact-head independent
review and landing remain the parent's responsibility; review is not waived.
