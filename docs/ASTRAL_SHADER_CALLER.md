# Astral retained shader caller — SHADER-CALLER-009

**Rejected at the second retained caller's original signature guard.** The
unchanged selected compute wrapper cannot reach this caller's shader upload.
This is a concrete static rejection, with **zero new metadata semantic mappings**,
zero compute translations and no runtime, frame or gameplay claim.

Read the run plan, first units,
[consumer predecessor](ASTRAL_SHADER_CONSUMER.md), metadata evidence,
translator contract, format diagnosis,
[translation evidence](ASTRAL_SHADER_TRANSLATION.md), [inventory](ASTRAL_SHADER_INVENTORY.md)
and preflight. Their suggested experiments were treated as
proposals; the result below comes from retained original instructions and data.

## Independently verified identities

The predecessor producer run `3b942234d3eb4900be6cb6321cf56da2` reported head
`b5c43b6f6d29cdfa1fd1307d4e1f2f0e8b3c183b`. Corrected-scope independent
Astra/medium review `459c5e74bf3c4217b1d42b6266d29646` passed that exact head.
Its normalized patch SHA-256 is
`389b540a81a30c1a930780bd83991e869481fb1d47abee67ab3ce340bb541739`.
The landing receipt names reviewed head above and landed head
`2b9b3dccbd19923d5846d8d08db9a9c1f3140e89`. Both commits independently reproduce
that patch; the landed head is an ancestor of local main. The document is
byte-identical at the reviewed head, landed head and local main. This review
supersedes the predecessor's earlier failed scope review; it does not erase the
predecessor's disclosed preliminary inspection.

All **20/20** indexed predecessor files matched their byte lengths and SHA-256
hashes. The predecessor index matched its producer-reported hash. The producer,
passing review, landing and run identities were checked and independently hashed.
The exact candidate inventory SHA-256 is
`240af776acc7eaad5df57af3e1a38d083e359f4186fda8df1df0a802b96b0de6`.
Selection is exclusively its **second address-ordered non-registration caller**;
no new candidate search or call-graph expansion occurred.

The same retained decoded member, complete wrapper, original control and original
code matched the predecessor's identities. Wrapper SHA-256 remains
`b0fb6bc81e1340f73ca8b4b19ab5f613370c2cc03fa476c236b43013f97d2da8`.
No input was extracted, decoded, altered or translated. Private receipts preserve
its member selector, original extents and individual hashes.

The retained main/SDK flat images, NSOs and every segment matched the import
manifest and predecessor identities. All seven retained generated-file identities
matched. Original module-relative virtual offsets equal flat-image file offsets;
generated instructions use their module base plus those offsets. Live bases and
function-pointer contents were not observed. The registered upload name, original
lookup/store instructions and slot relocation were checked. The retained SDK
upload shim's original bytes and default dispatch relocation chain matched the
predecessor; no upload body or sibling upload function was explored anew.

## One caller and its rejection boundary

The complete selected caller contains **99 original instructions**. Each decoded
instruction matched its retained generated comment in order, with exact original
address and generated line recorded privately. No generated code was executed.

| Boundary | Original evidence | Limit |
| --- | --- | --- |
| Entry and initialization | The wrapper base is the caller's third entry argument directly. A separate destination-holder argument supplies the upload destination after a fixed adjustment. An earlier indirect initialization must return a nonzero low byte. | Input construction, actual object addresses and initialization result remain unknown. The initialization body was not followed. |
| Signature guard | Original address formation selects a pixel-wrapper signature. The original PLT, GOT relocation and dynamic symbol resolve the four-byte comparison to `strncmp`. The unchanged selected compute-wrapper prefix differs. Nonzero comparison branches to the zero-return failure path. | This is a decisive rejection if the guard is reached; initialization may fail earlier. No runtime ordering or successful initialization is claimed. |
| Conditional argument formation | After the guard, the caller checks two wrapper bytes against context bounds, aligns a context allocation cursor to 256 bytes, bounds the copy extent, and forms source/length from the wrapper's original code-offset/length words. | These operations describe the caller's conditional path. They cannot associate this rejected wrapper with a successful upload or give the checked bytes metadata meanings. |
| Conditional upload | A helper and two indirect calls supply mapped-address components. The upload uses the registered slot, count one and one stack pair. One pair element combines those components; the other adds the wrapper's control-offset word to its base. Exact register, stack and arithmetic expressions are private. | Helper bodies and indirect implementations were not followed. Their results, live slot contents and selected-wrapper input association remain unknown. |

