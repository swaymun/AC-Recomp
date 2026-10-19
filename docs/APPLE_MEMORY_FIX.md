# Apple memory policy — MAC-MEM-FIX-002

Native **default remains blocked**. The explicit **apple-high-v1** profile passed
five fresh native processes, including the actual patched upstream memory
functions. Both original-layout simulator applications passed the shared zeroing
and protection checks: **26.5 tested / 26.0 minimum target**. This is memory-policy
validation, not a runtime/gameplay build, physical-device test, or performance claim.
Independent review is assigned to the parent; no nested review was performed.

## Diagnosis and preserved baseline

On October 18, 2026, macOS 26.6.2 / Darwin 25.6.0 / arm64 / 16 KiB host pages,
the original probe again rejected occupied ranges without replacing mappings.
The final default process had these actual VM regions:

| Range (half-open) | Current / maximum protection | VM tag |
|---|---|---|
| `0x51A000000..0x81AC00000` | none / none | 0 |
| `0x81AC00000..0x81B000000` | RW / RWX | 2 (`VM_MEMORY_MALLOC_SMALL`) |
| `0x81B000000..0xB1A000000` | none / none | 0 |

Heap, alias, stack and kernel reservations failed in that process; modules and
optional thunks succeeded. Earlier processes had different randomized addresses.
Self-inspection records exact VM bounds, permissions and extended-info tags;
`vmmap` on a separate task-owned held probe confirmed `MALLOC_SMALL` mappings in
the occupied area. The inaccessible tag-0 ranges are adjacent to malloc-small
mappings, but their tag does **not** establish their owner. Do not attribute them
to nano malloc or xzone malloc solely from these observations.

A fresh original-range process with only `MallocNanoZone=0` still failed alias,
stack and kernel. No allocator environment workaround was validated. Additional
local candidate experiments and their failures are retained privately, not
promoted to recognized/supported launcher settings. No global allocator or
security setting changed. The policy below requires no allocator override.

The original whole-page test still reports `reused_first_byte=90` (`0x5a`) after
successful `MADV_FREE`, `PROT_NONE`, then RW recommit. The probe retains that test,
its original ranges and its failure exit separately from the new profile. Default
`--native` / `--all` still fail when original reservations are unavailable.

## Explicit native profile and generated pointer contract

Apply `runtime/patches/apple-memory.patch` to Wonder exactly at
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. The patch changes only original runtime
code in `runtime/include/nx/{cpu,runtime}.h` and `runtime/src/platform_mac.cpp`.
It applies cleanly to committed pinned blobs. No CMake or generated source change
is included in this unit.

For native Mac integration, compile **every runtime and generated-module
translation unit** with `-DNX_APPLE_HIGH_MEMORY=1`. Use a clean build directory;
do not reuse static libraries compiled for the default layout. The profile is a
build decision, never an automatic retry after reservation failure. Mixing
profiles across translation units is unsupported and not detected at link time.
Combining the profile with a caller-defined `NX_BASE` is a compile error.

| Region | Base | Size |
|---|---|---|
| Modules (`NX_BASE`) | `0x7000000000` | `0x20000000` |
| Heap | `0x7100000000` | `0x180000000` |
| Alias | `0x7300000000` | `0x400000000` |
| Stack | `0x7800000000` | `0x100000000` |
| Kernel | `0x7900000000` | `0x100000000` |
| Thunk identifiers | `0x7B00000000` | `0x100000` |

All ranges remain inside the original reported 39-bit guest address space
`[0x8000000, 0x8000000000)`. Sizes and direct guest-pointer-as-host-pointer semantics
remain intact. Generated code's existing
`NX_BASE + (module_base - 0x4000000000)` expression makes the SDK base
`0x7010000000`; generated canonical module-base inputs remain unchanged.
Tests compile the actual patched headers with this expression and both profiles.
Do not substitute a different `--base` in the generation command to compensate.
Reservation still uses a non-destructive hint, rejects alternate addresses and
returns failure. No `MAP_FIXED`, overwritten region, dynamic relocation or
changed guest-pointer representation is introduced.

The launcher must execute the consistently compiled binary normally, with no
allocator override required. The runtime's existing fatal-on-reservation-failure
policy remains mandatory. Five fresh memory-probe processes passed these exact
ranges; a future OS, linked dependency or application startup can still occupy
them. Validate again in the final linked runtime after SDL/framework startup.
The unchanged mobile layout remains selected when the opt-in macro is absent.
The high profile has not been tested on either simulator.

## Zeroing and protection semantics

Guest allocations use 4 KiB pages; this host uses 16 KiB pages. The patch preserves
the existing split at host-page boundaries:

