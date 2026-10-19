# Astral hwopus contract investigation

HWOPUS-CONTRACT-074, 2026-10-18. Documentation only; no build or guest launch.
Baseline: `bc246f852a266ee0cd07f2aa6347631a14f8c129`.
Candidate NVN-TEXTURE-072 is `55a6599c674ebdfa46ba2f663f198f19643e67b8`;
this investigation does not accept that candidate or replace its independent review.

## Observed boundary

The retained normal Mac launch at 21:04:10Z exited 1 after 2.889 seconds.
Its log ends with SM command 1, `GetService(hwopus)`, and the strict
missing-service fatal. The separate retained LLDB stack reaches `make_service`
through SM, IPC dispatch, the kernel send bridge, generated SDK code and the
game caller. Its presented-frame counter is zero. This is service **acquisition**
failure before the manager session is returned. There is no observed hwopus
manager/decoder command, PCM, audible output, first frame or gameplay.

The generated SDK path resolves the service-name string to `hwopus` and creates
its hardware Opus manager through HIPC. The stack's SDK work-buffer-size API
and its actual game caller identify the purpose: initializing cached work-buffer
requirements. This conclusion follows the caller and service lookup, not the
last graphics log entry. The caller statically asks for mono at 8000, 12000,
16000, 24000 and 48000 Hz, then stereo at those rates, retaining the maximum
rounded size per channel count. The SDK cache starts in zero-initialized storage;
a cache miss acquires the manager, performs the size query, rounds its result up
to 4096 bytes, caches it and releases the manager. Execution stopped during the
first acquisition; the ten requests are a static prediction, not an observed log.

## Static wire contract

Offsets below are relative to command arguments after SFCI, or reply scalars
after SFCO/result; they are not packet offsets. This SDK emits CMIF request
with context (HIPC type 6), SFCI version 1 and a context token. Existing runtime
parsing accepts this. Integer scalars use the runtime's little-endian ABI.

| Interface / command | Input | Successful output | Evidence limit |
| --- | --- | --- | --- |
| Manager 1: work-buffer-size query | 8 bytes: sample rate u32 at 0, channel count u32 at 4; no buffer descriptors or handles | Result plus one u32 byte count at scalar offset 0 | Direct SDK marshaller, manager vtable and startup caller agree; console service's numeric sizing algorithm is absent |
| Manager 0: open single-stream decoder | Same packed rate/channels at 0/4, transfer-memory byte count u32 at 8; one **copy** handle for transfer memory; no data buffers | One decoder interface, returned as a moved session handle in this path; no additional scalar | SDK initialize path; not reached in retained run |
| Decoder 6: single-stream interleaved decode with reset flag and time | Reset bool byte at scalar 0; one input A map-alias buffer, one output B map-alias buffer | Consumed bytes u32 at 0, samples per channel u32 at 4, processing time u64 at 8 | SDK decode wrapper/vtable and marshaller; not reached |

The decode buffer attributes are input `In|MapAlias` and output
`Out|MapAlias|NonSecure`; the HIPC header declares one A and one B. The runtime
currently preserves address/size but drops map-alias flags. Do not require a
C receive-size table or silently choose pointer buffers for this decode path.
The single-stream wrapper selects decoder command 6; adjacent multistream
wrapper selects 7. Manager commands 2/3 and decoder 0–5 exist in this SDK's
client vtables, but are outside the first startup path and outside the proposed
unit. Do not register those commands as empty successes.

The SDK checks a compressed block has at least an eight-byte envelope, validates
its declared payload fits, checks PCM capacity using sample count × channels ×
two bytes, and passes only that framed block to the decoder. Successful decoding
returns signed 16-bit interleaved PCM. Header byte order, second header field,
complete packet validation/error mapping, firmware work-buffer formula and
processing-time units remain **unknown in this investigation**. No buffer bytes
or invented timing result should be returned before those contracts are resolved.

