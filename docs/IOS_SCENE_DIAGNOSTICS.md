# IOS-TRANSPORT-004: owned simulator scene trace prerequisite

This unit collects diagnostic evidence. It does **not** pass app startup, scene
activation repeatability, rendering, touch, or gameplay. The saved-receipt verifier
passes when retained evidence is internally consistent, including honestly unknown
or unavailable trace states. It never promotes `simctl launch` exit 0 to activation.

Only these dedicated simulator identities and `local.acs.ios-host-002` are allowed:

| Family | UDID | Device type |
| --- | --- | --- |
| iPhone | `883683CC-F98A-4B53-9FC8-F02E60A52F30` | iPhone 17 Pro |
| iPad | `6D9DC697-AFFB-4C27-A8A7-44A83AA3B367` | iPad Pro 11-inch M5 / 12 GB |

Runtime is **26.5 tested / 26.0 minimum target**. Physical acceptance is unverified;
cross-ISA byte match is N/A; semantic and gameplay coverage remain unknown.

## Preserved input identity

The failed IOS-SCENE-003 head is
`15f331d18045607acc2141ec26c158ab5bebb308`. Its report, source diffs and baseline /
experiment build-install-launch receipts were read only under its private
`ios-scene-003` evidence directory. The tool hashes those inputs in `reference`.
No failed branch, source, executable, signing data or installation was modified.
The two installed apps match the **rejected experiment**, not the reverted final
manifest. All three files match the preserved signed bundle, and strict signature
verification passed for the reference and both installed apps:

| Identity | SHA-256 |
| --- | --- |
| ACSHost executable | `7800120551da9ec519e00aaa905b5f21a8399c034de3bf168eae75fae1b1d338` |
| Info.plist | `4841a3805959c5d85f7a16843dd4c30e1aacdce634c25a9a6cd0571bf62bade0` |
| CodeResources | `44abb488c97513d2fe1d90a61ab16ddea720fd54fd26c0b7db9acbf78d312821` |

Experiment source head: `f5a29c0af81b0f92b97fee8792c3abc52c1bf7d1`.
App.mm source hash: `0385abd01fb35044c008fedb77426c2dae87c648c888def882da4488a79f03cf`.
The receipt contains the other original source hashes. The final reverted
Info.plist hash was `3f88e6ababfb8e7f572e7d835033a8e67520b2ec85e585b19fe13954dc785d35`;
no installed experiment result is attributed to that final source.

## Bounded collection

The standard-library tool uses subprocess argument lists, new child process groups,
UTC start/end timestamps, explicit exits/timeouts and SHA-256 for every command
output. Every command deadline is at most 20 seconds in the live sequence (the API
rejects deadlines above 30). Timeout cleanup kills only the newly created child
process group. Simulator-spawned commands and the app are contained by shutdown of
the exact dedicated device; no global service reset or name-based kill is used.

The collector requires exact UDID/name/type/runtime and an initially Shutdown
device. It refuses to disturb an already booted session. Before booting it checks
the installed bundle's full file hashes and strict signature. It never installs,
rebuilds, changes app configuration or deletes scene archives. It reads tool help
before choosing `log show`; help's documented usage exit 64 is accepted only for
help. Each family receives at most one launch with a unique token and 12-second
RPC limit. Existing owned app journals are filtered by that token. A live PID
query uses only a PID found in those owned journals and checks full executable
path and token. An absent or stopped process is never sampled by name.

The datastore predicate selects the exact installed app executable, plus
SpringBoard/runningboardd/frontboardd events explicitly mentioning the owned
bundle. Structured events are filtered again before retention. Only selected
fields survive; email addresses and other bundle identifiers are redacted. No
broad log archive, unrelated process sample or device inventory is retained.
Original raw stdout is hashed; only filtered trace content is saved. Initial
conservative redaction also hid the owned `-default` scene suffix in some events;
those IDs remain unavailable in those retained messages. The current filter
preserves that suffix. It does not reconstruct IDs from a redaction placeholder.

The first preflight incorrectly treated `log help show` exit64 as a tool failure;
it made **zero launches**, restored both devices and is retained under
`.local/ios-transport/preflight/`. The first actual queries used fractional epoch
timestamps, which this runtime rejected with exit64. Those are tool invocation
failures, not proof of unavailable platform tracing. They are retained unchanged.
One corrected historical query per family used supported UTC timestamps and
succeeded, without another app launch. Its prior receipt is hashed and retained.

