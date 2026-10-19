# Astral NVN program binding

NVN-PROGRAM-087 fixes a confirmed CPU replay defect behind the observed
`no vertex shader` rejection. Astral binds vertex and fragment stages from
separate NVN program objects. Recording preserves the stage mask, but inherited
replay discards it and replaces one global program handle. A fragment-only bind
therefore removes the previously bound vertex stage even when both translations
are present and correctly classified.

The original overlay is `runtime/patches/astral-nvn-program.patch`. Under
`NX_ASTRAL_STRICT`, replay keeps a program handle per NVN stage and changes only
slots selected by `Cmd::mask`. Graphics resolves vertex/fragment stages from
their respective programs; compute resolves its separate slot. Resolution stays
at replay time. Null, absent, empty or wrong-stage programs do not reuse an old
shader. No cache expansion, shader substitution or permissive fallback is added.
The default-title program path and the existing draw rejection checks remain.
The current renderer still supports only vertex, fragment and compute stages;
this overlay does not implement geometry or tessellation.

## Causal evidence

The parent boundary receipt was verified against its assigned SHA-256
`b08cc541b4bf922eeb058f414adb02a5a027da8304a97bff18f22b1f46112ffb`.
Its 53,923,753-byte stderr matches SHA-256
`12def90b09e390a39649f9b0ef5d04f4d5c7f13801f2daeee288b693d8741a47`.
It records 1,207 cache records and ends with 55,076 draws, zero completed,
54,844 rejected without a vertex stage and 232 without a program. The parent's
capture observation is black; it is not a game frame. Unit 086's result remains
subject to its own independent review.

The worker checked 16 saved bind observations against 086's actual debugger
stdout. Consecutive binds on the same command buffer use mask 1 for a program
containing a reflected vertex shader, then mask 2 for a different program
containing a reflected fragment shader. The measured main generated caller uses
the same proc indirection for both calls and explicitly supplies those two
masks and distinct program fields. Raw guest source and addresses stay private.
The separately captured launch stderr confirms that those program objects had
already retained their successfully loaded stage hashes. Five matching original
Astral code/control samples agree with the documented control magic, code size,
program bounds, graphics start offset, code-block SHA-1 and SPH stage. They are
offline samples, not a new snapshot of the guest's live shaderData memory.

The traced path is:

1. `nvnProgramSetShaders` reads 16-byte code/control pairs; `Ext` uses 24 bytes.
   GPU code addresses resolve through `pool_at_gpu` to pool storage plus offset.
   This runtime maps guest CPU pointers directly as host pointers; control pointers
   are not GPU addresses and need no additional relocation.
2. `shader_for` validates the control magic and size, hashes the complete code
   block using the first 16 SHA-1 hex digits, then loads the matching SPIR-V.
   Stage classification comes from SPIR-V reflection. The program stores pointers
   to successfully resolved cache objects. Invalid control, absent translation
   and reflection failures remain failures.
3. `nvnCommandBufferBindProgram` records both the program and mask. The defect is
   in `draw_command`: the original assignment ignores the mask. The next draw
   resolves only the last program and increments `no_vertex` for a fragment-only
   vector. It does not reach pipeline creation.
4. The overlay preserves selected bindings and combines only their matching
   reflected stages for graphics. Compute binds cannot replace graphics slots.

A virtual memory pool would require `pool_host` rather than direct pool storage
in `set_shaders`; that is a separate source concern, with no causal evidence for
these observed successful program loads. This unit deliberately does not change
it. Remaining missing shader hashes, compute coverage, pipeline linking and any
later GPU or service failure remain unresolved. Offline translation totals do
not establish rendering or explain every rejected draw.

## Production regression and integration

Run exactly:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_nvn_program.py -v
git diff --check main HEAD
```

The test uses the pinned public runtime, existing local Vulkan headers and a
local C++20 compiler. `NVN_REFERENCE` and `NVN_VULKAN_INCLUDE` can select those
existing inputs. It downloads nothing and uses no game, device, cloud or GPU.
It compiles the actual program lifecycle, HLE bind recorder and full replay state
translation unit. Draw/dispatch selection prefixes are taken verbatim from the
production file and compiled up to their first GPU-dependent work. Synthetic
memory/cache adapters supply stage objects; GPU callbacks throw if invoked.
The full changed production translation units also receive syntax checks in
Astral and default profiles. This is CPU boundary evidence, not GPU execution.

The unmodified production path must reproduce `no_vertex=1` after separate
vertex/fragment binds. Patched Astral must retain both; the default profile must
preserve inherited behavior. Cases cover a combined program, selective stage
replacement and null unbind, empty/unknown masks, compute isolation and unbind,
wrong-stage/missing/finalized programs, object reinitialization and state reset.
Private receipts retain source, overlay, fixture and binary identities and
actual outputs under `.local/nvn-program-087/`.

Apply this overlay to a private copy of the recorded stable runtime only after
independent Astra/medium exact-head/result review. The three affected baseline
files are byte-identical to the public pin below. This unit does not integrate
it into the stable tree, change build orchestration or launch the game. The
parent must assign the later bounded native integration/run explicitly; 086's
frozen inputs and result stay unchanged. Review is required and is not waived.

The underlying runtime is MIT-licensed SuperMarioWonderRecomp at
[`010ed7a596a621c15d3a8dfa5795ca8c3668b066`](https://github.com/BelmanteGu/SuperMarioWonderRecomp/tree/010ed7a596a621c15d3a8dfa5795ca8c3668b066).
Its `runtime/src/nvn/nvn_state.cpp`, `nvn_draw_state.h` and `docs/nvn/SHADERS.md`
provide the local source contracts used here. Existing upstream license and
third-party notices remain applicable; the overlay and synthetic fixtures are
original. No leaked SDK header or third-party game source was used in the patch.

Mac and Linux remain partial. Windows remains blocked with the rented Windows cloud machine saved and off and
controls NOT READY. iPhone and iPad simulators remain separately partial,
26.5 tested / 26.0 minimum; physical acceptance is unverified. No genuine game
frame or gameplay is confirmed. Cross-ISA byte match is N/A.
