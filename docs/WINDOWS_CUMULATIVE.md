# Cumulative native Windows startup

The existing `scripts/check-windows-native stage/probe/run` interfaces remain in
use. Omitting `--profile` preserves the three-overlay `windows-native-v1`
baseline and the exact stage command in [WINDOWS_NATIVE.md](WINDOWS_NATIVE.md).
Explicit `--profile windows-cumulative-v1` selects a closed, hash-frozen profile.
There is no arbitrary overlay path or custom profile option.

The cumulative order is Apple memory, bootstrap, control importer, SQSHL,
notifications, APM, audio, IPC receive framing, HID, applet storage, Windows.
The importer/SQSHL patches preserve preparation-tool provenance; accepted
regeneration is consumed rather than rerun. Every patch hash is frozen in
`CUMULATIVE_HASHES` in `tools/windows_native.py`. AM044 independently passed at
`df2c57ba8a2a6af47d7f5adc6a62e87a64fd7aca`; HID045 independently passed at
`0ee4224829d3d23c232b3906a5c0f77ffbf92c64`. Both were ancestors of the main
used for this profile. AM storage's frozen patch hash is
`b9cda5617da673c458fba6f36c9480d52cca2ab6cd9a9260e60b8ebd01f527ed`.
A changed overlay requires a separately reviewed successor profile.

Stage on Mac, using discovered and hash-verified existing private inputs:

```sh
scripts/check-windows-native stage \
  --repo "$PWD" --reference "$PINNED_WONDER" \
  --inputs "$CANONICAL_ASTRAL" --gen "$ACCEPTED_REGEN/gen" \
  --control-metadata "$ACCEPTED_CONTROL_RECEIPT" \
  --generated-receipt "$ACCEPTED_REGEN/report.json" \
  --profile windows-cumulative-v1 \
  --out "$PWD/.local/windows-cumulative-047/stage-01"
```

Wonder must be clean at `010ed7a596a621c15d3a8dfa5795ca8c3668b066`.
The output must be fresh, ignored, private and separate from input trees.
Symbolic paths, hardlinked files, missing inputs and nonregular tree members
are rejected. Canonical module/NPDM/boot validation and validated control-header
production use the existing shared validators. The accepted regeneration receipt
must bind the exact canonical manifest and every generated file's post-generation
hash; a merely well-formed lifting report is insufficient.

The package manifest binds profile, ordered overlay hashes, every prepared
source, generated files, canonical flat modules, control receipt, regeneration
receipt, and the packaged driver. Cumulative packages also contain the original
patches and regeneration receipt for independent rechecking. Every package member
has size and SHA-256. ZIP identity and complete member manifest are recorded in
`transfer-request.json`. The parent must check the separately communicated ZIP
and manifest hashes before extraction; the manifest is an integrity record,
not a signature. No keys, dumps or account authentication are included. RomFS
is omitted; reaching asset loading requires a separately authorized parent
transfer of the exact owned files, with hashes.

Before paid execution, place a private handoff in the current store's inbox:
archive absolute path/hash/size, manifest path/hash/full member inventory,
canonical non-key input identities, measured staging revision, exact commands,
time estimate, and required fresh parent controls. The parent exclusively owns
transfer, spending reservation, provider start/stop and signout. Old Windows025
endpoints/session receipts do not authorize another session. If fresh verified
transfer, installed toolchain, session readiness, budget reservation and hard-stop
receipt are absent, return the concrete preparation checkpoint immediately.
Do not wait, poll SSH, probe an Off machine, or reserve spending automatically.
Independent Astra/medium review of this exact committed head is required before
landing; the worker does not launch a nested reviewer or waive that gate.

After that fresh parent receipt, use the installed x64 Visual Studio developer
environment (`VsDevCmd.bat -arch=x64 -host_arch=x64`) and its existing Python,
clang-cl, CMake, Ninja, Windows SDK and Vulkan headers. No installer is part of
this unit. These commands perform detection then a fresh configure/build/launch:

