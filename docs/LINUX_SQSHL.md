# LINUX-SQSHL-021: fresh generated-main Linux compilation

This is a build-only integration lane. It does not regenerate code, launch a
title, invoke the startup supervisor's `execute`, install packages, provision a
host or change runtime behavior. The only reused startup-supervisor functions
are bounded process/session and receipt primitives. All game-derived inputs,
objects, executable and detailed commands remain private and ignored.

The producer is CPU-REGEN-020 at
`39fc30ab25d83b328e1026a12892db1fc18b305a`, patch identity
`0bdb67cad8a330deb3368937fa942949bf54e03aa72b113572aa01a4abc35222`,
producer run `7419dea9b2ad455fad02b4d6f044911c`. Independent Astra/medium
review `7cfaa9ed177144348c6f072f388d0b85` passed that exact head; the
parent's landing receipt records the same reviewed/landed head and patch at
2026-10-18T13:15:08.980673Z. Git main ancestry and the complete patch identity
are independently checked before private producer artifacts are consumed.
The 85,200 native/bigint/UBSan cases belong to accepted CPU-SQSHL-019;
this lane makes no additional instruction-semantics claim.

## Fail-closed boundary

`tools/linux_sqshl_build.py dispatch` validates the landed unit row, worker
report, independent review, landing, both reported artifact hashes, every
retained artifact-manifest member, exact regeneration report, clean tracked
sources and original reviewed helper/patch/dependency-lock bytes. It resolves
the input, generated and prepared paths from the validated producer commands.
The original reviewed audit checks all 319 generated files against canonical
bytes plus exactly eight accepted statement replacements and the deterministic
coverage-report change. All 110 SDK files remain identical. Original input
NSO/flat/NPDM/manifest bytes and all eight original instruction words are
rechecked. The 449 prepared source identities match IPC-CALLER-014's **final**
`prepared/prepared.json`; its initial preparation remains the separate pinned
canonical-input receipt. Neither receipt is substituted for the other.

Expected counts remain:

| Module | Canonical functions / handled / unsupported | Fresh functions / handled / unsupported |
|---|---|---|
| main | 27,763 / 2,569,143 / 8 | 27,763 / 2,569,151 / 0 |
| SDK | 33,573 / 1,302,326 / 0 | 33,573 / 1,302,326 / 0 |

Current task registry, SSH-ready and original-transfer receipts are treated as
data: provider hooks and arbitrary commands in them are never executed. Host
`acs-recovery-linux` must map to the owned RunPod Pod given by `--pod` or
`ACS_RUNPOD_POD_ID` (never hard-coded); a live check
reads only `RUNPOD_POD_ID` from PID 1, never the whole environment. Mismatch or
unavailability refuses remote work. There is no provider or auth interface.

The transfer contains only required extracted inputs, generated files, original
helpers and shipped patches. An explicit member manifest and archive SHA-256
bind the transfer; regular members are hash-checked before extraction. Existing
outputs, links, traversal, object reuse, bad pins, dirty dependency checkouts,
missing strict flags and incorrect compile counts are refused. No canonical
input or prior output is modified. Only the existing pinned Wonder, SDL3 and
Vulkan-Headers checkouts, installed SDL prefix, Clang, Ninja and task CMake are
used. Nothing is downloaded.

Local dispatch retains the normalized path returned by `prep.private` and
validates strict containment beneath this worktree's normalized
`.local/linux-sqshl-021` ownership root before any output creation or write.
`prep.private` alone only enforces repository `.local` containment. Symlinks
in the original spelling are rejected before normalization can erase them;
unit-root aliases, traversal escapes, existing destinations and children of
retained output directories are refused. Only the ownership root may already
exist on a new output's parent chain.

Fresh preparation/configuration is followed by `cmake --build … --parallel 3
--target astral`. All 395 compile commands must retain strict mode,
`-ffp-contract=off` and `-march=x86-64-v3`; all object outputs must be unique and
inside the new build directory, and absent before compilation. The supervisor
records exact argv, UTCs, exits, compiler/tool hashes, objects, Ninja dependency
and link commands, named linked-file hashes, executable identity and post-build
source/input/generated/dependency revalidation. Hashing a binary never executes
it. System runtime behavior is not established by static dependency hashes.

Each subprocess has a fresh owned session, bounded output and TERM/KILL cleanup,
including compiler groups enumerated through `/proc`. Receipts survive failures.
The shared budget is at most 1,500 seconds, at most three compiler jobs, dispatch
before 14:30Z and completion before 15:00Z. Remote work reserves cleanup time and
runs with its own expiry, even if the local SSH child disappears. A complete
network/host failure and descendants that create new sessions remain explicit
cleanup uncertainties; the tool does not claim global process absence.

