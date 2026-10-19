# Astral shader input association — SHADER-ASSOCIATION-011

**One immediate direct edge is established; selected-wrapper association remains
blocked at its incoming pointer.** The one inspected construction body forwards
its own third entry argument to the exact third retained caller. It does not tie
that argument to the selected unchanged member. Inspection stops there.
`translation_ready` remains **false**, with **zero invented mappings** and
**zero compute translations**.

Read the run plan, first units,
[third caller](ASTRAL_SHADER_CALLER_THIRD.md) and its linked
[second caller](ASTRAL_SHADER_CALLER.md), [consumer](ASTRAL_SHADER_CONSUMER.md),
metadata, contract,
format, [translation](ASTRAL_SHADER_TRANSLATION.md),
[inventory](ASTRAL_SHADER_INVENTORY.md) and preflight.
Reports and reproduction scripts were inspected as untrusted evidence before
execution; their suggested investigations were not treated as recovered behavior.

## Exact predecessor and unchanged inputs

Producer run `ceba8f59395a43c599bfe800b9300d9e` reported exact head
`1f8f771afb34c45e92c53f6fa61fa1f9400d8ba9`. Independent Astra/medium review
`d592f57e36fa4c13b625c63c3229e421` passed that head; the landing receipt names
that same reviewed and landed head. Producer/reviewer run records, reports and
landing receipt were independently hashed and checked. Recomputed normalized
patch SHA-256 is
`fa23da0e23a16bb13125247c1b25448cd00035ed1f2f8c17bba6ae0cf2a22849`.
The head is an ancestor of local main, whose third-caller document is identical.

All **21/21** predecessor indexed files matched sizes and SHA-256 hashes. The
index matched both producer and reviewer evidence:
`cf14905f3c437402ceb44d0958b5094fc2cfb337a40312732467f0062dce7c9f`.
Predecessor provenance SHA-256 is
`50e4ddf3218c32553c3c758e56f3e68f6722bd57b93372254a720a45d4793115`;
analysis SHA-256 is
`1dc9e78fed9a13135631bbcab46801706bcbfde3fc0aa528dd13fd1cabd1a0ad`.
External identities recorded in that provenance were also rehashed, including
the existing candidate inventory. Coordinates came exclusively from these
verified receipts; there was no new upload-candidate search.

The same decoded member, selected wrapper and original control/code partitions
matched unchanged. Whole-wrapper SHA-256 remains
`b0fb6bc81e1340f73ca8b4b19ab5f613370c2cc03fa476c236b43013f97d2da8`;
control SHA-256 is
`3e29fac8dd40e4f6cf00f6ad3e3487678f4a2805a881c5d4c62b34997156092c`;
code SHA-256 is
`a3acc3f4d95f2872edda8bb9158526c4890101b30d2200044a1750e8005bac7a`.
Exact member identity, original extents and decoded-member hash remain private.
Both retained original modules, NSOs, every flat segment and seven predecessor
generated files matched their recorded identities. No input was extracted,
downloaded, decoded, translated or modified.

## The one authorized immediate edge

Starting from the recorded third-caller entry, a literal search for that exact
symbol in the existing generated tree returned **four hits**: its declaration,
definition, address-table entry and **one direct call**. All hits and the four
containing-file hashes are retained privately. The table reference was not
promoted into a call edge or followed. The sole direct call is necessarily first
in original address order; only its complete containing body was inspected.
The third upload body was not repeated.

All **70 original instructions** in this construction body matched generated
comments in order, through its final return. Original module-relative offsets,
flat-image offsets, generated lines and the complete body hash are retained in
private `analysis.json`. Generated code was never executed. Live module bases
and call results were not observed.

