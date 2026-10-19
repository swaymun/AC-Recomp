# Astral touch screen

`runtime/patches/astral-touch.patch` gives the game a touch screen. Astral polls
`nn::hid::GetTouchScreenState<16>` every frame; the runtime previously answered
it with an all-zero state (`NoRawDeviceState`). The patch applies after
`astral-launcher.patch` (which itself follows `astral-perf-hud.patch` and
`astral-audio-dump.patch`) and is listed last in `runtime/patches/series.macos`,
so `tools/acr_build.py` applies it to the macOS player build. Every change is inside `NX_ASTRAL_STRICT`
conditionals, like the other `astral-*` overlays: without it the patched files
preprocess to the original bytes (`tests/test_astral_default_profile.py`), and
`GetTouchScreenState` stays `NoRawDeviceState`.

## Platform API

`platform.h` gains one call:

```cpp
struct TouchPoint { uint64_t id; float x, y; };
size_t read_touches(TouchPoint* out, size_t max);
```

Contacts are fractions (0..1, top-left origin) of the window's client area; `id`
is stable while a contact is held. Implementations:

| Platform | Source |
| --- | --- |
| iOS (`ios-astral-parity.patch`, `ports/ios`) | touches that begin on no on-screen control, or any touch while the controls are hidden |
| macOS, Linux | left mouse button held over the game window = one contact (`SDL_GetMouseState`, window size in points), sampled on the main thread in `sample_input()` with the pad under `g_pad_lock`; `read_touches` returns that cached copy, and each new press gets a new id |
| Windows, Android | none yet (`return 0`) |

The desktop hunks add the cached contact next to `g_pad`, a sampling helper
before `sample_input()`, two lines at the end of `sample_input()` and
`read_touches` after `read_pad`; `main()` is untouched.

## HID mapping (`hle_hid.cpp`)

`GetTouchScreenState` fills the guest's `TouchScreenState<16>` (0x290 bytes):

| Offset | Field |
| --- | --- |
| 0x00 | s64 sampling number (host time at the 60 Hz sampling rate; never backwards; +1 when the contacts change within one period) |
| 0x08 | s32 count |
| 0x0c | reserved |
| 0x10 + 0x28·i | `TouchState[i]` |

`TouchState` (0x28 bytes): 0x00 s64 delta time (ns since the contact began),
0x08 u32 attributes (bit 0 Start, bit 1 End), 0x0c u32 finger id, 0x10 u32 x,
0x14 u32 y, 0x18/0x1c u32 diameter x/y (15), 0x20 s32 rotation angle (0),
0x24 reserved.

Sources: libnx `nx/include/switch/services/hid.h` (`HidTouchScreenState`,
`HidTouchState`, `HidTouchAttribute_Start = BIT(0)`, `HidTouchAttribute_End =
BIT(1)`), the public libnx headers,
and public interoperability documentation (
TouchScreen shared memory). The size agrees with the runtime's previous 0x290
zero-fill and with the SDK symbol `TouchScreenState<16>`.

Behaviour:

- Coordinates are Switch screen pixels, 1280 × 720. The presenter fits the 16:9
  picture into the window with bars (`nvn_present.cpp`), so the mapping removes
  the bars; points on a bar clamp to the nearest edge.
- Finger ids are the lowest free index 0..15, kept while the host contact is held.
- A new contact carries the Start attribute on its first sample. A released
  contact is reported once more with the End attribute at its last position,
  then its id is freed.
- At most 16 contacts; extra host contacts are ignored.
- The first poll logs `hid: touch screen polled`, and held contacts are logged
  every 300 non-empty samples, so a run's log shows whether the game reads it.

## Tests

`tests/test_astral_touch.py` compiles the shipped `hle_hid.cpp` block from the
patch against stubbed platform calls and checks layout, attributes, finger-id
reuse, the end report, letterboxing for a wide (iPhone) and a 4:3 (iPad) window,
the time-based sampling number and the 16-contact limit. It also compiles the iOS bridge's touch-point API and
checks that every platform implements `read_touches`.

## Relation to `astral-launcher.patch`

The launcher (`launcher.cpp`, `input_map.cpp`) also edits `platform_mac.cpp`/
`platform_linux.cpp` (`main()`, `sample_input` bindings from `controls.ini`).
This patch is generated against baseline + `astral-launcher.patch` and applies
after it without offsets; the patched `platform_mac.cpp` compiles
(`clang++ -fsyntax-only`, Astral strict). A later launcher change to the end of
`sample_input()`, `g_pad` or `read_pad` needs this patch refreshed. Mouse-as-touch
is not routed through the launcher's controls mapping and is not configurable
there.
