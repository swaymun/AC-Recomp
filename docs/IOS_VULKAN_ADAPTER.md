# Simulator Vulkan adapter (IOS-VULKAN-ADAPTER-053)

This unit supplies loader lookup, retained window/Metal-layer identity and simulator
linkage. It establishes adapter execution in compiled host fixtures and separate
arm64 iPhone/iPad simulator package links. It does not establish Vulkan rendering,
swapchain synchronization, guest execution, gameplay, simulator runtime behavior or
physical-device support. Native synthetic presentation belongs to IOS-VULKAN-PRESENT-054.
The package links use SDK 27.1 with minimum deployment target 26.0; no simulator
runtime version is tested here.

## Source selection

The untrusted reference is exact commit
`f2c239a52936a6336bc5fe994314096ccb9a5729` from exhausted IOS-VULKAN-046.
Only its incremental `ios-vulkan.patch`, window/layer ownership core, main-thread
publication and loader/surface bridge were selected after inspection. The native
probe, smoke-mode branches, synthetic presentation and old acceptance claims were
excluded. IOS046 stays `needs_split`, failures 2; this unit does not modify its state.
The new publication guard also enforces main-thread ownership in release builds.

Apply `ios-vulkan.patch` after the reviewed `apple-memory.patch`,
`astral-bootstrap.patch`, `ios-runtime.patch` and `ios-nvn-compile.patch` on Wonder
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. It changes only upstream
`CMakeLists.txt` and `runtime/src/platform_ios.mm`. Preparation/integration profile
selection is outside this unit; no shared preparation tool is changed.

## Ownership and failures

UIKit attaches and resizes the CAMetalLayer on main. Workers read mutex-protected
snapshots and acquire retained window/layer pairs. Inactive or disconnected scenes
refuse new windows and surface creation. Leases survive target closure without
releasing a replacement target; an outstanding lease on the same window with a
replaced layer blocks ambiguous reuse until released. Duplicate/unknown releases
fail. Final Objective-C releases from workers are dispatched to main.

Surface creation uses only retained layer identity, resolves both create and destroy
entry points, and zeros the output before failure. Missing cleanup support refuses
creation. Driver allocation errors propagate. If the scene closes during creation,
the new surface is destroyed before returning surface-lost. MoltenVK's source-tag
MVKSurface::initLayer retains the layer; the adapter relinquishes its temporary
retain. This source observation does not prove release-binary/source equivalence.
Normal runtime mode still boots the guest once on its owned worker and retains
existing touch/lifecycle behavior. It adds no synthetic frames or probe invocation.

## Pinned public dependency

Use the already staged receipt SHA256
`666bc78ede4976b3c30588625a6e73f19fd7d0b158eb419e18d2aac3c03caaa8`.
MoltenVK 1.3.0 source tag is
`49b97f26ae013b9e5bfb3098ee5dea5e4f58e9e8`; simulator static slice SHA256 is
`c6579190db24f622856c7fbc0bd2bdab7a2338f083945aa1ea0cab8afc38df27`.
The device-only archive and macOS libraries cannot substitute for the all-archive
simulator slice. Configure validates arm64 LC_BUILD_VERSION simulator platform
and pinned library/core-header hashes. Tests revalidate all 19 staged artifacts,
51 headers, XCFramework platform/variant/architecture, and SDK text stubs for all
11 direct linked dependencies. No dependency is downloaded or rebuilt.

## Verification and evidence

Run:

```
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_ios_vulkan_adapter.py -v
git diff --check main HEAD
```

The threaded C++ fixture executes the actual lease core. An Objective-C++ fixture
executes the actual publication and surface adapter with small UIKit test doubles,
real Foundation/QuartzCore and stateful Vulkan callbacks. It checks main-thread
publication (including deliberate off-main termination), worker surface access
without UIKit reads, resize/inactive/resume/detachment, target closure during
creation, allocation errors, missing cleanup proc and deferred final destruction on main. It is host-fixture evidence,
not simulator execution or a real Vulkan driver rendering test.

Separate iPhone/iPad family manifests and production App.mm links use the pinned
static slice and simulator SDK. Only guest boot/memory/thread/fatal symbols are
replaced by original link stubs. No guest-derived input or probe is linked.
Real compiled device/macOS archives are rejected by configuration despite matching
arm64 architecture. Overlay application is checked on the exact Wonder pin.

Private ignored `.local/ios-vulkan-adapter-053/` retains the old source/raw reports
as untrusted reference, measured sources, fixture and simulator-link binaries,
commands, test output, dependency/platform audit and cleanup receipts. Source
hashes identify measured bytes separately from final report HEAD. Optional
`ACS_ADAPTER_EVIDENCE` captures receipts during tests; final report validation uses
the repository's actual orchestrator validator and rejects empty evidence.
No simulator session, provider, shared preparation service or unrelated process
is started or stopped. Temporary test directories clean up; private receipts stay.
Independent Astra medium review of the exact final head is required before landing;
this worker does not commission a nested reviewer or waive review.
