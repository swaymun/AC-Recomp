# Astral simulator guest entry

This unit adds an incremental patch after `apple-memory.patch` and the reviewed
`astral-bootstrap.patch`. Its upstream ownership is exactly `CMakeLists.txt` and
new `runtime/src/platform_ios.mm`. The separate `ios-nvn-compile.patch` overlay
owns only the external-command block in `runtime/src/nvn/nvn_pipeline.cpp`;
see `IOS_NVN_COMPILE.md`. Fix round 1 rebased the clean branch onto landed main
`eaa42fb9fa34afa9143116e903e6d85625817a85`, which is the pinned dispatch revision.
The original attempt used `6fc5eb07083d2bc9c944d81dd4d492e9580b62fb`.
Wonder remains pinned to
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. CONTROL-RUNTIME-024 and
IOS-LAUNCH-RESCUE-026 independently passed Astra/medium review before dispatch.
IOS026 established UIKit/Metal host preflight, without executing the guest.

The simulator target links the real runtime boot, loader, kernel, services and
reviewed CPU-REGEN-020 generated modules. It excludes `platform_mac.cpp` and its
SDL desktop entry. Every runtime and generated translation unit receives
`NX_ASTRAL_STRICT=1` and `NX_APPLE_HIGH_MEMORY=1`. Generated translation units use
`-O0 -ffp-contract=off` for a bounded first-boundary build; this establishes no
performance acceptance. (`ios-astral-parity.patch` later replaces this with
`NX_IOS_GAME_OPT`, default `-O2` as on macOS; see `ASTRAL_IOS_SIM.md`.) Runtime C++ and Objective-C++ use C++20. The build uses
an arm64 iPhoneSimulator SDK and deployment minimum 26.0; acceptance runtime is
26.5, separately from the installed SDK version.

UIKit keeps the IOS026 scene, touch overlay and input cancellation lifecycle.
A single owned pthread with a 64 MiB host stack calls `nx::boot`; UIKit's main
thread remains available. A token-correlated journal records worker entry and a
main-queue callback during boot. The guest retains its authenticated NPDM-derived
main-thread configuration. Memory reservation, host-page-preserving decommit,
POSIX file I/O, clocks and threads follow the reviewed Apple platform contracts.
Failed thread creation is fatal. Input maps each bridge face/shoulder/trigger/
plus/minus button explicitly to Npad bits. Both stick axes retain up-positive Y,
scale to ±32767, and set the corresponding stick-direction bits. Background and
inactivity release the bridge's held touches through the existing scene adapter.

Graphics and audio remain **blocked acceptance**. No verified simulator MoltenVK
library was found in the task's local runtime/SDK stores. This implementation
links no macOS Vulkan binary and makes no successful Vulkan/audio fallback.
The original IOS028 implementation made window/surface/loader and audio requests
explicit fatal boundaries and persisted their operation names. IOS-HOST-037 below
replaces the native window-state/ownership boundary; presentation remains blocked.
The runtime build uses Vulkan headers only.
`validate_simulator_library` inspects Mach-O build-platform metadata, rejecting
macOS and physical-device libraries even when they contain arm64. The supervisor
also checks the final executable's simulator platform. There is no guest-frame,
gameplay, audible-audio, IPA or physical-device claim. Runtime-mode UIKit renders
no diagnostic Metal frames.

## Reproduce with existing reviewed private inputs

Use `tools/prepare_runtime.py` with the existing `--repo`, `--reference`,
`--inputs`, `--gen`, `--out`, `--control-metadata`, `--cmake`, `--ninja`,
`--prefix` and `--vulkan-include` arguments, adding:

```sh
--ios-simulator --generated-receipt <CONTROL024-native-final/prepared.json> \
--configure --build --jobs 2
```

The generated receipt must match the upstream pin, import-manifest identity and
all generated file hashes. It must identify the reviewed CPU-REGEN-020 outputs;
no regeneration is performed. Preparation rejects source/input/patch/host drift.
All inputs and outputs remain in ignored `.local` storage. Configure is bounded
to 90 seconds and the compiler child group to 600 seconds. Preparation's other
subprocesses also have deadlines.

After a real build, the implemented IOS026-compatible adapter command is:

```sh
scripts/check-ios-runtime --prepared <private-prepared-directory> \
  --inputs <canonical-private-import> \
  --host-registry <IOS026-private-directory/devices.json> --seconds 60
```

