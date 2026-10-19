# Astral shader input edge — SHADER-INPUT-012

**A second direct forwarding edge is proven; association with the selected
unchanged compute wrapper remains unknown.** The single new body passes its
incoming **second** argument as the accepted construction entry's **third**
argument. It supplies no selected-member identity or extent provenance.
Inspection stops at that incoming pointer. `translation_ready` remains **false**,
with **zero new semantic mappings** and **zero compute translations**.

Read the run plan, first units,
[accepted association](ASTRAL_SHADER_ASSOCIATION.md) and its referenced
[third caller](ASTRAL_SHADER_CALLER_THIRD.md), [second caller](ASTRAL_SHADER_CALLER.md),
[consumer](ASTRAL_SHADER_CONSUMER.md), metadata,
contract, format,
[translation](ASTRAL_SHADER_TRANSLATION.md), [inventory](ASTRAL_SHADER_INVENTORY.md)
and preflight. Retained reports/scripts were inspected as
untrusted evidence; their suggestions were not treated as original behavior.

## Verified predecessor and unchanged inputs

Producer `dd329673789e4b42a336c761fc25729c` reported reviewed head
`2f7bdb0ccdfc8eba02396bbd5af42be43a13ea3d`. Independent Astra/medium review
`0b2a2e3d6e5142a49f9f5ee176f1b14c` passed that exact head. Its landing receipt
names reviewed head above and landed head
`b369a2e2cab5d91ebad0efb791d7082831a8ef38`. Both commits independently reproduce
normalized patch SHA-256
`7aa91739cec417ffde370e110e7eba2ebe65183c81a568952528396e4ffc3aeb`.
The landed head is an ancestor of local main. The association document is
byte-identical at the reviewed head, landed head and main. Producer/reviewer run
records, reports and landing receipt were checked and independently hashed.

All **29/29** indexed predecessor files matched sizes and SHA-256 hashes. The
index's complete file set, excluding its stated self-reference exclusions, also
matched the retained directory. Its SHA-256 matches producer and reviewer reports:
`ce26d8927fe7d70eb782a5ab06ca376700da363500183964569f45020e078fdd`.
Predecessor provenance SHA-256 is
`3af44a34888cc08a08613fceb165e84baf9206226e6fd9e6395a8a34c289a0d6`;
analysis SHA-256 is
`a5c3be80eff8331521b63183d7770148f0347605b97a037d0c45aa5787e3efaa`.
All external identities recorded in that provenance were rehashed before use.

The same retained decoded member, wrapper and original control/code partitions
matched unchanged. Wrapper SHA-256:
`b0fb6bc81e1340f73ca8b4b19ab5f613370c2cc03fa476c236b43013f97d2da8`;
control SHA-256:
`3e29fac8dd40e4f6cf00f6ad3e3487678f4a2805a881c5d4c62b34997156092c`;
code SHA-256:
`a3acc3f4d95f2872edda8bb9158526c4890101b30d2200044a1750e8005bac7a`.
Exact member identity, decoded-member hash and original extents remain private.
Both retained original modules, NSOs, every flat segment and seven predecessor
generated files matched their recorded identities. No extraction, download,
decompression, shader translation or input modification occurred.

## One immediate direct tail-call body

Starting exclusively from the verified construction entry coordinates, a literal
search for its exact symbol in the existing generated tree returned **four hits**:
its definition, declaration, address-table entry and **one direct tail branch**.
There are **zero link-register-writing direct calls** to this symbol in those
hits. The unconditional direct branch is a tail call, preserving the existing
return address; its target is explicit, with no indirect resolution required.
It is the sole direct call-site body and therefore uniquely first in original
address order. The table reference was not followed or promoted to a call.

Only that new complete body was inspected. All **9/9 original instructions**
matched generated comments in order, ending in the direct tail branch. Original
module-relative offsets, flat-image offsets, generated lines, containing-file
hashes and complete body hash are retained privately. Module-relative virtual
offsets map to flat-image offsets; live module bases remain unobserved.
Generated code was never executed. No predecessor body was re-disassembled.

