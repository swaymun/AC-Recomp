# IOS-SCENE-OBSERVER-008

This original wrapper observes the pinned installed rejected experiment without
editing, installing, building, attaching a debugger or changing scene archives.
Diagnostic completion can be a reproducible blocker. It is not simulator startup
or gameplay acceptance. Independent **Astra/medium exact-head review** is mandatory
before parent uses `scripts/land`; this worker starts no nested review and does
not land, push or create a PR.

## Fixed collection contract

`tools/observe_ios_scene.py` imports the inspected landed
`tools/diagnose_ios_scene.py` unchanged. Its only live invocation is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/observe_ios_scene.py --collect .local/ios-scene-observer-008/live/receipt.json
```

The receipt directory must not already exist. There is no caller predicate,
device, token, timeout or launch-count override. Do not run it again after this
unit's live allowance is consumed. Exit 2 preserves blocked startup acceptance.

The exact fixed predicate is:

```text
process == "ACSHost" OR ((process == "SpringBoard" OR process == "runningboardd" OR process == "frontboardd") AND eventMessage CONTAINS "local.acs.ios-host-002")
```

Native help must expose debug/ndjson/predicate/timeout support. The inherited
local help/man-page checks establish unsuffixed timeout seconds. Native timeout
is 25 seconds, supervision is 30 seconds including its final half-second cleanup,
and each pipe has an 8 MiB cap. Full-observed byte hashes and retained raw-prefix
hashes are computed before filtering; the command output file hash identifies
the separate redacted representation. Only exact installed executable-path app
events or named owned-bundle system events survive. Other paths, email addresses
and third-party bundle identifiers are redacted. Raw streams are not retained.

Each family must match its exact available live/plist identity, runtime 26.5,
name/type/UDID and initial Shutdown state. Already Booted blocks it without a
boot/shutdown. Only dedicated iPhone `883683CC-F98A-4B53-9FC8-F02E60A52F30` and
iPad `6D9DC697-AFFB-4C27-A8A7-44A83AA3B367` may change state. Full installed
file maps must equal the pinned preserved signed experiment, and strict
signature verification must succeed before boot. Preserved app/source hashes
are defined in the inherited helper and independently checked against Git blobs
and retained build/install/launch receipts.

One stream begins before at most one launch per family, using a fresh per-family
token and an eight-second launch RPC deadline. RPC timeout is a live failure,
even if a later journal shows app startup. There is no subsequent `ps` query or
observation after that failure. A successful RPC still needs a unique journal
PID followed by exact `ps` PID/path/token identity. The same process must be
verified around a measured eight-second interval. No other PID is queried.
Listener readiness is not exposed by native log; the short prelaunch pause
does not prove readiness.

On failure there is no retry/recollection. Stream finalization remains bounded
and precedes owned shutdown. Journal retention follows the observation/stream
and never reconstructs a missing live identity. Successful stream acceptance
requires exit 0, both EOFs before group signalling, no truncation, byte counts
strictly below cap and equal full/prefix hashes. The first failure survives
secondary finalizer or cleanup errors. Exact live/plist Shutdown and installed
hashes are checked afterwards. Group-signal failures and escaped host descendants
remain explicit uncertainties even when the simulator is Shutdown. Normal work
is limited to an 80-second budget to reserve shutdown/reverification; every
child is bounded to at most 30 seconds and every family to 120 seconds.

## Retained predecessor checks

Before live use the wrapper requires independently passing Astra review
`f243035d3e9e49c9931a0ef8324d8520` of exact head
`c9e49b5beb856cabb11277c7fab4421e7ba94bf2`, the landing receipt at
`52369d223a9dd08bc5d571dde8aee2117d990e74`, matching normalized patch
`10beb5f0d42258e1c3cdc664165b8fff033fea667fb52679481b5a70a7a11c62`, and landing
ancestry in both HEAD and main. Reviewed/landed/current/predecessor/executed helper
bytes must all hash to
`a6bd53f7ce07214a058d50ec08c1c6541b0e2c992c91ff16e6d34297c6500db7`.
The immutable filtered receipt must hash to
`23ea40f1833182ccb7fd7a8062251d73041614b8d1e9beb692e18596b7cbe170`, with every
command output intact and both bounded filtered streams valid. Older capped
collector/source receipts and historical delivery SHA-256
`7afd5b41a7498591ebcd25192e548d43006d1414ed53393551d33ab7bbb82d1d` are rechecked;
transport and delivery receipts pass the inherited offline verifier. These
checks repeat after collection without rewriting predecessor data.

The original App.mm source has launch and `scene-connect` markers plus activation
snapshots, but no scene-creation transaction receive/ack instrumentation. System
request/registration candidates are reported separately from app transaction
delivery, acknowledgement and token-correlated delegate entry. Text candidates,
restored session IDs, registration, handshake and RPC exit 0 cannot establish
delivery or acknowledgement. Empty logs establish neither absence nor capability.

## Offline verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ios_scene_observer.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ios_scene_diagnostics.py' -v
```

