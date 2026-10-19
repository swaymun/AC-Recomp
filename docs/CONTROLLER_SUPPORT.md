# Controller support capability

The ordered `astral-controller-support.patch` follows landed `astral-hid.patch`
on Wonder `010ed7a596a621c15d3a8dfa5795ca8c3668b066`. It changes only the two
ShowControllerSupport registrations and their handlers in `hle_hid.cpp`.
No shared preparation or supervisor changes are required.

The policy reuses HID045's explicitly configured logical No1 FullKey endpoint:
keyboard/touch/controller input, not proof of a physically attached controller.
Only an existing endpoint with a maximum of one player and connection takeover
enabled can complete automatically. No buttons, connections, user choice or UI
are generated. Identification-color and explanatory-text UI requests fail.
The handler leaves Npad input, histories, supported IDs/styles and disconnection
state unchanged. No polling or input injection occurs during confirmation.
A disabled endpoint, missing FullKey style, persistent disconnect, multi-player
range or unavailable UI returns `0x183aca`, the pinned SDK's applet-failure result.
Failures leave result storage untouched. It never claims a user cancelled.

## ABI evidence

Direct private canonical SDK inspection identifies the argument-only public
wrapper at `+24f4d0`, result-pointer wrapper at `+24f530`, and common core at
`+24f230`. The first takes Arg in x0; the second takes ResultInfo in x0 and Arg
in x1. Core transfers exactly `0x21c` argument bytes and copies exactly eight
result bytes. Return is a 32-bit Result in x0, zero on successful completion;
core constructs `0x183aca` for applet failure and adds `0x200` for status 2.
The adapter uses the observed failure result; it does not simulate an applet.
SDK SHA256: `0cc8d26fbcb0e4953ef414b029d72935014e988fd59ab24b3f35121ddc3e565c`.
The canonical main imports the argument-only overload through PLT `+9f8120`,
called at `+9998e8`. This corroborates the prior MAC048 observed boundary,
without accepting MAC048's bounded-log parser or consuming its unlanded code.

The SDK's `SetExplainText` addresses strings at offset 24 with stride 129.
The matching old four-player structure is documented in the primary
libnx hid_la.h:
seven header bytes (signed player min/max, takeover, left justify, JoyDual,
single mode, identification color), four RGBA colors, explanatory-text flag at
23 and four 129-byte strings. Total 540 bytes. ResultInfo is signed player count,
three padding bytes, then a 32-bit Npad ID. Modern eight-player layout is not
accepted. Valid legacy ranges are min 0..4, max 1..4, min <= max; flags must be
canonical bool bytes. Argument extent must be fully readable; result-pointer
ABI requires eight writable bytes even for an unavailable capability. Null,
unmapped, partial, read-only output and arithmetic overflow remain strict errors.
The argument-only overload does not interpret x1 as storage. A validated snapshot
supports overlapping input/output safely. Success writes one existing player and
No1 (0), with zero padding. No unrelated unsupported boundary changes.

## Verification and limits

`PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_controller_support.py -v`
composes actual pinned source with landed patches and this overlay, compiles the
whole HID translation unit plus real HLE registry/dispatch, and executes the
handlers. Synthetic input covers both ABIs, configured/absent/disconnected
endpoint, player/style policy, malformed and inaccessible arguments, output
canaries/overflow and retained strict sensor/assignment failures. Private receipts
record source, patches, fixture, binary, compiler argv, UTC and executable output.
These are capability tests, not platform gameplay acceptance.

Independent Astra/medium review of the final exact head is required before
landing. Nested workers are forbidden by the assigned brief; parent owns review
commissioning. No review is waived. Linux, Windows, iPhone and iPad simulator
integration remain separately measured; simulator evidence cannot accept a
physical device. Native measurement details are appended after the fresh run.

## Fresh native measurement, 2026-10-18

Measured runtime source commit: `81d2e5a4ebddbb9c409d8e86b5214305a50c9225`.
The later report/test documentation head is separate. Private direct preparation
composed the ten ordered overlays listed in `tests/test_controller_support.py`,
using the canonical authenticated control metadata and regenerated main/SDK
inputs. It used the landed preparation and bounded process helpers from that
commit, never the unlanded MAC048 supervisor. HID045's full independent review,
normalized patch, current scoped bytes and main ancestry were verified privately.
The original native receipt `86079c170d173edbda4e0f44f75b4f7cf9ee9a44c2383be918a27cc862263b0b`
and its 68,645-byte original guest trace were independently rehashed and retained;
this is input evidence, not MAC048 acceptance.

Fresh configure passed at 18:34:05Z. Build passed at 18:46:21Z after 735.47
seconds with two jobs: 395 translation units and 395 objects, every command
carrying exactly `NX_APPLE_HIGH_MEMORY=1` and `NX_ASTRAL_STRICT=1`.
Composed HID source SHA256 is
`0e8e097a02aaac7e5f84968ef3d1604236918be036a8b2ba6047ee1bc0316dff`;
its 27,440-byte object SHA256 is
`214bf176b7dcbbcbe470436baafe5be812d27910a197cf90e2bd23ebfff94623`.
The 56,069,528-byte arm64 executable SHA256 is
`c76a50a521ca0afdb99dd53f73aceba0e5ab5f738bd0fbf15f2aa75cd914f604`.
All source/object identities and compiler commands remain in the private receipt.

Genuine guest launch ran 18:46:21–18:46:24Z within a 20-second bound, with no
log truncation or timeout. It dispatched the observed argument-only overload
and recorded min=1, max=1, takeover=1, single=1, existing logical connection=1,
result=0. It then progressed through asset directory/file access and native
window/layer creation. The remaining blocker is a **signal 11 crash**, data
address zero, native executable offset `+268bd84`, with guest LR
`sdk+39d7d0 (nn::vi::SetLayerScalingMode +0x30)`. This is the observed crash
context, not proof of its root cause or a newly implemented service.
The native process exited -11; no successor was implemented or fatal suppressed.
The older IPC-only observation parser returns no unsupported IPC boundary here;
the direct retained crash trace is the evidence. No supervisor acceptance is
claimed from that parser result.

No worker input was injected. Scripted-input and recording environment variables
were excluded. The logical keyboard/controller input endpoint comes from the
existing platform mapping; physical controller connection and actual pressed
buttons were not measured. Synthetic A/stick values were used only in capability
tests, never in the guest launch. Prepared sources and canonical input manifest
were unchanged after execution. All three bounded stages completed with empty
owned cleanup-group lists. Providers, transfers and unrelated processes were
untouched; ignored private evidence is retained.

There are no observed advancing game frames or inspected gameplay visuals.
The trace contains no NVN dispatch lines; this is not a rendered-frame counter.
No screenshot, clip, official-reference visual comparison or visual-update
publication is claimed. macOS remains partial/blocked at the recorded crash.
Windows, Linux, iPhone simulator and iPad simulator receive no new integration
acceptance from this Mac measurement. Physical Apple devices remain unverified.
Private build, launch, dependency, ABI, immutable original-input and cleanup
receipts are under `.local/controller-051/`. One preliminary private preparation
attempt stopped before building while scanning mixed JSON record types; its
receipt is preserved alongside the successful fresh preparation/build run.
