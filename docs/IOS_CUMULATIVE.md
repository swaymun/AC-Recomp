# IOS-CUMULATIVE-041

The explicit `--ios-simulator --ios-profile ios-simulator-cumulative-v1` profile
composes the exact landed overlays from main
`2d27411abb2bb8d8b0e489c76893fd5e6352d42e` in this order:

1. apple-memory
2. astral-bootstrap (including logger and strict control runtime)
3. astral-control-import (importer source; metadata is consumed from CONTROL024)
4. astral-audio
5. astral-notifications
6. astral-apm
7. ios-runtime
8. ios-nvn-compile

The original default `ios-simulator-high-v1` remains unchanged. Cumulative
selection is a closed list with exact landed SHA-256 values, file/link checks,
complete patch dictionary and explicit ordered-list validation. A forged receipt
matching edited local patch content still fails. No custom overlay/hash override
is available. Existing pin, control, generated, source, host and build identities
remain required. The importer overlay does not regenerate inputs or establish
that importer code executes in the simulator.

Apple memory precedes bootstrap; bootstrap creates the service context needed by
audio/notifications/APM. Audio touches hle_audio.cpp, notifications svc_am.cpp,
APM svc_misc.cpp, while control-import touches importer files. iOS changes CMake
and adds platform_ios.mm; NVN changes nvn_pipeline.cpp. Temporary Git/subprocess
tests apply every selected patch against the exact Wonder pin and compare every
source hash with default preparation followed by the service-only deltas. This
checks actual overlap/prerequisites without editing any patch implementation.

Fresh private preparation uses canonical `.local/game-private/astral`, reviewed
CPU-REGEN-020 generated main/sdk and CONTROL024 metadata/generated identity.
The private command and receipts are under this worktree's
`.local/ios-cumulative-041/`. No generation, provider, account, SSH or network
operation is involved. Runtime builds use at most two jobs; the existing strict,
high-memory, arm64 simulator and 26.0 minimum checks remain mandatory.

The runtime script validates the installed executable on each registered dedicated
26.5 device, refuses an existing bundle, correlates PID/run-token callbacks,
checks live process ownership when present, retains logs and UTC timestamps,
and removes only its verified installed app before shutting down its owned device.
Cumulative launch also validates current authorization/deadline/cap and exact
landed independent service reviews using the existing supervisor checks.
Overlay inclusion is reported separately from observed handler execution.

Native graphics and audio remain unsupported until actual measurement reaches
and validates them. Diagnostic host frames are not guest frames. Both families
need their own real guest receipt; source equivalence and compilation cannot
establish gameplay or physical-device acceptance.

Independent exact-head Astra/medium review is required before landing. This
worker cannot start nested workers; parent owns that review and its slot. No
review is waived. Build/runtime results and final report revision are recorded
separately below when available.

## Measured result — 2026-10-18 17:36–17:37Z

Both real native guests entered SDK `nn::init::Start` and `nnMain`, progressed
past the former ISelfController14 boundary, and stopped at **strict IPC missing
service: hid**. This is startup progression, with zero observed game frames.
Measured runtime revision: `1ac6acb1d2d27ff59698d06c2d60c28f036a23e8`.
This documentation closeout is a later revision, not a second measurement.

| Family | UTC interval | Guest PID | Launch-to-boundary | Owned cleanup |
| --- | --- | --- | --- | --- |
| iPhone | 17:36:43.645–17:37:04.954 | 14555 | 1.440 s | app removed; device Shutdown |
| iPad | 17:37:04.954–17:37:25.803 | 15331 | 1.664 s | app removed; device Shutdown |

Each independently token-correlated trace records ISelfController14/11/12,
IParentalControlService1, three accepted logger packets, APM OpenSession and
ISession0. The actual APM handler acknowledged mode0/configuration00020004;
host clocks remain unchanged. Audio is included in source/build but no audio
handler execution was observed. NVN compile inclusion is not graphics execution.
Both scenes became active and recorded UI-responsive-during-boot callbacks.
The fatal processes exited before the supervisor's live `ps` sample; no live
process-path observation is claimed. Callback PID/token, launch-returned PID and
installed-binary hash agree separately for each family.

The new boundary correlates with `runtime/src/ipc.cpp:37` (`make_service`), its
strict factory-lookup fatal at line41, and the observed `sm: GetService(hid)`.
`hle_hid.cpp` has direct HLE bindings but no IPC service registration in this
composition. The separate newly landed IPC-buffer overlay is outside this exact
selected profile; no missing HID implementation or renderer was added here.

The fresh build compiled all **397 translation units**, using two jobs and all
existing simulator/strict/high-memory/arm64/minimum26.0 guards. It identifies as
IOSSIMULATOR, minos26.0; both measured devices use26.5. Its unsigned executable
SHA-256 is `595ef967e202f842e05bccbc10eee067d0a93b251c3c14ffe75b36950b19f714`.
Preparation SHA-256 is
`52e69584514139c26b27266dbe9b77fa87172377f17e0dd24ea484581c225889`;
compile-database SHA-256 is
`83ea46278f4800b3da1f8cd6dd680bff9480e2e0560f86e5508ed465cd634330`.

Private `.local/ios-cumulative-041/final-evidence.json` binds the full ordered
patch identities, 451-file source fingerprint, compile/binary/control/host/log
hashes, UTC timestamps, per-family receipts and source correlation. Raw guest
logs and the full runtime receipt remain in ignored
`.local/ios-guest-entry-028/run-3ce8dc9b624b4d3fb53a2e41a288e638/`.
Before/after inventories have identical simulator states, including unrelated
simulators. An earlier ownership preflight failed on OpenStep plist parsing
before either app installation or guest launch; its receipt is retained. The
bounded native parser fix has a real converter subprocess regression test.

Native graphics/audio, advancing game frames and gameplay remain unmeasured;
no gameplay screenshot or clip exists to deliver. Independent Astra/medium
exact-final-head review remains a parent-owned landing gate and is not waived.
The next implementation unit needs a genuine HID IPC route and semantics, then
another separately authorized bounded cumulative startup on both families.

## Final bounded repair — retained measurements

Round-one Astra review `236a7ace90f84f12a2a408f3972f2a1b` failed head
`0dbcf3d7361e67cd072b0a125ff3d5b1f1b64ff4`: an app ownership lookup or uninstall
exception could skip device shutdown, and the branch lacked current main.
That failed review is retained. This second attempt separates uninstall and
shutdown exception handling. Shutdown independently rechecks registry and live
device ownership through `sim()`, even after app cleanup fails. Termination,
evidence collection, uninstall and shutdown errors remain distinct; a failed
uninstall is never reported as app removal. Unrelated or reassigned devices
remain protected by the same exact ownership guards.

Subprocess tests execute the actual ownership functions and cleanup AST with a
synthetic command transport. They cover failed uninstall, failed app lookup,
changed executable identity, simultaneous uninstall/shutdown failures, changed
device/registry identity, redirected UDID, successful cleanup and no owned boot.
They never invoke real simctl. The retained native receipts above are the
17:36–17:37Z observations from measured revision `1ac6acb`; this cleanup-only
repair neither rebuilds nor reruns them. The retained source/binary/log hashes
are rechecked separately from the final repair revision and regression results.
The complete branch is rebased onto current main before final verification.
Exact-final-head Astra/medium review remains parent-owned and required before
landing; this repair is not independently accepted merely because tests pass.
