# Astral HID host API overlay

`astral-hid.patch` changes only the pinned Wonder runtime's `hle_hid.cpp`.
It intercepts exact imported SDK APIs through the existing HLE registry; it does
not install a HID IPC service. Capability verification passes; independent
Astra/medium exact-head review and cumulative native guest execution remain
required before landing and platform acceptance, respectively.

## Observed boundary and caller trace

Both retained IOS-CUMULATIVE-041 guest logs hash to
`93526d080ec3712a6a3ccbef395199130755b86febea3dfcbf083236e366e2f0`.
They execute `InitializeNpad` and `SetSupportedNpadIdType`, then request `hid`
and stop at strict missing-service handling. No game frames were observed.

Private canonical SDK symbols and selected original code identify the matching
main call sequence: initialize Npad, set IDs `{0,32}`, call
`SetNpadHandheldActivationMode(0)`, set style mask `7`. The exact imported symbol
is `_ZN2nn3hid29SetNpadHandheldActivationModeENS0_26NpadHandheldActivationModeE`.
Main's PLT at `+9f8100` serves callsites `+99973c` and `+9999d8`. The logs do not
record the HID caller PC, so the dynamic callsite is not distinguished. Both
static candidates use the same API and argument.

The SDK public wrapper at `+23c9a0` calls the detail wrapper at `+226f70`, which
calls `CreateHidServerProxy` at `+2486a0`. That function calls
`ConnectToHipcService` at `+248768` with the `hid` name at `+9cf92c`. Thus an
unbound imported SDK setter explains the observed request; no broad service
inventory or empty factory is used to bypass the failure. This is a static
caller correlation with real startup evidence, not a new guest execution.

Primary evidence identities:

| Input | SHA256 |
| --- | --- |
| Canonical manifest | `fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d` |
| Main flat | `8e98a5f28a8d94ff021a1bf24a6d47a1c53e96047c629c99dfc3a26487ae2668` |
| SDK flat | `0cc8d26fbcb0e4953ef414b029d72935014e988fd59ab24b3f35121ddc3e565c` |
| Wonder revision | `010ed7a596a621c15d3a8dfa5795ca8c3668b066` |

Raw selected disassembly, inspection script, canonical/log hash checks and a
structured trace receipt remain ignored under `.local/hid-045/`. No game bytes
or derived code are added to Git.

## ABI and supported behavior

The primary SDK detail implementations copy `0x28` bytes for all five Npad
state types: FullKey (`+227d60`), Handheld (`+227f90`), JoyDual (`+2281c0`),
JoyLeft (`+2283f0`) and JoyRight (`+228620`). Singular public wrappers take
`State*` in x0 and a reference to a 32-bit Npad ID in x1. Plural wrappers take
`State*`, signed 32-bit capacity and ID reference in x0/x1/x2. Only FullKey
carries host data: sampling at 0, buttons at 8, four signed stick coordinates
at 16/20/24/28, connected attributes at 32, zero padding through byte 39.
The other four styles return disconnected states and are never advertised.

The host's `plat::PadState` contains buttons and four axes. It has no physical
controller connection flag or raw mouse, keyboard, touchscreen or motion data.
The connected device here is the logical host keyboard/touch/controller input
endpoint No1, enabled only by an explicit supported ID and FullKey style. It
must not be described as proof of an attached physical gamepad. iOS already
supplies this endpoint through `acs_input_poll`; this overlay does not alter
that platform mapping. Physical gamepad hotplug support needs a separate
platform API change, outside this unit's scope.

Initialization is idempotent and initially advertises no enabled styles or IDs.
Supported IDs are 0..7, Other 16 and Handheld 32; only No1 can connect.
Style masks accept the five existing style bits; advertised capability remains
FullKey only. Handheld activation modes 0..2 and Joy hold types 0..1 are
validated and stored; no handheld or Joy device is created. ID updates reject
duplicates, invalid addresses, more than ten IDs and unknown IDs atomically.
A zero ID count disables all endpoints without reading the array.

Host button bits are delivered unchanged with stick-direction bits derived
from clamped axes at half-range. No scripted input is added by this overlay;
any host-provided automation remains a host concern. `DisconnectNpad(No1)`
detaches the logical endpoint for the remainder of this process. Reapplying
IDs or styles cannot fabricate a reconnect. Disconnect and policy updates
clear history, preventing old connected samples or pressed buttons leaking
across transitions.

