# Bounded Linux Astral startup

## LINUX-SUPERVISOR-043 pre-run checkpoint

This unit extracts the scoped original supervisor and tests from untrusted
LINUX-GUEST-027 candidate `0167e494c4c5bc04aa3d36f1d21c88ec33b805f1`.
The supervisor's only changes from that candidate are its reviewed-main pin and
receipt unit label. The tests are byte-identical to the candidate and are rerun
locally against this checkpoint. Unit 027 remains **needs_split / two failures**:
stale ancestry, then a trailing empty evidence string. Its original reports and
ledger history are preserved. Any mechanically normalized report is historical
data only; it does not repair its stale failure-count claim or approve that head.
No third implementation fix is made in 027 and no review is waived.

The checkpoint is rebased onto actual reviewed main
`df2c57ba8a2a6af47d7f5adc6a62e87a64fd7aca`. Its fixed `REVIEWED` pin
requires that ancestor and exact current bytes of every consumed helper, patch
and dependency lock; tracked dirt and caller-selected pins are rejected.
Main includes independently reviewed CONTROL024, LOGGER029, AUDIOOUT032,
NOTIFY033, APM030 and IOS036. The six-patch composition below preserves the
original 027 acceptance scope. Main's separate `astral-ipc-buffer.patch` (039)
and `astral-applet.patch` (040) are present in ancestry but are **not composed
or exercised** here; subsequent AM integration and native acceptance remain
separate work. The final bounded 043 attempt mechanically rebases onto this
main without changing the implementation premise. MAC042 `2f67509b` only
changes its separate service-batch supervisor, tests and documentation; its
implementation is not duplicated here. All 12 consumed helper/patch/lock files
remain byte-identical to the previous `0e9ee64` baseline. The original malformed
043 report and its separately hashed normalization audit remain retained, and
failure 1 remains recorded. Staging of old 043 `0c203f218ed4` is historical
until parent supplies a fresh receipt for this final exact head.

The preparation helper SHA-256 is
`0119b0b8112a89042218f81a8ae179bd06ae4aed4e683fe1cc8fa8f3383feb53`.
Its CONTROL024 version was legitimately superseded by independently reviewed
IOS036 `73ceb0c65016615b29cb02354d75ae29acf26a90`, whose actual review
base is landed APM `791031333db04f67688c47b868bcd1ab5be4b246`.
The current helper is byte-identical to that reviewed IOS036 version and the
candidate's pinned `2d27411` version. This is an audit of the consumed helper;
it neither changes the shared helper nor duplicates MAC-PROVENANCE-042 work.
The retained private provenance audit records review runs, exact reviewed heads,
landed ancestry, normalized patch identities and current hashes. Historical
CONTROL024 helper bytes are not substituted for the reviewed supersession.

Only current `2026-10-18-afternoon` controls are accepted: all four targets,
matching owner approval/authorization SHA-256, at most three workers, at most
(amount omitted) total, **20:30Z cutoff / 21:00Z deadline on October 18**. The authorization,
objective and both JSON controls are hashed. Stale, malformed, extended, late
or changed authorization fails closed; there is no CLI deadline override.
Parent must also confirm the live store is not stopped before dispatch.

Preparation requires the exact CONTROL024 prepared receipt SHA-256
`a3c9827ead0ee15fbc3a7474b043d8bcb637a6672a849d7e1448344220e06d9a`
and control receipt SHA-256
`f4421237f6365a6252834b6e64a00f575a1d28da515d8b53e8efbce4f92eac88`.
The generated receipt binds actual regenerated main/SDK files, canonical import
manifest `fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d`
and Wonder `010ed7a596a621c15d3a8dfa5795ca8c3668b066`.
Control metadata is reparsed, checking CNMT/NACP/NPDM linkage, dump identity and
producer patch. Pinned receipt bytes do not replace actual input validation.
Before launch and after execution source/input identities are rechecked.
Inputs/output must be ignored, untracked, nonsymlink repository `.local` paths;
output is fresh and disjoint from inputs/generated files.

The existing preparation interface composes unchanged landed patches in order:

1. `apple-memory.patch`
2. `astral-bootstrap.patch`
3. `astral-control-import.patch`
4. `astral-audio.patch`
5. `astral-notifications.patch`
6. `astral-apm.patch`

