# Astral third retained shader caller — SHADER-CALLER-010

**Signature-compatible, with conditional upload arguments established; blocked
at the selected-wrapper input-object association.** The third retained caller's
original comparison accepts the unchanged selected compute wrapper's prefix.
That alone does not establish an upload, compute-stage selection or metadata
semantics. `translation_ready` remains **false**, with **zero invented mappings**
and zero compute translations.

Read the run plan, first units,
[second caller](ASTRAL_SHADER_CALLER.md), [original consumer](ASTRAL_SHADER_CONSUMER.md),
metadata evidence, translator contract,
format diagnosis, [translation evidence](ASTRAL_SHADER_TRANSLATION.md),
[inventory](ASTRAL_SHADER_INVENTORY.md) and preflight.
Retained reports and scripts were inspected as untrusted evidence; their proposed
next steps were not treated as recovered game behavior.

## Verified predecessor and fixed selection

The predecessor producer run `22852b73bb6144a6a266d3efdec43b4b` reported exact head
`ca63663b0e0a5b94cbea5e947de63cc897b70492`. Independent Astra/medium review
`583dd01b8a414754b411fc5377374c12` passed that head. Its landing receipt names the
same reviewed and landed head. Independently recomputed normalized patch SHA-256:
`37c0393b8b3bd8ba6c8c64f343978503b80c5c50709c2a23a48c93139500b9a5`.
The landed head is an ancestor of local main; its document is byte-identical on
main. Producer/reviewer run identities and report files were independently hashed.

All **22/22** predecessor indexed files matched byte lengths and SHA-256 hashes.
Its receipt index matched producer/reviewer hash
`828522c2acc9c6d899e4f5a1ba8dc0b7aa83dfa9b9f5cafc964a24b78e9990c1`.
External files carried in its provenance were rehashed as well. The pre-existing
`candidates.json` independently matched
`240af776acc7eaad5df57af3e1a38d083e359f4186fda8df1df0a802b96b0de6`.
Selection is exclusively its **third address-ordered non-registration caller**,
identical to the predecessor's recorded next candidate. No new candidate search,
fourth caller or repeated first/second caller analysis occurred.

The retained decoded member, entire wrapper and original control/code partitions
matched unchanged. Wrapper SHA-256 remains
`b0fb6bc81e1340f73ca8b4b19ab5f613370c2cc03fa476c236b43013f97d2da8`;
control SHA-256 is
`3e29fac8dd40e4f6cf00f6ad3e3487678f4a2805a881c5d4c62b34997156092c`;
code SHA-256 is
`a3acc3f4d95f2872edda8bb9158526c4890101b30d2200044a1750e8005bac7a`.
Exact member identity, extents and decoded-member hash remain private.
No extraction, decompression, shader decoding, translation or input modification
was performed.

## Complete original caller and conditional arguments

Both retained main/SDK flat images, NSOs, every segment and seven generated files
matched their manifest/predecessor identities. Original module-relative virtual
offsets equal flat-image offsets; generated instructions use module base plus
offset. Live bases were not observed. All **98 original instructions** of this
one caller matched its generated comments in order, with exact original addresses
and generated lines retained privately. No generated code was executed.

The original registration name, lookup/store slice and relative slot relocation
were checked again. The selected caller uses that registered upload cell.
Registration's supplied resolver and the live cell contents remain unknown;
static relocation is not evidence of actual provider/default selection.

| Boundary | Established original behavior | Remaining condition |
| --- | --- | --- |
| Entry and initialization | The third entry argument is the wrapper base directly. The second argument is the destination passed unchanged to initialization and upload. Initialization must return a nonzero low byte; the caller then stores a fixed word in the destination. | Actual arguments, initialization result and the stored word's meaning remain unknown. No initializer body was followed. |
| Signature | Original address formation selects the compute-wrapper signature. The original PLT/GOT relocation and dynamic symbol resolve the four-byte comparison to `strncmp`. The unchanged selected prefix compares equal. | This closes only the signature mismatch question. Initialization may fail earlier, and equality supplies no input-object association or stage-enumeration mapping. |
| Further guards | Two wrapper bytes are checked against signed context bounds. A context cursor is aligned to 256 bytes, and the code-length word bounds an allocation against a context limit. A formed destination address must be nonzero. | Runtime bounds, allocation state and byte meanings are unknown. Original arithmetic wraps at register width; no overflow safety is inferred. |
| Copy arguments | A direct call receives the allocation destination, wrapper base plus its original code-offset word, and its original code-length word. | Its body was not followed. If the wrapper argument were the selected wrapper, these expressions identify its unchanged retained code extent; that antecedent is unproven. |
| Mapped components | An untraversed helper must succeed and supply two stack values. Two indirect calls consume those values; one return value combines with a stack value. | Helper outputs, indirect targets and mapped-address values are unknown. |
| Upload arguments | Destination is the second entry argument; count is one; the pair-array address is a stack pair. Its first element combines the mapped components; its second is wrapper base plus the original control-offset word. The call loads through the registered upload cell. | Actual pointer values, live dispatch and selected-wrapper association remain unknown. Conditional expressions do not prove a successful upload. |
| Return | Guard/helper failure returns zero. After upload, the caller normalizes the upload result's low byte to a Boolean. | No return value or upload was observed at runtime. |