The adapter rechecks exact IOS026 registry names, UDIDs, device types, runtime
26.5 and availability before each simulator operation. Both dedicated devices
must be shut down initially. It installs a separate `local.acs.guest-entry-028`
application, packages only hash-verified main/sdk flat images into its owned
Documents/guest/analysis directory, and refuses existing guest data/evidence.
No keys, NSP, arbitrary source paths or RomFS trees are copied. This small boot
package is sufficient only until the first file/graphics/audio boundary; missing
later data remains an explicit failure, never synthetic content. One launch per
family runs for at most 60 seconds. Each owned application is terminated and its
device shut down, with private logs and hashes retained. Existing guest data is
preserved; a second launch requires a fresh app container under lead control.

## Verification and measured result

`tests/test_ios_runtime.py` uses temporary repositories, actual Git patch
application to the exact locally available pin, generated synthetic fixtures
and actual CMake simulator configuration. It rejects device targets, wrong
memory/strict profiles, mismatched reviewed inputs and wrong-platform libraries.
The compiled input fixture executes the shipped adapter mapping with the real
bridge. A timed child fixture verifies owned-process-group cleanup and retained
logs. The optional pinned-source/SDK integration test skips explicitly when
those local prerequisites are unavailable. Existing preparation/runtime tests
also pass after the shared tool changes.

The original attempt reached step 376/401 and stopped before linking at
`runtime/src/nvn/nvn_pipeline.cpp:108`: the iOS SDK marks `std::system`
unavailable. Independent Astra/medium review
`63ebf19e00a047a9a226729909a6d0e3` failed that exact head because required
native linking, installation and guest execution had not occurred. Its private
logs and `blocked-result.json` are preserved unchanged. Fix round 1 has explicit
authorization for the separate bounded external-command overlay; no availability
suppression, replacement renderer, service change or source regeneration is used.

The adapter now requires the complete current patch and UIKit host identity sets,
including the new overlay. Omitted overlays, stale hashes and modified binaries
are rejected. A worker-entry journal alone is reported as `boot_worker_entered`;
`guest_startup` additionally requires the runtime's actual `nn::init::Start`
entry log. The aggregate measurement also requires a main-queue response during
boot. Neither state implies a guest frame or gameplay.

Fix-round evidence is retained separately under
`.local/ios-guest-entry-028/fix1/`. Native build and family results are recorded
there rather than overwriting the initial failure evidence.

The fresh native build **linked successfully** with max two jobs. All 397
compile commands contain the strict/high-memory macros, arm64 simulator SDK
and minimum 26.0. The binary's Mach-O build platform is `IOSSIMULATOR`;
linked libraries are Apple SDK frameworks/system libraries, with no macOS
Vulkan or Homebrew binary. SDK 27.1 compiled the app; runtime 26.5 was tested.
The original built executable SHA-256 is
`03e7e600979acabfdb9b24df2c8bca389fb743f8ee7099c91c591fbe472d1f5e`;
the copied, ad-hoc-signed launch executable SHA-256 is
`1932074f4f7d59a319ff0f328c5665cd7cb2583af2b0d16e9fd433c513e7ad8d`.

Both dedicated devices installed and launched `local.acs.guest-entry-028`, once
per family. iPhone PID 55240 reached the boundary after 1.448 seconds and iPad
PID 55972 after 1.978 seconds, measured by the supervisor from launch invocation.
Both token-correlated journals record `nx-boot-enter` and a subsequent
`ui-responsive-during-boot` main-queue callback. Both native logs contain:

```text
astral strict boot: host rtld replacement; main+sdk; unsupported guest instructions remain fatal
loaded main at 7000000000 (27763 functions, 55869 relocs)
FATAL: unsupported iOS host operation: window_minimized
```

**Guest startup remains blocked on both families.** Neither log reaches SDK
loading or `entering nn::init::Start`; this is a measured native boot/host
boundary, not execution of the real guest entry. Both report zero guest frames
and no gameplay. There is no diagnostic Metal-frame replacement. The supervisor
correctly exits 1 with `status=blocked`. The two guest logs have identical
SHA-256 `9f665df431c85581404f6c7059180bb845afa5cf9e0de3220e4ae669d3fa3909`.

The reviewed runtime's `kernel_init` starts watchdog and stall-sampler host
threads before module loading. Both contain `window_minimized` calls; the
stall sampler polls after 5 ms. This source evidence explains how the missing
visibility contract can stop boot before guest entry, though no native stack
trace was captured to identify which caller won the race. Per the bounded brief,
work stops at this newly evidenced prerequisite. A follow-up must implement a
real UIKit lifecycle-derived, thread-safe window visibility contract and repeat
both guest measurements in fresh owned containers; returning an unconditional
success value or disabling the watchdog would not resolve the contract.
Simulator Vulkan/presentation and audio prerequisites also remain unverified.

