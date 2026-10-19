# Astral PKZ shader handoff — SHADER-PKZ-003

The local read-only snapshot contains **82 PKZ archives**, **7,576,710,848 bytes**,
and **8,462 directory members**. Every archive passed the bounded directory parser;
each input has a streamed SHA-256 in private evidence. Six explicitly selected
shader-bearing DAT members were decoded, totaling **9,487,888 bytes**. They contain
**1,521 wrappers**, with **1,348 distinct whole-wrapper SHA-256 values**. These
numbers describe this snapshot and selected containers, not the game's complete
shader population or semantic coverage.

One **256-byte graphics code / 2,001-byte control pair** was extracted from the
smallest observed wrapper (2,281 bytes). The exact original Wonder layout checker
reports no problems, and the landed manifest validator accepts its one-row
`manifest.tsv`. **No translation was attempted, and rendering is unverified.**
The total extracted/translated game shader denominator and overall semantic
coverage remain unknown. Cross-ISA byte match is N/A.

The final private inventory run took **8.693 seconds**, including hashing all
archives and decoding the six selected members. The initial directory/decode run
took 11.121 seconds. Both are bounded local measurements, independent of the
parent's still-unproven remote RomFS transfer. No remote checkout was changed.

## Direct source and format evidence

Dependency SHADER-TOOLS-002 landed at
`29a04b7503bcef8c2219874f6f4e4baacb133b71`. Its synthetic translation established
translator readiness only. This unit adds the first measured real container
handoff, without adding another translator.

