# UIKit / Metal launch rescue — IOS-LAUNCH-RESCUE-026

**iPhone and iPad simulator host preflight passed:** fresh build/install, visible
advancing Metal frames, a second cold process, actual UIKit stick/button touches,
Home/background/foreground, and cancellation of a trigger held across interruption.
**26.5 tested / 26.0 minimum target. No game runtime or gameplay is present.**
Physical devices, audio and MoltenVK presentation are unverified. Parent owns the
independent exact-head review; this worker started no nested workers or reviewers.

## Implementation and provenance

The original UIKit/Metal overlay, C input bridge and bridge tests are adopted from
preserved IOS-HOST-002 commit `9ae75b057e057b2edab890d1dc40107ac004d8fd`.
The rejected app, its devices and failure evidence are unchanged. This unit uses
fresh `local.acs.launch-rescue-026`, executable `ACSRescue`, bundle version 26,
and its own two registered ACS devices. It does not relaunch the stale bundle.

`Info.plist` declares `UIWindowScene` and the scene delegate. The app delegate
also explicitly returns the scene class and delegate from
`configurationForConnectingSceneSession`. The scene delegate retains its UIWindow,
creates the host controller and makes the window key and visible. The controller
owns MTKView and Metal objects. Metal completion callbacks update UI/evidence on
the main thread. The title says **ACS · HOST PREFLIGHT**, and its status says
**Original Metal diagnostic · no game runtime**. Its analytic shader is original.

The prior rejected identity reached did-finish-launching with zero connected
scenes. The fresh identity/configuration now connects scenes and survives cold
relaunch. Because both identity and scene configuration changed, this evidence
does not isolate the historical failure to one manifest field or establish that
the old scene state was corrupt.

All overlay hit regions use safe-area coordinates in landscape: two sticks,
ABXY, L/R, ZL/ZR, plus/minus. Buttons have at least 44-point hit regions. UIKit
objects map to monotonic touch IDs, with the control fixed at touch begin;
stick moves outside the original region retain that identity. The journal records
bindings as `[identity, control]`, without UIKit pointers. Cancellation, inactivity,
background, disconnection, size/orientation or effective scene geometry changes
clear the bridge and touch table. Input is disabled and Metal paused while
inactive; reactivation starts neutral.

The C ABI in `InputBridge.h` supports coherent thread-safe polling, exclusive
stick ownership, shared button owners, 32 touches, invalid/duplicate ID rejection,
radial clamping, nonfinite neutralization and harmless stale move/end events.
Axes are right/up positive, magnitude at most one; ZL/ZR are digital triggers.
`ACS_BUTTON(control)` is the host mask, not an assertion about guest HID layout.

## Reproduction and scope controls

On this arm64 Mac with Xcode, Python 3, ffmpeg and ffprobe:

```sh
bash -n scripts/check-ios-host
scripts/check-ios-host --input-test
scripts/check-ios-host --simulators
git diff --check
```

The script compiles directly against the installed simulator SDK with
`arm64-apple-ios26.0-simulator`, ARC and warnings as errors, ad-hoc signs and strictly
verifies the fresh bundle. Compiler invocations are sequential (at most one
compiler job; below the two-job cap). Every child command has a deadline; compiler
and recording groups are task-owned and killed on timeout. There is no provider,
authentication, download or paid API operation.

Only devices created and recorded in this worktree's ignored
`.local/ios-launch-rescue-026/devices.json` are eligible. Each operation checks exact
UDID/name/type/runtime/availability; no `booted` alias is used. An already Booted
task device is refused to avoid replacing an active UI session. Only devices booted
by this command are shut down, including after failure. No erase/delete, broad
CoreSimulator reset, unrelated app termination or Wonder operation is used.

Each family needs fresh token-correlated callback and GPU reports, a verified live
PID/path/token, advancing completions, a decoded video, and a second neutral cold
process. The command **does not inject touch events**; visible UI acceptance below
is separate. On a launch timeout it records failure without retry loops: request
parent visible launch on that exact device and perform at most one bounded minimal
UIKit comparison. Do not restart the historical observer chain.

Device Hub may open a fresh simulator's hardware display in portrait even though
the app's view is landscape. Select the exact ACS device and **Rotate Left** for
an upright, unletterboxed landscape display. This rotation must be checked after
boot. It is separate from the app's landscape view/safe-area validation.

## Retained private evidence

All paths below are under this worktree's ignored `.local/ios-launch-rescue-026/`.
Captures, binaries, device IDs and app journals are not committed.

`run-20261018T153426Z-47ad59/` is the build installed for the visible UI tests.
Both app signatures verified. Its initial and cold launch results are:

| Family | Landscape view points | GPU completions | Cold process PID | H.264 duration |
| --- | --- | --- | --- | --- |
| iPhone | 874 × 402 | 60 → 540 | 46936 | 4.578333 s |
| iPad | 1210 × 834 | 60 → 540 | 48778 | 4.680000 s |