```powershell
python C:/acs-units/WINDOWS-CUMULATIVE-047/package/driver/windows_native.py probe
python C:/acs-units/WINDOWS-CUMULATIVE-047/package/driver/windows_native.py run `
  --package C:/acs-units/WINDOWS-CUMULATIVE-047/package `
  --out C:/acs-units/WINDOWS-CUMULATIVE-047/run-01 `
  --deadline PARENT_FRESH_HARD_STOP_UTC --seconds 1200 --jobs 3 --launch-seconds 30
```

Replace the deadline token with the explicit parent hard stop, leaving provider
cleanup margin before the requested Off time of 20:45Z. The driver additionally
reserves 15 seconds before its deadline. Cumulative execution rejects a budget
above 1,200 seconds and launch above 30 seconds. Detection, configure, build and
launch share that budget, so compilation cannot consume more than 20 minutes.
The prior fresh 395-object build took 365.844 seconds: allow roughly 8–12 minutes
for transfer/configure/build/launch/evidence, with the full 20-minute ceiling
and additional parent cleanup margin available. This estimate is not a spend
reservation or proof of current host performance.

No objects or build cache are transferred or reused. CMake compiler launchers
are cleared; cumulative compile sources must match hashed package members and
cache wrappers are rejected. All compile commands retain strict Astral mode and
floating-point contraction disabled. The driver checks fresh object absence,
records the actual compile graph, hashes every produced object and PE32+ AMD64
EXE, then launches that EXE with bounded trace output. Object count is measured,
not hardcoded to 395. Post-run package drift is checked. Pull compact receipt,
compile graph, logs/guest trace and executable identity privately; verify them
against the transferred source/package and the parent's measured run receipt.

A new native Windows run has not been measured by local preparation. The prior
Windows025 guest reached `ILogger` command 0 at 16:07:17Z; that remains historical
partial startup evidence only. Unsupported services stay strict errors. A real
EXE/guest trace is required to establish the next boundary. Presentation, input,
audio, save/reload, advancing frames and gameplay remain unknown until observed.
Cross-ISA byte match is N/A without a valid reference. Server 2025 is not Windows
11 acceptance. If actual rendering is reached, retain the first genuine frame
and approximately five seconds of advancing frames privately, inspect playback,
and report title/menu/loading/cutscene/gameplay, input and audio separately.

Verification:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_windows_native.py -v
git diff --check main HEAD
```

Tests use temporary repositories and real local subprocesses, no VMs, network,
credentials or spending. They compose all frozen patches onto an actual clean
local pinned Wonder checkout (`WINDOWS_REFERENCE` can select its location),
verify the HID and AM composition, and exercise synthetic profile/receipt/hash,
link/path, compiler, timeout and package failures. Synthetic launch output is
explicitly fixture evidence and establishes no Windows or guest acceptance.

## Local preparation checkpoint

At 18:11:50Z on October 18, fresh private staging at implementation revision
`ab9a8d672db64a88e1c120ad019b8094c24d8abe` passed package and ZIP verification:
11 frozen overlays, 450 packaged source files including the validated private
control header, 319 generated files, and 785 ZIP members. Every member's size
and SHA-256 matched the manifest. Archive SHA-256:
`ece5546c72a4e0885df2c104d3c11f8d8e678f89143c2162a95b66c8bf4a39a0`.
Manifest SHA-256:
`c77fe28a5b0094af694aacfdc8ade223454c99cf81aff950043b369a3cb17ce9`.
Private archive/member inventory and discovered producer receipts remain under
`.local/windows-cumulative-047/`; the concrete parent request is
`inbox/windows-cumulative-047-pre-run-request.json` in the afternoon store.
This is a local preparation measurement, separate from the final report head.
No new native Windows EXE, guest boundary or frame has been measured. The fresh
parent transfer/toolchain/session/reservation/hard-stop receipt is absent;
no SSH or provider operation was performed. Exact-head Astra/medium review and
parent-controlled session readiness remain required before the next native run.
