# IOS-COLLECTOR-006: bounded collector prerequisite

This is a **blocked collector investigation**, not scene startup or gameplay
acceptance. Exactly one no-app-launch system stream was run per dedicated family.
Both native streams exited 0 and reached stdout/stderr EOF, but both exceeded the
8 MiB retained-output cap. No successful collection, event completeness, event
absence, scene delivery, acknowledgement or platform capability limit is inferred.
No app was built, installed, launched, activated or attached to a debugger.

## Offline findings and ownership policy

The baseline is parent source `3825a46` (including landed delivery prerequisite
`8e1fac1`). All 43 existing tests remain, including receipt integrity and mutation
rejection. In this workspace the historical private receipt is available read only,
so its formerly skipped test also runs. New real-process fixtures establish:

- An immediate parent can exit 0 while a descendant retains both pipe handles.
  The original collector waited until its deadline instead of completing cleanup.
- A descendant can close both pipes and keep running; immediate-parent exit and
  pipe EOF alone do not establish descendant cleanup. The original collector
  returned success without terminating that descendant.
- An escaped-session pipe holder caused the original group signal to raise
  `PermissionError` on this Mac. The old second `communicate(timeout=2)` could
  also raise; it supplied neither a complete-cleanup proof nor an EOF receipt.
- Concurrent 1 MiB stdout/stderr output followed by timeout must keep draining.
  A separate escaped fixture is self-expiring; no guessed or global PID is killed.

Baseline observations are private in
`.local/ios-collector-006/{baseline,lifetime-baseline}.json`. The exact inherited
pipe baseline exited 0 after 0.804s; the escaped case raised after 0.802s; the
closed-pipe descendant case returned 0 after 0.072s while its descendant survived.
These are observations of distinct fixtures, not an explanation for the historical
28-second native stream failure.

The production runner now drains nonblocking stdout and stderr through a selector.
It checks the newly created session/group identity and keeps its direct child
waitable with `waitid(WNOWAIT)` until **after** the final group signal. This reserves
the leader PID against reuse while cleanup targets that group. A very fast child
already observed as exited remains reserved, even though Darwin rejects its
`getpgid` query. Unsafe live group identities are rejected without group signals.

When the direct child exits, or the execution deadline expires, SIGKILL targets
only this reserved group. There is no graceful-wait phase: the event records this
hard-stop policy explicitly. Exit observation, signal outcome, escalation policy,
per-pipe EOF times, truncation and unknown descendants are separate fields. A sent
signal is not proof that escaped descendants died. Service-side simulator
processes also lie outside the host group; dedicated-device shutdown contains
that side of this experiment. No process-name kill or global reset is used.

The execution allowance is `min(requested_timeout, 29.5)` seconds, with at most
0.5s additional cleanup, keeping process supervision at or below 30s. Reads and
child-exit checks do not block. At the hard end, pipes close locally even when EOF
is unknown; the result fails and cannot support an absence inference. Each pipe
retains at most 8 MiB while excess bytes are drained. The final implementation
hashes/counts all bytes actually read separately from each retained prefix. The
first failure survives later timeout, EOF and cleanup errors. Stream joining also
has a finite deadline. Trusted non-Popen test doubles retain their injected
transport; actual Popen objects, including factory-wrapped ones, use supervision.

An EOF reached only after group intervention does not establish native pipe
completion. The final implementation records `eof_before_group_signal` and requires
it before labelling a future native stream complete. `collector_complete` describes
retained IO/child completion, never proof that every descendant is gone.

## Local capabilities and exact live experiment

`xcrun simctl help spawn` returned 0. Its deprecated `--standalone` uses a NULL
Mach bootstrap port, preventing connection to simulator services; it was not used.
Each dedicated simulator's `log help stream` returned usage exit 64 with complete
pipes and documented:

```text
--timeout <num>[m|h|d]          Terminate streaming after timeout has elapsed
```

The local `/usr/share/man/man1/log.1` explicitly states that omission of minutes,
hours or days means seconds. Its SHA-256 is
`ffea5e751ff3a2bdf5b3a126b4d0ed17e3e43bdabe9ee823c8b4cde7ea11b35a`.
Thus the experiment used unsuffixed `5`, not an unsupported `5s` suffix.

For each exact UDID below, the only stream command was:

```sh
xcrun simctl spawn UDID log stream --style ndjson --level debug --timeout 5 --predicate 'process == "SpringBoard"'
```

Its independent execution deadline was 12s (12.5s including cleanup). Every child
was bounded below 30s and each full family sequence below 120s. Boot, help and
identity commands had their own 8–20s limits. Identity queries selected the exact
UDID, then matched live runtime, name, type, availability and state against its
on-disk plist before boot and after shutdown. An already booted session is left
unchanged and blocks this experiment, since restoring that session after a
service-side cleanup failure has not been established.

