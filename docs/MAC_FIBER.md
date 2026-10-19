# Mac fiber continuation adapter

FIBER-IMPL-078 adds an original Apple arm64 stackful adapter for the exact
DispatchFiberContext export. It preserves suspended native C++ call chains;
restoring guest SP alone does not implement a fiber. This is a measured candidate,
not independently accepted gameplay or a landing authorization.

The independently checked 077 evidence and actual compilation inputs agree on
the dispatcher ABI: pointer-to-context slots, a stack-resident saved frame,
callee-saved integer and full vector state, a first-entry trampoline argument,
and a restored return continuation. The generated dispatcher instead returns to
its source host caller. The earlier observed null store was in SwitchToFiber.
The destination's precise allocation/zero-register history remains unobserved;
a zero callee-saved register is legal and is covered by the regression.

The overlay leaves InitializeFiber, SwitchToFiber, SDK TLS and ThreadType layout
unchanged. First entry dispatches the SDK trampoline on an owned host stack.
Subsequent entries restore the suspended host stack and its native return chain.
Guest saved frames remain authoritative for the guest callee-saved values.
Host assembly preserves the Apple arm64 callee-saved integers, vectors, SP,
FPCR and FPSR. Each 8 MiB stack has inaccessible guard pages at both ends;
allocation is bounded to 1024 contexts per thread. CPU, host thread and guest TLS
ownership are checked, as are mapped permissions, ranges, alignment, source
stack membership, lifecycle and stale continuation identities.

FinalizeFiber interception calls the original guest finalizer before releasing
the owned stack. Active or foreign finalization is rejected. Thread retirement
returns to the original host root stack before freeing a currently active fiber
stack. Normal thread return and ExitThread call the cleanup hook. HLE diagnostic
names follow the suspended thunk stack. The existing loader already selects the
registered HLE for both imported and internally defined symbol relocations;
no broad relocation or generated-code change was needed.

Only the macOS target activates this backend. Linux, Windows and simulator
behavior is unchanged; this patch does not establish fiber support there.
Non-arm64 macOS builds fail explicitly at the adapter compile gate. No deprecated
ucontext API, fabricated pointer, no-op success, broad RET rewrite, guest source,
or guest binary is included in this overlay.

## Production regression

The standard-library unittest extracts public runtime inputs at the pinned
upstream revision, applies the real overlays in a temporary Git repository and
compiles the production adapter, assembly, CPU header and loader/dispatch source.
Synthetic VM and current-thread boundaries supply original fixture memory only.
They do not replace the continuation implementation. The kernel cleanup call
sites are compiled in the cumulative native executable; the fixture directly
exercises that same retirement hook, rather than a second kernel.

The original six-test result did not prove callback completion or independent
thread operation. Sol/high review `23bf3564b8c74ce58f67cd9d412b7130` failed exact
head `e272d31e6f0c400bc032eef1ac1d465b55eb7950`: P1 found callbacks incrementing
counters before suspending and a manually forced completed lifecycle; P2 found
the foreign-thread probe failing at source ownership before checking its
destination. Private baseline probes independently reproduced both gaps.
The first two setup attempts hit reference Git timeouts, before compilation.
The initial fixture compile used a nonexistent memory-state enum and was fixed.
Those original six tests passed in 7.252 seconds; that result remains partial.

Fix round 1 runs seven production tests without skips. Original synthetic
trampolines call the callbacks through the real production function table. Each
callback returns normally through its preserved native frames; only then does
its trampoline mark the guest lifecycle completed and transfer through the
production adapter. Root observes completed, suspended contexts, verifies that
re-entry is rejected, and invokes the registered finalizer HLE. That HLE calls
the original synthetic guest finalizer, checks retirement, and frees the stacks.
No completion state is forced by the root or finalization fixture.

Two simultaneously live threads each own distinct mapped root contexts, root
and fiber guest stacks, host stack locals, CPU objects, TLS identities and guest
register sentinels. Both execute the repeated root/A/B/A/root flow. At a shared
suspension boundary each attempts the other's destination with its own valid,
already-claimed source. The foreign-destination error is checked before both
threads resume their own flows, return their callbacks, finalize and retire.
A separate case retains foreign-source rejection. The fixture's process-exit
shim throws for negative probes; it restores diagnostic bookkeeping after these
expected fatal errors so later probes can run. Production fatal behavior is
unchanged.

