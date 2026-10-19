# Bounded graphics batch

`tools/build_astral_shader_batch.py` composes the existing bounded PKZ inventory,
DAT parser, `graphics_pair` checker and strict shader translator. It does not
modify their implementations. Select **two to four** representatives, including
at least one vertex and one fragment. These are independent representatives;
their adjacency or presence in one container does not establish a linked pipeline.

## Private selection and extraction

Create an ignored JSON selector file with `schema: 1` and a `representatives`
array. Each record must have exactly these fields:

| Field | Required value |
| --- | --- |
| `archive` | Exact input-root-relative PKZ path |
| `member` | Exact decoded DAT member name in that PKZ |
| `index` | Integer DAT directory index |
| `stage` | `vertex` or `fragment` |
| `wrapper_sha256` | Expected full lowercase wrapper SHA-256 |
| `code_sha1_16` | Expected lowercase upstream code identifier |

Obtain selectors from retained authorized private inventory and actual wrapper
bytes. Those retained records are selection hints, not proof: extraction rereads
the original authorized archives, hashes every archive, decodes only explicitly
selected members and reparses DAT directories. It checks original wrapper
extents, graphics/control headers, SPH stage, code/control lengths, program and
constant extents, padding, expected stage and both expected identifiers.
Compute and unknown wrappers fail closed; no headers or compute metadata are
invented. Duplicate sources and duplicate/conflicting code identifiers are errors.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/build_astral_shader_batch.py extract \
  --repo "$PWD" --input "$AUTHORIZED_ROMFS" \
  --selectors "$PRIVATE_SELECTORS" --output "$PWD/.local/graphics-batch-next"
```

The input inherits the inventory's bounds: 128 archives, 2 GiB each, 12 GiB
aggregate, 32,768 directory entries, 8 MiB compressed/decoded per selected DAT,
16 MiB aggregate decoding, 16 MiB windows, 1,024:1 expansion, 100,000 discovery
nodes and depth 32. Inventory has a cooperative 120-second deadline. The batch
adds a four-representative cap and 1 MiB JSON bound. Outputs must be fresh,
ignored `.local/` descendants, without tracked paths, symlink components or
input overlap. Regular-file reads refuse hardlinks and detect identity changes.
Private files are mode 0600; new batch/handoff directories are mode 0700.
Concurrent hostile ancestor renames are outside this local snapshot workflow.

`inventory/` retains the original source-chain receipt, selected compressed and
decoded bytes. `handoff/` is the small transferable input: one aggregate
upstream-compatible `manifest.tsv`, generated code/control files and `index.json`.
The index maps each exact upstream code identifier to full code/control hashes,
the original wrapper header, checked manifest fields, archive identity, compressed
and decoded member identities and DAT wrapper extent/hash. Every translation
reconstructs that exact wrapper, reparses it and checks all manifest fields and
hashes before invoking the translator. This is suitable for future exact-hash
runtime lookup; no runtime consumer is implemented here. Keep the index's own
receipt hash as the transfer anchor; self-contained metadata is not an
independent authentication authority for original game ownership or provenance.

## Translation gate

Without `--toolchain-prefix`, extraction returns exit 0 with the explicit status
`extracted-translation-blocked`, zero translated products, and a concrete next
command in private `batch.json`. This is successful extraction only. Supply a
currently installed local prefix to extract and translate together, or translate
the compact handoff later:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/build_astral_shader_batch.py translate \
  --repo "$PWD" --input "$PRIVATE_HANDOFF" \
  --output "$PWD/.local/graphics-translation-next" \
  --toolchain-prefix "$VERIFIED_LOCAL_SHADER_PREFIX"
```

The unmodified strict translator rechecks the supported Wonder and shader-translator pins,
dependency lock, package contents, runtime files, restore locks, executable/DLL
and validator hashes. It requires complete successful result rows and validates
every SPIR-V module for Vulkan 1.2. This tool additionally rejects symlink,
hardlinked, oversized or nonregular outputs, requires exact hash-named products
(not merely matching counts), checks SPIR-V magic/instruction extents and the
expected vertex/fragment entry-point model, and independently runs `spirv-val`
again on those exact bytes. The second validator invocation has a 60-second
timeout. Translation otherwise inherits the existing strict API's subprocess
behavior; there is no new dependency preparation or global translator timeout.
Failed translation exits 1 and preserves its private rejection receipt; products
from a failed batch are never indexed as accepted. There is no validation bypass.