`commands.log`, `summary.json`, per-family `startup.jsonl`, completion/input JSON,
process identity, screenshots and videos bind those observations. The script
records source hashes alongside its precommit HEAD; hashes identify the actual
built files. The final verification rerun `run-20261018T154706Z-74cf24/` also passed
both families (60 → 480 GPU completions; fresh cold PIDs 93731 / 94811). It is
retained separately and does not replace this UI build's identity.
The UI build and final rerun have identical App/input/plist source and executable hashes.

`ui-acceptance.json` checks the two token-correlated live interaction sessions:

| Family | UI process / token | Controls seen | Paused → resumed GPU count | Held ZR → cancel |
| --- | --- | --- | --- | --- |
| iPhone | 72032 / `ui-026-iPhone-154014` | left/right stick, A, ZR | 2640 → 4080 | 5.367 s |
| iPad | 51538 / `ui-026-iPad-153555` | left/right stick, A, ZR | 5940 → 10140 | 7.218 s |

For each family, `ui-<family>/interaction.mp4` records real simulator UI,
`foreground.png` shows the resumed host and `input-events.jsonl` records distinct
stick/button bindings and release to neutral. `background.json` contains two
stable GPU-count samples while backgrounded; the same PID resumes to the larger
count. `startup.jsonl` contains scene-inactive/background/foreground/active
callbacks. `completed.json` contains GPU counts and the final neutral input state.
The iPhone's timed `held-ZR.png` snapshot actually preceded the held press and is
not held-input proof. Its accepted journal and recording provide that proof.
iPad's separate `held-cancel.mp4` covers its
successful held-input cancellation after the first interaction recording.

Home was exercised through Device Hub. To interrupt a continuously held CUA
mouse touch without a second mouse action releasing it first, a bounded delayed
`simctl launch com.apple.Preferences` brought Settings forward on the exact ACS
device. No setting was changed. Each accepted sequence is **touch-began, ZR=128,
active=1 → background release → touchesCancelled, buttons=0, active=0**, with no
intervening touch-ended. Reopening the host preserves the PID and resumes neutral
rendering. Simultaneous owners/capacity are tested in the compiled bridge test;
this does not claim simultaneous multi-finger UIKit injection.

Original simctl interaction recordings fully decode, but their repeated timestamps
produce non-monotonic DTS warnings with ffmpeg's default null muxer. Original
files remain intact. Compact `ui-<family>/review.mp4` and iPad
`held-cancel-review.mp4` use a fixed 15 fps timeline and fully decode with empty
ffmpeg error output. Screenshots were visually inspected. The two owned ACS
devices returned to Shutdown. The
Wonder device remained Booted and was not operated. Earlier unsuccessful keyboard
Home/hold timing attempts remain in the private evidence and are not counted as
held-touch acceptance.

## Next actual guest integration unit

Runtime entry cannot be added honestly within these seven scoped files. The
reviewed `astral-bootstrap.patch` explicitly rejects `CMAKE_SYSTEM_NAME=iOS`;
upstream `runtime/src/platform_mac.cpp` owns a desktop `main`, SDL event loop,
window creation, input and audio. Linking that launcher into UIApplication would
create a conflicting entry/lifecycle. No guest function or success stub was added.

The next unit needs these explicit changes outside this scope:

1. Add a simulator CMake target and `platform_ios.mm` against the pinned Wonder
   revision, replacing desktop `main`/window glue. Link the existing UIKit host,
   input bridge, current strict runtime and private regenerated main/sdk modules.
   Run `nx::boot` on a bounded-lifetime worker after scene setup; keep UIKit on the
   main thread and log the first genuine loader/SDK/guest entry or strict blocker.
2. Implement the platform `read_pad` snapshot from `acs_input_poll()`: map every
   named mask explicitly to the runtime's PadState bits, scale each normalized axis
   to the runtime's signed stick range (32767), preserve up-positive Y, and keep
   inactive input neutral. Never memcpy this ABI into guest shared memory.
3. Package only verified private module/control inputs into ignored simulator
   storage; bind the actual data root and strict metadata policy. Retest memory
   reservations in the final linked app. Use the simulator's validated default
   mobile layout consistently across all runtime/generated translation units;
   the native macOS high-memory profile has not been validated on simulators.
4. Supply a real Metal-backed Vulkan/MoltenVK surface and iOS audio/lifecycle glue
   when guest startup reaches those paths. Preserve strict unknown-service/shader
   failures, including the separately owned parental Initialize implementation.

Success for that successor means an actual token-correlated guest entry trace in
both apps, then real guest frames/input/audio. These diagnostic frames provide no
gameplay coverage, physical-device acceptance or cross-ISA correctness claim.