Both devices were restored to Shutdown after preflight, diagnostic launch, and
historical query. All commands targeted only these two devices and this app. No
Wonder or unrelated-device operation was issued. No claim is made about concurrent
external actors' unrelated simulator state.

## Commands and saved evidence

The authorized live collection already ran. **Do not rerun `--collect` for this
unit**: its one-launch-per-family allowance is exhausted. The generic interface is:

```sh
python3 tools/diagnose_ios_scene.py --collect <new-private-directory>/receipt.json
python3 tools/diagnose_ios_scene.py --trace-retained <existing-private-directory>/receipt.json
python3 tools/diagnose_ios_scene.py --retain-journals <existing-private-directory>/receipt.json
```

`--trace-retained` performs no app launch. It verifies an existing receipt, retains
a hashed prior snapshot, checks signed installed identity, boots only an initially
Shutdown owned device, reads only the saved launch interval, and shuts it down.
`--retain-journals` only reads existing owned files and writes private evidence;
it does not boot or launch. Data container metadata must match the owned bundle.

`--collect` and `--trace-retained` exit2 while scene transaction request/ack remain
unknown, even if collection succeeds. Command/tool failure is recorded as blocked.
`--verify-saved` is offline: it reads retained files, exact ownership/argv grammar,
UTC/deadline/exit schema, known app/source identities, hashes, correlated journals,
observation indices and failure/unknown states. It starts no child process and does
not read current simulator state. Exit0 means valid evidence, not startup success.
Both `reference.source_sha256` and `reference.inspected` must contain exactly the
pinned path sets and lowercase SHA-256 values from the preserved experiment and
inputs. Missing, empty, malformed, extra or changed identities fail verification.
Collection checks the same pins when inspecting preserved inputs; offline
verification checks the recorded maps without reading the predecessor worktree.
Device states must be integers and agree before and after the diagnostic.
`not_needed` requires no boot, launch or shutdown commands. `restored` requires an
initial and final Shutdown state (1), an owned boot attempt, and a successful,
non-timeout shutdown after each boot/launch cycle in timestamp order. A failed or
timed-out boot still requires restoration; an earlier successful shutdown cannot
justify a later failed cycle. No label can override contradictory state or exits.
A saved receipt is an integrity record, not a cryptographically authenticated
attestation of the host or an independent source rebuild.