| Boundary | Proven in the new original body | Limit |
| --- | --- | --- |
| Incoming values | The first, second and third entry arguments are saved temporarily for argument rearrangement. | No original selected-member identity accompanies any argument. |
| Context source | The first outgoing argument is read from a fixed module-relative pointer slot. | Live slot contents and the pointed-to context remain unknown. The slot and its target were not followed. |
| Direct tail edge | Outgoing arguments two, three and four equal incoming arguments one, two and three respectively. The final original branch targets the exact accepted construction entry. | The relevant wrapper pointer is only this body's incoming second argument. There is no selected base, length or extent construction. |
| Complete-body behavior | Nine instructions perform register moves, one module-relative address formation/load and the tail branch. No intervening calls or guards occur. | This establishes forwarding independently of callee-saved-register assumptions inside this new body. It does not establish behavior after entry into the accepted construction body. |

Composing this edge with the accepted predecessor remains conditional on that
predecessor's original guards and ordinary preservation of its saved registers
by untraversed calls. Its destination/context, supplied resolver, actual upload
cell, runtime path and successful upload remain unknown. Registration and prior
upload bodies were not inspected again. No helper, resolver, loader, additional
caller or fourth upload caller was traversed.

## Missing artifact and premise assessment

The exact unresolved selected-wrapper boundary is **this new body's incoming
second argument**, copied into the accepted construction entry's third argument.
No dereference or original selected-member provenance for that pointer occurs
here. The module-loaded context pointer is separately unresolved and untraversed.
Signature compatibility and conditional downstream extent expressions cannot
establish the selected wrapper's participation. Association is **unproven**;
this result does not reject the path.

The minimum missing artifact is **one provenance-bearing original dataflow or
captured argument record binding this exact incoming second argument
(equivalently the accepted construction entry's third argument) to the unchanged
selected retained member base and original extents, with the address-coordinate
mapping needed to compare them**. A raw pointer without member identity and
extent provenance is insufficient. No such artifact was obtained here; no
runtime capture is authorized or performed by this unit.

**Further static forwarding searches alone have no demonstrated value for
closing this association.** Two association edges have now only moved unbound
incoming pointers. Repeating this method would extend the chain without evidence
that the next body contains selected-member provenance. Stop this approach until
the named artifact exists or a separately scoped investigation has concrete
provenance-bearing evidence. No automatic next-caller or loader search is
proposed. Resolver/live-provider selection remains a separate prerequisite.

No metadata semantics, compute-stage mapping, executable start/length meaning,
scheduling placement, dimensions/units, memory requirement or resource binding
is established. The control tail remains uninterpreted. Translator defaults,
plausible values and output reflection supply none of these facts. No runtime,
adapter or translator implementation is delivered.

## Reproduction, verification and review

Ignored `.local/shader-input-edge/` retains `provenance.json`, complete literal
hits, the one new generated body, original analysis, reproduction scripts and
command receipts with UTC start/end, commands, exits and script hashes.
`run.py` bounds child commands to 85 seconds. The complete SHA-256 index covers
all local evidence except itself and the finalizer's command receipt to avoid
self-reference; its hash is carried in the structured worker report. External
inputs are referenced and hashed without being copied or modified.

No analysis failure occurred in this unit. The predecessor's initial padding
count failure and exact failed script remain separately preserved in its verified
29-file index; they were not rerun or overwritten. Read-only reproduction:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 .local/shader-input-edge/reproduce.py
```

Required verification after rebasing onto current local main:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_astral_pkz.py' -v
git diff --check
```

Only this safe original document is tracked. No predecessor edits, runtime
launch, SSH, provider/auth action, credential access, paid inference or nested
worker/review occurred. The parent must commission **independent Astra/medium
whole-head review before `scripts/land`, without waiver**. This worker commits
only its scoped branch and does not land, push any branch or create a PR.

**macOS/Linux remain partial; Windows remains blocked by unready Windows cloud machine controls;
separate iPhone and iPad simulator scenes remain blocked.** Runtime is **26.5
tested / 26.0 minimum target**; physical acceptance is unverified. No platform
was exercised here. Compute translations remain **zero**, semantic/gameplay
coverage **unknown**, and cross-ISA byte match **N/A**. The 15:00Z deadline,
14:30Z cutoff, (amount omitted) total cap and all four target families remain unchanged;
parent owns providers and authentication.