Each requires a reverse check (already applied) or successful forward check and
application. Conflicts fail. Private provenance records patch hashes, complete
source fingerprints after each step and the generated control header. Applying
an importer patch does not execute the importer. Bootstrap-only or non-strict
preparation is rejected before build; no regeneration or runtime fix is added.

The dependent native unit must use explicit parent-supplied `--repo`,
`--reference`, `--inputs`, `--gen`, `--out`, `--cmake`, `--ninja`, `--prefix`,
`--vulkan-include`, `--generated-receipt`, `--control-metadata`, `--controls`
and `--xvfb-run` paths. Maximum execution is **1,500 seconds total**, at most
**three compile jobs**, and **one launch of at most 60 seconds under owned Xvfb**.
Preparation/configure/build/start share the monotonic budget, reserving up to
15 seconds for cleanup/evidence. Every outer child owns a new session;
configure inherits its preparation session. Linux cleanup terminates groups in
that session, including Ninja compiler groups. New-session escape remains a
limitation; global descendant absence is not claimed. Output is capped at
16 MiB, with separate configure/runtime logs watched (overshoot between polls
is possible). Exact argv, times, exit/signal, logs, compiler commands, object
counts and executable hashes stay private. Counts and process exits establish
no semantics, renderer, audio, input, save/reload or gameplay acceptance.

## Parent staging and dependent transfer

Only local retained receipts were read in 043. No SSH, transfer, compilation,
guest execution, provider or authentication action occurred. Parent's
17:30:07Z source-ready announcement points to immutable
`/root/ACSRecomp/.local/parent-source-1728/source.bundle`, SHA-256
`c84dd702a68928f58a23ba117848d99135459fc5ea8fea0f2933233a2b5cdd88`,
820,028 bytes. Its local receipt was independently hashed and matches required
`b8c4a6640ecb2ca869a34f7d8245ec8eb5985ab5fe0206244433a58c183202a9`.
It contains **027 candidate 0167e494 and main 2d27411**, so it cannot establish
readiness for this new checkpoint. Transfer is not review or launch approval.

After independent **Astra/medium exact-head pass**, parent must transfer a
**new immutable source-only bundle containing the final committed 043 head and
its current-main ancestor**, without overwriting 1715, 1728 or legacy staging.
Target only the existing owned Pod configured as `ACS_RUNPOD_POD_ID`, alias
`acs-afternoon-linux`. Return exact approved head, source bundle path/bytes/
SHA-256, isolated checkout path, clean tracked status and fresh readiness.
The ignored checkpoint artifact contains the exact request and head. Parent
owns transfer and remote checks; this worker neither lands nor starts a reviewer.

Parent's retained 17:17:22Z dependency announcement supplies paths under
`/root/ACSRecomp/.local/parent-deps-1715`: clean pinned Wonder, SDL
`a8589a84226a6202831a3d49ff4edda4acab9acd`, Vulkan-Headers
`e3b1eec08173d6b825cd3ac88c885a63b621504a`, CMake 3.31.6 and Xvfb.
Its two local receipt hashes are checked and retained. Historical 17:24:20Z
readiness reports RTX A4500 / driver 580.159.04; this is retained host evidence,
not a fresh remote check or guest-renderer observation. Parent must revalidate
these dependencies, resource ownership, controls and actual private inputs at
the next dispatch. Existing control refresh is under
`/root/ACSRecomp/.local/parent-control-024-1658`. The native-input root's packaging
manifest cannot replace the canonical import manifest bound to `data/analysis`.

**No native configure/build/start or gameplay acceptance comes from 043.**
The separate dependent unit begins only after independent pass and fresh parent
readiness, then records the first actual guest boundary with the bounds above.
All private receipts, original malformed report, mechanical-normalization audit,
review provenance and exact verification output remain in ignored
`.local/linux-supervisor-043/`. Original 027 private evidence stays untouched.
Historical Linux results below do not validate this checkpoint or its inputs.

Read-only local revalidation in 043 checked all **319 actual generated files**,
canonical inputs, linked control metadata and all **450 retained prepared source
files** against prepared receipt SHA-256
`e43b64ba94f14d23d76a5aa1e9d882544b9d5c29f4103a4d0ac303ee0951666a`.
Its ordered six patch hashes match this checkpoint's current bytes and its
Wonder source/reference pins match. No preparation output was rewritten, no
source was regenerated and no configure/build/start was invoked. This validates
retained preparation identity locally; the dependent native unit must still
validate the actual remote copies after parent transfer.