The original [Astral Extractor PKZ reader/writer](https://github.com/cabalex/astral-extractor/blob/d4d87fe707fc4fa8f2c355df03e448906313b364/scripts/filetypes/pkz.js)
and [DAT reader/writer](https://github.com/cabalex/astral-extractor/blob/d4d87fe707fc4fa8f2c355df03e448906313b364/scripts/filetypes/dat.js)
were directly inspected at revision
`d4d87fe707fc4fa8f2c355df03e448906313b364`. The original implementation's browser
name heuristics are not reused: this original parser reads bounded directory
fields and terminated names. Source copies and SHA-256 receipts remain ignored.

PKZ's observed little-endian layout is:

| Offset | Field |
| --- | --- |
| `0x00` | `pkzl`, four bytes |
| `0x04` | observed header word `0x00010000` |
| `0x08` | uint64 archive byte length |
| `0x10` | uint32 entry count |
| `0x14` | uint32 record-table offset |
| `0x18` | uint64 name-table byte length |

Each 32-byte record contains four uint64 values: name-table-relative name offset,
uncompressed length, archive-relative payload offset, compressed length. The
name table follows the records and starts with the 16-byte padded `ZStandard`
tag. Every observed archive agrees with this header/tag, and every recorded
payload begins with standard Zstandard frame magic. Only the six selected frames
were actually decompressed; the remaining payloads have not been validated.

DAT begins with `DAT\0` and six uint32 fields: member count, offsets-table offset,
extensions-table offset, names-table offset, sizes-table offset and hash-table
offset. Names start with a uint32 fixed slot width. Member offsets and sizes are
uint32; extension slots are four bytes. Tables, names, suffix agreement and
nonempty payload extents are checked. The hash-table contents are not interpreted
or claimed to authenticate the directory.

All 1,521 selected wrappers agree with a six-word little-endian header:
magic, opaque tag, control length, control offset, code length, code offset.
The control starts after the 24-byte header, its end equals the code start,
and the code end equals the wrapper end. This is a directly measured extent
relationship; opaque tag semantics and trailing control metadata remain unknown.
Four tag values were observed; extraction rejects unobserved values.

The pinned Wonder [container parser and layout checks](https://github.com/BelmanteGu/SuperMarioWonderRecomp/blob/010ed7a596a621c15d3a8dfa5795ca8c3668b066/tools/maxwell/containers.py)
and [harness manifest loader](https://github.com/BelmanteGu/SuperMarioWonderRecomp/blob/010ed7a596a621c15d3a8dfa5795ca8c3668b066/tools/maxwell/spirv_harness/Program.cs)
were directly inspected at `010ed7a596a621c15d3a8dfa5795ca8c3668b066`.
The outer VSO/PSO/CSO wrappers are not recognized by `open_blob`; direct bounded
invocations on two wrapper samples exit 1 with `no shader container recognised`.
However, the actual graphics code/control extents satisfy its original `Stage`
checks: graphics code magic, control magic, SPH stage, code size, program start,
constant-data alignment and zero padding. Original checks passed for **1,451
selected graphics wrappers**. This is structural compatibility, not translation.

The original [executable scanner](https://github.com/BelmanteGu/SuperMarioWonderRecomp/blob/010ed7a596a621c15d3a8dfa5795ca8c3668b066/tools/maxwell/exefs_shaders.py)
also matched five bounded graphics samples, but its fixed `0x880` control-copy
size would overlap code in these wrappers. It was not used for extraction.
The new adapter uses the actual checked wrapper extents and emits only one
explicitly selected graphics pair. It does not invent code headers or scan for
shader offsets. The 70 selected compute wrappers fail Wonder's expected compute
code-header check, so compute pair extraction is explicitly rejected.

## Measured denominators

| PKZ member suffix | Count |
| --- | ---: |
| `.dat` | 3,856 |
| `.dtt` | 2,923 |
| `.eff` | 1,028 |
| `.evn` | 227 |
| `.wta` | 129 |
| `.wtp` | 129 |
| `.bin` | 90 |
| `.epb` | 52 |
| `.vat` | 16 |
| `.bxm` | 5 |
| `.vfd` | 3 |
| `.wtb` | 3 |
| `.bnvib` | 1 |
| **Total** | **8,462** |

The six DAT directory counts are **645, 544, 86, 164, 60 and 22**. Their wrappers
have matching signatures/suffixes: **612 VSO, 839 PSO, 70 CSO**. No claim is made
that other DAT/DTT/effect members contain no shaders. The smallest selected
shader-bearing DAT is **73,760 bytes**, containing 22 VSO wrappers. Its smallest
wrapper is 2,640 bytes; the globally smallest wrapper in this bounded selection
is 2,281 bytes in a different DAT. Distinct wrapper hashes do not count distinct
shader programs, variants or translated code blocks.

## Bounds and private outputs

`tools/inventory_astral_pkz.py` uses the standard library plus optional installed
`libzstd` through `ctypes`; no package install, subprocess decoder, account data or
archive-contained executable is used. The observed backend is libzstd **1.5.7**;
its resolved library hash is retained privately. Envelope parsing follows the
[Zstandard v1.5.7 format specification](https://github.com/facebook/zstd/blob/v1.5.7/doc/zstd_compression_format.md).

Defaults cap discovery at 100,000 nodes/depth 32, 128 archives, 2 GiB per archive,
12 GiB aggregate input, 16,384 entries per archive, 32,768 aggregate entries,
4 MiB name tables, 256-byte names and 1 GiB declared member lengths. Decoding
requires explicit selectors: at most eight probes, 8 MiB compressed/decoded per
probe, 16 MiB aggregate decoded data, 16 MiB frame windows and 1,024:1 expansion.
A cooperative 120-second deadline is checked during hashing, archive and probe
processing; these are not OS-level hard process deadlines.

The decoder rejects dictionaries, oversized windows, invalid reserved bits,
size disagreement, truncation, trailing data and concatenated frames. Directory
parsing rejects bad extents, overlap, malformed names, traversal and unsupported
headers/compression tags. Input symlinks and hardlinked/nonregular files are
refused; file identity/size/timestamps are checked again after each archive.
Outputs require a fresh ignored `.local/` descendant of the selected worktree,
with no symlink components, tracked output or overlap with input storage. All
payload output filenames are generated independently of archive names. Private
files use mode 0600 and new output directories mode 0700. Concurrent adversarial
renaming of ancestor directories is outside this local snapshot workflow.

Private runs are retained at `.local/pkz-inventory-001/`,
`.local/pkz-inventory-002/` and `.local/pkz-inventory-003/`. `inventory.json` records each archive hash, private
names, bounded extents, selected frame hashes, decoded member hashes and output
hashes. The final run contains `sample.code.bin`, `sample.ctrl.bin` and
`manifest.tsv`. Original source hashes, upstream rejection logs, original
layout-check counts, the one-pair cross-check and backend provenance are under
`.local/pkz-evidence/`. No game-derived payload or names inventory belongs in Git.

## Reproduce and hand off

Supply absolute input/output paths. Metadata-only inventory needs no decoder:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/inventory_astral_pkz.py \
  --repo "$PWD" --input "$ROMFS" --output "$PWD/.local/pkz-inventory-next"
```

Choose exact archive/member selectors from that private receipt. To decode a
bounded DAT and extract one observed graphics wrapper, use its private directory
index; the tool preserves the wrapper-relative code/control offsets:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/inventory_astral_pkz.py \
  --repo "$PWD" --input "$ROMFS" --output "$PWD/.local/pkz-pair-next" \
  --probe "$ARCHIVE::$MEMBER" \
  --extract-pair "$ARCHIVE::$MEMBER::$DAT_INDEX"
PYTHONDONTWRITEBYTECODE=1 python3 tools/prepare_shader_tools.py check-manifest \
  --repo "$PWD" --input "$PWD/.local/pkz-pair-next"
```

The exact tab-separated header is:

```text
id	stage	code_off	code_size	ctrl_off	ctrl_size	program_start	program_bytes	const_off	const_size	code_sha1_16	code_file	ctrl_file
```

Code/control hashes and exact private source identity are in the receipt, never
replaced by a synthetic shader. The landed manifest checker reports `stages: 1`
for the produced pair. No translator or upstream checkout was modified.

Next unit: **SHADER-ASTRAL-004**, validate and translate just this one graphics
pair with the already reviewed SHADER-TOOLS-002 batch harness. Transfer only its
manifest/code/control to a fresh private directory, verify their receipt hashes,
retain the translator status/resources and independent Vulkan 1.2 validation,
and stop on the first failure. Translation success would still leave rendering
and resource binding unverified. A separate compute-format unit should explain
the 70 observed CSO code-header differences without inserting synthetic headers.

## Verification and review gate

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_astral_pkz.py' -v
```

Seventeen synthetic-only tests exercise the production parsers, raw Zstandard
frames/native decoding, malformed size/count/offset/name/compression boundaries,
actual multi-record overlap/duplicate rejection, graphics pair checks, unknown
compute boundaries, temporary Git output confinement, link rejection, immutable
input hashes, rejection receipts and real CLI subprocess behavior. Native decode
tests explicitly skip if optional libzstd is absent; they ran on this Mac.

Independent **Astra/medium review of the exact committed head remains required
before `scripts/land`**. The lead commissions that review; this worker ran no
nested worker/reviewer, did not waive review and did not land or push a branch.
