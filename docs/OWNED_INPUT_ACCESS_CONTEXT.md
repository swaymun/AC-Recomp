# INPUT-CONTEXT-017: access-context comparison is inconclusive

No useful difference in existing OS access context can be established from the
retained evidence. The smallest evidenced execution difference is the importer
binary identity and invocation purpose: historical full importer versus later
patched native diagnostic and Python descriptor walk. This is not evidence that
binary identity caused the block. The successful import's parent/application
provenance is absent, so the premise that another worker-side probe can isolate
an access-policy difference is unsupported. Do not retry source access or change
permissions on this evidence.

## Retained success versus failure

| Case | Direct retained observation | Missing context / interpretation limit |
|---|---|---|
| Historical successful parent import | `real-import-state.json`: PID 20161, started 2026-10-18T08:16:31.453547+00:00, complete, exit 0, 56.59 seconds; importer SHA-256 `d9521d8414c837890655ff34032ceb5e3362bde315da1aeed60b1015219a91d0`; pin `010ed7a596a621c15d3a8dfa5795ca8c3668b066` | No PPID, comm, launch command, responsible application, signing identity, entitlement or access grant. Do not inspect a current process with this historical PID: PID reuse would not recover provenance. |
| Canonical adoption | Adoption receipt and manifest bind the same parent state/log/tool hashes; retained parent log hash matches the adoption record | Historical extraction did not begin with an NSP hash. Adoption is historical corroboration, not current readability. Manifest's wrapper-built binary hash `3f97380d52f3cdb228fbd91fdaf786398c3517d61d311f85e2fe3d1aad1c8e35` is distinct from the original parent tool; do not substitute it as the successful process. |
| CONTROL-METADATA-015 staged native child | Receipt names private `nximport-probe-2`, hash `910c7c934b846bc27f576c90a613968d1e3f374c14a8a67a9f578731ff691dc8`; 12:04:18.499737–12:04:28.632297 UTC, exit -9; retained `opening_input_0` localizes the first key-path open interval before `run_import` | Exact native executable and command are retained; no native PID/PPID, OS access attribution or observed errno. Not a source-read or encryption result. Final rebuilt probe's different hash is not this executed child's identity. |
| INPUT-READ-016 Python children | Receipt names `/opt/homebrew/opt/python@3.14/bin/python3.14`; synthetic read returns 4096 bytes; path lstat succeeds; descriptor walk last marks Documents ancestor open, then exit -9 at 12:18:19.212826 UTC | Receipt records command/interpreter but not actual historical comm or ancestry. Same argv interpreter spelling does not establish identical historical binary bytes or OS access attribution. No final source open/read was reached. |

The CONTROL-METADATA-015 full hash timeout has no intermediate progress and is
not evidence of an open failure. The native key-path interval and Python ancestor
interval also differ in operation; they cannot establish a common policy cause.
No keys, source files, source metadata, xattrs or directory listings were queried
in this unit. The parent log was hashed only to match its retained adoption
identity; raw log text was neither printed nor copied into the new receipts.

## One live context phase, now closed

2026-10-18T12:26:00.484365–12:26:00.517944 UTC; elapsed **0.033593250 seconds**.
The collector and four ancestors were inspected, five processes total. Only
PID, PPID, state and comm were requested. The following are parsed fixed-field
observations, not argv. Exact comm paths remain in the private receipt.

| PID | PPID | State | comm observation |
|---:|---:|---|---|
| 80037 | 72520 | Ss | Homebrew Python 3.14.7 Python.app executable (owned receipt collector) |
| 72520 | 72512 | S | Homebrew Codex vendor `aarch64-apple-darwin/bin/codex` (current worker) |
| 72512 | 72498 | Ss | `node` (no absolute binary path reported) |
| 72498 | 1 | Ss | Same reported Homebrew Python executable path |
| 1 | 0 | Ss | `/sbin/launchd` |

The observed worker chain ends in Python parented by launchd. No interactive
terminal appears in this snapshot. This does not prove the successful import
used a terminal, identify a TCC responsible application, or show a changed grant.
The chain is current, not a reconstruction of either predecessor's ancestry.

Exact commands, each run once with a 2-second timeout, all exit 0:

```text
/bin/ps -p 80037 -o pid=,ppid=,state=,comm=
/bin/ps -p 72520 -o pid=,ppid=,state=,comm=
/bin/ps -p 72512 -o pid=,ppid=,state=,comm=
/bin/ps -p 72498 -o pid=,ppid=,state=,comm=
/bin/ps -p 1 -o pid=,ppid=,state=,comm=
```