Before live use all 15 then-existing observer tests and all 62 inherited tests
passed. After collection, offline receipt verification and mutation tests were
added; all 20 observer tests pass without skips against the retained receipt.
These later changes add only offline verification and its CLI option, tests and
documentation; they did not change or rerun the executed live collection path.

Tests use stateful fake commands plus real local fake subprocesses for concurrent
pipe backpressure, raw/prefix hashes, redaction, cap-before-timeout first-error
preservation and descendant-held pipes. They cover single stream/launch ordering,
the eight-second interval, two owned identity checks, launch timeout stopping all
observation, absent journals, identity failures, help/boot/finalizer failures,
already Booted refusal, scoped cleanup and empty-log nonacceptance. No test boots
a simulator or invokes a cloud/provider/auth operation.

The offline-only command is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/observe_ios_scene.py --verify-saved .local/ios-scene-observer-008/live/receipt.json
```

It validates the completed two-family receipt, including honestly unavailable
app observation, output/source/journal hashes, scope, help, deadlines, single
stream/launch counts, chronological collection and cleanup. Exit 0 means retained
evidence integrity. It starts no subprocess. It is not a general verifier for
interrupted preflight receipts. This is an integrity record, not a cryptographic
attestation of the host. Later read-only analysis is separate from the original
receipt and does not reconstruct live process identity.

## Authorized live result: precise blocked observation

**The one-stream/one-launch allowance is exhausted on both families. No retry is
authorized.** The fixed app-relevant native 25s/supervisor 30s/cap 8MiB collection
prerequisite succeeded, but both launch RPCs failed their eight-second deadline.
The wrapper stopped app observation: no `ps` command was issued, no live identity
was established, and no measured eight-second app window is claimed. Each primary
failure is retained verbatim as launch exit -9, timeout true, execution/pipe
deadline exceeded. That failure does not establish why native launch RPC did not
return, a lifecycle defect, or a platform visibility denial.

All times are 2026-10-18 UTC:

| Family | Stream start–end | Stream/family seconds | Observed stdout/stderr bytes | One launch start–end |
| --- | --- | --- | --- | --- |
| iPhone | 11:38:43.041516–11:39:10.572613 | 27.531097 / 34.050326 | 1,541,703 / 44 | 11:38:43.344518–11:38:51.367054 |
| iPad | 11:39:18.810761–11:39:46.086296 | 27.275535 / 35.533912 | 1,606,805 / 44 | 11:39:19.082241–11:39:27.088985 |

Both streams exited 0 without supervisor timeout/truncation; both EOFs preceded
group signalling, and byte counts were strictly below cap. Native 25 seconds is
the requested timeout; measured wall times include simctl-spawn overhead. Both
stderr streams contain only the known nonfatal getpwuid warning. Full-observed
stdout hashes equal their raw-prefix hashes:

| Family/pipe | Full-observed SHA-256 = retained raw-prefix SHA-256 |
| --- | --- |
| iPhone stdout | `a912c643c40b7397ed8020e12bd2700707795d35226c28e886cb281708f2a23d` |
| iPad stdout | `35aa55d017a6488e6c24e248c0cc7063d2091395dec04838edd49c130756d7c5` |
| Both stderr | `8b9e4a529f3e367142876bd0ce03ed7c7f10a50657c9a73fda0d6e30867e7523` |

Each family has an owned-bundle system open request and FrontBoard app connection.
No server-registration candidate is retained. This is not evidence of absence.
iPhone retains 1,066 scoped events; iPad 1,104. Each contains 680 exact-path app
events, but **zero live-identity-correlated app events**, because no live identity
was collected after launch failure. `app_event_count=0` in the receipt describes
that missing correlation, not missing app logs. Offline analysis does not promote
the journal PIDs 72988 / 74126 to live verified identities.

Both post-stream journals contain six token-correlated markers (main,
did-finish-launching, delay 0/1/5/10) and four activation snapshots, all with zero
connected scenes. Read UTCs are 11:39:10.676777 and11:39:46.204342. Persistent
session IDs remain `EC029773-D8BE-449B-BD48-BBA343785F28` and
`FF7C1CCE-3288-44C4-AF46-793F65CC8BB4`. No exact-path app message mentions
either corresponding session. Neither this text search nor the journal proves
transaction absence. There is no token-correlated scene-connect marker;
**app transaction delivery, acknowledgement and delegate entry remain unknown**.

Scoped shutdown followed stream finalization: iPhone 11:39:10.678612–
11:39:14.050031, iPad 11:39:46.206556–11:39:49.582965, both exit 0. Exact
live/plist Shutdown identities were reverified at 11:39:14.349497 /
11:39:49.885427. Both full installed file maps remained unchanged. Group signals
returned EPERM after exit/EOF; **group signal failed, descendants unknown** remains
the outcome. Simulator shutdown does not prove escaped-host-descendant absence.

Private evidence under `.local/ios-scene-observer-008/` remains ignored and retained:

| Artifact | SHA-256 |
| --- | --- |
| `live/receipt.json` | `3e7286a4861d18b821b7cfab07181943690918a1b7674c650eb21e7aa2ded52f` |
| `live/observer-source.py` (exact executed bytes) | `2b0fba3db5c49e095d0ef89589f456530b13e462523af49f3b919acaecb3efa2` |
| `live/helper-source.py` | `a6bd53f7ce07214a058d50ec08c1c6541b0e2c992c91ff16e6d34297c6500db7` |
| `live/command-007.json` (redacted iPhone stream) | `8baa2988cb62088db47f665bf03086dde8fd8203590f4ab05ef48928db0131b7` |

`live/receipt.json` retains all 19 command argv/UTC/exits, per-pipe full/prefix
hashes, EOF/signals and cleanup uncertainty, with before/after predecessor records
identical. `analysis.json` is a later offline summary, and `index.json` inventories
private file lengths/hashes. All original receipts/snapshots remain immutable.

The next blocker is the bounded launch-RPC failure preventing an accepted live
identity/window. Any changed RPC/observation premise needs a separate explicit
brief; this unit permits no further live attempt. Independently, the pinned app
has no transaction receive/ack observer. A separate permission/symbol/observer
prerequisite is needed before attributing a scene boundary or proposing a lifecycle
patch. No debugger/injection or manifest/source change was made here.

All four platform families remain in scope: macOS/Linux partial; Windows blocked
by unready Windows cloud machine controls; separate iPhone/iPad startups blocked unless directly
evidenced. **26.5 tested / 26.0 minimum target**; physical acceptance unverified.
Cross-ISA byte match N/A; overall semantic/gameplay coverage unknown. Parent alone
owns providers/auth. Deadline 15:00Z, dispatch cutoff 14:30Z, total cap (amount omitted).
