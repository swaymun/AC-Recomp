# SERVICE-BATCH-034 cumulative macOS startup

`tools/service_batch_startup.py` composes the exact reviewed logger/bootstrap,
AudioOut and notification overlays through `prepare_runtime.prepare_source`'s
existing ordered-list interface. It changes no shared runtime or preparation
file. APM030 is included only when its exact review and landing already exist;
there is no wait for that unit. No other service overlay is accepted implicitly.

The supervisor validates the current afternoon authorization digest, four target
families, (amount omitted) total cap, three-worker cap, mode, STOP marker, same-day controls,
20:30Z dispatch cutoff and 21:00Z deadline. It checks fixed required dependency
heads, independent Astra/medium passing review records, normalized exact commit
patch identity, main/worker ancestry, landed file equality and current file
hashes. The reviewed base must reproduce the exact normalized patch identity, using
the ledger base or actual commit parent. This supports multi-commit fix rounds
and clean rebases whose dispatch ledger base predates the final review. Normal
review metadata/final pairs and combined recovered-review records are supported. Shared
preparation and base patch files must match main snapshot
`a8984f8a6c9986b4261fb515bb6f9005e2940639`.

Inputs, control metadata and existing regenerated main/sdk are validated by the
shared preparation functions before composition and again before launch. The
Wonder reference must be clean at `010ed7a596a621c15d3a8dfa5795ca8c3668b066`.
There is no regeneration. Full composed source fingerprints, ordered patch
hashes, input/control/generated identities, compile database, executable, logs,
outputs and UTC timestamps remain private under a fresh ignored worktree
`.local` directory. Unsafe paths, links, tracked outputs, overlapping inputs and
existing output directories are refused. Original inputs and private evidence
are retained, never deleted during cleanup.

The overall parent process bounds validation, preparation, one configure, one
build, launch and evidence collection to at most 25 minutes, reserving ten seconds
for termination. Build jobs are 1 or 2. Every translation unit must carry exactly
`NX_APPLE_HIGH_MEMORY=1` and `NX_ASTRAL_STRICT=1`; both generated modules must occur
in the compilation database. Launch is at most 60 seconds. Children use argv
lists without a shell. Process groups are isolated and observed descendants are
tracked across Ninja's separate groups; cleanup signals only owned groups.
Stage stdout and private guest trace are capped at 16 MiB. There is no provider,
credential, simulator, network or account operation.

Run from the committed assigned worktree, supplying absolute paths:

```
PYTHONDONTWRITEBYTECODE=1 python3 tools/service_batch_startup.py \
  --root /absolute/canonical/repository --repo /absolute/assigned/worktree \
  --store /absolute/canonical/repository/.local/orchestrate/2026-10-18-afternoon \
  --reference /absolute/private/pinned/reference --inputs /absolute/private/astral \
  --gen /absolute/private/existing/gen --control-metadata /absolute/private/receipt.json \
  --out /absolute/assigned/worktree/.local/service-batch-034/measurement \
  --cmake /absolute/cmake --ninja /absolute/ninja --prefix /absolute/dependency/prefix \
  --vulkan-include /absolute/headers/include --jobs 2 --seconds 1500
```

`measurement.json` retains composition and actual stage receipts;
`supervisor.json` records the enclosing timer and cleanup. A missing or incomplete
measurement, failed build, timeout, missing startup stage or missing runtime trace
is blocked evidence, never a synthetic pass. Guest exit zero cannot establish
frames or gameplay. Safe summaries extract only service/selector grammar, never
guest text payload. A dispatch observation establishes a reached path, not handler
correctness or audible output. Unobserved handlers remain unverified.

If game frames appear, the owner requires private screenshots/short clips,
inspection and comparison against the official observations in canonical
`.local/game-run-control/GAMEPLAY_REFERENCE.md`. This tool does not infer visuals
from log counts or claim a capture was inspected. macOS remains partial or blocked
until actual gameplay criteria pass; Linux, Windows, both iPhone and iPad simulator
sizes remain independently partial/blocked. No physical mobile acceptance exists.

Offline validation uses only standard-library Python, temporary Git repositories,
real ordered patch application and fake child processes. It covers exact review
and ancestry, content drift, wrong/missing review, stale/late/changed authorization,
STOP, unsafe outputs, compiler profiles, subprocess errors, log bounds, descendant
cleanup and payload-safe boundary extraction. No credentials, cloud resources or
real game data are used in these tests.

Independent Astra/medium review of this unit's final exact committed head is
required from the parent; this worker cannot start nested reviewers and does not
waive that gate. Runtime measurement is recorded below when available.

## Actual cumulative measurement, 2026-10-18

The one configure/build/start ran from committed supervisor head
`136eec05cf147673ab1410bb024054e3626a0004`. Final follow-up changes strengthen
PID-reuse protection, reject direct internal-worker invocation without its owning
supervisor, require nonempty boundary evidence, and support finalized review-record pairs
and multi-commit review bases; they do not change runtime,
patches, build flags or the measured executable. The final code is covered by the
offline suite; no second native build or guest launch was performed.

