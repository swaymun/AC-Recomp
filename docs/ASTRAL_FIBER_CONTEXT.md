# Astral fiber continuation contract

FIBER-CONTRACT-077 is a diagnosis, not a runtime fix or a gameplay result.
The cumulative Mac crash exposes a concrete mismatch between guest fiber
control flow and the generated native call stack. It does not establish that
thread TLS is absent or that adding an InitializeFiber success hook is valid.
All private instruction listings, pointers, generated source and register
identities are retained only under `.local/fiber-contract-077/`.

The faulting SDK export is **SwitchToFiber**, not InitializeFiber. The earlier
InitializeFiber label describes the surrounding lifecycle and must not be used
as the fault identity. The SDK's own exported symbol table, relocation and
original instructions establish this distinction.

## Accepted cumulative baseline

075 producer run `3e3f5d747a8a4530b26ec79560d27a66` completed at head
`2b377681726133ddba003601dba4b5049c3ab092`, rebased base
`5044e9baed57ad8fbd7367664779c80193504690`, normalized patch SHA256
`5f9186ef67bb84264e545521359130591957dd536b77a292306f794cf1462a0f`.
Its independently passing review is
`62bc3213e41341659380d8cb12d7290e`; guarded landing records the same head
and patch at 21:35:08Z. Its immutable source-report SHA256 is
`ec75c06d0fad2bf64f520693e77ddfbce44e595b336e9af5774580e4fdf378af`.
075 landing was verified before this analysis. Its dependency is satisfied.

The retained executable and current native executable both hash to
`c247165b19a5fac3a3a37959ba62561c9a49697e4381eded5adbdf1aab46e0d5`.
All 26 indexed producer artifacts match their recorded sizes and SHA256s.
All 451 source files in the 075 after-fingerprint still match native-current.
The actual generated compilation inputs were obtained from the retained
compile database, rather than assumed from another similarly named tree.
The five relevant generated files also match the accepted regeneration receipt.
The checkpoint's native/debug receipt and log hashes match the originals.
Private `source-checks.json`, `regeneration-binding.json` and
`retained-hash-checks.json` record these independent checks.

Observed native execution was 21:22:43.799953Z–21:22:49.461782Z,
5.661788 seconds, SIGSEGV. Ten hwopus work-size requests completed; native
open/decode was not observed. The separately retained debugger run stopped at
the same null store, measured zero presented frames and explicitly killed its
target. This unit ran no build, guest or debugger.

## Causal chain and confidence

1. **Observed:** the host fault writes two zero words through a null host
   destination. Host disassembly of the hash-bound executable maps that
   destination to a guest callee-saved register in the CPU object, loaded
   immediately after the fiber dispatcher returns. Host and guest registers
   are different objects; the debugger's host CPU-object pointer is not a
   guest FiberType argument.
2. **Static, bound to the compiled source:** the scheduler caller passes an
   embedded fiber object. It can initialize/finalize that object and then calls
   SwitchToFiber through its import. The fault occurs after the latter's
   dispatcher call, not at a write through the initialization argument.
3. **Static path, supported by reaching the later fault:** SwitchToFiber reads
   the current SDK ThreadType through guest read-only TLS, obtains its active
   fiber state, constructs a temporary root context and publishes the target.
   The guest register later used for cleanup initially holds the active-state
   field pointer. Those earlier thread-state loads and stores completed on the
   observed path. A wholly missing thread pointer would fail earlier.
4. **Original SDK and generated semantics agree on the data moves:** the
   relocated dispatcher saves the outgoing stack/register context, loads the
   destination context, restores its stack, callee-saved integer and vector
   registers, and restores its return continuation. Original guest return
   transfers control to that restored continuation. First-entry initialization
   supplies a fiber trampoline and argument; a resumed fiber instead needs its
   suspended continuation.
5. **Confirmed static incompatibility:** the generated dispatcher ends with an
   ordinary C++ return. It therefore resumes the source host caller even after
   restoring the destination guest context. The generic return emitter makes
   this assumption explicit. The source cleanup then uses the destination's
   restored callee-saved value as its pointer. The observed null destination
   is consistent with precisely this path. The final assignment to that guest
   register in the dispatcher comes from the destination saved frame.