Private startup/command logs and `receipt.json` are retained under
`.local/ios-guest-entry-028/run-b1816b972840489ebaefab51a7f603fd/`.
Both dedicated simulators ended in Shutdown. Logged simulator mutations target
only their registered UDIDs. An unrelated Wonder simulator changed state during
the measurement interval; it was neither controlled nor restored by this unit.
The fresh evidence index binds scoped sources, native build/configuration,
compile commands, startup journals and the exact blocked receipt.

The staged whitespace check required normalization of the overlay's blank
context lines after the measurements. The original patch and build are preserved
under `fix1/ios-nvn-compile-before-context-normalization.patch` and
`fix1/native-before-context-normalization/`. Fresh preparation of the final
patch reproduced every source hash and the compile-command bytes exactly; a
second clean native build verifies the final receipt. It produced the identical
executable SHA-256 shown above. `fix1/patch-context-equivalence.json` binds both
builds to the retained launch evidence. Neither family was rerun.

Nine runtime tests, four compiled external-tool tests and twenty existing
preparation/runtime tests pass, with no skips. Required shell syntax and Git
whitespace checks pass. These checks do not waive the failed guest-startup gate.

Input manifest SHA-256 is
`fb92667f4ac8dbb67f014dfe4de6a205803e435b73577cb0dab48d5410f6cc2d`; control
receipt SHA-256 is
`f4421237f6365a6252834b6e64a00f575a1d28da515d8b53e8efbce4f92eac88`.
Canonical sorted-JSON generated-file identity SHA-256 is
`e9948c47d3c3c4c7302f8e519ffda1eba8f59410defbfdf16ee5638441bab5ef`, from
reviewed CPU-REGEN-020 head `39fc30ab25d83b328e1026a12892db1fc18b305a`.
No nested worker or reviewer is started. Independent exact-head Astra/medium
review belongs to the lead, remains required, and is not waived.

## IOS-NATIVE-LINK-036 recovery

This bounded unit recovers the nine-path result of IOS028 commits
`0db068da35f9fb9b4a0640887a523d894afbbe4f` and
`58989e6f7f18096f2d659ec854be120bd6be43a5` onto current main
`a8984f8a6c9986b4261fb515bb6f9005e2940639`. All seven code, patch and test
files and `IOS_NVN_COMPILE.md` retain their exact final IOS028 bytes; this
section is the sole addition to the recovered documentation. The original
worktree, both recorded failures and all earlier artifacts remain untouched.
The older dispatch revisions above describe the original measurements.

Independent worker-side evidence validation at 2026-10-18T16:42:55Z checked
every file in the retained IOS028 evidence index against its recorded size and
SHA-256, then checked the recovered files against committed Git blobs. Fresh
preparation using this worktree's code, current shared patches, canonical import,
validated control metadata and reviewed generated modules reproduced the entire
retained prepared receipt byte for byte:
`c1cf7ccadcb0ecd508c2acef55c2b9fbefba9e0cb289f457e06483178adba19d`.
All 451 actual prepared source files matched that receipt. Their sorted compact
JSON fingerprint is
`9d08478edf7ac0fc09abd5caa7d429bde7e9d300c6d29366d0856f74159f005f`.
No source regeneration, native rebuild or new guest launch was needed.

The validation also inspected all 397 retained object files and compile commands,
the final native build identity, both normalized/unnormalized executable hashes,
the signed launch executable and its signature/platform, and the exact installed
executable in each registered simulator's private container. Both installed
executables matched the signed launch SHA-256 above. Their retained file mtime
is 2026-10-18T16:27:19.464996Z; the final equivalent native executable's mtime
is 2026-10-18T16:36:53.458594Z. File mtimes are artifact observations, not launch
timestamps. Both installed flat modules and retained in-container startup and
guest logs matched their original identities. Token/PID-correlated journals
establish a main-queue callback after worker entry for each family. The ten
logged simulator mutations target only the two registered UDIDs; read-only
inventory confirmed both dedicated devices remain Shutdown.

