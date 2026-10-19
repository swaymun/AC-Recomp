# Astral texel-write coalescing

`runtime/patches/astral-texel-coalesce.patch` is the last overlay in `runtime/patches/series.macos` (after
`astral-save-profiles.patch`); `series.linux` lists it before `astral-linux.patch`.

`nvnTextureWriteTexels` copies the texels into a queue on the texture (`Texture::writes`). The queue is applied to the
GPU image only when the texture is next sampled (`apply_texel_writes`). Astral's title movie writes its YUV planes
(one 1600x900 and two 800x450 R8 textures, triple-buffered) every frame. On Linux (RunPod A40) the queue grew by
about 1 GB every 30 s on the title menu, found with heaptrack (`write_texels`), until the 8 GB memory guard stopped
the game after about 3.5 minutes. The iOS simulator showed the same growth on the same menu. The macOS desktop build
stayed at 2.0 to 2.4 GB.

Before a write is queued, `drop_covered_writes()` removes the pending writes of that texture that it covers
completely: same mip level and a box (x, y, z, width, height, depth) contained in the new one. Those writes would
be overwritten as soon as the queue was applied, so the image ends up with the same contents. Partial overlaps, other
levels and anything larger stay queued in their original order. A texture that is written every frame now keeps one
pending write. On Linux, resident memory stayed at 1.48 to 1.54 GB over a 10-minute run.

The change is inside `NX_ASTRAL_STRICT`. Without it `nvn_objects.cpp` preprocesses to the original source.
`tests/test_astral_texel_coalesce.py` compiles `drop_covered_writes()` from the patch bytes and checks the cases
above. It also checks that the overlay applies after the series and that the default profile is unchanged.