Private evidence directory: assigned worktree
`.local/service-batch-034/native-1/`. All private inputs and outputs remain there
or in their original canonical ignored locations. The enclosing receipt records
**16:38:50.808156Z–16:49:33.794286Z**, **642.979 seconds**, including cleanup.
The enclosing supervisor returned 0 for a completed measurement; the guest
returned **1**, establishing a strict unsupported boundary rather than gameplay.

| Stage | UTC start–finish | Result |
| --- | --- | --- |
| Configure | 16:39:01.390468–16:39:05.069871 | Exit 0, 3.679 s |
| Native build | 16:39:05.254563–16:49:24.041520 | Exit 0, 618.780 s; parallel 2 |
| Real guest | 16:49:27.862075–16:49:29.360726 | Exit 1, 1.499 s; no timeout; limit 60 s |

`file` identifies the 56,049,608-byte executable as **Mach-O 64-bit arm64**.
All **395** translation units passed the strict/high-memory checks. Before and
after startup, the 450-file composed source fingerprint and validated private
input/generated identities remained unchanged. Stage receipts retain exact argv,
log hashes, process identities, timing and owned-group cleanup observations.

| Retained evidence | SHA-256 |
| --- | --- |
| measurement.json | `de64d560caf549aeebf85495cbbbe055d12f177685e085d25cfea702584f6600` |
| supervisor.json | `c506ab1b81d252c702af541b37b8b8aeb1ad52ad2741d09ce701b9fd6c1e163c` |
| build/astral | `f50e2afc166459f3766765353a727f48438d2f190c6bc9e484a0956baab73b83` |
| build/compile_commands.json | `c97e21326eb3f4099a0b0e7b077f7f94840d540d432d205dbbbc325ca16d3d27` |
| configure.log | `26980d0ff28eaed4bc0716a55993f8297fe9174052eef37c18d1b2da37c79444` |
| build.log | `524a5776ba2ae8c015c981fe210e08c1ec660693c6215850bcfa96efe631c594` |
| guest-trace.log and startup.log | `8162d80b908eda435ffe8a9ce168dff274c180a3d1cc9a5759c816cefee27f12` |

| Reviewed dependency | Reviewed exact head | Landed main head |
| --- | --- | --- |
| LOGGER029 | `748fe27a0a507ca9c934b3a7c1dfd6b949207491` | `eaa42fb9fa34afa9143116e903e6d85625817a85` |
| AUDIOOUT032 | `a539fd08fadec5ec9e264c6cb707462cc656e924` | `a539fd08fadec5ec9e264c6cb707462cc656e924` |
| APPLET-NOTIFY033 | `ed7877483faa45886fcd91ade1343ce114eac175` | `a8984f8a6c9986b4261fb515bb6f9005e2940639` |

Ordered patch SHA-256 identities:

- apple-memory: `a3d5225648bb88cae4dfa9647950745ac3f3de742c39fafe5c24387b2e741104`
- logger/bootstrap: `05f84f0025cc7074f157232e066288fae8f8b5c9ada535820cf2c5a2adff2f7c`
- AudioOut: `19b27662567bdb1ef10f51e661e0c69798ae2b19bcdf81c96d76f1add2fcc121`
- notifications: `bb7e30290e0058bf4754e4f0c2e4f9f96ae955f564fb052c858c4ab9bc29fcea`

APM030 was **not landed at this measurement's preflight** and was excluded,
without waiting. Its later main landing does not retroactively change this
composition. The actual first unsupported boundary was **ISession command 0**,
after observed `apm` command 0 opened the session. The pinned runtime's APM
registration constructs that empty ISession. This is the boundary APM030 is
intended to address; its actual guest behavior remains unverified by this run.

The guest accepted **three ILogger packets** and reached ISelfController
**11, 12, 13, 14, 16 and 91**, progressing beyond the former command-14 stop.
Other observed dispatches include parental initialization, application proxy,
common-state getter and window-controller operations. A reached dispatch is not
a correctness assertion for every branch or lifecycle transition. Notification
queue draining and real host mode/resume transitions remain unverified.
No AudioOut HLE calls were observed; submitted/released audio, device delivery
and audible output remain unexercised. No frame capture was retained or inspected;
no official-reference visual match, game frame or gameplay is claimed. macOS is
**partial, blocked at ISession 0**. Linux, Windows, iPhone simulator and iPad
simulator acceptance remain partial/blocked outside this unit; physical mobile
acceptance is absent. Independent final-head Astra/medium review remains pending
parent commissioning, not waived.

Closeout retained the exact executed supervisor privately as
`.local/service-batch-034/executed-supervisor.py`, hash-checked against the runtime
receipt, so rebasing does not lose that provenance. The safe private
`.local/service-batch-034/closeout.json` records that the owned worker and guest
PIDs were absent and source/build/executable/log/receipt evidence remained present.
The final offline suite passes **13 tests**, including multi-commit finalized
review pairs, missing overlays/reviews and PID-reuse rejection. No further native
configure/build or guest launch was performed after the measured run.
