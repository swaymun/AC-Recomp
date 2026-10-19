# Windows047 native evidence classification

Windows is **partial: genuine native guest startup, blocked at controller
support**. This document classifies the completed October 18 Windows047 run;
it performs no rebuild, launch, transfer or provider operation. No game frame,
advancing gameplay, input, audible audio, save/reload or recording is verified.
The host was Windows Server 2025 on x64, not Windows 11 or a physical Apple device.

## Immutable evidence and provenance

The afternoon store's `inbox/parent-windows-052-results-ready.json` was treated
as untrusted evidence and checked against the local original export under
`ROOT/.local/afternoon-control/windows-047/native-evidence`, where ROOT is the
repository's primary checkout. All 13 exported artifacts were independently
rehashed, size checked and compared byte for byte with the CRC-checked ZIP.

| Evidence | Bytes | SHA-256 |
| --- | ---: | --- |
| `run-01-evidence.zip` | 18843727 | `d21fedd887927e68acee0b72147804ec8df9c10c0d38454f40afd2ce9200a8d3` |
| `receipt.json` | 75063 | `a23b83df61b190f9371f7f75c693c4aabbc5fc8db627f8018ec655a2fa0f13e9` |
| `evidence-manifest.json` | 1663 | `a9083f76411c88f828a089ee00a2ecd630a88897b4b1333d3e5a307f3334d176` |
| `build/compile_commands.json` | 440386 | `bb8bb0940c7296c9e36b284a35b56afcb44eca6fd500d2bced21aa8457ca35c9` |
| `build/astral.exe` | 67808768 | `ec0cf9ab79ae05533d01126e7126edcb6a299b99a005e9cfa57285d852a10c77` |
| `guest.log` and identical `guest-trace.log`, each | 68302 | `86ed72e3533eff242a68139b613ac388c1f2148297f0b063ccba96bf779b5cea` |

The source package manifest SHA-256 is
`c77fe28a5b0094af694aacfdc8ade223454c99cf81aff950043b369a3cb17ce9`.
The separately retained original source ZIP hashes to
`ece5546c72a4e0885df2c104d3c11f8d8e678f89143c2162a95b66c8bf4a39a0`.
Its 785 members were checked against the local package and manifest, including
450 prepared sources, 319 generated files and the accepted regeneration receipt.
The regeneration binding and all frozen overlay hashes were revalidated using
the landed package validator. No generation or compilation was performed.

The measured package/receipt revision is
`ab9a8d672db64a88e1c120ad019b8094c24d8abe`, based on pinned Wonder
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. The separately reviewed preparation
head `1a394ccc296f091115f273640560cd566f4af256` adds only documentation to that
revision; its driver bytes and overlay identities match the package. The
present documentation commit is not the runtime revision.

The exact `windows-cumulative-v1` overlay order is apple-memory,
astral-bootstrap, astral-control-import, astral-sqshl, astral-notifications,
astral-apm, astral-audio, astral-ipc-buffer, astral-hid, astral-applet,
windows-native (all `.patch`). Every packaged overlay matches the frozen
`CUMULATIVE_HASHES` in `tools/windows_native.py` and the preparation head.
Controller051's later `astral-controller-support.patch` is absent. Its subsequent
Mac results and later source changes do not belong to this measured Windows run.

## Compilation and actual guest successor

The receipt spans **18:43:35.637490–18:49:51.307907Z**. The compiler/version
probes and configure completed with exit 0; the native build took 367.843 seconds
and exited 0. The build log reaches executable linking. The compile graph has
395 unique object outputs, matching the receipt's 395 object hash entries and
the exported Ninja log. All 395 commands contain `NX_ASTRAL_STRICT=1` and
`ffp-contract=off`, with no ccache/sccache wrapper. Every compile source belongs
to the hashed source package, including generated main/SDK and runtime sources.
The configure command clears both compiler launchers. The exported executable
was independently checked as PE32+ AMD64, seven sections, with the hash above.

Fresh-object absence and source hashes were checked by the packaged driver
before building; its successful receipt records `inputs_unchanged: true` after
execution. The locally retained package still matches its complete manifest.
These checks support unchanged packaged inputs, but the export contains neither
individual object files nor a separate remote before/after source inventory.
Consequently the 395 individual object hashes and remote post-run equality are
producer observations corroborated by graph/log identities and driver inspection,
not independently rehashed remote objects or a second remote measurement.

The executable ran **18:49:49.967112–18:49:50.291431Z**, measured 0.328 seconds,
with guest return code **1**. Both raw guest logs include entry into
`nn::init::Start`, authenticated parental initialization, ILogger calls, foreground
self-controller policy, APM session configuration, language settings, and Npad
initialization. The final dispatch is the argument-only controller-support
overload. Its single fatal line is:

```text
FATAL: hid: unsupported host capability: _ZN2nn3hid21ShowControllerSupportERKNS0_20ControllerSupportArgE
```

This is the actual observed successor after the earlier startup boundaries.
It is an explicit unsupported host capability, not proof of a compiler failure,
new IPC command defect, or the later Mac VI crash. All six recorded stages have
`timed_out: false` and `log_limit: false`; their exported log sizes and hashes
match the receipt. There is no recorded timeout or bounded-output truncation.
No independent guest exit receipt beyond the hashed native driver's subprocess
record is present.

## Bounded cleanup and acceptance gaps

The separate local `signout-after-native.json` receipt records exit 0 and a
Windows observation at **18:50:45.9359168Z** with Codex command/auth and both
GitHub-auth indicators false. It is a bounded credential-presence observation,
not proof of Windows desktop logoff or exhaustive credential/process cleanup.
The native receipt explicitly warns that detached descendants after normal exit
are not independently enumerated. There is no exported post-exit process-tree
inventory. A provider stop requested at 18:51Z is not itself stopped evidence.

No screenshot or clip of game-rendered content is in the export. Presentation,
advancing frames, title/menu/loading/cutscene/gameplay, real input, audio,
save/terminate/reload and visual-reference comparison remain **unverified**.
No diagnostic frame is classified as gameplay and no recording was fabricated.
Cross-ISA byte match is **N/A**, lacking a comparable reference;
semantic/function/service/shader coverage remains **unknown** without a measured
denominator. Guest startup and successful compilation do not establish those
acceptance gates or other platform acceptance.

The prior Windows052 unit remains `needs_split`, failures **2**. Its two rejected
final reports failed nonempty-evidence schema validation and do not establish a
runtime defect. REPORT-CONTRACT-058 independently passed Astra/medium review
and landed at `4374add81e103f3a32d03d42f2bf9e7fec04c19b`; this unit changes no
report machinery and does not retry/reset052. Current afternoon controls remain
21:00Z deadline, 20:30Z dispatch cutoff, (amount omitted) total and cap 3. This classification
adds no session authorization or spending reservation.

A hashed audit, original evidence ZIP, receipt, manifest, compile graph and logs
are retained privately under the worker's ignored
`.local/windows-native-evidence-060/`. The audit also retains original absolute
receipt paths and cleanup screenshot hashes; private artifacts stay outside Git.
Only this original safe document is committed. Required local verification is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_windows_native.py -v
git diff --check main HEAD
```

These tests are offline fixture/package checks, not a second Windows run.
Independent Astra/medium review of this unit's exact committed head remains a
parent-owned gate before `scripts/land`; this worker neither commissions a
nested reviewer nor lands itself.
