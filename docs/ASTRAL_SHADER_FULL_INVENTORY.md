# Whole-archive Astral shader inventory — SHADER-FULL-INVENTORY-118

`tools/astral_shader_full_inventory.py` decodes **every** member of every PKZ
archive (not a selection), finds every shader wrapper, writes a harness batch,
validates the harness products against a reference data set and assembles a new
data set. No game run is needed. Game-derived bytes, names and outputs stay in
ignored private storage; nothing here is game data.

## How wrappers are found

Each decoded member is scanned for the control magic `0x98761234`. A wrapper is
accepted only when the 24 bytes before it are a six-word wrapper header
(`magic, tag, ctrl_size, ctrl_off, code_size, code_off`) with `ctrl_off == 24`,
`code_off == 24 + ctrl_size`, and these hold:

- magic is `VSO\0`, `PSO\0` or `CSO\0`;
- control `+0x704` equals the wrapper's code length (1 byte to 16 MiB);
- graphics: program start `+0x708` is `0x30`, code magic `0x12345678`, SPH stage
  matches the wrapper; compute: program start is 0 (Astral's headerless compute);
- program and constant extents fit in the code block.

Code and control are copied exactly from the extents the header declares.
No header is added and no byte is changed. The key is `sha1(code)[:16]`, the
same key the runtime computes (docs/SHADER_CACHE_HANDOFF.md). The wrapper tag
is recorded, not used as a filter, and Wonder's constant-alignment layout is
counted but not required. A control magic with no valid header in front of it
is counted as an orphan, by container type and reason. DAT directories are
parsed recursively only to say where each wrapper sits (exact DAT child or
nested inside something else); a DAT that fails to parse is still scanned.

When one code block appears with different controls, the variant seen most often
is put in `batch/` (ties are broken by control SHA-256). If variants differ in
the bytes the harness reads (`0x6f8..0x70c` and `0x748..0x758`), each other
variant goes in `variants/<n>/` so it can be translated on its own.

## Use

```sh
PY=/opt/homebrew/bin/python3   # a Python whose ctypes finds libzstd
$PY -I tools/astral_shader_full_inventory.py extract --input "$ROMFS" --out "$PRIVATE/extract" --jobs 8
dotnet astral_spirv_harness.dll --batch "$PRIVATE/extract/batch" --out "$PRIVATE/out" \
  --astral-headerless-compute --target-env vulkan1.2 --jobs 8
$PY -I tools/astral_shader_full_inventory.py validate --batch "$PRIVATE/extract/batch" \
  --out "$PRIVATE/out" --reference "$DATA_V7/spirv" --dumps "$MISS_DUMPS"
$PY -I tools/astral_shader_full_inventory.py assemble --reference "$DATA_V7" \
  --reference-receipt "$DATA_V7_RECEIPT" --out "$PRIVATE/out" --dataset "$NEW" \
  --receipt "$NEW_RECEIPT" --source ... --translator ... --validation ...
```

`batch/manifest.tsv` uses the header the harness's `LoadJobs` expects: column 10
is the key, columns 11 and 12 are the code and control files. `assemble` copies the
reference data set's symlinks and empty directories as they are, copies every
reference product and its `results.tsv` rows unchanged, and only adds new
`ok`/`ok-retry` products. It never replaces a reference product. The receipt has
the same fields as the V7 receipt.

## Measured result (2026-10-19, this Mac)

- 82 archives, 8,462 members, 14,853,397,212 decoded bytes, about 7 s with 8 processes.
- **1,521 wrappers** (612 VSO, 839 PSO, 70 CSO). All are exact DAT children of
  `.dat` members; **no wrapper or orphan control magic exists in any `.dtt`,
  `.eff` or other member**. 32 `.dat` members (and 10 nested DATs) are empty
  directories with zero entries. No unparsable wrapper.
- **1,332 distinct code blocks**: 532 vertex, 731 fragment, 69 compute.
  15 keys have more than one control; 1 (`d5472b1deab3dd75`, compute) has two
  different workgroup sizes, one occurrence each. The tie-break (control SHA-256 order) picks the variant
  the runtime was not seen using; `assemble` keeps the V7 product, but a data set built
  from the batch alone would carry the wrong workgroup size for this key.
- Harness: 1,279 `ok`, 53 `ok-retry` (50 compute, 3 fragment); 0 invalid,
  exception, timeout or `spirv-val` failure.
- All **1,288/1,288** V7 keys are present. **1,287** products are byte-identical
  with the same stage (`validate` compares the SPIR-V bytes and the stage only;
  identical bytes imply identical resources). The 1,288th is the tied compute
  conflict: the tie-break picked the other control. Its other variant, translated
  alone, is byte-identical to V7, and its control matches the runtime's dumped one.
- Against the 81 runtime miss dumps: 81/81 code identical; the harness-read
  control fields are identical for 80/81 (the exception is the conflict above).
  Dumped controls are 0x880 bytes against the wrapper's 0x850. The shared bytes are
  identical except in four dumps at `0x7d0..0x7df`, which the harness does not read.
- New data set = V7 + 44 products (31 fragment, 11 vertex `ok`; 2 compute
  `ok-retry`), 1,332 products total.

The archives hold 1,332 shader programs, and every hash the runtime has asked for
is among them. Whether the 44 new products are ever requested, and whether any
product renders correctly, is not measured here. The runtime keys a product only
by code, so the tied compute block will run with whichever control the game
supplies. The V7 product, kept unchanged, matches the control that was observed.

## Tests

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3 -m unittest tests.test_astral_shader_full_inventory -v
```

The tests use original synthetic wrappers, DAT and PKZ archives with raw Zstandard
frames. They cover exact code/control extraction for each stage, headerless compute,
rejection reasons, unknown tags, nested and orphan discovery, malformed DATs,
control conflicts and variant batches, the CLI, validation mismatch reporting and
assembly that keeps reference products. The libzstd tests are skipped when
the interpreter cannot load libzstd.
