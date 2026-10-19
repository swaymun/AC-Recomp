# Upscaling the game's picture (astral-upscale.patch)

Astral Chain renders at a fixed 1600x900. The runtime scales that picture to the window. This overlay lets the
player choose how. It is applied last in `runtime/patches/series.macos`, after `astral-touch.patch`.

| Setting | `NX_UPSCALE` | `settings.ini` `upscale =` | What reaches the window |
|---|---|---|---|
| Bilinear (default) | unset or `bilinear` | `bilinear` | the current behaviour: `vkCmdBlitImage` with a linear filter, stretched to the whole window |
| FSR 1 | `fsr` | `fsr` | AMD FidelityFX FSR 1: EASU upscales into an RGBA16F intermediate the size of the picture, then RCAS sharpens it into the swapchain image. The 16:9 aspect is kept (bars on a window of any other shape). |
| (MetalFX, not offered) | `metalfx` | `metalfx` (read as `fsr`) | not built yet: an alias for `fsr`; logs `MetalFX is not in this build; an alias for fsr` and uses FSR 1 (see the design below) |

- `NX_UPSCALE_SHARPNESS` sets RCAS sharpening in stops, from 0 (sharpest) to 2 (none). The default is 0.2, FSR 1's own
  default. Values outside that range are clamped, and one that is not a number falls back to 0.2.
- The launcher's Settings screen has an **Upscaling** row: Bilinear / FSR 1. MetalFX is not offered until it is built; an older
  `upscale = metalfx` in `settings.ini` reads as FSR 1.
  The choice is saved in `<data root>/settings.ini` as `upscale = ...` and exported as `NX_UPSCALE` when the game starts,
  unless the environment already sets `NX_UPSCALE`. A value set in the environment shows on the row as set by
  `NX_UPSCALE` and cannot be changed there. Bilinear is the default and is not exported.
- When `NX_UPSCALE` is unset, the pinned runtime's own switches still work: `NX_FSR=1` and `NX_FSR_SHARP`. When
  `NX_UPSCALE` is set, it takes precedence (`bilinear` turns FSR off even with `NX_FSR=1`), and
  `NX_UPSCALE_SHARPNESS` takes precedence over `NX_FSR_SHARP`. An unknown value (`NX_UPSCALE=lanczos`) is logged and
  treated as bilinear.

## How it works

The FSR 1 passes come from the pinned runtime (SuperMarioWonderRecomp): `runtime/src/nvn/nvn_present.cpp`, with the
SPIR-V in `nvn_fsr_spirv.inc`, built from `tools/shaders/fsr/easu.frag` and `rcas.frag`. These are a GLSL port after AMD
FidelityFX FSR 1.0 (MIT; see `runtime/patches/astral-upscale.NOTICE` and `THIRD_PARTY_NOTICES.md`). Before this overlay,
Astral could not use them: turning the present pass on (`NX_FSR=1` or `NX_PRESENT_PASS=1`) made vi
`SetLayerScalingMode(FitToLayer)` return an error, and Astral stops at boot on that error. The overlay makes three
changes:

1. `runtime/src/nvn/nvn_upscale.h` (new) reads `NX_UPSCALE` and `NX_UPSCALE_SHARPNESS`, and `nvn_present.cpp`'s
   `fsr_on()` and `fsr_sharpness()` use it.
2. `hle_vi.cpp`: FitToLayer (mode 2) succeeds whether frames go through the blit or through the present pass. On a 16:9
   window the two give the same geometry. On any other window shape the present pass adds bars where the blit would
   stretch. Every other mode still returns the error.
3. The launcher's Upscaling setting (`input_map.cpp/.h`, `launcher.cpp`).

Each pass works in the following way:

- **Resize and HiDPI.** The swapchain has the window's pixel size (SDL `HIGH_PIXEL_DENSITY`, so a 1280x720-point window
  on a Retina display is 2560x1440). Whenever the swapchain is rebuilt, the intermediate is rebuilt to match.
- **No upscale needed.** When the picture on the window is not larger than the shown part of the game's texture in
  both directions (a window at 1600x900 pixels or smaller), the plain present pass draws it with no EASU and no RCAS.
- **Crop.** `nvnWindowSetCrop` is honoured: EASU reads only the shown part of the texture.
- **Frame dumps** (`NX_DUMP_FRAMES`) still capture the game's own 1600x900 image (`gpu_present` dumps `src`). The
  upscaled swapchain image is never captured, so dumps are the same with every setting. Headless runs never upscale.
- **Cost.** About 0.13 ms per frame at 1440p on Apple silicon (upstream's measurement), one extra render pass.

The overlay changes nothing unless `NX_ASTRAL_STRICT` is defined. Without it, `nvn_present.cpp` and `hle_vi.cpp`
preprocess to exactly the pinned source, and `nvn_upscale.h` preprocesses to nothing.

## MetalFX (design, not built)

MetalFX's spatial scaler (`MTLFXSpatialScaler`, macOS 13 and later) would replace EASU on macOS. The plan:

1. Enable `VK_EXT_metal_objects` on the MoltenVK device. Export the `MTLTexture` of the game's window texture with
   `vkExportMetalObjectsEXT`, and export an output texture: either a private RGBA16F `VkImage` created with
   `VkExportMetalObjectCreateInfoEXT`, or the swapchain image. The output needs `MTLTextureUsageRenderTarget`; the
   swapchain's `CAMetalDrawable` texture is not exportable in a stable way.
2. Each frame: end the Vulkan command buffer, export its `MTLCommandQueue` (`VkExportMetalCommandQueueInfoEXT`) and
   encode `MTLFXSpatialScaler` into a Metal command buffer on that same queue, between the game's submit and the
   present. A shared `MTLSharedEvent`, exported as a Vulkan semaphore, orders the work. Then draw the scaler's output
   into the swapchain image with the existing RCAS pass (or a plain copy), so letterboxing and the HUD stay as they are.
3. Fall back to FSR 1 when the extension, the device (`supportsDevice:`) or the export is unavailable.

It needs an Objective-C++ translation unit linked against MetalFX.framework, plus a native check on hardware. That is
why this version ships FSR 1 only.

## Tests

`tests/test_astral_upscale.py` (CPU only, no game or GPU):

- `spirv-val --target-env vulkan1.0` passes for EASU, RCAS and the present vertex and fragment shaders.
- `nvn_present.cpp` is compiled with fake Vulkan functions, and the recorded passes are checked under each environment:
  EASU into RGBA16F at the picture size, then RCAS into the swapchain. The checks cover letterboxing, a HiDPI
  drawable, the crop, no upscale at or below 1600x900, resize, the sharpness, `NX_FSR` compatibility, the MetalFX
  fallback, and bilinear or an unset `NX_UPSCALE` (no pass: the blit).
- `settings.ini` round-trips, and `NX_UPSCALE` is exported only when the environment did not set it.
- The VI FitToLayer change is checked, with strict (Mac profile) and default syntax checks.
- The default profile is unchanged, and `windows-native.patch` still applies on top.

A native check on the 3024x1964 MacBook Pro, run once for each setting, about 16 s each, with a 1280x720-point window
(2560x1440 pixels): with `NX_UPSCALE=fsr` the log shows
`vi: FitToLayer uses the host present pass (aspect kept)`,
`swapchain 2560x1440 ... drawn by the present pass` and `FSR 1: 1600x900 -> 2560x1440 (sharpness 0.20 stops)`. With
`NX_UPSCALE` unset, the log shows the blit as before.