| Family | Exact identity | Stream UTC interval | Exit / EOF | Total family |
| --- | --- | --- | --- | --- |
| iPhone | `883683CC-F98A-4B53-9FC8-F02E60A52F30`, ACS IOS-HOST-002 iPhone, iPhone-17-Pro | 11:08:16.521364–11:08:22.018207Z | 0; both EOF; 5.496843s | 11.596457s |
| iPad | `6D9DC697-AFFB-4C27-A8A7-44A83AA3B367`, ACS IOS-HOST-002 iPad, iPad-Pro-11-inch-M5-12GB | 11:08:28.376755–11:08:34.056214Z | 0; both EOF; 5.679459s | 11.933573s |

Date is 2026-10-18. Both identities matched runtime
`com.apple.CoreSimulator.SimRuntime.iOS-26-5`, initially Shutdown/state 1 and
available. Both native exits preceded the supervisor deadline and both pipe EOFs
preceded group-signal attempts. Group signalling returned EPERM on the now-exited
leaders; this is recorded as an **unknown descendant outcome**, not absence.
A later scoped `pgrep -g 16274,16809 -l` exited 1 with empty stdout/stderr: neither
recorded host stream group had a matching process at closeout. This does not
establish absence of escaped descendants.

Both stream command records retain the primary failure `output byte cap exceeded`.
The family summary in the original live receipt is less precise (`native stream
exit/EOF failed; collector blocked`); command-level evidence establishes that EOF
actually succeeded and truncation blocked collection. The final code propagates
the precise underlying error. The live receipt is preserved unchanged.

| Retained stream output JSON | SHA-256 |
| --- | --- |
| `live/command-005.json` (iPhone) | `2d946aa7d8ae860d5004798bf37b035fa7d87602775777662a633d81f7df4bb7` |
| `live/command-012.json` (iPad) | `7ff72de0e1e866335afadff2664f67fb5184086065cbc2f859ab6ddee9753c39` |

The preserved live runner's `raw_stdout_sha256` hashes its **retained 8 MiB
prefix**, not discarded overflow. Its total raw stream hash and exact overflow
length are unavailable. The final implementation adds incremental full-observed
hashing, observed byte counts and separate retained-prefix hashes; that improvement
is tested offline and was not retrospectively attributed to the live experiment.

Private receipt directory: `.local/ios-collector-006/`. `live/receipt.json` SHA-256:
`937df12b84229319d42eedcc9474f346d672d508cdf51ec7b79c7f12c9a46d30`.
It records parent source HEAD plus exact executed collector hash
`8818318f9f5bc96cca82cc4217228775705559d54f4dfff73102f16333ebcde2`;
`live/collector-source.py` preserves those executed bytes. Final offline refinements
are distinguished from this live source. Every command retains argv, UTC intervals,
exit, timeout, signal/EOF fields and output hash. Logs stay ignored/private.

## Ordered cleanup and next gate

Stream finalization preceded shutdown on every attempted boot. iPhone shutdown
11:08:22.115220–11:08:25.518146Z and iPad shutdown
11:08:34.134295–11:08:37.462896Z both exited 0 without timeout. Exact live/plist
identity checks verified Shutdown/state 1 afterward; the separate closeout repeated
those checks. Closeout receipt SHA-256:
`8928c720849f1b96929752b5c997d1d0c881ce958275b3a8f22a66bf2462848f`.
No prior receipt or worktree was modified; the prior delivery receipt still hashes
to `7afd5b41a7498591ebcd25192e548d43006d1414ed53393551d33ab7bbb82d1d`.
All private files are retained. No further live stream or app evidence is collected.

The smallest distinct next experiment requires a separate brief: keep the same
5-second native / 12-second supervisor limits, and narrow the predicate to
`process == "SpringBoard" AND eventMessage CONTAINS "IOS-COLLECTOR-006-<nonce>"`.
This isolates idle-stream termination/EOF below the cap; empty output cannot prove
platform or transaction absence. Establish complete bounded collection before
requesting another scene observation. The earlier 28-second timeout cause remains
unestablished; a working 5-second system stream does not resolve that difference.

Offline executable checks (no simulator operation):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ios_scene_diagnostics.py' -v
git diff --check
```

The collector CLI is `--collect-collector FRESH_PRIVATE_DIRECTORY/receipt.json`
under `.local`; **this unit's live allowance is exhausted**. Historical
`--verify-saved` compatibility remains intact for transport and delivery receipts;
the collector receipt is a separate investigation format, not scene acceptance.

Independent **Astra/medium whole-head review** is required from the parent before
`scripts/land`; no nested worker/reviewer was started and the gate is not waived.
Both simulator scene startups remain blocked: **26.5 tested / 26.0 minimum**.
Physical acceptance is unverified; macOS/Linux are partial and Windows blocked.
Cross-ISA byte match is N/A; overall semantic/gameplay coverage is unknown.