The new ignored evidence directory is `.local/ios-native-link-036/`, including
`audit_reuse.py`, `reuse-audit.json`, the fresh prepared receipt and test logs.
The audit records absolute retained artifact paths, hashes, sizes and UTC mtimes;
original logs remain in the IOS028 worktree. Its validation is evidence for reuse,
not the mandatory independent Astra/medium review of the final recovered head.
The lead must commission that exact-head review before landing; it is not waived.

This split accepts native linking, installation and the `nx::boot` boundary on
both iPhone and iPad simulators. It preserves the failing supervisor result and
zero guest frames. Real guest entry, presentation, audio and gameplay remain
blocked. IOS-HOST-037 owns the next `window_minimized` capability and must repeat
both family measurements after changing runtime behavior. This recovery makes
no physical-device claim: 26.5 tested, 26.0 minimum target.


### IOS036 report fix round 1

The first IOS036 report (`7d875c27919f4bfd84c45a7f9182298f`) was rejected
for missing structured evidence. Its committed recovery
`e061dd4eafa06f81773bc6a46d68b4947c7511f8`, report files and ignored evidence
are preserved. This report-only fix uses producer run
`5b7821bd3f9643b9bd05b83e91bcf8c4`. The recovery was rebased onto main
`791031333db04f67688c47b868bcd1ab5be4b246`; the only subsequent scoped change
is this provenance section. Runtime code, both overlays, tests and the
supervisor retain their exact original IOS028 bytes.

At 2026-10-18T16:49:06Z, fresh preparation from the rebased code again produced
the identical prepared receipt and all 451 source hashes recorded above.
The read-only evidence audit rechecked all original indexed files, 397 objects,
strict/high-memory compile commands, build/platform/signature identities and
both installed simulator containers. Both registered devices remained Shutdown;
no simulator mutation, native rebuild or source regeneration was performed.
The previous IOS036 artifact index and rejected reports were hash-checked and
retained. New audit, preparation and focused verification artifacts are isolated
under `.local/ios-native-link-036/fix1/`. Their index records the final committed
head, current-main ancestry, paths, SHA-256 identities and UTC file mtimes.

Both families retain the measured `nx::boot`/main-queue boundary and explicit
`window_minimized` fatal, with zero guest frames. IOS028 remains at two failures;
IOS036 preserves its first report failure. Independent Astra/medium review of
the final rebased head remains mandatory and parent-owned before landing.

## IOS-HOST-037 window boundary

The UIKit host now owns the window platform functions. Independent source
inspection used the actual prepared pinned `platform.h:46-51`,
`kernel_watch.cpp:114,164`, `hle_vi.cpp:41-50`, `nvn/nvn_vk.cpp:281-286,648-649`,
`vk_bridge.cpp:274-281,319` and `vk_swapchain.cpp:416,442`. Watchdog reads occur
before guest entry. VI acquires/releases native handles; swapchain refresh uses
replacement generation and releases its previous handle. These contracts require
real lifecycle state and ownership even before presentation is implemented.

All UIKit sampling runs on main: scene connection, active/inactive, foreground,
background, geometry/layout, window replacement and disconnect publish a mutex
protected snapshot. Missing, hidden, inactive, background or zero-size windows
are minimized. `sceneWillResignActive` clears explicit activity intent before
UIKit changes its activation enum; layout cannot reactivate the snapshot.
Window pixels are rounded `UIWindow.bounds * window.screen.scale`; screen pixels
use the window's screen's native bounds ordered landscape. A disconnect clears
both sizes. Identity changes, including disconnect/reconnect, increment generation;
geometry or activity alone does not. Guest readers only copy synchronized C++
state and never synchronously dispatch to main or read UIKit properties.

`create_window` leases the actual retained `UIWindow` identity and fails explicitly
when unavailable. It creates no render surface. The snapshot keeps its own retain;
old leases survive replacement/disconnect. `release_window(nullptr)` is safe;
known leases release exactly one retain, with final guest-originated UIKit release
asynchronously dispatched to main. Unknown/double releases fail explicitly and
cannot release the replacement window. Vulkan loader/surface and audio operations
remain fatal unsupported boundaries. Runtime mode still submits no diagnostic
Metal frames, and no game-frame or physical-device claim follows from these APIs.

The compiled C++ fixture executes the shipped snapshot/lease implementation with
active/inactive/background/foreground, changed pixel sizes, replacement,
disconnection, stale/unknown/null releases and 10,000 concurrent publications
against a guest reader/acquirer. Native UIKit compilation and the exact pinned
Git/CMake integration test supplement this fixture. Both simulator measurements
and final hashes are recorded below from the bounded native run. Independent
Astra/medium exact-head review remains parent-owned, mandatory and unwaived; this
worker starts no nested worker or reviewer.

