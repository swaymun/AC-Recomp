# Astral NVN window crop and depth mode

`runtime/patches/astral-nvn-window-depth.patch` packages two reviewed runtime
fixes (units 099 and 106 v2) plus two review hardening items. Every change is
under `NX_ASTRAL_STRICT`; the default profile preprocesses to the same source
as before. It changes only `runtime/src/nvn/nvn.h`, `nvn_queue.cpp` and
`nvn_pipeline.cpp`.

## What was wrong

**Window crop.** The pinned runtime implements `nvnWindowSetCrop` but not
`nvnWindowGetCrop`. The proc fell through to the generic trace stub, which
returns without writing the caller's `NVNrectangle`. Astral reads that
rectangle every frame to size its screen targets and viewports, so it built
zero or garbage viewports and presented black frames. The overlay registers
`nvnWindowGetCrop`. Before any `SetCrop` it returns `{0, 0, width, height}` of
the window's first texture. After `SetCrop` it returns the game's own
rectangle (`Window::guest_crop`), not the `NX_ULTRAWIDE`-widened one, which
stays in `Window::crop` for presentation. An unknown window, or a window with
no known first texture before any `SetCrop`, is fatal. A null output pointer
writes nothing.

**Depth mode.** Astral calls `nvnDeviceSetDepthMode(1)`
(`NEAR_IS_ZERO`: clip z already in 0..w). The runtime ignored the call and
always attached `VK_EXT_depth_clip_control` with `negativeOneToOne`, the
mode-0 (`NEAR_IS_MINUS_W`, Wonder) convention. The overlay stores the mode,
returns it from `nvnDeviceGetDepthMode`, and attaches clip control only for
mode 0. Any mode other than 0 or 1 is fatal. The 32-bit enum argument is
read from the low word of `x1`. One device is assumed, so the mode is global.

## Hardening added after review

- **`NX_CLIP_Z_PATCH=1` with mode 1 is fatal.** `depth_remap` rewrites vertex
  z from -w..w to 0..w. Applied to output that is already 0..w, it would
  compress depth into the far half. Skipping the rewrite silently would
  ignore an explicit opt-in workaround. Strict therefore fails at the
  `SetDepthMode(1)` call. `depth_remap` is a process constant and the mode
  can only become 1 there, so this is the earliest complete check.
- **A depth-mode change after any pipeline is fatal.** `pipeline_depth_mode()`
  reads the mode and freezes it under the same lock as `SetDepthMode`.
  `graphics_pipeline` calls it on a cache miss before building any shader
  module (which is where `NX_CLIP_Z_PATCH` acts), and `compute_pipeline`
  calls it before creating one. Pipelines are not rebuilt for a new mode, so
  a later change is refused instead of being half applied. A second change
  before any pipeline is also fatal, as in reviewed v2. Setting the current
  mode again is not a change.

## Evidence summary

The private evidence covers unit 098's diagnosis, 099's crop fix and 106's
depth-mode fix. It stays outside Git. Each run was a 40-second guest session
on the Mac native build.

- Before 099: 60,917 draws completed with no program, vertex-shader,
  pipeline or index rejections and zero missing shaders. Only 1 of 1,028
  captured frames was non-black.
- 099 (crop): 390 of 430 frames were non-black, from 23,964 completed draws.
  That run's runner control did not pass: the process inventory timed out,
  so cleanup was not verified.
- 106 (crop plus depth mode, second run): 1,125 of 1,162 frames were
  non-black, from 297,822 completed draws. Zero shaders were missing and the
  runner control passed. Paired before/after review captures stay private.

"Non-black" is a pixel measure. It does not confirm a correct frame or
gameplay. The two hardening items above were added after these runs and have
CPU tests only. They have not had a game run.

## Regression

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_nvn_window_depth.py' -v
```

`tests/test_nvn_window_depth.py` prepares the pinned runtime with the native
overlay order (the cumulative stack through `astral-nvn-init`, then
`astral-nvn-texture`, `astral-nvn-program`, `astral-fiber`, `astral-hwopus`,
`astral-prepo`, `astral-fs-commit`), then runs `git apply --check` and applies
this overlay. It asserts that exactly the three files change. It compiles the
production window/depth region of `nvn_queue.cpp` and the clip-control
decision of `nvn_pipeline.cpp` verbatim, using synthetic object, texture and
ultrawide adapters, and covers:

- **Before:** no HLE for these procs.
- **Strict:** the first-texture default, the unwidened guest rectangle, fatal
  unknown window or texture, depth mode stored and returned, fatal unknown
  mode, clip control per mode, fatal change after a pipeline, fatal second
  change, and the fatal `NX_CLIP_Z_PATCH` conflict.
- **Default:** no new procs and `SetCrop` unchanged.

It also checks that both pipeline constructors freeze the mode before
`module_of`. Both full changed TUs get syntax checks in both profiles, and the
default-profile preprocessed output must equal the unpatched one (registrar
`__LINE__` names normalised). This is CPU evidence only: no GPU, Vulkan
device or game.

## Accepted risks

- The native order above is the test's canonical stack. No tool applies it
  yet; the native build tree is prepared by hand. That live tree also carries
  further unlanded NVN changes, and this overlay's context against those is
  not verified here.
- Only one device is assumed. A second device with a different mode would be
  refused once pipelines exist, or merged before then.
- The guest's `NVNrectangle` layout (four `int32`: x, y, width, height) and the
  first-texture default come from reviewed behaviour, not from an SDK header.
- The hardened form has no game run yet (see above).

The underlying runtime is MIT-licensed SuperMarioWonderRecomp at
`010ed7a596a621c15d3a8dfa5795ca8c3668b066`. The overlay and fixtures are
original.

## Offline shader harness

`tools/astral_spirv_harness/` holds the opt-in `--astral-headerless-compute`
patch for Wonder's offline Maxwell to SPIR-V harness, together with its build
project. See its [README](../tools/astral_spirv_harness/README.md) for build,
regression evidence and accepted risks. `tests/test_astral_spirv_harness.py`
checks that the patch applies to the pinned `Program.cs` and that the flag is
opt-in.
