# Astral original shader consumer — SHADER-CONSUMER-008

**Blocked at the selected compute-wrapper-to-upload association.** The original
SDK's default name-to-function dispatch for `nvnProgramSetShaders` is now resolved
statically, including its relocations. One main-module caller through the
registered slot was followed. Its original signature guard rejects the selected
unchanged compute wrapper, so this path supplies **zero independent metadata
field mappings** and justifies no translation or adapter change.

## Exact predecessor and selected input

Read the run plan, first units,
metadata evidence, and its contract, format,
translation and inventory predecessors. The predecessor's suggested experiment
was a starting point; its assumptions were not treated as original-code evidence.

Independently validated the following retained identities:

- Astra/medium producer `10639445c38040eeb0c4d6ea53e6ff33`, committed head
  `54bc61d37ad613aaa9826318dfaa7f0380cf16cf`.
- Passing Sol/high review `6df7d27eb6ff48b08a166d2d38eac456`, reviewing that exact
  head with normalized patch SHA-256
  `d14ce19d2cc0b45d0bf1a87e2e53f68d218241eed9510a9022daaa9a5a32c37c`.
- The producer's landing receipt names the same head, reviewed head and patch.
  That commit is an ancestor of local main, whose metadata document is
  byte-identical. All 13 files in the predecessor's private receipt index matched
  their recorded hashes. Producer/review/landing files were independently hashed.

Rechecked exactly the same retained decoded member and selected wrapper:
SHA-256 `b0fb6bc81e1340f73ca8b4b19ab5f613370c2cc03fa476c236b43013f97d2da8`.
The complete member, wrapper, original control and original code hashes matched.
No extraction, decoding, translation or modification of those inputs occurred.
Original extents, member identity and hashes remain in private `provenance.json`.

## Resolved original path and its limits

The owned main and SDK flat images and retained NSOs matched the import manifest's
sizes and SHA-256 hashes. Every flat segment matched its recorded segment hash.
The seven generated files used for the trace matched the predecessor's hashes.
These establish retained local identity, not fresh remote authentication or live
load state. Original module-relative virtual offsets map to flat-image offsets;
generated code uses its module base plus that offset. Exact coordinates,
relocation records, segment maps, image hashes and generated line mappings remain
private in `static.json`.

| Boundary | Original evidence established | Limit |
| --- | --- | --- |
| Recorded bootstrap anchors | The main anchor is an import; the SDK anchors identify public and internal bootstrap entries. Their original instructions were checked against the retained generated comments. | An imported name alone is not a shader consumer. |
| SDK bootstrap dispatch | The internal entry reaches an indirect thunk. Original dynamic-table `RELA` records resolve the thunk's pointer cell and table entry to an original resolver. The public path can select/cache a provider object. | Flat-image zero pointer slots are unresolved relocations, not proof of absent functions. Public provider selection was not executed or fully resolved. |
| Original default name resolver | Its prefix check, indexed name comparison and original relative name table select the `ProgramSetShaders` row. The corresponding relocated default function-table slot resolves to original executable code. The table contains 512 sorted names. | Runtime override tables and fallback/provider paths remain unknown. This establishes a static default entry, not the entry actually selected during gameplay. |
| Selected upload entry | The resolved entry sets the fourth argument to zero and tail-branches into its common body. The inspected body prefix saves the incoming destination, count and pair-array arguments. | No selected-wrapper pointer values are supplied by this entry. Helpers, virtual consumers and downstream metadata loads were not followed. |
| Main registration | An original lookup/store slice associates the full upload name with a function-pointer cell. A relative relocation identifies that cell, and the selected caller loads through it. | The registration routine's supplied resolver and live cell contents were not observed. The association is conditional on that initialization path. |
| One selected main caller | Chose the lowest original address among three callsite candidates referencing that cell. Original instructions and generated comments agree throughout this caller. It checks an input wrapper signature, constructs one pair and invokes the slot with count one. Its four-byte comparison resolves through the original PLT relocation and dynamic symbol to `strncmp`. | The checked signature is for a graphics wrapper and differs from the selected compute wrapper. The unchanged selection cannot pass this caller's guard. No compute-wrapper association follows. |

This advances beyond the predecessor's generated literal-name search: the new
facts come from original instruction bytes, dynamic relocations, indexed tables,
and a caller's argument construction. No HLE name association, Wonder default,
plausible field value or translated-output reflection supplies a semantic proof.

