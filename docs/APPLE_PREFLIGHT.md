# Apple memory preflight — APPLE-PREFLIGHT-001

Measured October 18, 2026 on this arm64 Mac (macOS 26.6.2, Darwin 25.6.0).
**Native macOS: blocked by occupied fixed ranges. iPhone and iPad simulator apps:
reservation/page/stack probe passed.** Mobile is **26.5 tested / 26.0 minimum target**,
built with the installed 27.1 simulator SDK. Physical devices remain untested.
This is an original memory probe, with no game input, runtime linkage or game execution.
Independent review belongs to the parent; this worker has not spawned reviewers.

## Source assumptions checked

Inspected the detached source checkout at exactly
[`010ed7a596a621c15d3a8dfa5795ca8c3668b066`](https://github.com/BelmanteGu/SuperMarioWonderRecomp/tree/010ed7a596a621c15d3a8dfa5795ca8c3668b066):

- [`runtime/src/memory.cpp`](https://github.com/BelmanteGu/SuperMarioWonderRecomp/blob/010ed7a596a621c15d3a8dfa5795ca8c3668b066/runtime/src/memory.cpp)
  reserves modules, heap, alias, stack and kernel in that order; failures are fatal.
  Thunks are an optional reservation and are never read, committed or executed.
  Kernel allocations round to 4 KiB with 4 KiB default alignment.
- [`runtime/include/nx/runtime.h`](https://github.com/BelmanteGu/SuperMarioWonderRecomp/blob/010ed7a596a621c15d3a8dfa5795ca8c3668b066/runtime/include/nx/runtime.h)
  and [`runtime/include/nx/cpu.h`](https://github.com/BelmanteGu/SuperMarioWonderRecomp/blob/010ed7a596a621c15d3a8dfa5795ca8c3668b066/runtime/include/nx/cpu.h)
  select the following Apple layout. Guest pointers are host pointers. The guest's
  reported address space is `[0x8000000, 0x8000000000)` (39-bit); the runtime does
  not reserve that entire address space.
- [`runtime/src/platform_mac.cpp`](https://github.com/BelmanteGu/SuperMarioWonderRecomp/blob/010ed7a596a621c15d3a8dfa5795ca8c3668b066/runtime/src/platform_mac.cpp)
  uses a non-destructive `mmap` hint with `PROT_NONE`,
  `MAP_PRIVATE | MAP_ANON | MAP_NORESERVE`, accepts only exact equality, and unmaps
  alternate returns. Commit expands to host-page boundaries with RW `mprotect`.
  Partial-page decommit zeroes bytes; whole pages use `MADV_FREE` and `PROT_NONE`.
  The game worker requests a 64 MiB pthread stack.
- [`CMakeLists.txt`](https://github.com/BelmanteGu/SuperMarioWonderRecomp/blob/010ed7a596a621c15d3a8dfa5795ca8c3668b066/CMakeLists.txt)
  selects `platform_mac.cpp`/`memguard_mac.cpp` for all `APPLE` builds, expects SDL3,
  Vulkan headers and a macOS executable. There is no separate iOS bundle/lifecycle
  branch. `runtime/CMakeLists.txt` does not exist at this revision. Generated game
  code is not needed by this probe and was not generated or processed.

## Measurements

Ranges below are half-open. All successful reservations stay live simultaneously;
boundary commits/readbacks follow the complete reservation pass. The probe continues
after required failures only to collect diagnostics and exits nonzero.

| Region | Intended range | Size | macOS final run | iPhone 26.5 app | iPad 26.5 app |
|---|---|---|---|---|---|
| Modules | `0x300000000..0x320000000` | 512 MiB | exact + RW endpoints | exact + RW endpoints | exact + RW endpoints |
| Heap | `0x400000000..0x580000000` | 6 GiB | occupied; rejected alternate | exact + RW endpoints | exact + RW endpoints |
| Alias | `0x600000000..0xA00000000` | 16 GiB | occupied; rejected alternate | exact + RW endpoints | exact + RW endpoints |
| Stack | `0xA00000000..0xB00000000` | 4 GiB | occupied; rejected alternate | exact + RW endpoints | exact + RW endpoints |
| Kernel | `0xB00000000..0xC00000000` | 4 GiB | occupied; rejected alternate | exact + RW endpoints | exact + RW endpoints |
| Thunk (optional) | `0xE00000000..0xE00100000` | 1 MiB | exact, no access | exact, no access | exact, no access |

Required reservations total 30.5 GiB; including thunk, 32,750,174,208 bytes.
The native final process already contained VM regions
`[0x568000000, 0x869000000)` (no access),
`[0x869000000, 0x869400000)` (RW), and
`[0x869400000, 0xB68000000)` (no access). These intersect the failed ranges.
An earlier process had different overlapping addresses and successfully reserved
heap; therefore availability varies with process startup layout. VM observations
establish occupation, not which allocator/component owns it. No alternate layout,
fixed replacement mapping, allocator override or global setting was used.

All three processes measured:

- Host pages **16,384 bytes**, guest pages **4,096 bytes**, 64-bit pointers.
- A second reservation over the already occupied module range was rejected and
  its original byte remained intact. Alternate mappings were immediately released.
- Inside the exact module mapping, freeing a shared 4 KiB slice zeroed that slice
  and preserved both neighboring data and the remaining host-page contents.
- Whole-page decommit returned success, changed protection to none, and recommit
  restored RW. The first reused byte was **90 (`0x5a`)**, the previous data:
  `MADV_FREE` did not guarantee zero-on-reuse. This observation is reported, not
  treated as an allocation/protection failure.
- A worker requested **67,108,864 bytes** of stack; the running thread reported
  **67,121,152 bytes**. Creation/join succeeded and reported capacity exceeded the
  request. Main-thread stack limits do not prevent this separate worker stack.
- `RLIMIT_AS`/`RLIMIT_DATA` were unlimited; `RLIMIT_STACK` soft/hard were
  8,372,224 / 67,092,480 bytes. Task VM inspection succeeded. Simulator values
  describe a process running on this Mac, not device jetsam or entitlement limits.

Only a few boundary pages and a small page-policy sample were touched. This does
not prove 6 GiB of resident heap, physical-memory capacity, sustained allocation,
performance, GPU sharing, or tolerance of memory pressure.

## Reproduce

Requires Xcode command-line tools, an arm64 Mac, Python 3, and the installed iOS
26.5 simulator runtime. No signing identity or credentials are read: simulator
bundles use an ad-hoc signature, verified with `codesign --verify --strict`.

```sh
bash -n scripts/check-apple-memory
scripts/check-apple-memory --native
scripts/check-apple-memory --simulators
scripts/check-apple-memory --all
```

Default is `--native`. Native and `--all` deliberately exit **1** when a required
range is unavailable; that is a measured portability blocker, not a hidden skip.
Simulator-only mode exits zero when both in-app reports pass. Other command errors
are retained in `failure.txt` with the exact command/output in `commands.log`.
Each run gets a new ignored evidence directory. `summary.json` records probe exit
codes separately from command failures. Native compilation uses warnings as errors.
Optional native CMake entry: `cmake -S probes -B .local/apple-memory-build` then
`cmake --build .local/apple-memory-build`; CMake was unavailable on PATH here, so
this entry was not executed. The direct Clang build was executed.

The script generates a minimal Objective-C++ application entry and app bundle in
private storage, compiles the shared original probe for
`arm64-apple-ios26.0-simulator`, signs it, installs and launches it by exact task
UDID. It reads the app's own Documents report and atomic completion marker, which
include `TARGET_OS_SIMULATOR=1`, runtime/model and the probe exit code. It does not
substitute `simctl spawn` or a host-only executable for application execution.

Devices are named `ACS APPLE-PREFLIGHT-001 iPhone` (iPhone 17 Pro) and
`ACS APPLE-PREFLIGHT-001 iPad` (iPad Pro 11-inch M5). Reuse requires an exact match
of registered ID, name, runtime and device type. Only these task devices/apps are
booted/installed/launched/terminated/shut down. No reset/erase/delete is used.
The dedicated devices, apps and private evidence are retained. Existing Wonder
simulators are untouched.

## Private evidence and next gates

Paths are relative to this worktree, under ignored
`.local/orchestrate/2026-10-18/apple-preflight/`:

- `source/`: detached inspected upstream checkout at the pinned revision.
- `devices.json`: dedicated iPhone/iPad UDIDs; do not publish them in tracked docs.
- `run-20261018T080720Z-8317c6/`: final generated `main.mm`, signed
  `ACSMemoryProbe.app`, native binary, `commands.log`, `signature.txt`,
  `macos.txt`, `iPhone.txt`, `iPad.txt`, app completion JSON, `summary.json`, and
  before/after inventories. The overall `--all` failure is expected from macOS.
- `run-20261018T080627Z-8cf418/`: preceding successful signed-app execution on
  both families, plus native collision measurements.
- `run-20261018T080549Z-068a5c/`: initial build error retained. The simulator SDK
  rejects `mach/mach_vm.h`; switching self-inspection to supported `vm_region_64`
  from `mach/mach.h` resolved it. No private API was needed.

The next native unit must resolve the occupied fixed-layout premise before runtime
integration, including consistency of generated addresses and guest-visible maps;
this probe deliberately preserves the pinned layout. Whole-page zeroing semantics
also need an explicit policy and a regression test if fresh guest pages must be
zeroed. The mobile build needs a genuine iOS lifecycle/platform target before a
separate UIKit/Metal-frame unit. Neither Metal presentation nor MoltenVK was tested.
Physical-device virtual-address limits, signing/entitlements, resident-memory and
jetsam constraints, and performance remain separate unverified gates. No on-device
JIT, game startup, game frame or gameplay is claimed.