Each `(ID, style)` has its own newest-first history, capped at 16 samples.
Each positive-capacity read adds one current observation. Singular reads do
not populate plural history. Zero and negative capacities return zero without
polling or accessing output/ID pointers; positive capacities are capped at 16
and require writable storage for that capped capacity. Only returned entries
are written; unwritten tail slots remain untouched. Sampling numbers describe
these host polls, not hardware tick timing. All Npad policy/history operations
are serialized with a mutex.

Mouse SDK detail `+226400` copies `0x28` bytes. Pinned keyboard layout is
`0x30`. `TouchScreenState<16>` RingLifo at `+234dd0` uses output stride `0x290`
(16-byte header plus sixteen 40-byte contacts); its shared-storage stride
`0x298` is deliberately not used as the API output size. Absent raw devices
return zero sampling/count/attributes and no contacts or keys. Overlay touches
remain controls for Npad, not fabricated guest touchscreen coordinates.

Six-axis and vibration enumeration return zero devices; plural sensor reads
return zero samples without writing outputs. Singular sensor reads, sensor
start, vibration-device use and both controller-support overloads fail
explicitly because those host capabilities are unavailable. Controller-support
must not claim a successful selection or invent a player count. Joy assignment
and style-update events are also explicit unsupported boundaries. Missing
raw-device initialization is a no-op paired with disconnected read behavior.
No fake sensor orientation, vibration device, connection-change event or
controller-support applet success is reported.

## Executable verification

Run exactly:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_hid_runtime.py -v
git diff --check main HEAD
```

The Python test uses standard-library subprocess/Git integration and the
existing `tools.prepare_runtime.prepare_source` helper. `HID_REFERENCE` can
select another clean pinned original checkout. It creates a fresh ignored
source and applies this ordered composition:

```text
apple-memory.patch
astral-bootstrap.patch
astral-control-import.patch
astral-sqshl.patch
astral-notifications.patch
astral-apm.patch
astral-audio.patch
astral-ipc-buffer.patch
astral-hid.patch
```

It compiles the complete composed HID source, real loader registry, HLE thunk
allocation and `call` dispatch with strict mode and Apple high-memory defines.
Synthetic host input and VM permission queries isolate the boundary; handlers,
registrations and dispatch are not substituted. Assertions cover the actual
startup arguments, all five singular/plural names, exact sizes and canaries,
null/unmapped/overflow arguments, ID/style policy, signed and zero capacities,
per-ID/per-style history, policy flushing, disconnection, host button/stick
mapping, raw-device absence, and explicit sensor/applet failure. This is
capability testing, not real SDK or game execution.

Each run prints an ignored receipt path with UTC time, the exact ordered patch
hashes, every consumed source hash, compiler arguments, fixture/binary identity
and nonempty executable output. Preserve earlier receipts and failed reports.
The independent review must use the final committed head and normalized patch
identity supplied in the worker report. Review is pending parent commissioning,
not waived: the brief forbids nested workers, and the lead owns reviews.

## Next cumulative integration recipe

After an independent Astra/medium pass, the parent lands the reviewed head and
commissions the subsequent integration unit. Use a fresh private source/output;
call `prepare_source(reference, fresh_source, ordered_patches)` with the list
above and any additional independently landed overlays current at that point.
For iPhone/iPad add the already reviewed iOS runtime/NVN overlays before the
service overlays, as in the existing IOS041 preparation. Record exact patch and
source fingerprints, canonical manifest/control/generated receipts and native
host-source hashes before building. The generic `prepare_runtime.py` CLI does
not automatically select `astral-hid.patch`; do not reuse an old prepared tree
or mistake a capability receipt for inclusion in a native build. Shared
preparation/integration tooling remains unchanged by this unit.

Build the existing full runtime with `NX_APPLE_HIGH_MEMORY=1` in every Apple TU;
keep iOS minimum 26.0 and tested simulator runtime 26.5. Run genuine Mac and
both simulator guest startups using their existing bounded launch/collection
procedures. First confirm HLE dispatch of the exact handheld setter and
progress beyond the prior `GetService(hid)` failure; then record actual host
input at the Npad boundary and observe advancing game frames/input response.
Report the next strict capability failure honestly, including explicitly
unsupported sensors/controller support if reached. No IPC factory bypass is
authorized. If a different SDK route still requests HID IPC, retain its caller
trace and request the precise service/shared-state scope before changing it.

Native cumulative startup, advancing visuals, guest input response, audio and
save/reload remain unverified here. Genuine Windows/Linux runs and physical
Apple devices also receive no acceptance from these tests. Preserve meaningful
real visual milestones privately with platform, UTC time and revision; notify
the parent only when such evidence actually exists.