Lifecycle is partly established statically: manager clients are reference
counted; releasing the final reference sends protocol Close then closes its
handle. Opening creates transfer memory from caller workspace, copies its handle
into the request and releases the local handle after the call; a decoder backend
must retain any needed object ownership. Finalize releases the decoder interface
and clears its SDK object. Reset sets a flag consumed by the next decode, rather
than sending an immediate reset request. Session/domain ownership and serialization
already exist in IPC; alias/clone/domain teardown still require production tests
before implementing stateful decoding.

## Inspected integration and available codecs

All paths in this paragraph are relative to the read-only stable tree
`.local/orchestrate/2026-10-18-evening/native-current/source` in the parent checkout:

- `runtime/src/ipc.cpp`: registry, strict missing-service/command failure, SM
  acquisition, A/B parsing, session/domain close, result/object serialization.
- `runtime/src/ipc.h`: actual header; `runtime/include/ipc.h` does **not** exist.
  `IpcCtx::arg` zero-fills on short input, so handlers must validate lengths
  explicitly. `push_object` delegates session/domain serialization to IPC.
- `runtime/src/hle_audio.cpp`: AudioOut PCM device/timer pacing and inherited
  AudioRenderer integration; no hwopus service registration or Opus decoder
  backend. Codec IPC is separate from the PCM sink; this blocker does not justify
  editing AudioOut or inherited renderer offsets.
- `CMakeLists.txt`: explicit `NX_RUNTIME_SOURCES` includes audio and service TUs;
  a new service TU needs an explicit source entry. Mac/Linux link SDL3, Windows
  links XAudio2, Android AAudio. No Opus library is currently linked. The separate
  tracked `runtime/patches/ios-runtime.patch` supplies simulator integration and
  explicit unsupported audio boundaries; this Mac trace establishes nothing there.

Actual private generated callers are in
`.local/game-private/astral-work/gen/main/code_167.cpp` and
`.local/game-private/astral-work/gen/sdk/code_022.cpp`; SDK exports are in
`gen/sdk/table.cpp`. NSO relocations, not zero-filled raw vtable slots, connect
those wrappers to their marshallers. The canonical SDK is
`.local/game-private/astral/exefs/sdk`; its flat analysis image is
`.local/game-private/astral/analysis/sdk.bin`. Exact function identities,
relocations, addresses and disassembly are retained only in private receipts.

The generated SDK exports software Opus size/init/decode/reset routines, including
single-stream and multistream support. Their presence establishes an available
potential guest backend, not working hwopus service emulation or its firmware
workspace size. Local `/opt/homebrew/lib/pkgconfig/opus.pc` records host libopus
1.6.1 and `/opt/homebrew/lib/libopus.{a,dylib}` exists with headers. It is neither
a pinned repository dependency nor linked by this build; its host state-size
must not be mistaken for firmware requirements. No dependency was installed.

## Smallest successor and necessary split

Recommend one bounded **HWOPUS-QUERY** implementation, separate from decoding.
Its exact tracked scope should be:

1. `runtime/patches/astral-hwopus-query.patch`: original overlay creating
   `runtime/src/svc_hwopus.cpp` and adding it to the private upstream
   `CMakeLists.txt` source list; register `hwopus`, implement only manager 1.
2. `tests/test_hwopus_query_runtime.cpp`: synthetic production IPC fixture.
3. `tests/test_hwopus_query_runtime.py`: pinned-source composition, compilation
   and subprocess driver with ignored receipts.

No `hle_audio.cpp`, IPC framework, platform adapters, generated source or
canonical SDK edits. Unsupported manager/open/decoder commands remain strict
failures. This scope cannot claim audio decoding or an opened decoder.

