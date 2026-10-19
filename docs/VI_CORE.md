# VI layer and scaling core

This unit extracts only the original VI overlay and synthetic dispatch fixture
from candidate `c18d5efaa0f776764590485a64ef4884b0ccc308`. It imports no native
supervisor, continuation tool or integration document. VI063 remains failed after
two rounds; its prior review is evidence of missing native acceptance, not approval
of this unit. Independent Astra/medium review of this unit's exact committed head
and `scripts/land` are still required through the lead.

The supported capability is one opaque display and one layer backed by the host's
singleton window. Open/create/native-window outputs require all eight bytes to be
writable before allocation or mutation. Wrong-kind, stale, foreign and null tokens,
uninitialized operations, duplicate opens/creates and invalid enum values fail
strictly. Destroy and close retire tokens without destroying the platform-owned
window. Tokens are never reused. Initialize is reference counted; Finalize at zero
is benign, intermediate releases preserve live handles, and the last release
retires all handles. Reinitialization creates fresh identities.

SetLayerScalingMode consumes Layer* in x0 and the low 32 bits of x1, with no output
pointer. Only mode 2 (FitToLayer) succeeds, using the existing full-extent host blit.
Modes 0, 1, 3 and 4 return `0x272`; modes outside 0..4 fail strictly. Requested
present-pass/FSR policy also returns `0x272`, including when a pass might later
fall back to blitting. This deliberately conservative check never changes renderer
configuration. (Later in the series, `astral-upscale.patch` lets FitToLayer succeed
with the present pass on too: it keeps the 16:9 aspect, which is the same geometry on a
16:9 window and adds bars on any other shape. Astral stops at boot when this call fails,
so NX_FSR, NX_PRESENT_PASS and NX_UPSCALE=fsr could not boot before;
docs/ASTRAL_UPSCALE.md.) Missing host windows return `0x272` from create/native-window
without modifying output. This is an API boundary implementation, not full VI IPC
or renderer emulation. Existing vsync and nv allocator behavior is outside this
unit's new verified capability.

Fresh private inspection of canonical main/sdk inputs records exact imports,
relocation/PLT binding and disassembly in ignored `.local/vi-core-068/abi.txt` and
`main-call.txt`. Main's exact scaling import binds to the PLT call at main+9c4890;
the caller loads Layer* into x0, sets w1=2 and tests w0. SDK+39d7a0 saves w1 and
x0, uses the display-service/object path, and returns `0x272` for failed native
window operation. It cannot safely consume opaque runtime tokens as SDK objects.
SDK Initialize+392c90 increments a shared 64-bit reference count; Finalize+3936e0
ignores zero, decrements nonzero and releases objects only at zero. This inspection
exposed the extracted candidate's missing Finalize/refcount support, fixed here.
No disassembly or game-derived source is tracked.

The regression prepares a fresh clone of pinned Wonder runtime
`010ed7a596a621c15d3a8dfa5795ca8c3668b066` and applies twelve overlays in order:
Apple memory, bootstrap, control import, SQSHL, notifications, APM, audio, IPC
buffer, applet, HID, controller support, VI. It compiles actual patched hle_vi.cpp,
loader.cpp and production presentation-policy functions with strict/high-memory
flags, in one compiler process. Synthetic writable memory, host-window and fatal
adapters exercise registry dispatch, supported/unsupported modes, enum width,
extent overflow/read-only/cross-region guards, canaries, allocation failures,
destroy/close, reference-counted finalize/reopen and stale identity rejection.
Five separate executions cover default blit, present pass, FSR, FSR overriding an
explicit pass-off setting, and both settings off. Receipts preserve ordered patch
hashes, full current source/header hashes, fixture/test/binary hashes, compiler
identity/version and commands, logs and observed results in ignored local storage.
These are current synthetic observations, not historical native-build provenance.

Native/gameplay verification is absent and semantic match remains unknown.
Cross-ISA byte match is N/A. There is no game launch, frame, performance or
platform acceptance claim for macOS, Windows, Linux, iPhone simulator or iPad
simulator. No old build objects were reused, inspected or authenticated by this
unit. The old incomplete 285-object attempt remains a failed native measurement.
A fresh native successor may follow independent landing only if it records
observed source, compiler/toolchain, build tools, external headers, configuration
and private input provenance before building in isolated source/build directories,
with realistic time for completion and cleanup before the run deadline. Do not
reconstruct missing old provenance or claim reuse of historical objects.
