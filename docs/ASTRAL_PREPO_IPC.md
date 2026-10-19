# Bounded prepo:u local SaveReport adapter

This original overlay adds `prepo:u` and only commands 10102 (`SaveReport`) and
10103 (`SaveReportWithUser`). It changes exactly the public upstream file
`runtime/src/svc_misc.cpp`, after the accepted bootstrap/control/logger/APM
composition. It adds no imports, HLE symbols, command aliases or build sources.
The production SM registry, IPC parser, kernel PID bridge and handle/domain
lifetime implementation remain unchanged.

## Evidence and limits

081 candidate `e0c38c014fe3dde6792aad4563e197f76ff12ba9` recorded an actual
`sm: GetService(prepo:u)` followed by `strict IPC missing service: prepo:u`.
This establishes an attempted service open, **no executed prepo commands**.
The parent inbox explicitly requested this disjoint implementation while 081
was under review. The later 22:45Z platform-status receipt records that 081
failed independent Astra/medium review for writing readbacks to retained data.
That failure is preserved; neither its application result nor its supervisor
has been promoted to accepted native integration by this unit.

The original main NSO symbol table and retained generated import table agree on exactly eight prepo imports:
Initialize, PlayReport constructor, SetEventId, SetBuffer, Add(string), Add(bool),
Add(int64), and Save(Uid). These justify potential paths, not execution counts.
No prepo implementation was found in the pinned LAS/letsgo inventory; none is
claimed or copied here.

Read-only original SDK NSO relocation and AArch64 disassembly corroborate the
retained generated SDK at these module-relative addresses:

| Path | Contract fact |
| --- | --- |
| `0x32d690` → shim, `0x32f980`, `0x32fe60` | Initialize acquires a service object through SM; first string at `0x9fb8f0` is `prepo:u`. No guessed prepo Initialize command. |
| `0x32e4b0`, relocated vtable slot `0xb7f240` | Save(Uid) invokes the new SaveReportWithUser wrapper at `0x3303e0`; event length includes one NUL; final u64 parameter is zero. |
| `0x3303a0`, `0x3303e0` | Command IDs `0x2776`/`0x2777` = 10102/10103; GOT `0xba9f58`/`0xba9f60` resolves to marshallers `0x330680`/`0x330880`. |
| `0x330680`, `0x330880` | CMIF type 6, PID descriptor, one input pointer (attribute 9, X), one input map-alias (attribute 5, A), no output data/object. Scalars are reserved u64, or Uid[16] then reserved u64. |
| `0x9fb8b0`, `0x9fb8b8` | SDK report buffer bounds 3..13003 bytes. |
| `0x32ee60`, `0x32f010`, `0x32f490` | Event is 1..31 lowercase ASCII/digit/underscore bytes plus NUL; report is a flat MessagePack map, at most 100 fields, keys 1..63 ASCII identifier bytes, case-insensitive duplicate rejection. |
| `0x330420`, `0x330440`, `0x32f810` | Transmission request/status are separate operations; SDK SaveResult normalizes some nonzero results. This adapter does not borrow those unknown error meanings or imply that normalized SDK success proves delivery. |

Private `.local/prepo-ipc-083/inputs.json` timestamps and hashes original NSO,
flat SDK analysis image, selected generated TUs/main table and 081 observation.
`trace_contract.py`, `more_contract.py`, `last_contract.py`, `symbols.txt`,
`contract-disassembly.txt`, `contract-more.txt`, `report-validation.txt`, and `main-imports.json`
preserve selected relocation/disassembly derivations. These are private audit
inputs and are never compiled into fixtures or copied into Git.

## Supported behavior

The saved report body supports the main-import-backed string, bool and signed
integer values, plus the corresponding unsigned MessagePack integer encodings.
Strings are bounded to 63 bytes and checked for valid UTF-8. Fixmap/map16/map32
and fixstr/str8/str16/str32 encodings are parsed with subtraction-based bounds.
Unsupported values (including floats, binary, arrays and nested maps) fail
explicitly, even if broader SDK APIs can create them. There is no claim to a
complete prepo server or complete SDK value coverage.

Both command signatures require exact argument bytes, a live kernel-authenticated
PID descriptor, reserved-zero u64 and exactly the X/A descriptors above. Direct
unauthenticated contexts, stale owners, extra handles/objects/buffers, unreadable
or overflowing buffers, bad event terminators, truncated maps, invalid keys,
duplicate keys and trailing bytes are fatal adapter errors before storage or
reply mutation. VM regions are checked before copying either buffer. The UID is
stored as supplied data; it grants no network account or ownership assertion.
The service binds to its first successful saving process and its metadata
lifetime. Production session/domain/clone ownership supplies close behavior.

Save and transmit are distinct SDK requests. This implementation fulfills Save
by storing the exact validated report locally under
`NX_DATA_ROOT/user/prepo/<slot>/report.bin`; it performs no external sends and
implements no transmission/status command. Success means the host file was
written, flushed, synced and closed. It is neither an upload nor a delivery
receipt. There is no silent eviction or report discard.

There are exactly 64 slots, bounding saved data below 1 MiB. Existing slots
survive process restart and are never overwritten. Each record contains seven
little-endian u64 fields: format version 1, command, authenticated process ID,
UID low, UID high (zero for 10102), event byte count including NUL, report byte
count; then event and MessagePack bytes. This is an original host format, not
Nintendo's storage format. Empty/failed allocations remain reserved for audit.
Root/user/prepo symlinks are refused; newly created slot directories isolate
files from preexisting filenames. The host data root must already exist.

