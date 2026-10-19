# Astral NVN block-compressed zero fill

`runtime/patches/astral-nvn-bc-zero-fill.patch` packages the reviewed fix of
unit 121 plus its review findings. Every change is under `NX_ASTRAL_STRICT`;
the default profile preprocesses to the same source as before. It changes
only `runtime/src/nvn/nvn_upload.cpp`, `nvn_pipeline.cpp` and
`nvn_pipeline.h`, and applies after the native Astral overlay order and
`astral-nvn-window-depth.patch`.

## What was wrong

The runtime clears images it has no data for: `clear_image` (an upload that
would read past what was staged, a pitch-linear BC texture, a render target
never uploaded) and `ensure_contents`' "never written: black" clear. Both use
`vkCmdClearColorImage`. Metal cannot clear a block-compressed image, and
MoltenVK reports that as `VK_ERROR_FEATURE_NOT_PRESENT` for the whole submit,
so every command in it is lost, compute results included. In every native
run this happened about 6 to 8 seconds after boot.

## The fix

`zero_fill_compressed` fills the range of a BC1 to BC7 image with
`vkCmdCopyBufferToImage` from an all-zero upload instead, one tightly packed
region per level covering the requested layers. It returns false for every
other format, which keeps its clear. `bc_zero_fill_regions` is the region
plan alone, so it can be tested on the CPU.

All-zero blocks decode to black. Alpha is 0 in BC2, BC3 and BC7 (mode byte 0
is BC7's reserved mode, which decodes to all zero). Alpha is 1 in BC1, where
equal endpoints select the 3-colour mode and index 0 is opaque black, and in
the formats without alpha (BC4, BC5, BC6H). `vkCmdClearColorImage` with zero
would have given alpha 0 for BC1 RGBA. These images have no defined
content (never written, or their upload was refused), so either is black
standing in for missing data.

## Review findings folded in

- **3D images (medium).** `nvn_image.cpp` gives a 3D image one layer and
  `depth` slices. Each level now copies `max(1, depth >> level)` slices and
  counts them in the size; the reviewed version copied one slice.
- **Large fills (low).** A fill of 1 MB or more gets a staging buffer of its
  own on the same terms as a large texture upload (`staging_wanted`,
  `NX_STAGING_RING=1` keeps the ring), so a scene load's fills cannot wrap
  the ring over the uploads of the same submit.
- **Decoded colour (low).** The comment now says what each format decodes
  to (above), not "zero in every BC format".
- **Magenta (low).** `clear_image(..., magenta)` cannot write the magenta
  debug colour into BC blocks. The first such skip is logged.

## Test

`tests/test_nvn_bc_zero_fill.py` stacks the overlays on a fresh copy of the
pinned runtime and compiles the whole production `nvn_upload.cpp` with
synthetic Vulkan and upload adapters that record calls. It checks:

- before the overlay, the strict stack clears a BC image with
  `vkCmdClearColorImage`;
- region offsets, sizes and extents for 2D chains down to 1x1, arrays, 3D
  (depth halved per level), odd sizes and sub-ranges, with BC1's 8-byte and
  BC7's 16-byte blocks;
- no regions and no fill for RGBA8, ASTC, ETC2 and depth formats;
- `clear_image` on BC: copies from zeroed ring bytes, no colour clear, the
  magenta skip logged once; other colour and depth images clear as before;
- staging for a 4 MB fill with synchronous submits and with a quarter of the
  ring used, the ring otherwise, and with `NX_STAGING_RING=1`;
- the `ensure_contents` guard in `nvn_pipeline.cpp`;
- both profiles' syntax, and that the default profile preprocesses
  identically.

No game, GPU or device is used. The scratch copy is removed only when every
assertion passes.