### Measured IOS037 native startup

The common native simulator target linked successfully with two compile jobs.
All 397 compile commands passed the strict/high-memory, arm64 simulator and 26.0
minimum checks. Mach-O reports `IOSSIMULATOR`, minimum 26.0 and SDK 27.1; both
actual simulator runtimes were 26.5. Only Apple system/framework libraries are
linked. The unsigned build executable SHA-256 is
`f306bfa96c75557205ae0794a0ab122f1c4a1d63c0d2d0f59ba2c09c42b7653a`;
the ad-hoc-signed installed executable SHA-256 is
`e82859668d1fc911d19b959248c1b0bf2f8e7bb3b164f80f43c12e60504a7529`.
The prepared receipt SHA-256 is
`bda3e5476f491e731b4a1dab7d564493d706cf462f0f08f9212eac39d38f8ef3`;
compile-command SHA-256 is
`b5e3d8272a9a23a74dc56d70e2a3a7ac2b341fd6df32870466c665e0b882aca1`.

Final UIKit-only edits were made while the first full build was still compiling
generated modules, before `App.mm` compiled. A separate fresh preparation from
the final inputs reproduced all 451 patched source hashes. Its only identity
difference was the final `App.mm` hash. The original receipt/logs are retained;
`host-finalization.json` records rebinding the native receipt to that freshly
produced identity and rerunning the normal identity-checked configure/build.
The final App object is newer than its final source. No generated source was
regenerated or changed. The source identity and build identity were revalidated
before installation. This provenance is explicit rather than treating the first
preparation's earlier host identity as the final build identity.

The private supervisor is an isolated copy of the landed adapter, changing only
the evidence location, bundle ID, dispatch provenance and added UTC/executed-script
identity fields. All ownership/input/source/build checks and cleanup remain.
The fresh bundle is `local.acs.guest-entry-037`, preserving IOS028's app containers
and original worktree. Measured runtime-code head is
`e638e6158d5b3ce4ac40deb7c7703f1e0d805ced`; subsequent scoped documentation
records these results without changing its runtime, host or test bytes.

| Family | Launch UTC, 2026-10-18 | PID | Time to fatal | Window/screen pixels |
|---|---|---:|---:|---|
| iPhone | 17:08:57.267671Z | 22752 | 1.606 s | 2622 × 1206 |
| iPad | 17:09:15.187578Z | 23474 | 1.451 s | 2420 × 1668 |

Both token-correlated journals record generation 1 and `minimized=false` on
main at `scene-active`, the same pixel snapshot on the guest worker at
`nx-boot-enter`, and a later main-queue `ui-responsive-during-boot` callback.
Both actual guest logs pass the former `window_minimized` boundary, load main
and SDK, link with zero unresolved strong imports, enter `nn::init::Start`,
and then enter `nnMain`. The precise next observed boundary on both is:

```text
FATAL: strict IPC missing command: service=ISelfController command=14
```

No service fallback was added by this unit. Vulkan presentation and audio remain
explicitly unsupported and were not reached in these traces. The supervisor's
`status=measured` accepts real guest startup only; gameplay remains **blocked**
on that IPC prerequisite and subsequent unverified capabilities. Both families
have zero measured guest frames. No screenshot/capture or visual update is
presented as a game frame, and no physical iPhone/iPad acceptance is claimed.

Both guest logs have SHA-256
`5da3951371f690d50685879302b0461526ba69e666c0c960d3054cee6f74a467`.
The iPhone startup journal SHA-256 is
`51b3b18c40d1dbf0586cb176620edadeb8b03e0d6bdeb0da8944188af07abe09`;
the iPad journal SHA-256 is
`f1e0543c5e77202a51bb7e3f953a744b2c3b622153952c7d5e718d3406c94c76`.
Private logs, input/source/binary identities, the executed supervisor and its
receipt are retained under `.local/ios-host-037/`, with the actual runs in
`run-7940395d4d084db981c8cf671a9c4ea9/`. Both dedicated devices were independently
confirmed Shutdown after owned-app termination. Every logged simulator mutation
targets only their registered UDIDs. No unrelated simulator/process was controlled.
All ten focused tests pass without skips. Mandatory independent Astra/medium
review of the final scoped head remains outstanding and parent-owned; it is
not waived by successful builds or these startup measurements.
