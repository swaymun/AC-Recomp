# IOS-COLLECTOR-FILTERED-007: filtered collector prerequisite

Both dedicated simulator streams completed bounded collection below the output
cap. This establishes only the five-second, narrowly filtered no-app collector
prerequisite. It establishes no event absence, logging capability, app activation,
scene delivery, acknowledgement or startup/gameplay acceptance. No app was built,
installed, launched, activated or recollected. This unit's one-stream-per-family
live allowance is exhausted; do not rerun it.

## Fixed mode and preserved contracts

The distinct CLI is `--collect-filtered-collector FRESH_LOCAL_DIRECTORY/receipt.json`,
where the directory is fresh and under ignored `.local`. There is no caller
predicate or nonce CLI argument. `secrets.token_hex(16)` generates an unpredictable
per-run nonce. Only exactly 32 lowercase hex characters can enter the predicate:

```text
process == "SpringBoard" AND eventMessage CONTAINS "IOS-COLLECTOR-FILTERED-007-<nonce>"
```

Both families share that run nonce. The actual argv retains `eventMessage`; native
`log` renders it as `composedMessage` in its filter banner. The command uses native
`--timeout 5`, with a separate 12-second supervisor plus at most 0.5-second cleanup.
The local timeout help/man-page grammar remains checked and retained. The existing
8 MiB per-pipe cap, concurrent draining, full-observed and retained-prefix hashes,
reserved process-group identity, EOF chronology and first-error rules remain
unchanged. Children have 8–20-second requested limits (maximum supervision bound
20.5 seconds); each family is bounded below 120 seconds. A stream cannot qualify
with truncation, missing/late EOF, unequal full/retained hashes, unknown byte counts,
a nonzero exit or a supervisor timeout. Counts must be strictly below the cap.

An exact available live/plist UDID, name, device type, runtime and Shutdown state
are required before boot. Already Booted blocks that family without shutdown.
Only these dedicated devices may be booted or shut down. Stream finalization
precedes shutdown and exact live/plist Shutdown re-verification. Historical
`--collect-collector`, transport/delivery collection and `--verify-saved` contracts
are preserved. Filtered receipts are a separate investigation format, not scene
acceptance. CLI exit 2 deliberately preserves the blocked scene-prerequisite status.

## Independently checked predecessor identities

Read-only checks before and after the live sequence matched predecessor HEAD
`1ea1c66e454f35280a82a2f6808a593eaca093c9`, its committed and worktree collector
source, preserved executed source, live and closeout receipts, all 17 command-output
files, and the historical delivery receipt. No predecessor file was changed.
The inherited Astra review identity in the brief is `Astra5f097465`; this unit
verifies the exact underlying bytes and does not replace that review.

| Preserved IOS-COLLECTOR-006 identity | SHA-256 |
| --- | --- |
| Committed/worktree collector source | `fe0b31d4befb6dee03dab756165ccabd4bc9f7c1ff46a97e8a8d931b84f4a38a` |
| Live executed collector-source.py | `8818318f9f5bc96cca82cc4217228775705559d54f4dfff73102f16333ebcde2` |
| Live receipt.json | `937df12b84229319d42eedcc9474f346d672d508cdf51ec7b79c7f12c9a46d30` |
| Closeout receipt.json | `8928c720849f1b96929752b5c997d1d0c881ce958275b3a8f22a66bf2462848f` |
| Historical delivery receipt.json | `7afd5b41a7498591ebcd25192e548d43006d1414ed53393551d33ab7bbb82d1d` |

The predecessor remains blocked: native exits and both EOFs succeeded, but the
8 MiB output cap failed. Its old raw hashes describe retained prefixes; the full
observed hashes added later are not retrospectively attributed to that experiment.
The older 28-second collector failure remains unexplained.

## Measured live sequence: 2026-10-18 UTC

| Family / dedicated UDID | Stream UTC | Stream seconds | Whole family seconds | Native exit / EOF / truncation |
| --- | --- | --- | --- | --- |
| iPhone `883683CC-F98A-4B53-9FC8-F02E60A52F30` | 11:23:39.072391–11:23:44.904117Z | 5.831726 | 14.404084 | 0 / both before signal / false |
| iPad `6D9DC697-AFFB-4C27-A8A7-44A83AA3B367` | 11:23:53.797591–11:23:59.617199Z | 5.819608 | 14.734586 | 0 / both before signal / false |