Parent owns any dependency preparation, transfers and remote execution. This
tool never provisions, downloads, installs, SSHs or waits for a host. A remote
handoff needs only the six extracted files for two representatives, their exact
receipt hashes, this tool and its two existing helper modules, a matching
dependency lock and a freshly revalidated installed toolchain. Remote private
input/output paths must be fresh and ignored. Do not reuse historical host
readiness or a deleted Pod's endpoint.

## Measured local real-input result

One local canonical-input run on October 18, 2026 rehashed **82 archives /
7,576,710,848 bytes**, decoded **one 285,952-byte DAT**, and extracted **two**
representatives: **one vertex and one fragment**. The inventory phase took
**6.915 seconds**. The six-file handoff totals **10,449 bytes**, including a
429-byte manifest and a 5,379-byte provenance index. All original tool/input and
output hashes are retained in ignored evidence under
`.local/graphics-batch-real-001/`; selector evidence is under
`.local/batch-066-evidence/`. No game payload, member-name inventory or products
are committed.

No local toolchain receipt exists at either the assigned worktree's default
prefix or the canonical task repository's default prefix. **Translation is
blocked; zero real products were translated or newly validated by this unit.**
The earlier recovery-host vertex success remains historical evidence only.
Parent receives the exact small handoff and installed-toolchain requirements.

Two extracted representatives are not a game coverage denominator. Semantic
coverage remains unknown; cross-ISA byte matching is N/A. Shader structural or
SPIR-V validity never establishes resource compatibility, rendering or gameplay.
Native macOS, Windows, Linux and separate iPhone/iPad simulator acceptance remain
open project gates, unchanged by this tool.

## Verification and review

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_astral_shader_batch.py -v
git diff --check main HEAD
```

Tests run original synthetic fixtures through the real parsers, extraction CLI,
manifest checks and strict batch API. Fake translator and validator subprocesses
exercise success, nonzero exit, zero-exit failed rows, duplicates, missing or
misnamed products, invalid headers/stages, validation failure, symlinks and changed
tool identities. Dependency provenance alone is mocked for the fake toolchain;
no real credential, cloud machine or paid compute is used.

The parent must commission independent Astra/medium review of the exact producer
head and frozen base/normalized patch. Guarded `scripts/land` rebase, exact-patch
comparison and VERIFY remain mandatory after an independent pass. This producer
does not land, push, spawn a reviewer or waive review.

## Explicit runtime graphics chunks (schema 2)

The representative `extract` command and schema 1 retain their two-to-four,
vertex-plus-fragment rules. The opt-in `bulk-extract` command accepts a separate
private plan with exactly `schema: 2`, `mode: "runtime-graphics"`, `log_sha256`
and `probes`. Each probe has exactly `archive`, `member`, `archive_sha256` and
`decoded_sha256`. Supply source identities from retained authorized inventory;
they are rechecked against newly hashed original archives and newly decoded DAT
bytes. Names stay in private plan/receipts, never command arguments or Git.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/build_astral_shader_batch.py bulk-extract \
  --repo "$PWD" --input "$AUTHORIZED_ROMFS" --selectors "$PRIVATE_PLAN" \
  --runtime-log "$PRIVATE_RUNTIME_LOG" --chunk-size 128 \
  --output "$PWD/.local/runtime-chunk-next"
```

The runtime log must match the plan's full SHA-256 before requests are measured.
Only complete `nvn: shader HASH (code 0xSIZE bytes, control POINTER): no PATH/HASH.spv`
records count, with identical identifiers in both positions. Identifiers are
whole-code SHA-1 prefixes, checked by the production graphics parser, rather than
wrapper hashes or guessed associations from neighboring stages. Up to 32,768
unique requests and a 64 MiB log are accepted. The request set is sorted and
bound into every chunk receipt.

