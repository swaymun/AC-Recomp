# Astral NVN "could not untile": cube-map storage size

`runtime/patches/astral-nvn-cube-storage.patch` fixes the two `could not
untile` upload failures of the native runs. The change is under
`NX_ASTRAL_STRICT`, touches only `runtime/src/nvn/nvn_texture_layout.cpp`,
and applies after `astral-nvn-bc-zero-fill.patch`. The default profile
preprocesses to the same source as before.

## Symptom

    nvn/vk: texture 64x64 format 0x50: could not untile (8192 bytes)
    nvn/vk: texture 256x256 format 0x29: could not untile (704512 bytes)

`deswizzle_texture` returned no levels, so `upload_texture` returned
without uploading, and the image kept whatever the fallback clear gave it.

## Diagnosis

Both textures are cube maps: NVN target 8, builder depth 1. The trace's
texture lines give these parameters:

| | 64x64 | 256x256 |
|---|---|---|
| NVN format | 0x50 BC6H UFLOAT (4x4, 16 bytes) | 0x29 RGBA16F (8 bytes) |
| levels | 7 | 9 |
| block height (GOBs) | 2 (packaged) | 16 (packaged) |
| `storage_size` | 0x2000 = 8,192 | 0xac000 = 704,512 |

The check that fails is the size check in `nvn_tiling.cpp`
`deswizzle_texture`: `t.tiled_size > tiled_size`.

`nvn_image.cpp` makes a cube map an image of 6 layers, so `upload_texture`
asks for 6 layers. `block_linear_layout` then needs
`(layers - 1) * tiled_layer_stride + chain`:

- **64x64 BC6H.** Level 0 is 16x16 blocks: 256-byte rows (4 GOBs) and 2 GOB
  rows, one block at height 2, so 4,096 bytes. Level 1 is 8x8 blocks at
  height 1, 1,024 bytes. Levels 2 to 6 are 512 bytes each. The chain is
  7,680 bytes; aligned to a level-0 block (1,024) the face stride is 8,192.
  The texture needs 5 × 8,192 + 7,680 = **48,640** bytes; `storage_size`
  is **8,192**.
- **256x256 RGBA16F.** The levels are 524,288 + 131,072 + 32,768 + 8,192 +
  2,048 + 4 × 512 bytes, so the chain is 700,416. Aligned to 8,192, the
  face stride is 704,512. The texture needs 5 × 704,512 + 700,416 =
  **4,222,976** bytes; `storage_size` is **704,512**.

The untiling and the per-face stride are right. The size is wrong:
`storage_size` comes from the runtime's own `texture_storage_size`
(`nvn_texture_layout.cpp`, also the HLE of
`nvnTextureBuilderGetStorageSize`). That function computes one mip chain
and multiplies it by the builder's depth. A cube map has 6 faces even when
the builder's depth is 1, so the size is exactly one face. The runtime's
comment "cube maps keep their layer count in the builder's depth" holds
for Wonder but not for Astral.

The guest's own placement agrees. Consecutive 64x64 BC6H cube maps in the
trace sit 0xc000 = 6 × 8,192 bytes apart in pool memory, which is six of the
computed face strides. So the packaged data holds six faces at exactly this
stride. Other limits were checked and do not apply: there is no compressed
or sparse tail (Maxwell block linear only reduces the block height per
level, and the computed sizes match the observed spacing), and the block
heights match: the packaged value (2 and 16) is the default the size
computation uses.

## Fix

Under strict, a target-8 texture is sized with 6 layers. A builder depth of
6 gives the same size, and any other depth is fatal: it is not a cube map,
so the size would be a guess. Cube map arrays (target 9) and every other
target keep the builder's depth. Sizes become 49,152 and 4,227,072 bytes
(6 face strides).

The guest also reads this size through `nvnTextureBuilderGetStorageSize`.
Cube maps it lays out itself, such as render-target cubes, now get 6 faces
of pool memory instead of one, as a real driver would return. Before the
fix, the next allocation could overlap faces 1 to 5.

## Test

`tests/test_nvn_cube_storage.py` compiles the production
`nvn_texture_layout.cpp` and `nvn_tiling.cpp` with a synthetic format
table. A block-linear tiler written in the test, independent of
`nvn_tiling.cpp`, tiles patterned data for both trace cube maps and an
odd-sized BC1-like one. `deswizzle_texture` must accept the patched size
and return every byte of every level and face. One face's size must still
be refused. Before the overlay, and in the default profile, the test checks
the old one-face sizes and the failure. It also checks that depth 6 gives
the same size, that depth 3 is fatal, that 2D, 2D-array and cube-array
sizes are unchanged, and that the default profile preprocesses identically.

## Open risk

The count of 6 faces rests on the NVN cube-map definition and the pool
spacing observed for the BC6H cube maps. It has not been checked against
the real SDK driver's `GetStorageSize` for a cube map. The private SDK
layout evidence of `test_nvn_texture_layout.py` has no cube-map case.
