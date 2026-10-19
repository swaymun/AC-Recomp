# Selected shader cache handoff

`tools/check_shader_cache_handoff.py` checks a small, explicitly selected private
package against the existing runtime contract. It reads inputs without changing
the overlay, canonical assets or native source/build. It compiles only an I/O
adapter plus the production `nvn_shaders.cpp` and `nvn_spirv_reflect.cpp`, with
`NX_SHADERS_STANDALONE`, in a temporary directory using one compiler invocation.
There is no game launch, native application build, translation or provider work.

## Production contract

In `runtime/src/nvn/nvn_shaders.cpp`, `shader_for` reads control magic
`0x98761234` and the code-block length at control offset `0x704`. Valid lengths
are 1 through 16 MiB. The cache key is the first 16 lowercase hex digits of SHA-1
of **that entire code block**, including its header and padding; it is not a hash
of only the executable program, wrapper, control section or SPIR-V. The lookup is
`<NX_DATA_ROOT>/spirv/<key>.spv`. Missing, empty or non-word-aligned products fail.
Control constant size/offset are at `0x6fc`/`0x700`; `make_shader_info` checks their
extent and copies constant bytes from that same code block.

`parse_results_tsv` in `nvn_spirv_reflect.cpp` splits literal tabs, finds the
header column named `resources`, and maps the **first** column to that value.
It strips a trailing CR, skips short/empty-key rows, overwrites duplicate keys,
and counts parsed rows rather than unique keys. It does not check stage, status,
product size, quoting or hash syntax. The cache loads these records once and
caches both successes and misses by hash. Changing the data root/files during a
running process is not a reliable refresh; use a fresh serialized native run.

Reflection determines the stage from the SPIR-V entry point. `make_shader_info`
parses any supplied resource record and applies it to reflection. No record is
also permitted by production, but leaves storage descriptor offsets unknown.
Resource tokens, separated by spaces, are:

- `cb<bank>=s<set>b<binding>` for a constant bank.
- `sb[c<bank>+0x<word>]=s<set>b<binding>` for storage descriptors; the production
  adapter requires bank zero and multiplies the word offset by four.
- `tex<type>[c<bank>:<word>(x<count>)]=s<set>b<binding>` for textures; `(x<count>)`
  here denotes optional `x<count>` text, without parentheses. `img` is analogous.
  Bank `-1` means the default texture bank, c[2].

Every supplied resource must reference an existing reflected set/binding.
Production does not fully compare redundant texture/uniform metadata against
names, nor require a resource token for every descriptor. Standalone acceptance
therefore is not a general proof of semantic resource compatibility.

## Focused checker and trust anchors

Use the retained handoff index hash and a separately checked accepted-results
receipt hash as explicit anchors. The receipt anchors the result index, whose
entries anchor the retained translation outputs. These are local identity
checks, not a new ownership/provenance authority. The checker never executes
commands or follows path instructions embedded in receipts. The caller supplies
all directories explicitly; input reads refuse symlink components, hardlinks,
nonregular files and oversized files. Unrelated canonical links inside an
overlay are not traversed. Compiler/adapter outputs exist only in a temporary
directory; JSON is written to stdout for the caller to retain privately.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/check_shader_cache_handoff.py \
  --data-root "$PRIVATE_NX_DATA_ROOT" \
  --handoff "$PRIVATE_SELECTED_HANDOFF" \
  --handoff-index-sha256 "$CHECKED_HANDOFF_INDEX_SHA256" \
  --accepted-receipt "$PRIVATE_ACCEPTED_RESULTS_RECEIPT" \
  --accepted-receipt-sha256 "$CHECKED_RESULTS_RECEIPT_SHA256" \
  --result-index "$PRIVATE_ACCEPTED_RESULT_INDEX" \
  --translation-root "$PRIVATE_ACCEPTED_TRANSLATION_ROOT" \
  --native-source "$STABLE_NATIVE_SOURCE" \
  > "$PRIVATE_PREFLIGHT_RECEIPT"
