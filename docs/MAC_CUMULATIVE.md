# MAC-CUMULATIVE-038: cumulative native macOS acceptance

The cumulative supervisor requires APM030 at reviewed/landed commit
`791031333db04f67688c47b868bcd1ab5be4b246`, alongside the fixed logger,
audio and notification dependencies. Missing APM review, landing or patch content
blocks integration; an APM-excluded launch cannot establish progression.

Shared preparation retains the original `a8984f8a6c9986b4261fb515bb6f9005e2940639`
identities for every support file and base patch. The sole alternate identity is
`tools/prepare_runtime.py` from IOS036 exact reviewed/landed head
`73ceb0c65016615b29cb02354d75ae29acf26a90` (SHA-256
`0119b0b8112a89042218f81a8ae179bd06ae4aed4e683fe1cc8fa8f3383feb53`).
Accepting that alternate requires the passing independent Astra/medium review,
matching normalized patch and producer identities, exact declared scope, ancestry
in both main and the worker, and matching reviewed/landed contents for
all IOS036 files. The consumed helper must also match the current bytes exactly.
Unrelated current scope drift requires explicit independently reviewed landed
supersession, as described below. IOS036 uses the fixed review base
`791031333db04f67688c47b868bcd1ab5be4b246`: its two-commit final patch
reproduces the independently reviewed normalized identity
`ca67834827f87f427aa19eb89814da222d7be7582da97326c3c24df9a0572929`.
Its dispatch ledger base predates the APM landing, so that stale base and the
immediate parent cannot reproduce the final review. No arbitrary ancestor search
is used during acceptance. Unknown preparation or other support drift fails closed.
Temporary-Git tests exercise acceptance, unreviewed support drift, wrong
preparation contents, altered review and missing main/worker ancestry.

Use the absolute-path invocation documented in SERVICE_BATCH_STARTUP.md with a
fresh ignored `.local/mac-cumulative-038/` output directory in this assigned
worktree. The private prior SERVICE034 supervisor receipt supplies existing
input, generated-source, control-metadata, pinned reference and dependency paths.
No regeneration, providers, credentials or runtime patch changes are involved.
The original authorization, deadline, budget, worker, process ownership,
strict/high-memory compilation and bounded real-launch controls remain active.

The parent must independently review the exact supervisor commit with
Astra/medium before the cumulative run. This worker cannot start nested workers;
review is requested through the store inbox and is never waived. Measurement
revision and later documentation revision will be reported separately.

macOS acceptance remains partial/blocked until real guest evidence is measured.
Linux, Windows, iPhone simulator and iPad simulator retain their separate
partial/blocked status; this unit establishes no physical-mobile acceptance.
Only genuine inspected game visuals warrant private screenshots/short clips,
official-reference comparison and a parent visual-update announcement.

## Pre-run result, 2026-10-18

**Execution pending independent review; no native runtime measurement.** The
committed supervisor implementation is `0a0e8b66507e448652452adcc5ee428c32fdbe05`;
this documentation closeout is a later commit. Its source SHA-256 is
`477a36bd9708d9f260af1ead297f34f87f5a3304a85b19dc30fc0c88226d16a0`.
The direct real-repository preflight verified all four mandatory reviewed service
dependencies, including APM030, the exact IOS036 alternate preparation identity,
and current authorization controls. APM is required by code and preflight, but
**inclusion in a built executable remains unmeasured**.

At **17:08–17:15Z**, the worker requested pre-run Astra/medium review through the
store inbox and held execution. All three worker/review slots were occupied.
The lead checkpoint at **17:15:02.124920Z** requested that the running producer
finalize its scoped report so `orch review` can start, explicitly leaving
execution pending. This is a review scheduling block, not guest progression.
Independent review has not been waived or represented as passed.

Private receipts remain in this worktree's `.local/mac-cumulative-038/`:
`preflight.json`, `tests-pre-run.log`, `executed-supervisor.py`,
`launch-argv.json` and `pre-run-closeout.json`. The launch argv receipt SHA-256 is
`de8ad60be3ba76631f83ab01b4d07b7fc3c61caec7f30bd405d033ddb6517979`;
it reuses the original existing input/reference/generated-source paths privately.
The closeout records their receipt identities and hashes with a UTC timestamp.
The intended `native-1/` output directory still does not exist. All private input,
generated-source and prior native artifacts are retained in place.