Exact verification:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ios_scene_diagnostics.py' -v
python3 tools/diagnose_ios_scene.py --verify-saved .local/ios-transport/receipt.json
```

Tests use fake subprocesses only: deadlines/group cleanup, boot-failure restoration,
ownership rejection, malformed/hash-tampered receipts, unknown states, RPC success
without activation, failed diagnostics, trace redaction and offline verification.
Private evidence remains ignored under `.local/ios-transport/`; no binary or raw
account material is committed. Source/build receipt hashes refer to the preserved
predecessor; all new command outputs, journals and report remain in this worktree.

## Observed boundary

Times below are UTC. Trace message timestamps retain their explicit `-0400` offset.

| Family | One launch | Collected system evidence | App evidence / limits |
| --- | --- | --- | --- |
| iPhone | 10:18:31.970360–10:18:43.993303; RPC timeout12s, killed exit-9; PID26920 | 85 events; FrontBoard open request received 10:18:32.786626; app connection established 10:18:32.987456; scene-client handshake | Token/PID/path checked; main/did-finish and main queue observations at 0/1/5/10s; one session, zero connected scenes; no scene-connect marker |
| iPad | 10:18:51.760285–10:18:53.050837; RPC exit0; PID27424 | 99 events; FrontBoard open request received 10:18:52.107289; server registered new scene and logged Scene activated at 10:18:53.071248/61; app connection established 10:18:53.117332 | Retained token-correlated main/did-finish and delay0 journal after shutdown; one session, zero connected scenes then; no scene-connect marker. The observation window was short; later app connection is not ruled out |

Final trace outputs are `command-022.json` and `command-026.json`; both query
commands exited0 without timeout. Both emit the nonfatal warning
`getpwuid_r did not find a match for uid 501`. This warning did **not** prevent
trace collection. Earlier timestamp-parser failures must not be mislabeled as a
permission barrier. The iPhone live process path/token query is retained; the iPad
was not live-queried before shutdown, so no equivalent live-process check is claimed.

App restored session identifiers are
`EC029773-D8BE-449B-BD48-BBA343785F28` (iPhone) and
`FF7C1CCE-3288-44C4-AF46-793F65CC8BB4` (iPad). Journals resolve UIWindowScene and
ACSSceneDelegate. No mapping from those persistent IDs to an app-delivered
FrontBoard scene transaction was demonstrated. `Scene activated` is a server-side
log, not proof that ACSSceneDelegate connected or that Metal initialized.

Both families therefore have **evidence collection success**, **startup
unaccepted**, and **scene request delivery / app acknowledgement / scene delegate
unknown**. The collected logs establish that open requests reach FrontBoard and
that the app workspace connection can be established. They challenge a blanket
"simctl never sends anything" premise. They do not establish a lifecycle source
bug. RunningBoard's memorystatus warnings likewise do not establish causation.

## Final offline fix round

The preserved Astra/medium review `4f8800b47ca84f52941cf971a1923036` rejected
`793eff14b1daeaa60799961b7e2393ac29389c22`: its verifier accepted contradictory
restoration claims and missing source/input identity maps. This second and final
fix round changes offline validation and regression coverage only, plus recording
the unchanged final state when collection refuses to boot an existing session.
It launches no simulators, reruns no tracing, and changes no prior private receipt.

The existing saved receipt passes the stricter checks: both families record
initial/final state 1 and two owned boot/shutdown pairs (original collection and
the historical trace query). All four shutdowns exited 0 without timeout. The six
inspected input hashes were independently matched against the preserved files;
the six source hashes match the experiment summary. Mutation tests reject the
review's `final_state=3` plus failed/timed-out shutdown counterexample, failed
shutdowns even with `final_state=1`, missing/foreign/out-of-order cleanup, a later
failed boot cycle after an earlier successful cleanup, and incomplete/malformed
or incorrect source/input identities. Both exact VERIFY commands pass offline;
app-side delivery, acknowledgement and delegate entry remain unknown on each
family. Existing collection success and unaccepted startup remain separate.

The parent must obtain independent Astra/medium review of the **entire final
diff**, including the original diagnostic tool, before landing. The worker's
no-nested-reviewer restriction leaves that gate to the parent; review is not
waived and no landing is performed here. If the second review fails, split or
challenge the prerequisite instead of commissioning a third fix round.

## Proposed next bounded brief: IOS-SCENE-DELIVERY-005

**GOAL:** correlate an app-delivered scene-creation transaction and acknowledgement
with the restored session on both families, using the demonstrated server boundary.

**CONTEXT:** use this exact evidence and preserve failed heads. iPhone has an open
request/handshake without observed registration; iPad has server registration but
no observed app scene callback within its short window. No source fix is established.

**SCOPE:** exactly `tools/diagnose_ios_scene.py`,
`tests/test_ios_scene_diagnostics.py`, and `docs/IOS_SCENE_DIAGNOSTICS.md` in a new
main-based worker. Use the existing verified installed experiment bundles read
only. No host source/build changes or failed-worktree edits.

**ACCEPTANCE:** first establish app-targeted UIKit/FrontBoard transaction visibility
using a bounded live debug stream with an exact PID/path/token and session
correlation. Inspect stream help/capability first. Use at most one launch per family
with an equal 12-second app observation interval and a live owned-process identity
check; retain journals after that interval. All children must have deadlines <=30s. A missing stream capability or permission must become an explicit blocked
prerequisite. No archive reset, speculative manifest replacement or readiness stub.
Only a demonstrated defect can justify a separately scoped lifecycle fix.

**VERIFY:** `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p
'test_ios_scene_diagnostics.py' -v` and `python3 tools/diagnose_ios_scene.py
--verify-saved .local/ios-scene-delivery/receipt.json`. Live acceptance separately
requires app transaction/ack evidence; RPC or server-registration success is
insufficient. An unavailable trace must stay blocked.

**TIMEBOX:** 15 minutes. **FORBIDDEN:** unrelated devices, failed-worktree edits,
global resets, touch/runtime work, paid inference, nested workers and gameplay claims.

**REPORT:** distinguish system open-request receipt, app-side transaction delivery,
app acknowledgement and delegate entry; record unavailable prerequisites precisely.
Independent Astra/medium review of the entire exact IOS-TRANSPORT-004 diff is still
required from the parent before landing. No review is waived; this worker started
no reviewer and performed no landing, push or PR.

## IOS-SCENE-DELIVERY-005 — first attempt (preserved failure)

The first attempt used exactly one new launch per dedicated family, without changing
source, manifests, signed bundles, installations or scene archives. Its unchanged private
receipt is now `.local/ios-scene-delivery-failed-200d88c/receipt.json` (SHA-256
`11936e651547f18cc0dd5960a689c5e439bc83394ff39830a7b9d4dc9714971a`). The accepted predecessor
receipt was verified offline before use and copied, together with its referenced
outputs/journals, into `predecessor/` in that directory. Its exact SHA-256 is pinned
as `TRANSPORT_SHA`; the original predecessor worktree was read only. Existing
IOS-TRANSPORT-004 receipts still verify with this tool.

The successor **does not pass its planned equal-window/live-identity acceptance**.
Its offline verifier accepts an explicitly unavailable observation as failure
evidence, never as completion of that observation. App startup and gameplay remain
blocked. No platform permission failure was observed, and no lifecycle defect was
demonstrated.

### Capability and collection evidence

Host and each owned simulator's `log help stream` returned documented usage exit64
and exposed `--predicate`, `--level debug`, `ndjson` and `--timeout`. Thus scoped
app-side debug logging is available. Each stream used the exact installed app
executable path plus the predecessor's bundle-scoped system predicate. The stream
was started before launch, with native timeout28 and an independent child
deadline30. Listener-registration readiness is not exposed by this CLI; a
half-second pause is not evidence of subscription readiness.

| Family | System observations | App-side observations | Delivery / ack / delegate |
| --- | --- | --- | --- |
| iPhone | Open request, connection and server registration; 1,272 scoped events | 791 events from the exact installed executable/PID10491; FrontBoard sent-handshake messages; six token-correlated journal markers; no live `ps` check recorded | All unknown; no session-correlated scene-creation transaction/ack or scene-connect marker |
| iPad | Open request and connection; no registration matched by the retained parser; 1,073 scoped events | 680 exact-path/PID11956 events; live PID/path/token checks before and after 12.194s observation; FrontBoard sent-handshake messages; six token-correlated markers | All unknown; no session-correlated scene-creation transaction/ack or scene-connect marker |

The iPhone launch RPC exited0 at 10:40:52.205790Z. The iPad launch RPC timed out12s
and exited-9 at 10:41:41.762376Z; its separately queried app remained alive through
both PID checks. Neither RPC result establishes app acceptance. The iPad interval
was 10:41:41.768912–10:41:53.962926Z. The iPhone collector failed before recording a
live PID check or a timed observation. Its initial failure was overwritten by the
stream-timeout label in the first collector, so its exact cause is unavailable.
An immediate journal-read race is a possible explanation, not an established fact.
No live PID identity is reconstructed from later journals or log messages.

Both live streams hit deadline30 and were killed, exit-9. The initial implementation
left stdout piped without a concurrent reader while launching/observing the app;
pipe backpressure is a tooling risk and prevents treating the truncated stream as
proof of absent transactions. Native timeout28 did not yield a successful exit.
Neither timeout is evidence of missing log permission. The final implementation
drains the stream immediately in a bounded background reader; a real subprocess
regression writes 1 MiB before joining and proves that this does not block. It also
waits up to2s for the token-correlated startup journal, preserves the primary error,
and always runs owned shutdown even if stream finalization raises. Those initial repairs were
tested offline only at that head. The final-fix brief explicitly authorized one
additional launch per family after collector regression checks; that supersedes
the exhausted first-attempt allowance and is recorded below.

Journals were retained after the full stream interval and shutdown, filtered by the
unique launch token. Both have main/did-finish plus delay0/1/5/10 observations and
activation0/1/5/10 files, all with zero connected scenes. Persistent IDs match the
predecessor: `EC029773-D8BE-449B-BD48-BBA343785F28` (iPhone) and
`FF7C1CCE-3288-44C4-AF46-793F65CC8BB4` (iPad). The final receipt computes session
candidate indices only from exact live-verified PID/path app events. The iPhone
candidate list stays empty because live identity is unavailable; it does not
silently use a journal PID as a live check. The iPad has no event mentioning its
persistent ID. A handshake, method registration, restored session or server scene
registration cannot assert transaction delivery, transaction acknowledgement or
delegate entry. All semantic state fields remain unknown.

The unchanged original collection is retained as `original-collection.json` and
hashed as `prior_receipt`. The final receipt adds later read-only journals and
explicit observation availability. No original command output or predecessor
receipt was corrected, and no second launch or historical requery was attempted.

### Cleanup and provenance

Both devices started Shutdown (state1). Each owned boot attempt was followed by a
successful bounded shutdown: iPhone 10:41:20.855694–10:41:24.196980Z; iPad
10:41:59.270314–10:42:02.650865Z. Both exited0 without timeout and final device
plists reported state1. A later read-only closeout verifies those same identities,
states and installed file hashes. Every command has retained argv, UTC interval,
exit/deadline and output hashes. App/source/input maps remain the exact pins in
"Preserved input identity" above. No new build or installed-file provenance is
attributed to the reverted manifest. Runtime **26.5 tested / 26.0 minimum**;
physical-device acceptance unverified; game-frame/gameplay and semantic coverage
unknown; cross-ISA byte match N/A.

Exact successor verification (offline):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ios_scene_diagnostics.py' -v
python3 tools/diagnose_ios_scene.py --verify-saved .local/ios-scene-delivery/receipt.json
```