## Reproduction and offline verification

From a clean, accepted worktree, with the parent-owned store still valid:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/linux_sqshl_build.py dispatch \
  --store "$VALIDATED_RECOVERY_STORE" \
  --out "$PWD/.local/linux-sqshl-021/run"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_linux_sqshl_build.py' -v
git diff --check
```

The destination must be fresh. Do not retry against retained output. This dated
lane intentionally refuses later dispatch after its approved cutoff. It uses
only existing encrypted SSH, and fetches a compact hash-verified receipt archive.
The offline tests use temporary Git repositories, fake SSH and real bounded
Python child processes. They test exact review/landing identities, dirty tracked
sources, unlanded producers, wrong host controls, linked receipts, unsafe/hash-
mismatched archives, object/strict-flag refusal, failing children, expired bounds
and descendant timeout cleanup. No real SSH, cloud or credentials are used.

## Acceptance limits

Independent Astra/medium whole-result exact-head review remains mandatory before
`scripts/land`; the parent owns review and landing. No nested worker/reviewer,
waiver, branch push or PR is performed here. Build success establishes compilation
only. The strict parental command-1 startup gate is unchanged; no title launch
was attempted. macOS and Linux remain partial until gameplay. Windows remains
blocked by unready Windows cloud machine controls with no paid start. iPhone and iPad simulators
remain separately blocked, with **26.5 tested / 26.0 minimum** describing the
baseline rather than this unit's acceptance. Physical acceptance is unverified.
Overall semantic/gameplay coverage is unknown; cross-ISA byte match is N/A.

## Output-boundary correction and review status

First-round producer `520fd20dfdfa40a9ab67df3ccc7dd896` committed
`ac0ccba82d3f440b0c8e993a4cfa003328423d21`, full-patch identity
`570e734224348748466e3dc2f2ac5e8a1e03655f0862ff80032c189150a64d00`.
Independent Astra/medium review `9a1d5384db394e70993d170dfef78af5` **failed**
that exact result: dispatch checked lexical unit containment, discarded
`prep.private`'s normalized return, then wrote the original path. The spelling
`.local/linux-sqshl-021/../outside-unit-probe` could escape unit ownership.
Neither the review nor this correction created that escaped destination.

The corrected wrapper SHA-256 is
`bda999ec57b3f4610af704e277cb4651e030a87b187d99db8864bbecfe70808e`.
It is **verified offline only** with temporary directories, Git fixtures,
fake tools and bounded local test children. Regression checks refuse the exact
escape before mkdir, staging, SSH or writes; cover root aliases, symlinks
(including components erased by normalization) and overlapping retained runs;
and verify valid creation and refusal receipts use the normalized path.
No fresh real compilation, regeneration, remote SSH or title launch was done.

The build and archives below remain historical evidence of the original
`ac0ccba8` wrapper only. They do not establish execution of the corrected
wrapper. This is the one bounded correction after the first failed review;
the parent must obtain a new independent Astra/medium whole-result review of
the exact corrected head, unchanged full patch and historical evidence before
`scripts/land`, without waiver. A second failed round requires splitting the
unit or challenging its premise. This worker performs no nested review.

## Historical measured build and retained evidence

**Linux clean compilation passed; the executable was never launched.** The live
host check returned the configured owned Pod. The fresh remote workspace is
`/root/acs-units/LINUX-SQSHL-021`; the exact 335-member transfer manifest and
archive hash are retained locally. No predecessor checkout/output was changed.

| Stage, 2026-10-18 UTC | Start | Finish | Exit |
|---|---|---|---|
| Fresh prepare/configure | 13:21:30.987467 | 13:21:35.985616 | 0 |
| Clean three-job Astral build | 13:21:37.096762 | 13:28:21.668007 | 0 |

The build took **404.571 seconds**. All **395 objects** were absent before the
build, all 395 compile commands passed strict/platform flag checks, and Ninja
completed all **398** graph steps. Actual command:

```sh
/root/acs-units/LINUX-GPU-002/venv/bin/cmake --build \
  /root/acs-units/LINUX-SQSHL-021/repo/.local/prepared/build \
  --parallel 3 --target astral