The guard rejects before copy, mapping and upload on the selected input. Its
failure is sufficient to close this candidate. The argument trace is retained
for reproducibility, not evidence that the unchanged wrapper reaches that code.
Neither the guard nor any metadata word was bypassed, rewritten or defaulted.

An initial fixed-line generated-source read also displayed a prefix of the
following noncandidate function. It was not traced, disassembled or used as
evidence. The final reproduction extracts exactly the selected caller body.
No second complete caller, sibling upload function, loader/input-construction
chain or additional candidate body was followed.

## Established facts and remaining gate

| Required selected-wrapper fact | Result |
| --- | --- |
| Original wrapper/control/code identity and partition | Rechecked unchanged. |
| Second retained caller compatibility | **Rejected by its original signature guard.** |
| Exact selected-wrapper upload arguments and input-object association | **Unknown.** Only conditional caller expressions are established. |
| Compute-stage selection; executable start/length meanings | **Unknown.** |
| Scheduling-slot placement; X/Y/Z association, units and local versus dispatch interpretation | **Unknown.** |
| Local/scratch memory requirement, units, allocation scope and zero semantics | **Unknown.** |
| Shared-memory field meaning, size, units, scope and zero semantics | **Unknown.** |
| Constant extent/bank association, bound data/address and use mask | **Unknown.** |
| Buffer/texture/image bindings and dispatch state | **Unknown.** |

The control tail remains uninterpreted and `translation_ready` remains **false**.
Translator defaults, plausible values and output reflection supply no evidence.

The smallest different next premise is **only the third address-ordered caller
already present in the same verified candidate inventory**. Its existing function,
slot reference and generated line are copied as coordinates into this unit's
private receipts; its body was not examined here. A separately authorized unit
can test that one caller's original guard and argument formation. It must stop
at rejection or an unresolved association. It is not assumed compute-compatible.
If compatible, tying the exact retained member to its input object requires a
separate bounded construction/loader unit before interpreting metadata uses.
Live provider/default selection remains a separate conditional prerequisite.

## Reproduction, verification and release limits

Private ignored evidence is retained in `.local/shader-caller/`:

- `provenance.json`: predecessor producer/review/landing/run hashes, reviewed and
  landed patch identities, main ancestry, all 20 predecessor receipt checks,
  unchanged selected-input hashes and exact fixed candidate selection.
- `analysis.json`: module/segment/generated-file identities, original/generated
  coordinates, registration/relocation checks, signature rejection and complete
  conditional argument expressions. Raw instructions remain private.
- `provenance.py`, `analyze.py`, `reproduce.py`: reproduction scripts. Without
  `--output`, the first two print observations without rewriting receipts;
  `reproduce.py` compares both in memory excluding UTC timestamps.
- `*.command.json`: exact command arrays, UTC starts/ends, elapsed times, exits,
  output and script hashes. `run.py` bounds each child to 85 seconds. The first
  analysis exited one because manually entered assertion coordinates were off
  by one instruction; original-byte inspection corrected those coordinates.
  Its failure receipt and exact failed script are retained separately. The
  corrected analysis and read-only reproduction exited zero. This differs from
  the predecessor's earlier comparison-import assertion failure.
- `verify.json` and `receipt-index.json`: post-rebase checks, committed head,
  clean tracked status and evidence SHA-256 index.

Read-only receipt reproduction from this worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .local/shader-caller/reproduce.py
```

Required verification after rebasing onto current local main:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_astral_pkz.py' -v
git diff --check
```

Only this safe original document is tracked. No predecessor edits, source or
adapter changes, new extraction, download, runtime launch, SSH, credentials,
provider/auth operations, paid inference or nested delegation occurred. The
parent must commission **independent Astra/medium whole-head review before
`scripts/land`**. This worker does not waive review, land, push or create a PR.

**macOS and Linux remain partial; Windows remains blocked by unready controls;
iPhone and iPad simulator startup remain blocked; physical acceptance remains
unverified.** Separate simulators remain in scope. No platform was exercised.
Cross-ISA byte match is **N/A**; zero compute translations were measured here;
overall semantic/gameplay coverage is **unknown**. The approved 15:00Z deadline,
14:30Z dispatch cutoff and (amount omitted) total cap remain unchanged.