Offline verification uses temporary Git repositories and synthetic subprocesses
only. It exercises ordered patch application/conflict, private receipt binding,
controls, exact helper drift/ancestry, strict composition, failure propagation,
output/time bounds and absence of a frame claim. The actual Linux `/proc`
descendant-group fixture is skipped on macOS; this is not Linux acceptance.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_linux_runtime_startup.py -v
git diff --check main HEAD
```

## Observed LINUX-STARTUP-003 result

**Built; real guest startup blocked at ISelfController command 91.** The owned
Ubuntu/NVIDIA A5000 host was checked through `ssh acs-recovery-linux`; no remote
agent or account authentication was used. Its retained transfer archive matched
canonical SHA-256
`79dd84489bb55d71374b126bf8130c0c697059447ca5c17ea1ad6c010d9bd301`;
all **329 regular archive members** matched the isolated read-only input copy.
Wonder, SDL and Vulkan-Headers revisions matched LINUX_PREFLIGHT.md. All work
remains under `/root/acs-units/LINUX-STARTUP-003`, preserving other unit checkouts.

The full build ran **2026-10-18T09:55:33.124838Z–10:02:40.484905Z**, exited
**0** in **427.360 s**, without timeout or log-limit intervention. Ninja completed
398 graph steps, including archives/linking; **395/395 measured object files**
exist and **0 are absent**. These are compilation counts, not guest coverage.
The actual executable is 74,740,376 bytes, SHA-256
`ba747c6c44b79add371a136becfc738b5f184637bb0f745bcd1985ad326d250b`.
The first launch exited 1 at `SDL_Init: No available video device` before guest
execution; this failed attempt and its receipts are retained separately.

The initial configure/build used wrapper commit `6efddc0b53c39ac2d160eeb5c027ecdd838f3a58`.
After adding Linux session cleanup, identity revalidation and headless-display
support, the private `recheck.py` invoked the **final shipped module's
`run_stage` API** against the same verified build. It did not call the fresh-output
CLI again or rebuild in a different source tree. The repeat verifies reviewed
helper/patch bytes, complete prepared-source and input identity, unchanged compile
commands and every strict definition before and after execution. The final
wrapper SHA-256 is
`567aea17037a5713890ff5b60150890d11c8634184230f7bf0eacb2376c01099`.
The no-op three-job build exited **0** in 0.305 s. The owned Xvfb launch with
`NX_TRACE=1` ran **10:03:31.386122Z–10:03:31.835205Z**, exited **1** in
**0.449 s**, with **no signal, timeout or log-limit intervention**. A subsequent
`/proc` inspection found no live processes in its owned build/startup sessions.

Actual trace progression:

- Main and SDK map at `0x4000000000` and `0x4010000000`.
- Ten absent ELF weak relocations resolve under reviewed semantics; linking
  reports **91 HLE, 22,787 across modules, 0 unresolved**.
- Guest `nn::init::Start` executes at SDK+`0x289d90`, calls `__rtld_init`, and
  reaches `sm:`, `lm`, `apm`, `appletOE`, application proxy and window controller.
- The first fatal line is
  `FATAL: strict IPC missing command: service=ISelfController command=91`,
  through SVC `0x21` at SDK+`0x370ee4`.

The precise follow-up is the already identified readable/writable kernel-event
endpoint prerequisite, then the narrow self-controller command-91 copied-event
and command-90 suspended-tick contract described in RUNTIME_BOOTSTRAP.md.
No kernel/service/compiler behavior was changed here. All eight generated main
`sqshl` traps remain in the byte-identical inputs. SDK/main constructors and real
`nnMain` are **not reached**. No renderer identity was initialized/observed in the
trace; no game frame, gameplay, audio, save/reload or performance acceptance is
claimed. NVIDIA readback and the earlier synthetic cube capture remain separate
LINUX-GPU-002 evidence. Game metrics remain **unknown**; cross-ISA byte match is
**N/A**.

Compact evidence was fetched back to this Mac under the worktree's ignored
`.local/linux-startup/remote/.local/`: `startup/` holds full configure/build and
initial launch receipts/logs, exact compile/link commands and prepared-source
receipt; `final-repeat/` holds final supervisor receipts, trace and cleanup
receipt. `transfer-verified.json` and `dependency-identity.json` retain input and
toolchain checks. Original scripts and canonical nonsecret receipts are retained
in `.local/linux-startup/`; no binary or game-derived source was added to Git.

Evidence SHA-256:

| Evidence | SHA-256 |
| --- | --- |
| Full-build receipt | `a9db7264c6be05e03a2447de1df608a8e6bac7c1beed1e9ce4f5c8bf9069bc09` |
| Full-build log | `d6c89201994ff8a63e943d55015e128f3683591a8b6c0a0b2ff1db6b5095a3c8` |
| Final repeat receipt | `a4d770e3ad741f903ffc0fc25a1e8800dde500e70df820a6bc09c3cf6b4868dc` |
| Final guest trace | `a0eec0c9837cea9cbbdd3eb78cfdcf4f4aa885ab2aa1d96b1684ddf61e179fd4` |
| Transfer member receipt | `e70be1ce9bf4005156e91d3774021fd93dab2dfe4b44b9165710a338fd3d4bb9` |

The exact offline VERIFY passed all **9 tests on Linux**. On macOS it passed
with only the Linux `/proc` descendant-group case skipped. Independent Astra
review has not been performed by this worker and remains required before landing;
no review is waived.

## Observed LINUX-REFRESH-013 result

**Clean build passed; Linux advances past command 91 and command 16, then stops
at strict IParentalControlService command 1.** This closes the observed startup
gap against accepted macOS `e30b1395`; it does not establish gameplay parity.
No runtime change, parental-control implementation, workaround or second launch
was performed. PCTL-INIT-012 branch/output was not used.

The runtime input revision is reviewed dispatch main
`469d03f2888ed54727a6321666279b248e53d666`, containing landed
`e30b1395bfe848ba7c58530780113219732fff86` and
`a86a7e79e4cfe5f63447e4a9cd8b8b8c52cf2eb6`.
The actual remote wrapper checkout was
`e7a5dfda1f932c46525f8295aed911c3cd7e425a`; subsequent documentation/rebase
work preserves its wrapper bytes. The supervisor change is the fixed reviewed
revision and unit label only. All ancestry, exact-byte, clean-repository,
strict-mode, deadline, session and output bounds remain active. There is no
caller-supplied revision override.

Before preparation, the host's init-process task identity was independently
checked as the configured owned Pod. The canonical transfer archive's SHA-256 remains
`79dd84489bb55d71374b126bf8130c0c697059447ca5c17ea1ad6c010d9bd301`
(68,544,941 bytes). All **329 regular members** matched both archive content and
canonical originals after copying into this unit's isolated read-only inputs.
All **319 generated files**, **449 prepared source files** and **eight fatal
sqshl traps** were retained and verified. No predecessor output or dependency
checkout was changed. The documented Wonder, SDL and Vulkan-Headers revisions
were clean and matched; Clang 14, task-local CMake 3.31.6 and three compile jobs
were used. **Zero objects were reused**: all **395** translation units compiled,
and Ninja completed all **398** graph steps, including archives and final link.
Exact compiler commands and each resulting object hash remain private.

Recorded identities before preparation:

| Input/helper | SHA-256 |
| --- | --- |
| Wrapper | `48ff2b011246435d2a6dc55dc6437c070778a4d64f392c703a8ebedd645e7515` |
| Preparation helper | `ed7ab3d452852e2cf93587abf90ab97cec3c3e7c8898fea81af7772970dc324f` |
| Importer | `613591c1ccec0ad856098c3f6110ec97073d15d0c2ea305cfb495662cf1cc4b0` |
| Apple memory patch | `a3d5225648bb88cae4dfa9647950745ac3f3de742c39fafe5c24387b2e741104` |
| Astral adapter patch | `118f277ab668aec11cad8d46f13dbf1959db93949c7fd396bdc56f095fb0c383` |
| Dependency lock | `e932ebd7d36be38a35b70912c8893611e8f25a7bc8b9ec67ccfeb9c2e8886b5d` |
| Input manifest | `fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d` |

The supervisor used the command above with its fresh unit repository and
`--seconds 1000 --jobs 3`; expanded argv and selected environment are retained
for every stage. Times below are UTC on 2026-10-18:

| Stage | Start | Finish | Elapsed | Exit |
| --- | --- | --- | --- | --- |
| Prepare/configure | 11:54:37.692541 | 11:54:42.765321 | 5.073 s | 0 |
| Build actual astral | 11:54:42.786315 | 12:01:27.428743 | 404.642 s | 0 |
| Single NX_TRACE launch under Xvfb | 12:01:31.347052 | 12:01:31.787914 | 0.441 s | 1 |

Startup had a **45-second** bound; signal is **null**, timeout **false** and
log-limit intervention **false**. The executable is **74,756,296 bytes**, SHA-256
`967e78a61e5b478d5b3781271130b8a9203f6e04ea1ff68be6c1953514a39e84`.
Prepared-receipt SHA-256 is
`bcdc92da20047092d9e4862ee5b95231c32bd3adaea6dd37db2af38347394b4e`.
Source and all input identities were unchanged before and after execution.

The actual trace maps main/SDK at `0x4000000000` / `0x4010000000`, resolves the
same ten weak relocations and reports **91 HLE, 22,787 cross-module and zero
unresolved links**. It enters SDK `nn::init::Start` at SDK+`0x289d90` and invokes
`__rtld_init`, then observes:

```text
ipc: ISelfController cmd 91
ipc: ICommonStateGetter cmd 0
ipc: ICommonStateGetter cmd 1
ipc: ICommonStateGetter cmd 9
ipc: IWindowController cmd 10
am: AcquireForegroundRights: single application already in foreground
ipc: ISelfController cmd 13
am: SetFocusHandlingMode notify=0 background=0 suspend=1 (foreground)
ipc: ISelfController cmd 16
am: SetOutOfFocusSuspendingEnabled enabled=0 mode=1 (foreground runnable)
... pctl / pctl:s / pctl:a / pctl:r factories ...
ipc: IParentalControlService cmd 1
FATAL: strict IPC missing command: service=IParentalControlService command=1
```

The fatal request passes through SVC `0x21` at SDK+`0x370ee4`; nearby-symbol
labels in the shared veneer do not establish the higher caller. SDK/main
constructors and real `nnMain` are not reached in this launch. No renderer
identity is initialized/observed, and no decoded guest frame, audio, input,
save/reload or gameplay evidence is claimed. Synthetic NVIDIA probes remain
separate LINUX-GPU-002 evidence. No later instruction/service was investigated.

At **12:02:09.425333Z**, `/proc` inspection found no members in owned stage
sessions **15501**, **15573** and **16660** after supervisor TERM/KILL cleanup.
Children creating new sessions could escape this enumeration; global descendant
absence is not proven. No unrelated process was killed. All private outputs are
retained under `/root/acs-units/LINUX-REFRESH-013`; compact receipts/logs were
fetched and hash-verified on the Mac under `.local/linux-refresh-013/remote/`.
Original reproduction scripts and canonical nonsecret receipts are in local
`.local/linux-refresh-013/`. No provider, authentication, Windows or mobile
operation occurred.

| Evidence | SHA-256 |
| --- | --- |
| Overall supervisor receipt | `2524cc60d2b30c2bbc0e0f8bc3b6b52a1aab7b61e5ece747c359417bd06e983c` |
| Build log | `3e5ebd546d2935d4ccae59b5e3b6b571887ebd7e0d630be4dd9bbf85bfc76b19` |
| Guest trace | `72991baaf8c354deb84f7221a9492caa57c7f9a563359a67ff6c06f9f298bd48` |
| Object/source/input provenance | `e6e8d5fded8996cf8d9461d0392ca1501968b3b1949e662f52c7e7c859459544` |
| Cleanup receipt | `82e30a8dd446eb79b14f67157ad804c386ed6304dc11740e55bf9c7140a35875` |
| Fetched compact archive (130,054 bytes) | `91e73f9cf95c10bed99e746e9c8542f7332609625b6a14d301302219a2ec186f` |

Offline VERIFY passed **13/13 tests on Linux**, including the actual descendant
cleanup test; macOS passes with that Linux-only case skipped. The final rebased
committed-head verification is retained in local `verify-committed.json` and
`verify-committed.log`. Independent **Astra/medium exact-head review remains
mandatory and pending before scripts/land**; this worker does not start a nested
reviewer, land, push or create a PR. Review is not waived.

macOS and Linux remain **partial until gameplay**. Windows remains **blocked by
unready controls**. iPhone and iPad simulators remain **separately blocked**;
**26.5 tested / 26.0 minimum** describes the simulator baseline, not acceptance
by this Linux unit. Physical acceptance is **unverified**. Overall semantic and
gameplay metrics remain **unknown**; cross-ISA byte match is **N/A**.