Private `context-phase.json` retains per-command UTC/exits and exact safe comm.
The one-shot collector was invoked as
`python3 .local/input-context-017/context-phase.py` (exit 0). It follows only the
returned PPID, caps the chain at eight and stops rather than retries on failure;
its command budget leaves cleanup time inside 30 seconds. Each owned `ps` child
had a new process group and was reaped. No timeout occurred. No descendant scan
was performed; descendants escaping an owned process group cannot be excluded.
Raw output was discarded after strict parsing. No second context batch occurred.
Signing inspection was omitted because there is no historical responsible
binary/context to compare; signing alone would not recover that missing fact.

Read-only launch-source inspection: `scripts/orchlib.py` `codex_argv`,
`run_codex`, `monitor` and `detach` build a CLI command from configuration and
launch worker/monitor with `start_new_session=True`; monitor stdin is DEVNULL and
worker prompt stdin is a pipe. This is compatible with detached orchestration,
but the current fixed ps fields do not prove the Python ancestor's script or
configuration, and the source does not establish the original successful launch.
No process args, environments, TCC databases, broad logs or unrelated processes
were inspected.

## Concrete next action and precise blocker

Parent should stop commissioning input probes against this boundary. The minimum
next check is a **single, at-most-60-second user-visible inspection for an already
pending macOS file-access dialog**: record only its requesting application's name
and requested folder category, or “no pending dialog observed.” Do not trigger a
new request, open the inputs, click either response, or change any setting. This
check has not been performed here and does not presume a prompt exists. It asks
for an observation, not an owner permission decision. If no prompt is observed,
retain “cause unknown”; absence of a visible prompt proves no policy diagnosis.
The missing historical launch/application attribution remains the precise
comparison blocker. A later investigation needs new, separately scoped evidence
before selecting any access change or renewed input operation.

[Apple's official file/folder access guide](https://support.apple.com/en-euro/guide/mac-help/mchld5a35146/mac)
documents per-app Documents access controls under Privacy & Security > Files &
Folders (retrieved 2026-10-18). This establishes only a possible policy dimension;
it does not identify this process's attribution, establish a pending prompt,
explain blocking behavior, or justify changing a grant. No settings were opened.

## Evidence identities and delivery boundary

Private ignored receipts are retained under `.local/input-context-017/`; safe
projections redact source-path arguments instead of copying their exact argv.
Original exact predecessor commands remain in the read-only predecessor receipts,
bound by hashes below. No source arguments were executed here.

| Retained original artifact | SHA-256 |
|---|---|
| INPUT-READ-016 `run-0524986v/receipt.json` | `0d6df77cee39e2f059f639cf4a0687673f8b2385f742564224ea52c2357c8cf9` |
| INPUT-READ-016 `path-metadata.json` | `d3ca4594624b2eb9dd686c10f12c5f888584111389d8b15627b693154f2a3d20` |
| CONTROL-METADATA-015 `staged-probe-command.json` | `0ec1c51483c1c1eac25e2f322d4109a6a8dca73208d830ae8ebc809fe987748b` |
| CONTROL-METADATA-015 `audit-92z353eg/receipt.json` | `44ba56ae63d629300de3d52b392732a26956c5502ea1e935b0771907b6c63ab5` |
| Parent `real-import-state.json` | `7677676d03c7a1b6be70ba6207715c545d828faf22ade84f332ddd3346d44d0a` |
| Parent `real-import.log` | `a33d21eea45e0b95f6407ae82d54650d60fc11a8280024349cf3ba2ed4229836` |
| Canonical `.wrapper/adoption.json` | `721e6f39a159f1285709d676dfb718ab6abff9836004a67d0368f17760f8ea09` |
| Canonical `.wrapper/manifest.json` | `fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d` |
| This unit `context-phase.json` | `c6ff04c75282a8e515f4397de998be9c9c61c35b7aa07c32fd4fd71e748d7a00` |
| This unit `context-phase.py` | `631ff3d0525f857fdff5cf0cc296f8a8affaa57c21b2dd716b4c2d0aaef93ee5` |

`predecessor-receipts.json`, `historical-provenance.json`, `source-identities.json`
and `apple-policy.json` retain selected safe observations and identity records.
The Apple receipt is a paraphrase of the tool retrieval, not archived page bytes.
A final artifact index binds these files. Only this original documentation is
tracked. Required verification is `git diff --check`; no input tests were rerun.
Parent must commission independent Astra/medium review of this Sol/high exact
head before `scripts/land`; no nested review or waiver occurred.

No game progress is claimed. macOS/Linux remain partial; Windows, iPhone
simulator and iPad simulator remain blocked. Report 26.5 tested / 26.0 minimum;
physical acceptance unverified; gameplay/overall semantic coverage unknown;
cross-ISA byte match N/A. No provider, authentication, SSH, VM, game or mobile
operation occurred. Parent retains deadline/budget responsibility (15:00Z,
14:30Z dispatch cutoff, (amount omitted) total, maximum three workers including reviews).