Capacity, unsafe paths and host open/write/flush/sync/close errors stop explicitly
without acknowledging Save. Exact Horizon storage-error results are not known;
none are invented. Host power-loss transactionality, directory fsync/recovery,
malicious concurrent host filesystem replacement, uploads, agreement checks,
statistics, older commands 10100/10101, system-report commands and alternate
service names are outside this bounded contract. Unknown commands are always
fatal. The fresh private native data root below is mandatory.

## Synthetic production verification

`tests/test_prepo_ipc.py` composes pinned public runtime `010ed7a596a621c15d3a8dfa5795ca8c3668b066`
with the existing overlays and compiles the actual full production kernel,
parser/registry and service TUs with an original synthetic host/VM boundary.
Neither game source nor SDK code enters that compilation. A baseline executable
without this overlay reproduces the missing prepo service failure. The patched
executable covers real SM acquisition and kernel-PID substitution, both Save
signatures, exact persisted bytes, 13003-byte/100-field maximum, negative buffer
and framing cases, report validation, invalid handles, dead process, domain
conversion/clone/object/protocol close, explicit unrelated/unknown failures,
64-slot exhaustion, restart persistence, unsafe path and real stream failure.
Accepted APM, parental-control and caller/parser regression bodies also run
against this same composed production source, including last-thread teardown.
The stream fault fixture opens a real read-only stream; production fwrite,
fflush, fsync and fclose remain in use. No fake service/parser success is used.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_prepo_ipc.py -v
git diff --check main HEAD
```

Each invocation retains unique ignored `verify-*/receipt.json`, compiler and run
logs, binaries and synthetic stores. The receipt indexes overlay/production
source/test/binary hashes and actual compiler/run exits. This is synthetic
service acceptance only. No game/native build or launch ran in 083.

## Serialized native handoff (not executed)

Parent must obtain independent **Astra/medium exact-head patch/result review**,
then guarded `scripts/land` for 083. No waiver. Separately resolve 081's failed
review and accept the supervisor before using it. Assign a distinct native unit,
for example `MAC-PREPO-NATIVE-NEXT`, with exclusive native-current write ownership.
Preserve current source/configuration/binary receipts first; do not clean-rebuild
or mutate accepted data. Stop at current STOP/usage/budget controls.

After those gates, the successor applies only this landed overlay to the stable
source (full paths below are under the repository checkout, `$ACS_ROOT`):

```sh
repo="${ACS_ROOT:?set ACS_ROOT to the repository checkout}"
store="$repo/.local/orchestrate/2026-10-18-evening"
native="$store/native-current"
next="$store/worktrees/MAC-PREPO-NATIVE-NEXT/.local/mac-prepo-native-next"
git -C "$native/source" apply --check "$repo/runtime/patches/astral-prepo.patch"
git -C "$native/source" apply "$repo/runtime/patches/astral-prepo.patch"
"$repo/.local/game-private/astral-work/venv/bin/cmake" --build "$native/build" --parallel 2 --target astral
```

Run the build with an owned process-group supervisor and a 900-second bound;
retain command/exits, source/patch/executable hashes and compiler flags
`NX_ASTRAL_STRICT=1`, `NX_APPLE_HIGH_MEMORY=1`. The service lives in the existing
svc_misc TU, so no CMake/profile change is necessary.

Create `next` and a **new** `next/runtime-data` first. Copy the verified read-only
analysis/extract/shader input layout from `.local/evening-control/runtime-data-066-v2`
into this new root with `shutil.copytree(..., symlinks=False)` and record selected
hash equality; exclude old `frames`, `user`, and logs. Do not hardlink or symlink
writable trees back into accepted data. Create fresh `user` and `frames`
directories. Preserve the verified `astral.profile` from 081 in `next`, and
recheck loader hash `ad54a6a33e9b82592403f928d8d74bad98a6caf4df6151a50c762aaf7acf6735`.
Then use the independently accepted supervisor (once landed):

```sh
env NX_TRACE=1 NX_NVN_REAL=1 NX_DATA_ROOT="$next/runtime-data" \
  NX_LOG="$next/guest-trace.log" NX_NVN_FORMAT_PROFILE="$next/astral.profile" \
  NX_DUMP_FRAMES=1 \
  SDL_VULKAN_LIBRARY="$repo/.local/evening-control/mac-vulkan-loader-2212/libMoltenVK.dylib" \
  python3 "$repo/tools/run_mac_renderer_probe.py" \
    --evidence "$next/run-01" --cwd "$next" -- "$native/build/astral"
```

That supervisor limits guest execution to 40 seconds and the full owned group to
60 seconds including cleanup. Retain outer timing, receipt, final process
inventory, actual command IDs/results, local Save records, next strict failure,
frame/presentation telemetry and first genuine frame if any. No re-run merely to
repair a report. Synthetic Save coverage does not predict which commands the
native guest actually executes or guarantee a game frame.

Five target statuses are preserved: macOS partial, Linux partial, Windows
blocked, iPhone simulator partial, iPad simulator partial (26.5 tested / 26.0
minimum). No gameplay, audio/input route, physical-device or cross-platform
acceptance follows from this change; native acceptance is pending.