Exact register/stack expressions, instruction ranges, relocation records,
comparison constant identity and conditional selected extents are retained in
private `analysis.json`. No helper, upload body, sibling caller, loader chain or
input-construction body was explored. No guard was bypassed or metadata defaulted.
Inspection stops at the unresolved association.

## Precise blocked prerequisite and next bounded gate

The missing fact is **whether this exact retained wrapper supplies the third
entry argument of this original caller**, with a destination/context that satisfy
its guards and original registration that supplies the upload cell. Signature
compatibility and conditional control/code expressions cannot establish that
fact. This result does not reject the third caller and does not justify a fourth
caller search.

A separate bounded input-construction/registration investigation can start from
the existing private caller-entry coordinates, selected member identity and
registration slice. It should authorize one immediate input-construction edge
into this exact caller, require original evidence tying the selected member's
base/extents to the wrapper argument and the resolver to the registered cell,
and stop at the first unresolved pointer/indirect association. If those artifacts
are unavailable within that bound, report the exact missing artifact instead of
following a loader/helper chain. This is a proposal only; it was not initiated.
Actual provider selection remains a separate conditional gate.

Compute-stage selection, executable start/length semantics, scheduling-slot
placement, X/Y/Z association and units, local versus dispatch interpretation,
local/scratch requirements, shared-memory units/scope/zero semantics, constant
bank/bound-data/use-mask association and dispatch-time resource bindings all
remain **unknown**. The control tail remains uninterpreted. Translator defaults,
clamping, plausible values and translated-output reflection establish none of
these meanings. No adapter, translator or runtime implementation is delivered.

## Reproduction and review limits

Ignored `.local/shader-caller-third/` retains:

- `provenance.json`: predecessor producer/review/landing identities, patch/main
  checks, all indexed/external hashes, selected input and fixed candidate.
- `analysis.json`: original/generated coordinates, module/segment/source hashes,
  registration/relocation checks, compatible signature, conditional arguments,
  unresolved association and explicit empty semantic mappings.
- `provenance.py`, `analyze.py`, `reproduce.py`, `run.py`: inspected reproduction
  code; the first two print observations without writing unless `--output` is
  supplied. The runner bounds each command to 85 seconds.
- `*.command.json`: commands, UTC start/end, elapsed time, exits, output and
  script SHA-256 hashes. The initial probe was named `inspect.py`, shadowing the
  standard Python module during Capstone import. It exited one after a recursive
  import wrote a provisional inspection receipt. Its exact script, failed
  command and provisional receipt are preserved separately and are not accepted
  analysis. Renaming the probe corrected the import; final analysis passed.
- `verify.json`, `receipt-index.json`: post-rebase checks, exact committed head,
  clean tracked status and complete local evidence SHA-256 index. The structured
  worker report carries the index hash to avoid self-reference.

Read-only reproduction from this worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .local/shader-caller-third/reproduce.py
```

Required verification after rebasing onto current local main:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_astral_pkz.py' -v
git diff --check
```

Only this safe original document is tracked. No predecessor edits, additional
extraction/download, runtime launch, SSH, provider/auth operation, credentials,
paid inference or nested worker/review occurred. The parent must commission
**independent Astra/medium whole-head review before `scripts/land`**, without
waiver. This worker does not land, push or create a PR.

**macOS/Linux remain partial; Windows remains blocked by unready Windows cloud machine controls;
separate iPhone and iPad simulator scenes remain blocked.** Simulator runtime is
26.5 / minimum target 26.0; physical acceptance is unverified. No platform was
exercised here. Cross-ISA byte match is **N/A**; compute translations are **zero**;
overall semantic/gameplay coverage is **unknown**. The 15:00Z deadline, 14:30Z
dispatch cutoff, (amount omitted) total cap and all four platform families remain unchanged.