```

The checker reconstructs each selected wrapper through the existing graphics
parser, rechecks control/code identities, full code SHA-1, wrapper/SPH stage,
manifest bytes and original index. It checks accepted output identities and
exact selected TSV rows. It rejects duplicate/missing rows, wrong stage/status,
wrong size and missing or changed products even where production is permissive.
It also checks SPIR-V instruction extents and the single selected entry model.

Successful result statuses are exactly `ok` and `ok-retry`, matching
`prepare_shader_tools.check_results`. In the pinned upstream `Program.cs`,
`Translate` retries only after an exception, for SPIR-V unless retry is disabled.
The second attempt uses `DebugMode` to disable expression propagation; a produced
module receives `ok-retry`. The first attempt's exception can remain in the
`error` column after success. Batch validation still runs on that output and
changes status to `invalid` on failure. A retry status alone never authorizes a
product: all receipt/index/input identities, complete inventory, byte sizes,
stage checks, independent historical Vulkan 1.2 validation exits and production
resource/reflection checks remain required. Failed, unknown and empty statuses
are rejected without normalization or translation.

The compiled adapter then executes production `read_control`, `shader_hash`
(through `make_shader_info`), `parse_results_tsv`, `reflect_spirv`,
`parse_harness_resources`, `apply_harness` and `describe_like_harness`. It requires
the resulting hash/stage, record count and reflected resource description to
match. Unknown resource meanings or unresolved storage offsets fail this
preflight. The resource-description comparison is an additional conservative
preflight restriction, not a claim that production rejects every mismatch.
Selected inputs, accepted outputs, cache bytes and source identities are checked
again after execution. Concurrent hostile ancestor replacement is outside this
local snapshot workflow. No independent `spirv-val` rerun is implied; historical
accepted validator/output identities are checked.

## Measured handoff and next native measurement

SHADER-HANDOFF-073 checked the parent-prepared original overlay and its v2
replacement against the actual stable production source on October 18, 2026.
Both passed for **one vertex and one fragment**, with two successful production
standalone parser executions each. Observed descriptor counts were one for the
vertex and two for the fragment. This measures selected offline input/package
compatibility only. The vertex had zero location inputs/outputs and the fragment
had one of each; these measurements do not establish inter-stage linkage.

Use the **v2** data root recorded in the private handoff receipt for the next
serialized native run. The parent's v2 receipt removes the original overlay's
`nvn_trace.txt` symlink because runtime tracing writes/truncates that path. The
checker does not repair either parent overlay or write through any link. The
exact absolute `NX_DATA_ROOT`, accepted identities, source hashes, timestamped
preflight result and reproduction command remain in this worker's ignored
`.local/shader-handoff-073/` receipts and final report, not in tracked input data.

The native worker must own the next cumulative launch and observe actual upload
code/control identity, cache lookup/acceptance and subsequently pipeline
construction. No runtime patch is indicated by these two preflight results.
Additional requested hashes need their own real input/translation provenance;
there is no synthetic full-cache completion or fallback mapping. Missing cache
handoff at an earlier measured root is a separate downstream integration gap;
this work supplies no evidence that it caused the texture crash.

Guest consumption, a linked pipeline, an actual frame and gameplay remain
**unverified**. Total shader coverage is **unknown**. Mac gameplay remains first;
Linux, Windows and separate iPhone/iPad simulator acceptance remain open gates.

## Verification and review

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_shader_cache_handoff.py -v
git diff --check main HEAD
```

Tests use original synthetic code/control and reflection-only SPIR-V fixtures,
not game data or claims of validator success. They check whole-block hashing,
control length, stage, anchors, TSV rejection, malformed instruction extents,
symlink/missing products, CLI failure without writes, and production subprocess
acceptance/rejection. The production test discovers this run's stable ignored
source via Git's common directory, or accepts `SHADER_NATIVE_SOURCE`; if the
source/compiler is absent it explicitly skips that integration test. The real
private package run remains separate evidence. This unit's measured test run
included the production test with no skips.

Independent **Astra/medium exact-head review is required before landing**. The
parent commissions that review; this producer neither waives it nor lands/pushes.

SHADER-RETRY-082 retains its before/after contract fixture and one bounded
128-product production preflight under ignored `.local/shader-retry-082/`.
The public upstream source was locally checked against SHA-256
`888a38635228a410870c4703312aa3bbaaceecbfd7d7803a4f8430d3c9e9b04a`.
The additive fixture uses the upstream's full TSV column layout, including a
retained first-attempt error, and exercises the real standalone production
parser. Synthetic reflection modules do not establish validator success; actual
product validation evidence comes separately from the anchored private receipts.
The tests also reject failed/unknown/empty statuses, missing/duplicate/foreign
hashes, wrong stages, sizes, product hashes/sets, unsuccessful validation and
invalid resource bindings for retry outputs. All existing tests remain intact.
The single private production preflight passed all 128 products (39 vertex and
89 fragment), with 531 snapshotted input/receipt/product/source files unchanged.
It records selected parser source identities for the parent to prepare a fresh
overlay later; historical Vulkan validation was checked, not rerun locally.
This unit publishes no cache and consumes no products in a guest. All five
targets (Mac, Linux, Windows, iPhone simulator and iPad simulator) remain
partial/blocked; semantics and gameplay are unknown, and cross-ISA byte match
is N/A.