| Boundary | Established from the one original body | Limit |
| --- | --- | --- |
| Incoming values | The body saves its first argument as an owner/context source, second as a holder, and third as the prospective wrapper pointer. | No selected-member provenance is supplied for any incoming value. These labels describe uses, not recovered object types. |
| Preparation | It conditionally cleans old holder contents, clears the holder pointer/flag, tests the saved wrapper and an owner-loaded pointer, then makes an untraversed direct call using a fixed size-like literal and an owner-loaded value. Its returned destination must be nonzero. | Called bodies, indirect targets, return values and actual allocation behavior are unknown. No allocator or cleanup implementation was followed. |
| Exact third-caller edge | It clears a destination word, forms the context argument from an owner-loaded pointer plus a fixed adjustment, passes the returned destination as argument two, and forwards the saved incoming wrapper pointer as argument three. The original direct branch targets exactly the recorded third entry. | Forwarding across earlier calls assumes ordinary preservation of the saved registers. Call effects and runtime guards remain conditional; context validity is unknown. |
| Result handling | A nonzero third-caller result stores the destination and success flag. Failure paths conditionally invoke untraversed cleanup calls and clear holder state. | No call or successful result was observed. This establishes neither upload nor shader selection. |

The selected member's base and extents are **not constructed or bound here**.
The exact unresolved boundary is the construction body's **incoming third
argument**, saved in a preserved register and copied into the third retained
caller's third argument at the recorded direct call. No original member-backed
pointer, selected extent or selected-member identity is established for it.
Wrapper signature compatibility from the predecessor cannot fill this gap.

Only the existing registration lookup/store slice and its original relative
relocation were rechecked. They retain the same upload-cell association,
conditional on the resolver supplied to registration. The supplied resolver,
actual live cell contents and provider selection remain unknown. No resolver,
helper, loader chain, additional caller or fourth upload caller was traversed.

## Missing artifact and next bounded gate

The missing artifact is **original provenance tying this construction entry's
third argument to the exact selected retained member base and extents**. The
one inspected body merely forwards an unbound pointer. The selected-wrapper
association is therefore **unproven**, not rejected. Inspection stops at that
first unresolved pointer boundary.

A separately authorized gate could start only at this construction entry's
private coordinates, enumerate literal references to its exact symbol, select
at most one direct call-site body by original address order and inspect that
one complete body against original instructions. It must require the same
selected-member base/extents binding, stop at the first unresolved incoming or
indirect pointer, and report a missing direct edge rather than beginning a
loader search. This gate was not initiated. Resolver/live-provider selection
remains a separate prerequisite; no further chain is implicitly authorized.

No metadata semantics, compute-stage mapping, executable start/length meaning,
scheduling placement, dimensions/units, memory requirement or resource binding
has been established. The control tail remains uninterpreted. Plausible values,
translator defaults and translated-output inference supply no association.
No runtime, adapter or translator implementation is delivered.

## Reproduction and review limits

Ignored `.local/shader-association/` retains predecessor and input provenance,
the complete literal-hit enumeration, one generated construction body, original
analysis, reproduction scripts, and UTC/command/exit receipts. `run.py` bounds
each child command to 85 seconds. `receipt-index.json` covers all retained local
evidence except itself and the finalizer command receipt, avoiding self-reference;
the structured worker report carries its hash. External inputs are referenced
by path, size and SHA-256 rather than copied or modified.

An initial analysis compared through the next generated function boundary,
including alignment padding, and failed its instruction-count assertion. The
exact failed script and command are preserved separately. The corrected analysis
ends at the complete body's final return, matches every original instruction,
and passes read-only reproduction. The predecessor's separate import-shadowing
failure remains preserved in its independently verified index.

Read-only reproduction from this worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .local/shader-association/reproduce.py
```

Required verification after rebasing onto current local main:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_astral_pkz.py' -v
git diff --check
```

Only this safe original document is tracked. No predecessor edits, runtime
launch, SSH, provider/auth operation, credentials, paid inference or nested
delegation/review occurred. The parent must commission **independent
Astra/medium whole-head review before `scripts/land`**, without waiver. This
worker does not land, push any branch or create a PR.

**macOS/Linux remain partial; Windows remains blocked by unready Windows cloud machine controls;
separate iPhone and iPad simulator scenes remain blocked.** Runtime is **26.5
tested / 26.0 minimum target**; physical acceptance is unverified. No platform
was exercised here. Cross-ISA byte match is **N/A**; compute translations remain
**zero**; overall semantic/gameplay coverage is **unknown**. The 15:00Z deadline,
14:30Z cutoff, (amount omitted) total cap and all four platform families remain unchanged.
