# Astral host-save commit overlay

`astral-fs-commit.patch` changes only the pinned Wonder runtime's
`runtime/src/hle_fs.cpp`. Apply it after the existing runtime overlays in a new
private fixture/integration source. No build or patch is applied to the stable
native source by this unit. Native integration stays serialized after unit 075's
independent acceptance; this document does not assert that 075 landed.

## Static contract and evidence

The owned Astral main import table contains
`_ZN2nn2fs14CommitSaveDataEPKc`. The read-only SDK export table and generated
wrapper/helper bodies were inspected locally: `CommitSaveData(const char*)` and
`Commit(const char*)` pass the unchanged name to the same helper, with different
logging labels, and return the same 32-bit result. That helper looks up a mounted
filesystem and calls its accessor's commit operation. Thus registering the exact
older API to the host implementation of `Commit` is justified. This is static
compatibility evidence, not an executed Astral commit or an observed gameplay
failure. Private evidence retains identities and locations; no game-derived
code, addresses, disassembly or fixtures are included here.

The SDK accessor also manages guest open-file/cache state and has a writable-open
handle rejection path after its internal flush handling. The host runtime owns
its own `FILE*` handles instead of those SDK objects. The requested HLE contract
explicitly flushes writable host handles; it does **not** reproduce the SDK's
open-file rejection/abort policy, guest data-cache machinery, transaction system
or complete result taxonomy. Wrapper equivalence must not be interpreted as full
SDK behavioral equivalence.

The existing HLE registered only `Commit` with an unconditional success body.
`MountSaveData` maps all save names to the existing `user/save` root, without UID
separation. This overlay preserves that layout; it does not invent title-specific
save policy. ROM/cache root selection and default path resolution are preserved.

## Supported host behavior

Both exact registrations validate a bare mount name and look up its current
mount instance. Supported names contain 1–15 ASCII letters, digits, underscores
or hyphens. This is a conservative HLE subset, not the full SDK name grammar
(the SDK rejects some single-letter names and accepts additional characters).
`MountSaveData` rejects duplicate/invalid names and host directory errors. It
canonicalizes the save root under the configured data root. Save path resolution
rejects parent traversal, embedded backslashes/colons and canonical symlink
escapes. This protects the changed save path for a stable local filesystem;
concurrent hostile host symlink replacement is outside this path-based HLE's
contract. Other mounts retain their prior resolver behavior.

Under `g_fs`, commit flushes each writable host stream belonging to that mount
instance, checks `fflush` and the stream error flag, then checks `fsync` on POSIX
(or `_commit` on Windows). POSIX interrupted sync is retried. Every applicable
stream is attempted even after an earlier failure. Read-only streams and other
mounts are excluded. Existing `WriteFile` immediate flushing remains in place,
but seek, short-write and flush failures now return failure and latch the mount
error. `FlushFile` reports invalid handles and host flush errors. Detected errors
remain sticky until unmount, including after the failing handle closes; clearing
a stdio error flag alone cannot turn a lost write into successful commit.

Each file retains the mount instance it opened against. A weak live-file registry
also covers a handle erased by `CloseFile` while an operation still owns its
shared file. Commit, writes, table changes and file-position operations use the
existing lock; reads retain shared ownership and the existing positional-read
boundary. A remount with the same spelling has a new identity. The old file cannot
be accidentally committed or poison the new mount. This does not cancel an
already acquired operation; a write that acquires the lock after commit is a
later operation and needs its own commit.

## Result policy and persistence limits

No new result values are invented. Invalid/unknown mounts and missing handles
reuse existing `kTargetNotFound` (`0x2EE202`); detected host failures reuse the
runtime's existing `kPathNotFound` (`0x202`) host-error convention. These are
**approximate HLE mappings**, not verified SDK equivalents for invalid names,
permission errors, bad descriptors, short writes or failed sync. The scoped
NOTICE documents source provenance; the public references' generic error mapping
is not asserted to prove Nintendo result meanings.

Successful commit means that, at its lock boundary, tracked writable streams for
the requested mount have no detected sticky errors, their stdio buffers reached
the host, and their live file descriptors passed the host sync operation. The
synthetic test proves terminate/reopen persistence without close/destructors.
It does not establish multi-file atomicity, journal rollback, filesystem or device
power-loss durability, directory-entry syncing, recovery after a torn write,
close-before-commit descriptor syncing, UID separation, quota handling or all
pre-existing metadata/resize error behavior. Files already closed have the
existing close/host-cache behavior. No commit transaction or title policy is
copied from Zelda/Pokemon. Actual game save/reload remains untested.

## Verification

Run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_fs_commit.py -v
git diff --check main HEAD
```

The test composes the pinned public runtime with the existing Apple/bootstrap,
control-import, audio, notification and APM overlays before this overlay. Its FS
base matches the stable native FS source inspected read-only. The entire patched
production FS translation unit is compiled once as C++20; controlled glue supplies
CPU register storage, the registration table, logging and actual POSIX host
platform boundaries only. File and mount handlers are production code, invoked
through their exact registered names. No complete native build or game launch
occurs. A clean pinned checkout is required (`FS_COMMIT_REFERENCE` overrides local
discovery); missing source/compiler fails rather than silently skips.

Eight unittest groups cover both commit registrations with actual
mount/create/open/write/commit, immediate `_Exit`, fresh-process reopen/read;
buffered stream flush observed from host file size; invalid/unknown mounts and
handles; traversal and symlink escapes; ROM/cache isolation; real broken host
file descriptors causing flush, sync and write failures with error retention
after close; closed-but-owned files, unmount/remount generations and read-only
exclusion; and concurrent write/commit/close. Fault setup closes/restores a real
host descriptor and, for flush coverage, inserts synthetic buffered bytes into the
production-owned stream. It does not stub an I/O result or replace a handler.
Private receipts record source/patch/binary hashes and every process outcome.
The producer observed all eight groups / thirteen subprocess cases passing, with
no failures or skipped cases in the final focused run.

Acceptance remains macOS **partial**, Linux **partial**, iPhone simulator
**partial**, iPad simulator **partial**, Windows **blocked**. These focused macOS
host tests add no native integration, actual gameplay/frame/audio, simulator or
physical-device acceptance. Linux/Windows execution and the `_commit` branch are
unverified here. Independent Astra/medium exact-head patch/result review is
required before landing; no review waiver is granted by this producer.