**Sizing is the remaining implementation gate.** The SDK caller gives the wire
layout but cannot reveal the absent firmware service's size calculation. Do not
fill that hole with zero, a fixed large constant, guessed firmware arithmetic or
a no-op success. One defensible compatibility design is to define the requirement
as actual software-decoder workspace: query this SDK's existing software Opus
size API, preserve the CPU call state, and later initialize that same decoder
in the promised workspace. That is a proposed software-backend contract, **not**
verified firmware equivalence. The implementation assignment must explicitly
choose and validate it, including required alignment/overhead and transfer-memory
ownership, before a query reply is acceptable. If exact firmware equality is
required, split off a read-only sizing-reference unit instead; this investigation
has no firmware implementation or hardware query receipt to establish equality.

The software SDK approach avoids adding a host dependency and can share the same
compiled guest codec across the four platform families. A host-libopus approach
requires a separate serialized dependency decision (version/hash, notices, CMake
and platform linkage); local Homebrew availability alone is insufficient.
Shared build-list changes must be serialized with the parent. Apply the new
overlay only after required predecessors independently pass; parent owns stable
source composition and cumulative native acceptance. Automatic service-batch
provisioning/profile repair is outside this successor's scope.

Meaningful offline tests must compile the **actual composed service and IPC TU**
and exercise SM acquisition, type-6/context manager 1 requests, exact u32 reply
width/result framing, all ten startup rate/channel combinations, repeated
query/close/reacquisition and domain/clone lifetime. Verify the returned size
against the selected real codec's size API and prove page-rounded workspace is
sufficient for real initialization and a synthetic encoded packet decode with
guards around the workspace. That backend proof belongs in the fixture even if
the IPC decoder is deferred. Verify register restoration for guest codec calls.
Short payloads, invalid rates/channels, unexpected descriptors/handles, overflow
and unsupported commands must fail explicitly without output objects or writes.
Use synthetic original audio only; no game samples or SDK-derived fixture code
in Git. A fixture that merely checks a chosen constant is insufficient.

Faithful continuation through the **currently identified sizing phase** does not
need PCM decoding. Whether a decode occurs before the first frame is unknown;
retained execution never reaches decoder open. A later decoder unit must prove
open/transfer ownership, framed packet semantics, reset/state isolation, bounded
PCM writes, real codec output and close before advertising that support.

## Parent's later native acceptance requirements

This unit ran neither command. After independent exact-head Astra/medium review
of this document and independent review/landing of implementation dependencies,
parent should retain the existing cumulative source/build and use:

```text
<private astral-work venv>/bin/cmake --build <evening native-current>/build --parallel 2 --target astral
NX_TRACE=1 NX_NVN_REAL=1 NX_DATA_ROOT=<private owned data> NX_LOG=<new private trace> NX_NVN_FORMAT_PROFILE=<verified Astral profile> <evening native-current>/build/astral
```

Require a 900-second incremental-build bound and a separately recorded 60-second
owned-process-group native bound, current strict/high-memory compile definitions,
source/overlay and executable identities, exact environment and exit status.
Keep the verified texture profile; do not reset or clean-rebuild the source.
Inspect actual manager dispatch/replies and close lifecycle, record the first
new unsupported boundary and presented-frame count. A sizing-only unit should
stop explicitly at unimplemented open/decode if reached. Do not infer executed
commands from this static table. All four platform families, both simulators,
audio/input/save and gameplay retain separate acceptance; no current acceptance
is implied.

## Private evidence index

Own ignored directory: `.local/hwopus-contract-074/`.
`input-receipt.json` hashes the retained 072 report, observed result, both logs,
source provenance, inspected runtime files and private SDK/caller inputs.
`inspect_sdk.py`, `vtable.json`, `relocated-sdk-selected.json`,
`manager-decoder-disassembly.txt`, `ipc-marshalling-disassembly.txt`,
`sdk-symbols.txt` and selected caller excerpts preserve the static derivation.
`findings.json` separates observed/static/unknown claims and hashes the compact
receipts. These references are private audit aids, not distributable SDK data.
The stopped prior stores, stable tree/build and other worktrees were read-only.