The suite retains separate native locals, a host vector sentinel, first-entry
and resumed guest integer/vector sentinels, the legal zero-register regression,
nested HLE-name restoration, internal/import-style relocation selection, mapped
permissions and alignment, invalid/stale lifecycle checks, TLS ownership, both
actual stack guards, and active-fiber thread retirement with resource cleanup.
These tests require no adapter change: its existing lifecycle-3 outgoing
transfer, original-finalizer call and per-thread ownership paths pass the new
proofs. The production overlay and assembly are unchanged in fix round 1.
New evidence is under `.local/fiber-impl-078-fix1/`; original evidence is retained
unchanged under `.local/fiber-impl-078/`.

## Cumulative measured candidate

The baseline was accepted 075 binary SHA256
`c247165b19a5fac3a3a37959ba62561c9a49697e4381eded5adbdf1aab46e0d5`.
That retained binary and all prior evidence were left intact. Accepted 076 FS
and this fiber patch were applied once to exclusive native-current. Ordinary
incremental CMake/Ninja used two jobs and completed the build in 19.667 seconds.
All existing compile commands remained unchanged, with strict/high-memory flags,
real-renderer request, the retained private format profile and runtime-data-066-v2.
The resulting candidate binary SHA256 is
`dd69e7e2a407c20ab424dfcf8b59446cc3bbd958f6f270f0684afda6ad0ddb1a`.

The single native guest run executed 568 dispatcher HLE calls, one finalizer HLE
call and 284 present requests without the previous SIGSEGV or a strict fatal.
The supervisor requested a 60-second bound; the measured stage including cleanup
was 79.556 seconds and exited by SIGKILL (-9). **Native execution bound: FAILED.**
Its owned group was terminated and cleanup is recorded. This historical result
remains failed; the startup observations are partial.

The actual next blocker is renderer initialization: the log reports a Vulkan
Portability load failure and `nvn/vk: no Vulkan loader`. Consequently **zero
genuine displayed frames are evidenced**. Present requests are not successful
presentation: this runtime increments its guest frame counter even without a
working GPU path. No capture was produced and no gameplay is claimed. The
accepted runtime-data frame directory remained absent. The existing renderer
fallback was not altered or approved by this fiber unit.

Two bounded LLDB setup attempts failed before guest launch (script context and
an unavailable SBLaunchInfo method). No dynamic CPU/TLS/context probe or debugger
frame measurement was obtained; no further runs were made. The 077 static
premise and synthetic production continuation tests are distinguished from the
native trace's observed startup progress.

Distinct dependent **MAC-RENDERER-081** owns native supervisor/renderer validation
after independent 078 acceptance. It must verify retained Vulkan/MoltenVK
discovery configuration and require
actual renderer readiness before presenting counters as frames. Then run a fresh
bounded candidate with a working private debugger/capture recipe. No additional
installation, renderer replacement, save-state work or launch is authorized by
this document. 073v2 shader/data acceptance remains a separate requirement.
The split changes the single-unit adapter-plus-renderer premise and waives
neither gate. This fix round made no native source/build edits or guest/debugger
launches. The parent loader-ready instructions require a separately named,
post-acceptance run. There is one counted failed independent review; a second
failure requires stopping and splitting or challenging the remaining premise.
Independent Sol/high exact-head patch/result review is required and is not waived.

## Platform status

| Target | Status | Evidence revision |
| --- | --- | --- |
| macOS arm64 | partial | Historical 078 candidate over 077/076/075; native bound FAILED and renderer loader blocked. Fix-round production evidence under `.local/fiber-impl-078-fix1/`; no new native acceptance. |
| Linux x86-64 | partial | Retained `a3a1951d61785f2395e3441e6c46fa0a835160b6`; controller-support startup gate. |
| Windows x86-64 | blocked | Retained `ab9a8d672db64a88e1c120ad019b8094c24d8abe`; startup/session controls. |
| iPhone simulator arm64 | partial | Retained `1ac6acb1d2d27ff59698d06c2d60c28f036a23e8`; strict missing HID. |
| iPad simulator arm64 | partial | Retained `1ac6acb1d2d27ff59698d06c2d60c28f036a23e8`; strict missing HID. |

Both simulators retain 26.5 tested / 26.0 minimum target. No physical-device or
end-to-end gameplay acceptance exists. Semantic correctness remains incompletely
verified; cross-ISA byte match is N/A. No provider, paid compute, credentials,
remote or mobile work was performed.