### Next bounded prerequisite and review gate

First commission a collector-validation brief with **no simulator launches**:
exercise asynchronous draining, delayed token-journal arrival, identity failure,
stream deadline, journal retention and ordered cleanup using fake subprocesses.
The current real run cannot validate the repaired collector. A separately
explicitly authorized one-launch-per-family brief can then establish equal live
identity windows with that reviewed collector, retaining complete app-side debug
streams. If those streams still expose no session/transaction correlation, scope
a permitted debugger observer for the pinned app's UIKit/FrontBoard scene-create
receive and acknowledgement boundary, recording transaction and persistent-session
IDs; establish attach permission/symbol availability first. Neither debugger
access nor the necessary instrumentation is claimed available by this unit.
Do not replace the manifest or infer a lifecycle fix from the present evidence.

Independent Astra/medium review of this entire committed head remains required
from the parent before `scripts/land`. This worker started no nested worker or
reviewer, performed no landing/push/PR, and did not waive review. Passing offline
verification establishes integrity of retained **blocked/partial evidence**, not
completion of the planned equal-window acceptance or a platform root cause.


## Final fix round after Astra rejection 200d88c

The complete retained review `200d88c99a2c4c4db826b8f838dd185c` rejected
`d3af9ca3d69567eb618bc678514823bb928d34fc`. It demonstrated that the
unavailable-observation branch accepted a missing capability reference, a launch
command used as the help reference, and a stream moved one hour after shutdown.
The same branch now passes the common capability and chronology checks as the
complete-observation branch. Command references require nonnegative integer
indices, exact owned argv and complete help capabilities including debug level.
Help follows boot; the stream follows help, encloses launch and the observation,
and finishes before shutdown. Complete observations additionally require both
live identity checks around a measured 12-second interval. Missing intervals or
states cannot masquerade as complete observations. An explicit unavailable
interval remains valid historical failure evidence, without supplying live
identity or accepting planned observation coverage.