This establishes a translation/runtime **continuation ABI defect**, not a
missing service or an unsupported instruction. The existing CPU object models
guest registers; changing its guest stack pointer does not switch a host stack.
The existing longjmp exception adapter handles identified setjmp catch sites;
it cannot resume an arbitrary suspended fiber's native call chain. Dispatching
the restored return address once would address first entry only: later returns
can target the middle of suspended generated functions, which the current
function table cannot enter.

The retained debugger did not dump the CPU object, TLS memory, or destination
saved frame. Therefore the exact allocation history of the zero saved register,
first-entry versus resumed-destination state, and every original caller value
are **inferred rather than observed**. Initialization leaves other saved
register cells unspecified; zero there is not itself proof of corrupt input.
Earlier stack corruption, a malformed destination record, concurrency and host
undefined behavior have not been exhaustively excluded. They do not remove the
independently demonstrated continuation mismatch. No executed fix result exists.

## Public runtime comparison

Checked the requested pins, not the older dependency-lock LAS revision:

- [LASRecomp](https://github.com/peiikai/LASRecomp/tree/09f8e5ebf28aeefd6daa1456c73ae1b7a51efec5)
- [letsgo-recomp](https://github.com/raulzrrs/letsgo-recomp/tree/884f6d78035e537653c36579178cb0bb0c0b4f1d)

For each, read kernel, CPU and dispatch sources, generator/lifter and instruction
patch files, plus the staged HLE/service references. Sixteen fetched files match
the Git blob identities in the pinned tree receipts; exact SHA256s are private
in `reference-hashes.json` and `reference-extra-hashes.json`. Both generators
emit ordinary returns and direct native calls. Both kernels allocate per-thread
read-only TLS and associate a CPU with a host thread. Their setjmp/longjmp use
in thread entry is termination/unwind handling, not stackful guest fibers.
No Fiber or fiber-context implementation was found in the inspected paths.
This is a bounded negative finding, not a claim about every upstream revision
or every repository file. There is no evidenced compatible implementation here
to copy. Reuse their general thread ownership/cleanup principles, with MIT
attribution if actual code is adapted; do not replace the current runtime.

## Concrete successor brief boundary

Commission one separately authorized Mac-first implementation unit. Proposed
tracked scope is exactly `runtime/patches/astral-fiber.patch`,
`tests/test_fiber_context.py`, and this document. No implementation is authorized
by the present unit. The original overlay may affect only:

- upstream `runtime/src/hle_fiber.cpp` (new): a symbol-specific
  `DispatchFiberContext` adapter, guest save/restore helpers, root/first-entry
  and resumed-continuation management;
- upstream `runtime/src/platform.h` and `runtime/src/platform_mac.cpp`: the
  smallest owned host continuation/stack facility needed by that adapter;
- upstream `runtime/src/kernel.cpp`: a narrow thread-retirement cleanup hook,
  without changing ThreadType layout or TLS initialization;
- upstream `runtime/src/loader.cpp`: only if restoring the existing HLE-name
  bookkeeping across a suspended thunk requires it;
- upstream `CMakeLists.txt`: include the new translation unit.

Use the current loader's symbol relocation/HLE boundary for the exact dispatcher
export; preserve guest InitializeFiber, SwitchToFiber and GetCurrentFiber logic.
Retain SDK context records, integer/vector preservation, root return and callback
return semantics. If FinalizeFiber needs an interception for deterministic
host-stack release, constrain it to that export and call the original guest
finalizer; document its lifetime contract. Reject foreign-thread or stale
continuations and invalid mapped context/stack ranges. A source continuation
must resume only when its own context is restored. A host backend must preserve
suspended C++ frames and isolate fibers per owning guest thread. Preserve HLE
current-name bookkeeping, strict failures and owned-process cleanup.

Backend feasibility on Apple arm64 remains an implementation gate; this analysis
does not claim a particular deprecated host API works. First prove the selected
backend in the production adapter regression. Other platforms must fail
explicitly or retain their existing behavior until separately supported; this
unit does not authorize a platform-wide coroutine framework. If a correct
bounded backend requires generator-wide continuation labels or unrelated
platform changes, stop and split/challenge this scope. Do not turn every RET
into an indirect call, seed the null register with a plausible pointer, change
TLS merely to avoid this store, register a no-op, or swallow the crash.

## Regression and cumulative acceptance

The successor's standard-library unittest wrapper should compile the actual
production adapter and actual CPU/dispatch code against original synthetic guest
fixtures. It must prove ordered root → A → B → A → root execution with distinct
stack locals, multiple suspend/resume cycles, and callback completion. Compare
saved guest integer/vector state with independently chosen sentinel values;
verify TLS/current-thread identity stays thread-scoped while active-fiber state
changes. Reproduce the old failure using a legal destination whose saved
callee-register value is zero: the source cleanup must remain unexecuted until
its own continuation resumes. Test invalid ranges, alignment, stale/foreign
contexts, finalization, thread teardown, stack guards and cleanup without a
success fallback. Exercise loader symbol selection, including the SDK internal
relocation, so a correct unused helper cannot pass. No game bytes in fixtures.

After focused production regression and independent exact-head/result review,
the parent may authorize one serialized cumulative native unit: preserve 075
receipts/binary first; compose only independently landed overlays (including
076 FS if selected), record exact source/patch/compile identities; retain strict
Apple high-memory flags and existing real renderer/data/profile. Use normal
incremental Ninja, at most two compiler jobs, a 15-minute build and at most three
60-second guest/debugger runs under the established 30-minute-unit limits.
No clean rebuild, report-only rerun or concurrent native-current writer.

If dynamic confirmation is needed, use one bounded probe in that next unit:
capture guest CPU state, its owning thread/TLS ThreadType, outgoing and incoming
context-slot identities, mapped stack ranges and saved return continuations
immediately before dispatch; then capture the restored guest state and actual
next guest continuation. Store raw values privately. This distinguishes a valid
first entry from damaged saved state and proves the source cleanup waits for a
real return switch. Such a probe was not needed or authorized here.
Record actual exit/time, frame count and next blocker; capture a first genuine
frame privately if one appears. Passing this crash is only startup progress.
Gameplay still requires cold launch, menu, controlled movement/action, audible
sound, save, termination and reload; actual saves require the successor's scope.
After two failed fix rounds, split or challenge the premise.

## Target status retained from current evidence

| Target | Status | Existing tested revision and evidence |
|---|---|---|
| macOS arm64 | partial | `2b377681726133ddba003601dba4b5049c3ab092`; 075 native/debug receipts, zero frames and fiber null store. Later FS head `36471852b6e4633b6cef02e7d599ec7d832e42a2` is landed but not integrated into the measured native executable. |
| Linux x86-64 | partial | `a3a1951d61785f2395e3441e6c46fa0a835160b6`; `docs/LINUX_NATIVE_CUMULATIVE.md`, startup stopped at controller support. |
| Windows x86-64 | blocked | `ab9a8d672db64a88e1c120ad019b8094c24d8abe`; `docs/WINDOWS_NATIVE_CUMULATIVE.md`, partial startup and unready paid-session controls. |
| iPhone simulator arm64 | partial | `1ac6acb1d2d27ff59698d06c2d60c28f036a23e8`; `docs/IOS_CUMULATIVE.md`, strict missing HID after nnMain. |
| iPad simulator arm64 | partial | `1ac6acb1d2d27ff59698d06c2d60c28f036a23e8`; `docs/IOS_CUMULATIVE.md`, strict missing HID after nnMain. |

The non-Mac rows are retained prior observations, not reruns by 077. Both mobile
rows mean 26.5 simulator tested / 26.0 minimum target; no physical-device
acceptance. No target has verified gameplay. Independent Astra/medium review
of this exact committed diagnosis head and its private evidence remains required
from the lead before landing or implementing the proposed successor.