- Shared edge bytes are zeroed only inside the freed guest slice. Neighbor bytes
  remain intact and the shared host page remains RW. A 4 KiB slice cannot become
  a hardware guard while another live slice shares its 16 KiB host page; guest
  QueryMemory metadata remains responsible for that finer-grained distinction.
- Complete host pages are made RW, explicitly zeroed, optionally advised with
  `MADV_FREE`, then protected `PROT_NONE`. Retained lazy-free pages contain zeros;
  reclaimed anonymous pages also fault back as zeros. Failed whole-page protection
  changes abort because the upstream decommit interface has no error return.
  Failed advisory reclamation is harmless to correctness after explicit zeroing.
- This favors correctness over decommit cost: eager zeroing touches complete
  pages and may increase transient resident memory. Large-region throughput,
  memory-pressure behavior and guard/concurrency interactions need runtime-level
  validation. The existing caller contract must exclude concurrent access to
  memory being decommitted; partial edge writes still require committed RW bytes.

The native fixture and real simulator apps invoke functions extracted from the
**actual applied upstream patch**, not a duplicate zeroing implementation. They
check a shared 4 KiB slice, a mixed span with both shared edges and two complete
host pages, and five complete host pages. Every reused byte must be zero;
neighbors retain `0x5a`. Self-inspection requires full-page `PROT_NONE`, and a
Mach read must be denied before recommit. The occupied-range test separately
requires the original byte to survive a rejected overlapping reservation.

## Reproduction and evidence

Prepare an ignored upstream checkout at the exact pin (see `RUNTIME_MAP.md`).
Default source location is `.local/orchestrate/2026-10-18/apple-preflight/source`;
alternatively set `APPLE_MEMORY_SOURCE` to an existing pinned checkout. The script
reads committed Git blobs, copies only three original source files to its private
run directory, checks/applies the patch there and compiles only its memory section.
It never modifies the supplied checkout.

```sh
scripts/check-apple-memory --native                 # original baseline; observed exit 1
scripts/check-apple-memory --native-profile         # baseline + five high/fixed processes
scripts/check-apple-memory --all-profile            # also both fixed-policy simulator apps
scripts/check-apple-memory --simulators             # original layouts + fixed policy only
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_apple_memory.py' -v
bash -n scripts/check-apple-memory
```

Profile mode succeeds when its selected policy checks pass, while `summary.json`
retains `macOS.exit_code=1` and `baseline_failed=true`. This is explicitly **not**
a default-baseline pass. Tests on this worker ran five cases, zero skips, all
passing; native tests skip explicitly on non-Darwin or absent pinned source.

Policy simulator modes require the preflight's existing private `devices.json`
registration and validate exact ID/name/runtime/type before touching either task
device. In a fresh worktree, copy only that registry from the preflight evidence
into this worktree's ignored preflight directory; do not invent arbitrary IDs.
The task apps are ad-hoc signed and signature-verified, installed/launched as
applications, and checked through their own atomic completion markers. Only
`ACS APPLE-PREFLIGHT-001 iPhone` and `ACS APPLE-PREFLIGHT-001 iPad` were used.
No Wonder device/process, device erase/delete, credentials or game input was used.

Evidence retained under this worktree's ignored `.local/`:

- `memory-fix/default.txt`, `nano0.txt`: initial unchanged baseline and unsuccessful
  process-local nano override; both retain `0x5a` on whole-page reuse.
- `memory-fix/vmmap-default.txt`, `hold.txt`, `overlap-tags.txt`: actual task-process
  VM maps and extended-tag diagnostics. `vmmap-reserved.txt` retains an unsupported
  flag diagnostic; it is not a successful map capture.
- `orchestrate/2026-10-18/apple-preflight/run-20261018T082257Z-0892f9/`: initial
  full patched-policy native and simulator pass.
- `orchestrate/2026-10-18/apple-preflight/run-20261018T082446Z-3e7324/`: final
  instrumented full run, with `macos.txt` default FAIL, five `macos-high-*.txt`
  PASS, iPhone/iPad PASS, source fixture, command log, signed app, inventories and
  `summary.json`. Both simulator reports preserve original lazy-reuse byte 90
  alongside successful `fixed_partial`, `fixed_mixed` and `fixed_whole` checks.

Integration still requires the parent-reviewed patch to be applied by runtime
preparation, consistent profile flags across all native generated/runtime targets,
and full linked-runtime reservation/boot tests. Neither gameplay, resident 6 GiB
heap capacity, Metal/Vulkan sharing, mobile signing for physical devices nor
performance is established by this unit.