Both identities matched `com.apple.CoreSimulator.SimRuntime.iOS-26-5`, with names
`ACS IOS-HOST-002 iPhone` / `ACS IOS-HOST-002 iPad`, and device types
`iPhone-17-Pro` / `iPad-Pro-11-inch-M5-12GB`. Both were initially Shutdown/state 1,
available, and finally verified Shutdown/state 1. No other simulator was stopped.
Final identity UTCs: iPhone 11:23:48.581024Z; iPad 11:24:03.316395Z.

Each stream observed and retained exactly 172 stdout bytes and 44 stderr bytes.
Stdout contains the predicate banner and `{"count":0,"finished":1}`; stderr is
`getpwuid_r did not find a match for uid 501`. The warning did not change native
exit 0. Zero event records support no event-absence or capability inference.
Full-observed and retained hashes are identical for both families:

| Bytes | Full-observed SHA-256 = retained SHA-256 |
| --- | --- |
| stdout (172) | `692caeb95a8fd18e027a38e20c627f6205c1f132cf57af4a6edd8ac0881e819d` |
| stderr (44) | `8b9e4a529f3e367142876bd0ce03ed7c7f10a50657c9a73fda0d6e30867e7523` |

All 14 command output hashes and the exact executed source snapshot were checked
offline after collection. The live source base HEAD is
`2b9b3dccbd19923d5846d8d08db9a9c1f3140e89`; the code was uncommitted at execution,
so the snapshot hash, not that base HEAD, identifies the executed implementation.
The snapshot matches the final committed collector bytes.

| Fresh ignored artifact under `.local/ios-collector-filtered-007/` | SHA-256 |
| --- | --- |
| `live/receipt.json` | `23ea40f1833182ccb7fd7a8062251d73041614b8d1e9beb692e18596b7cbe170` |
| `live/collector-source.py` | `a6bd53f7ce07214a058d50ec08c1c6541b0e2c992c91ff16e6d34297c6500db7` |
| `live/command-005.json` (iPhone) | `1bd8c71e2963991f1c23185a779f8ad2da1691684dd83f865a36cd16fe90d095` |
| `live/command-012.json` (iPad) | `1bd8c71e2963991f1c23185a779f8ad2da1691684dd83f865a36cd16fe90d095` |

Every command retains argv, UTC intervals, exits, timeout, full/retained hashes,
observed byte counts, EOF times, signal outcomes and truncation. Both stream group
signal attempts returned EPERM after native exit and EOF. These are recorded as
**group signal failed; descendants unknown**. Neither exit/EOF nor subsequent
scoped shutdown proves escaped-host-descendant absence. Dedicated-device shutdown
returned 0 and exact state restoration succeeded. No global cleanup was attempted.
Private files remain retained and ignored.

## Offline validation and next bounded gate

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_ios_scene_diagnostics.py' -v
```

All 62 tests passed, without skips in this workspace. New tests cover exact
predicate identity and injection rejection, incomplete/truncated/at-cap rejection,
first-error preservation and ordered single-stream cleanup with fake commands,
private historical receipt/source identities, and temporary-Git predecessor/output
mutation rejection. Historical delivery receipt mutation checks also run read-only
against a temporary copy of the predecessor receipt.

Stop at this collector prerequisite. Parent must commission independent
**Astra/medium whole-head review of the final committed head** before `scripts/land`.
No nested worker or review was started; the review gate is pending, not waived.
After review, a separate bounded scene-evidence brief must establish app/scene
request and acknowledgement evidence with suitable collection; this idle predicate
cannot collect that evidence. No app launch or further live attempt is authorized
by this unit. If subsequent evidence needs a different predicate/window/cap, resolve
that exact collection prerequisite under a new brief before app observation.

All four platform families remain in scope: macOS/Linux partial; Windows blocked
by unready Windows cloud machine controls; both simulator startups blocked until separate scene
evidence. **26.5 tested / 26.0 minimum target**; physical acceptance unverified.
Cross-ISA byte match N/A; overall semantic/gameplay coverage unknown. Parent owns
providers/auth; no provider, SSH, paid inference or spending action occurred here.
The run retains its 14:30Z cutoff, 15:00Z deadline and (amount omitted) total cap.
