# Local owned-dump import

`tools/import_owned_dump.py` is a standard-library wrapper around Wonder revision
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. It builds the standalone CLI with
`clang++ -std=c++17 -O2` after checking HEAD and comparing all five importer source
and header files with that commit. It does not install dependencies, transfer
files, lift code, or claim gameplay.

Run only with owner-authorized local inputs. Key arguments are **file paths**;
Python checks their file metadata but never reads, hashes, copies, or logs their
contents. The importer opens the files locally. Every child process has stdout
and stderr discarded, including compilation and verification. Wrapper errors use
fixed codes. This intentionally trades detailed upstream diagnostics for a
strict logging boundary. Never add raw diagnostics or exception text to logs.

## Fresh import and resume

Use absolute paths, with the repository that owns private storage supplied by
`--repo` when running from an orchestration worktree:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/import_owned_dump.py \
  --repo "$ROOT" --reference "$PINNED_WONDER" \
  --dump "$OWNED_NSP" --prod-keys "$PROD_KEYS_FILE" \
  --title-keys "$TITLE_KEYS_FILE" \
  --out "$ROOT/.local/game-private/astral"
```

All variables above denote paths, never key values. `--title-keys` is optional.
The pinned importer selects the unique application title from decrypted program
metadata and refuses ambiguous inputs. An optional `--expected-title` asserts an
already observed ID. `--expected-size` and `--expected-sha256` impose additional
input gates. Only NSP/PFS0 input is supported by this wrapper.

Outputs must be descendants of the selected repository's ignored
`.local/game-private/`, with no tracked descendants or symlink components.
Existing directories/files are restricted to 0700/0600; the compiled CLI is 0700
when executed. Hardlinked private files are refused. An advisory exclusive lock
prevents concurrent wrapper invocations. It cannot lock a separately launched
raw importer: stop that process or observe its completion before using this tool.

The wrapper hashes and validates the input before extraction, records its
identity in `.wrapper/input.json`, and checks content plus inode/size/mtime again
after validation. Repeat the same command after interruption. The importer uses
its source identity and journal to resume; the wrapper refuses a different dump
hash/size and never deletes partial outputs. It accepts last-write journal
revisions and requires the final index to agree. An unknown existing partial
import or unknown populated output directory is refused. Choose another private
output path or investigate the original producer; do not delete its work.

A completed import is verified and inventoried without another extraction.
Every journal/index entry is checked for safe paths, size and CRC32. Counts and
source identity must agree with the completion marker; all analysis/RomFS files
must be journaled. Upstream `--verify` runs separately. Every retained NSO is
bounded, decompressed with a bounded stdlib LZ4 decoder, matched against its flat
segments and checked against embedded SHA-256 hashes when enabled. The NPDM's
ACI0 title ID must match the selected title. Extra modules are enumerated and
require explicit loader/address planning instead of silently assuming two.

## Adopt a completed parent import

Add these arguments only to reuse an extraction that the parent already finished:

```sh
  --adopt-state "$ROOT/.local/game-run-control/real-import-state.json" \
  --adopt-tool "$ROOT/.local/game-private/tools/nximport" \
  --adopt-log "$ROOT/.local/game-run-control/real-import.log"
```

The state must report completion/zero exit, the exact revision/output and the
matching tool SHA-256. The parent log must report successful completion. The
source title and program-NCA name/length must match the NSP's PFS0 table and the
NPDM. Only a fixed `rtld observed` flag and parent receipt hashes are retained
from diagnostics. Adoption is saved durably for subsequent verification runs.

The parent did not hash the source before its original extraction. Adoption
therefore corroborates filename, NCA size, title and journal CRCs, then binds the
current source hash. It cannot retrospectively prove byte identity at the time
of extraction. The private manifest states this limit explicitly.

## Private deliverables and limits

The wrapper prints only its completion status, manifest path and manifest hash.
Everything derived from the dump remains under private ignored storage:

- `.import/`: original source identity, CRC index/journal and completion marker.
- `exefs/`: raw retained NSOs; `analysis/`: flat modules and `main.npdm`.
- `extract/romfs/`: extracted files, unchanged by the wrapper.
- `.wrapper/manifest.json`: dump hash/size, importer provenance, actual title,
  NPDM fields/hash, each module's raw/flat hashes, 32-byte build ID, segment
  metadata and imported symbols, plus RomFS top-level extension/count/byte totals.
- `.wrapper/progress.jsonl`: durable phase/elapsed/exit/error records with periodic
  child and CRC progress. No raw child output or key contents.
- `.wrapper/adoption.json`: parent provenance when adopting an existing import.

`version: null` means unavailable. This pin does not extract CNMT/control
metadata; base-only does not establish a numeric or display version. The importer
unconditionally skips an NSO called `rtld` before retaining raw ExeFS, so its
build ID, segments and imports remain unavailable. Parent log observation is
separate from that source-level limitation. MOD0/dynamic metadata that cannot
provide a bounded symbol count is recorded as an explicit imports-unavailable
reason; malformed present metadata is rejected. NSO dynamic-string extents are
read at header offset `0x90`, and dynamic-symbol extents at `0x98` (size at
`0x9c`). Present extents must fit the ro segment and agree with dynamic-table
addresses/sizes; symbol sizes must be multiples of 24. A SysV `DT_HASH` count is
used only when the NSO symbol extent is completely absent. A malformed or
conflicting extent cannot fall back to the hash or an unavailable result; when
both counts exist they must agree. Partial dynamic symbol metadata is rejected.

The manifest contains exact argument arrays and working directories for a local
source clone in a task-owned sibling workspace, venv preparation and module-specific `python -m recomp` commands. For the observed
main/sdk layout it checks 256 MiB spacing, uses reference bases `0x4000000000` and
`0x4010000000`, and writes generated code under the private sibling workspace. Keep the source
clone, venv and generated products outside the extraction tree so verification
can continue enforcing its no-symlink/single-link boundary. Run the handoff
commands with `umask 077`; never apply patches to another worker checkout. These are
handoff commands, not executed work. Adapter commands use `git apply --check`
then `git apply` on `runtime/patches/astral-bootstrap.patch`, explicitly gated on
that patch existing and passing independent review. The adapter needs the
manifest title, NPDM system-resource size and exact `extract/romfs` path. No
working Astral runtime target is implied. Additional modules block this layout.

Unresolved inputs include exact CNMT/display version, omitted rtld bytes,
strict service/import failure behavior, and shader container decoding. Extension
counts identify investigation candidates, not shader support or graphics proof.
Keep manifests, symbols, hashes tied to inputs, assets, binaries, generated code,
and logs out of Git. The wrapper, synthetic tests and this document are safe
original tooling only.

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_import_manifest.py' -v
```

Fixtures use temporary Git repositories and a mock local importer subprocess.
They exercise path/tracking/link boundaries, malformed containers/journals/NSOs,
identity/title/segment mismatches, source-pin drift, discarded child output,
fresh import/reuse and changed-input refusal. They never use real credentials,
VMs, cloud APIs or paid resources. Report real-input validation separately.