The required supervisor tests pass **18 tests**, including real temporary-Git
provenance failures and real subprocess ownership/timeout cases. The intentional
reverse-order patch fixture emits a patch rejection and passes its assertion.
No runtime patches, source regeneration, provider or account actions occurred.

No configure, native compilation, executable or real guest launch was performed
in this pass. The 395-TU build and strict/high-memory profile verification remain
pending. No new guest boundary can be identified: the prior SERVICE034
**ISession command 0** stop excluded APM030 and cannot count as a result for this
composition. **Zero inspected game frames**, no screenshot/clip, no visual-update
announcement and no gameplay claim. This does not prove zero rendered frames in
an executed guest, because there was no guest execution.

Required scoped follow-up: independently review the final committed head with
Astra/medium, then run its supervisor from this committed assigned worktree using
the retained exact argv and a fresh output directory. Measure the full native
395-TU build, both required defines on every TU, APM patch/source inclusion,
real bounded guest startup, safe observed dispatches, first actual unsupported
boundary and retained artifact hashes/timestamps. Keep supervisor/runtime and
later documentation revisions distinct; inspect genuine visuals if any appear.
No speculative successor handler is authorized here.


## MAC-PROVENANCE-042: source provenance correction

This is a pre-run guard correction. It does not satisfy MAC040 native execution
acceptance or reset MAC040's retained first review failure. Independent
Astra/medium review of the exact final head is required before landing. A separate
MAC040 continuation must then perform a fresh bounded 395-TU native build with
two jobs, prove both required defines on every TU and APM inclusion, and measure
actual guest startup and the next strict boundary. No native build or guest
launch is authorized in this correction pass; gameplay remains unverified.

The historical review check still authenticates every file in the original
scope, the producer and independent Astra/medium identities, the normalized
patch, exact scoped landing equality, review-base ancestry, and landing ancestry
in main and the worker. Service dependencies retain their full current-scope
byte checks. Shared preparation requires the exact authenticated consumed helper
and original base/support patch bytes; a changed helper remains a hard failure,
even if a later iOS review accepts that helper for a different composition.

For non-consumed historical scope files only, drift must resolve through a
unique landed ledger successor whose explicit dependency edge names the original
unit and whose scope includes that file. The successor receives the same full
historical review/patch/scope/landing/ancestry validation. Its review base must
follow the original landing and retain the original file bytes; this rejects
unreviewed interim drift. All current successor scoped files must match, or be
explained by the same checks along an explicit successor chain. Missing,
ambiguous, cyclic, unreviewed or incorrect successors fail closed. No mutable
hash allowlist or hardcoded exemption for future iOS commits is used.

On the current source baseline, IOS-HOST-037 exact/landed head
`682713e6351811fa5c5055c0f08e56de41a5e621`, independently reviewed patch
`e4198acd4b6b60dc75af9933d6f2263b1f5d9c4320f4b375c82088e770fc6638`,
accounts for the four superseded IOS036 files: the iOS runtime overlay, App.mm,
iOS runtime tests and iOS runtime documentation. These are not consumed by the
Mac composition. The supervisor retains their review identities and file hashes
as private evidence alongside the original IOS036 identity. The consumed
`prepare_runtime.py` remains SHA-256
`0119b0b8112a89042218f81a8ae179bd06ae4aed4e683fe1cc8fa8f3383feb53`.

Temporary Git/subprocess coverage preserves the original 18 tests and adds
reviewed unrelated supersession, consumed helper and patch tampering, invalid
successor identities/scopes/dependency edges/patches/reviews, missing reviews,
both ancestry requirements, unreviewed interim or subsequent drift, and malformed
controls. Pinned reference/input validation, clean source, patch ordering,
strict/high-memory flags, budget/deadline/STOP and owned-process guards remain
required. Private preflight receipts are retained under this worktree's ignored
`.local/mac-provenance-042/`; their exact hashes belong in the worker report.