The caller's pair includes a pointer formed from its input wrapper base and the
wrapper's control-offset word. Its other pointer depends on copied/mapped code
and an indirect API result. Those expressions are recorded privately, with no
claim that the selected wrapper ever occupies that input object. The original
signature mismatch is the stopping boundary. Neither the main-module input
object's provenance nor the selected wrapper's dataflow into a successful upload
was established. The guard must not be bypassed, and the graphics caller's
behavior must not be generalized to compute wrappers.

A preliminary exploratory probe also printed the sibling `Ext` entry's
instructions and short snippets at the other slot references. That exceeded the
literal one-upload-entry inspection limit; it contributes no semantic result.
No sibling caller chain or second complete application caller body was followed.
The receipt-backed selected trace examines one upload entry and one complete
application caller. This scope deviation is recorded explicitly for review.

## Established versus unknown

| Required fact for the selected compute wrapper | Status |
| --- | --- |
| Retained wrapper/control/code identity and partition | Rechecked unchanged against predecessor receipts. |
| Original SDK default upload entry | Resolved statically; live provider/override selection remains unknown. |
| Selected wrapper's original upload arguments | **Unknown.** The selected caller fails its original signature guard for this unchanged wrapper. |
| Compute-stage selection | **Unknown.** Retained container classification is not original consumer stage evidence. |
| Executable start/length and code boundary semantics | **Unknown.** Preserved extents do not establish executable meanings. |
| Scheduling-slot placement | **Unknown for this wrapper.** The pinned translator contract remains separate evidence about the translator. |
| X/Y/Z, local versus dispatch dimensions, units | **Unknown.** No independent original field-load/use chain tied to this wrapper. |
| Local/scratch requirement and zero semantics | **Unknown.** |
| Shared-memory size, units, scope and zero semantics | **Unknown.** |
| Constant extent/bank, bound address/data and use mask | **Unknown.** |
| Buffer/texture/image bindings and dispatch state | **Unknown.** No query run or runtime observation occurred. |

`translation_ready` remains **false**. The retained control tail is still
uninterpreted; zero new compute translations were produced.

## Exact next gate

The missing prerequisite is now **a compute-compatible original caller and input
object construction tied to this exact retained wrapper**, rather than merely
an unresolved SDK function name. The SDK default entry is available for that
future trace; actual provider selection remains a separate conditional gate.

The smallest next static unit can select only the second address-ordered caller
candidate recorded in private `candidates.json`, follow that single caller's
original signature guard and argument formation, and stop if the selected wrapper
cannot be associated. That candidate is not claimed to be compute-compatible.
Its exact function, generated file/line and registered pointer cell are retained,
so no repeated literal-name search is needed. If compatible, a separately bounded
input-object/loader chain must tie the retained member's original control/code
extents to those arguments before following original metadata loads and their
uses. If incompatible, report that boundary rather than expanding to a whole
call graph. No runtime launch, new extraction or adapter is authorized here.

## Private receipts, checks and release limits

Evidence is retained in this worktree's ignored `.local/shader-consumer/`:

- `provenance.json`: exact predecessor/review/landing identities and receipt
  hashes, selected member/wrapper/control/code hashes and extents.
- `static.json`: module/segment hashes, original relocations, default lookup,
  original/generated coordinate pairs, one selected caller, signature mismatch,
  analysis-tool identity and explicit scope deviation.
- `candidates.json`: precise registered-slot references and the next bounded
  candidate; no second complete caller analysis.
- `*.command.json`: exact receipt-producing commands, UTC boundaries, script
  SHA-256 hashes, exits and output. `run.py` bounds child commands to 85 seconds.
  One initial static assertion guessed the comparison import incorrectly and
  failed; dynamic-symbol inspection identified `strncmp`, and the corrected
  final reproduction exited zero. The failed receipt is retained.
- `verify.json` and `receipt-index.json`: final post-rebase commands/exits,
  committed-head identity, clean status and evidence hashes.

Only this safe original document is tracked. No credentials, provider operations,
remote commands, downloads, new extraction, program execution, source/tool
patches, translation or platform exercise occurred. No predecessor or unrelated
worktree was modified. Required checks after rebasing onto current local main:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_astral_pkz.py' -v
git diff --check
```

Independent **Astra/medium whole-head review is mandatory before `scripts/land`**;
the parent commissions it. This worker does not spawn nested reviewers, waive
review, land, push or create a PR.

The existing one vertex translation is not rendering. **macOS and Linux remain
partial; Windows, iPhone simulator startup and iPad simulator startup remain
blocked; physical acceptance is unverified.** Separate simulators remain in
scope. Cross-ISA byte match is **N/A**, and overall semantic/gameplay coverage is
**unknown**. The approved 15:00Z deadline, 14:30Z dispatch cutoff and (amount omitted) total cap
are unchanged; this local static unit performs no provider/auth action.