Collector failure handling keeps `primary_failure` and appends secondary stream
or finalization errors without replacing it. Finalization failures still reach
owned shutdown. A collector failure requires a collector prerequisite; it cannot
assert that platform transaction visibility or permission is unavailable.

Offline checks passed before live use: the actual reviewed receipt was copied to
a temporary directory and mutated (missing/wrong/negative help references,
stream one hour after shutdown, missing intervals/states and rehashed incomplete
help output). Real local fake subprocesses exercise concurrent 1 MiB stdout and
stderr backpressure followed by a bounded timeout, plus successful draining before
join. Fake collector tests cover delayed token journals, exact identity failure,
both interval boundaries, first-error retention, stream-finalizer failure and
ordered owned shutdown. They start no simulators. The accepted transport receipt
was independently hash-checked and verified read only before recollection.

### Authorized final collection: collector blocked, split required

The final-fix brief explicitly allowed at most one further launch per dedicated
family after the offline checks above. Exactly one was issued for each. The new
receipt is `.local/ios-scene-delivery/receipt.json`, SHA-256
`7afd5b41a7498591ebcd25192e548d43006d1414ed53393551d33ab7bbb82d1d`.
The prior failed tree remains separately retained, byte for byte. **No additional
launch or tracing retry is authorized for this unit.**