No archive-wide decoding is enabled. At most eight explicitly named DATs are
decoded once each using the unchanged inventory/decoder. All existing archive,
compressed-byte, decoded-byte, expansion, window and directory bounds apply,
including 16 MiB total decoded bytes. Every graphics wrapper in those DATs is
validated before matching. Compute and unknown wrappers are counted and excluded;
malformed graphics wrappers reject the batch. Identical code/control products
are deduplicated with every archive/member/wrapper/header/stage association
retained privately. A code identifier with differing code, control or manifest
metadata is rejected from the product set; its source records go to private
`conflicts.json`. It is never resolved by choosing a nearby or first-seen stage.

Chunks contain 1–128 distinct unambiguous requested graphics products. The index
and selection both explicitly mark `schema: 2, mode: "bulk-graphics"`. A chunk
may contain only one graphics stage. The handoff totals at most 16 MiB, with a
1 MiB index limit; accepted translation output has a 16 MiB aggregate limit and
at most 136 files. Inventory has a 120-second wall deadline, followed by a
180-second extraction deadline. Bulk translation has a separate 180-second wall
deadline including its input checks, the unchanged strict translator and second
independent Vulkan 1.2 validation. These CLI deadlines use POSIX timers on
Linux/macOS and fail closed where unavailable. A rejected translation retains
private diagnostics/products but publishes no accepted product map or cache.

Resume extraction with `--resume "$PREVIOUS_HANDOFF" --resume-sha256 "$INDEX_SHA256"`
and a fresh output directory. Resume revalidates the previous handoff and binds
the plan, runtime requests, full archive snapshot and conflict set before taking
the next sorted identifiers. `completed` means extracted across chunks; it does
not mean translated, validated or integrated. Unmatched requests, conflicts and
remaining matched products remain separate exact sets. Reordered probe plans
produce the same sorted chunk identities. No accepted cache is mutated.

### Bounded local evidence and parent Linux job

The October 18 real-input scan independently verified the provisional 078 log
SHA-256 and measured **1,286** unique missing requests. Six explicit DAT probes
contained **1,451** structurally valid graphics wrappers and **70** excluded
compute wrappers. Of the requests, **1,219** had graphics associations: **1,205**
were unambiguous and **14** had conflicting controls. **67** were unmatched in
these probes. An initial conservative whole-batch rejection exposed the
conflicts; the corrected path excludes those identifiers and records their
sources. The subsequent inventory took **8.208 seconds** and extracted **128**
products into a **1,345,997-byte** handoff. **1,077** unambiguous matches remain
unextracted. All **1,286** requests remain untranslated by this unit. These counts
are bounded observations, not the game's full shader population.

Neither local default toolchain prefix had a toolchain receipt. Thus **zero**
products were translated, newly SPIR-V validated or cache-published. Parent owns
any later Linux execution. The useful job input is this one small `handoff/`
directory (manifest, anchored index and 128 code/control pairs), the original
three Python helper modules, matching dependency lock, and a separately verified
installed Linux toolchain prefix. No inventory archives or original dumps are
needed on that host. Verify the handoff index against the privately recorded
SHA-256 before running:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/build_astral_shader_batch.py translate \
  --repo "$LINUX_REPO" --input "$LINUX_PRIVATE_HANDOFF" \
  --handoff-index-sha256 "$PRIVATE_INDEX_SHA256" \
  --output "$LINUX_REPO/.local/runtime-translation-next" \
  --toolchain-prefix "$VERIFIED_LINUX_PREFIX"
```

The index anchor is mandatory for bulk translation. Successful output must have
`translation.json` with `schema: 2`, `mode: "bulk-graphics"`,
`status: "translated-validated"`, the exact `input_index_sha256` and
`input_manifest_sha256`, and exactly 128 accepted products. Retain all strict
translator results, resource metadata, toolchain identities and independent
validator receipts. Parent must freeze/hash that output and construct the
existing accepted-receipt/result-index package before any cache handoff. The
handoff checker requires explicit bulk translation markers and the same input
index anchor, then retains all existing exact product, result, source, resource,
reflection and validation checks. Old selected/v2 packages remain supported.

This job has not run. Unknown shader semantics, resource compatibility, actual
rendering and gameplay remain unmeasured. macOS, Linux, Windows and separate
iPhone/iPad simulator gates retain their prior partial/blocked state. Cross-ISA
byte matching is N/A. Independent exact-head Astra/medium review and parent-owned
guarded landing remain required; no platform acceptance follows.