```

Clang is **14.0.0-1ubuntu1.1**, CMake **3.31.6**, Ninja **1.10.1**. Exact tool
paths, hashes and full version output are retained. This build uses the same
pinned Wonder/SDL/Vulkan-Headers revisions documented in LINUX_PREFLIGHT.md,
and the accepted final IPC-CALLER-014 runtime patches. The preparation helper
hash is `ed7ab3d452852e2cf93587abf90ab97cec3c3e7c8898fea81af7772970dc324f`;
the bootstrap patch is
`7e96a8b8ffb24727e1caabcafdf4542c71d37c3d7bc833fd45ee8b3eca101dfa`.
The exact executed supervisor bytes match the original `ac0ccba8` wrapper:
`3a686e7c4a000e1cd59765d249d18cd4e4be25263dadc463fe4c008964c44cfa`.

The unlaunched executable is **74,772,240 bytes**, SHA-256
`15144f2f9c34ba3cf714209ee274945605cb04f5be1260b331f4708d6a989f82`.
All 449 prepared source hashes, all 319 generated hashes and original input
identities were revalidated after compilation. The receipt includes **907**
Ninja dependency-file hashes, installed SDL prefix hashes, all object hashes and
exact link commands. A supplementary read-only `readelf` inspection identifies
and hashes all five direct ELF shared-library dependencies and the ELF
interpreter; it does not execute the loader/title. Transitive runtime behavior,
Vulkan initialization and instruction execution remain unverified.

One final **local post-build audit refusal** is deliberately retained:
`ValueError: dirty tracked sources` at **13:28:30.395981Z**. The worker had staged
its three permitted implementation/documentation files while the remote build
was running. The remote build itself passed and its compact receipts had
already been fetched. After committing those exact scoped files, the same
read-only provenance validation passed from a clean tracked tree. No build,
regeneration, runtime change or title launch was repeated to clear this refusal.
The dispatch process's exit **1** is therefore retained separately from the
remote compile stage's exit **0**.

The supplementary validation also confirmed the reviewed producer ZIP matches
all retained members, the producer emitter source and native executable remain
unchanged, and all **1,678** predecessor macOS dependency hashes still match.
This does not add macOS execution acceptance.

At **13:28:58.633292Z**, independent `/proc` inspection found zero members in
all eleven recorded owned sessions (including configure, compiler/version,
build, dependency and ELF-inspection commands). The supervisor's candidate
cleanup-group identifiers alone are not a live-process count. New-session
escape and total host/network failure remain explicit uncertainties. No
unrelated process was signaled; all private inputs, outputs and original
reproduction scripts remain retained. Parent-owned host/provider cleanup is
outside this worker's authority.

Compact evidence is hash-verified under this worktree's ignored
`.local/linux-sqshl-021/remote-final/`; local orchestration/refusal receipts are
under `run/`. The retained ZIP packages these receipts, original private audit
scripts and final verification, without generated source, object files or the
executable. Large private build/transfer artifacts remain outside that ZIP.

| Receipt | SHA-256 |
|---|---|
| Overall native receipt | `8d63ac5bafec7eab724b8dc6cf63d263d1a71af06779bd66a63369538300151f` |
| Build log | `f96620e3ba4d34a2144cb48186c145cb843aa983ccb1eb4de62f2b1eaed17734` |
| Compile commands | `413b6fed7087f6234bc55762a346d420c68f198df642875ed7b4c2d8d793ff71` |
| Prepared-source receipt | `fbc77e80c9ebe23f0c764a4fe3c44278e95d4906b39a6134b975dade3b614e7a` |
| Fetched final compact archive | `ce62b4d9704c184f91a370ea3ad86a366cce4dd1b64a2d4c263462252481a15d` |
| First-round evidence ZIP, 386,408 bytes / 93 members | `5d5a654011c2971ddb75c1d86311685de3e540d371b112c6a09c6ace56e99b72` |
| First-round final-validation.json, 1,641 bytes | `41582a336cf5fdf7a958ee9e5d0c33e6263de1508e91c4291647ca5a332af78e` |

The original ZIP is `.local/linux-sqshl-021/evidence.zip`; the original final
validation is `.local/linux-sqshl-021/final-validation.json`. The fetched final
compact archive is `.local/linux-sqshl-021/final-compact.tar.gz` (283,342 bytes,
33 members). During correction, its archive hash and all 33 retained member
hashes were checked offline, the original ZIP passed its 93-member integrity
check, and the retained 395 compile commands passed strict/platform checks.
These files were retained unchanged. In particular, the original validation's
"corrected read-only clean-tree audit" describes the first producer's
post-commit provenance audit, not validation of this boundary correction.

Independent Astra/medium exact-head whole-result review of the correction
remains **pending and required before landing**, with no waiver. The acceptance limits
above remain unchanged.