| Family | System boundary | App observation | Delivery / acknowledgement / delegate |
| --- | --- | --- | --- |
| iPhone | Open request and FrontBoard app connection observed; no server registration matched | PID63836, exact executable/path/token checked before and after 10:54:07.012048–10:54:19.207313Z (12.195128s); 1,038 scoped events, 680 exact app events; six token journal markers | All unknown; no persistent-session transaction candidate; zero connected scenes in journals |
| iPad | Open request and FrontBoard app connection observed; no server registration matched | PID64956, exact executable/path/token checked before and after 10:54:44.967839–10:54:57.166027Z (12.198057s); 1,105 scoped events, 680 exact app events; six token journal markers | All unknown; no persistent-session transaction candidate; zero connected scenes in journals |

Both live help commands returned usage exit64 without timeout and exposed scoped
debug/ndjson/deadline capabilities. Both launch RPCs timed out12s and exited-9;
the separate exact live process checks show that the app survived those RPCs.
RPC completion is not app acceptance. Journals were retained after each full
12-second interval, at 10:54:19.218154Z and 10:54:57.175470Z. Their persistent
session IDs still match the predecessor (`EC029773-D8BE-449B-BD48-BBA343785F28`
and `FF7C1CCE-3288-44C4-AF46-793F65CC8BB4`). No ID is reconstructed or invented.

Despite asynchronous draining and passing fake-subprocess backpressure tests,
both native `log stream --timeout 28` children failed to return within the
independent30s deadline. They were killed with exit-9 and `timed_out=true`.
The recorded primary cause on each is exactly
`collector live stream failed: exit=-9; timeout=True`.
The retained outputs contain the nonfatal `getpwuid_r` warning, not a permission
denial. Last retained event timestamps are 10:54:06.576884Z and
10:54:44.784251Z; no event-completeness or transaction absence is inferred from
the streams. The immediate child/pipe wait timed out; the underlying reason
native timeout failed to complete is unestablished. A full measured app window
and two live PID checks do not repair this collection failure.

This is **collector blocked**, the second failed live attempt, requiring a split
or premise challenge. It is not a proven missing platform-observability
capability. The exact next bounded prerequisite is a separate **no-app-launch
collector unit**: exercise simctl-spawn/native-log timeout and process/pipe closure
on the dedicated device with independently bounded cleanup, including a fake
subprocess with a descendant retaining pipe handles. Establish successful stream
termination and retained output before requesting any new app observation. Such
a new live prerequisite needs its own brief; this unit performs no further live
work. Debugger attach permissions, symbols and app transaction visibility are
still untested. No manifest/lifecycle source defect is established.

Both successful shutdowns followed stream finalization: iPhone
10:54:24.761282–10:54:28.122058Z and iPad
10:55:02.709489–10:55:06.048180Z. They exited0 without timeout; final states are1.
A read-only `closeout.json` rechecks exact device identities, Shutdown and the
unchanged pinned installed file maps. Private commands retain argv, UTC intervals,
exit/deadline, output and raw-stdout hashes; no prior receipt was edited. Tests
also verify the historical unavailable observation and accepted transport receipt.
Runtime remains **26.5 tested / 26.0 minimum**; physical devices, app startup,
game frame/gameplay and semantic coverage are unaccepted; cross-ISA byte match N/A.

The parent must obtain an independent **Astra/medium whole-head review** before
`scripts/land`. This final fix does not waive that gate, start a nested review,
land, push, create a PR or change any provider/auth resource. Passing both exact
VERIFY commands validates retained blocked evidence and the offline repairs;
it does not fulfill app-delivery/acknowledgement acceptance.
