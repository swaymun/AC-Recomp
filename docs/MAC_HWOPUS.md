# Mac hwopus adapter

HWOPUS-IMPL-075 adapts the MIT letsgo-recomp single-stream service to the current
`nx::Service`/`IpcCtx` ABI. The patch adds only `runtime/src/svc_hwopus.cpp` and
CMake source/dependency linkage. It does not change the IPC framework, AudioOut,
guest code or canonical inputs. Enable explicitly with `-DNX_HWOPUS=ON`; the
option defaults OFF, adding no dependency or service to unconfigured targets.
The installed host libopus supplies all codec operations. No install is needed
on the measured Mac. The source and full license provenance are in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Established contract and compatibility boundary

The read-only HWOPUS-CONTRACT-074 candidate at
`0f84715aef87eaaeb58c8647c5d3c1d1d4746eb4` provides static SDK marshaller, relocated
vtable and startup-caller evidence. It is evidence, not an independently accepted
document dependency. Its static facts support these commands:

| Command | Arguments after SFCI | Output after SFCO/result |
| --- | --- | --- |
| Manager 1 | u32 rate, u32 channels | u32 required decoder-state bytes |
| Manager 0 | u32 rate, u32 channels, u32 page-rounded workspace bytes; one transfer-memory copy handle | one decoder interface, no scalar |
| Decoder 6 | bool byte reset, one A input and one B output buffer | u32 consumed bytes, u32 samples/channel, u64 elapsed microseconds |

CMIF request types 4 and 6 are accepted; the observed SDK uses type 6/context.
Non-domain scalar sizes include unavoidable word padding; domain argument lengths
are exact. Padding is not interpreted as arguments. Pointer/auto-select buffers,
unexpected handles/objects and other descriptor shapes fail. Decoder commands
0/1/4 and multistream manager 2/3/decoder 7 remain explicit fatal unsupported
boundaries, rather than success aliases. No actual need for them was established.

Packet envelope semantics come from the reused public letsgo implementation and
libnx's public hwopus header:
two big-endian u32 values, payload length and optional entropy final range. Zero
final range disables comparison; nonzero must match the real decoder. The time
unit follows letsgo's microseconds convention. These are explicit compatibility
choices, not proof of every Astral packet or firmware timing/error detail.
The private SDK investigation establishes an eight-byte envelope and signed
16-bit interleaved PCM, but not all header/timing details independently.

The ten statically requested configurations are mono/stereo at 8000, 12000,
16000, 24000 and 48000 Hz. Rates/channels outside this set fail. Size queries use
`opus_decoder_get_size(channels)`, and open initializes that same amount of real
host state. This is a software-backend workspace contract, **not** a guessed or
firmware-identical work-size formula. The SDK rounds queried sizes to 4096 bytes.
Open requires page-aligned, page-sized, mapped read/write transfer memory,
supplied bytes at least the query and no larger than the transfer object. The
service holds that object until the last decoder owner closes. Persistent codec
state lives in an aligned host-owned shadow, protecting libopus from guest
corruption; guest workspace contents are neither interpreted nor overwritten.
Transient packet/PCM/trial state is additional host memory, not console workspace.

[libopus documents contiguous, copyable decoder state](https://opus-codec.org/docs/opus_api-1.5/group__opus__decoder.html).
Each decode snapshots the packet, validates the framing/sample count/output
capacity, and decodes into temporary PCM with a copied state. Reset is applied to
that copy. Failure changes neither PCM nor persistent state. The mutex serializes
state updates; session/domain/clone ownership uses the existing IPC framework.
Guest VM permission/range validation covers every described region before access,
including overflow and crossing into unmapped regions. As in the existing runtime,
VM checks do not pin mappings against concurrent guest unmapping; full kernel
mapping pins are outside this two-path overlay scope.

No packet loss concealment, FEC or multistream is advertised. Zero payloads,
invalid packets, mismatched entropy ranges and insufficient output fail instead
of producing silence/truncated success. Payloads above 65536 bytes are rejected
as an explicit host resource bound (including padding), not a claim that larger
padded Opus packets are impossible. Only one framed packet is consumed; trailing
input bytes are untouched. Config/input failures use the two nonzero module-111
results retained from letsgo; exact firmware result-code equivalence is unproven.
Host allocation failure remains a process-level failure, never a success reply.

## Production verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_hwopus.py -v
git diff --check main HEAD
```

The test applies this overlay to the pinned upstream runtime plus the accepted
memory/bootstrap/IPC framing overlays. It compiles the resulting service,
`ipc.cpp`, `ipc.h` and `kernel.h`, linking the real installed libopus. Controlled
VM and kernel-handle glue replaces unrelated plumbing; neither the parser,
service nor codec is replaced. There are no game-derived test fixtures.

A real independent encoder creates original synthetic mono/stereo packets. All
ten rate/channel combinations compare actual PCM byte-for-byte with a separate
libopus decoder, check nonzero output and exact sample counts, then verify reset,
sequential state and unchanged PCM/state on failures. Guards surround PCM and
reserved workspace. Serialized tests cover SM acquisition, type-6 requests,
size/open/decode replies, clone/alias ownership, protocol close, domain object
returns/close and reacquisition. Direct ABI tests cover short scalars, invalid
rates/channels/work sizes, wrong/missing/stale handles, unsupported descriptors,
range overflow, access permissions and unmapped tails. Missing compiler, pinned
source or codec is a failure, never a passing skip. Private receipts retain
compiled source and executable identities, commands, output and exit status.

## Native measurement

The shared-lane gate was observed open only after NVN-TEXTURE-072's exact-head
Sol/high passing review and landing. Reviewed head:
`55a6599c674ebdfa46ba2f663f198f19643e67b8`; landed head:
`09e8ea10d81de3274931f44e68edbe051e25311f`. Its accepted binary and source receipt
were preserved before applying this overlay. All prior source fingerprints
matched 072; only the two permitted upstream paths changed. All prior compiler
commands stayed unchanged, including strict Astral and Apple high-memory flags.
Ordinary CMake/Ninja with two jobs compiled one new service TU and relinked in
3.507 seconds (configuration 1.355 seconds), within a combined 900-second bound.
The run uses the retained private texture profile and 073-accepted
`runtime-data-066-v2`. Actual launch at 21:22:43Z completed all ten manager-1 queries, returning
18468 bytes for mono and 27236 for stereo. It then stopped on SIGSEGV after
5.662 seconds in SDK fiber context initialization. The retained debugger run
confirmed the exact null store and a presented-frame counter of zero, then
explicitly killed its target. No decoder open/decode was reached in the game;
those paths have synthetic production-test evidence only. Two bounded launches
were used, with no timeout and no surviving owned processes. No frame was
available to capture. Next action is a separately scoped fiber-context diagnosis
using the retained exact stack/register evidence; it must not assume the last
NVN call caused the fault. A build or synthetic decode is not game audio or
gameplay acceptance.

macOS is partial. Linux, Windows, iPhone simulator and iPad simulator are
untested by this unit. No input, audio playback, save/reload or gameplay acceptance
follows from these tests. Simulator evidence would not establish physical-device
acceptance. Automatic overlay composition in `tools/service_batch_startup.py`
is outside this assignment and still needs an explicitly scoped follow-up.
Independent Sol/high review must cover the exact committed patch and retained
native result before landing; it is not waived.
