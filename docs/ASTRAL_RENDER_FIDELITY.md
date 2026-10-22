# Character material fidelity (RENDER-009)

`runtime/patches/astral-render-fix.patch` corrects the packaged texture layout
getter under `NX_ASTRAL_STRICT`. It supplies the getter's output argument and
uses the encoded block height for upload untiling. Shader translation, format
selection, sampler state and guest-visible storage sizes are unchanged.

## Root cause

In the pinned runtime's `runtime/src/nvn/nvn_objects.cpp:308-323`,
`TextureInitialize` calls `nvnTextureBuilderGetPackagedTextureLayout(builder)`
and interprets the return as a layout. The actual getter returns a presence
flag and writes a layout word through its **second argument**. The private
SDK getter and setter were inspected read-only to establish that contract;
their disassembly stays private. The old call also leaves the caller's second
argument live: `guest_call` only replaces explicitly supplied registers, so
the getter can write into the builder instead of scratch memory.

The runtime then discards the layout and estimates the block height from the
image height using a fit derived from Wonder textures. Astral's texture files
explicitly select a different height. For example, a 4096 by 4096 ASTC 8x8
atlas has layout `0x403`: its Y field is 3, meaning **8 GOBs**. The estimate
chooses **16 GOBs**. This permutes rectangular regions of the colour and
material maps before Vulkan sees them. The data remains valid compressed
blocks, so format validation and shader validation cannot detect the error.
The smaller mips can also have different offsets.

The fix passes four bytes of thread-local guest scratch as the second
argument, keeps presence separate from the output word, and reads the low
nibble as a log2 height. Values 0 through 5 give 1 through 32 GOBs; larger
values fail explicitly. A present layout whose output is zero still means
one GOB. An absent packaged layout keeps the existing default-layout path.
The default, non-Astral profile retains its previous code.

The untiler itself does not change. Its GOB geometry agrees with the
[independent Tegra tiling description](https://github.com/ScanMountGoat/tegra_swizzle#memory-tiling).
No code from that project is copied into this change.

## Code-first investigation

These hypotheses were ranked and checked before the new game runs. Line
numbers below refer to the private diagnostic source prepared from the pin
and existing overlays; the corresponding source names are upstream paths.

| Rank | Candidate and code | Evidence |
| --- | --- | --- |
| 1 | Packaged layout discarded, `nvn_objects.cpp:308-325`; untiler input at `nvn_upload.cpp:286` | Wrong getter ABI; 9 of 27 inspected body texture records disagree with the estimate. Offline atlas regions are scrambled at 16 GOBs and coherent at the encoded 8. |
| 2 | Format, normal-map binding, swizzle or mip sampling; `nvn_format.cpp:41-89`, `nvn_sampler_objects.cpp:22-38`, `nvn_pipeline.cpp:639-651` | Explicit BC/ASTC mappings preserve linear versus sRGB; sampler and swizzle state use SDK getters and slot views. These do not explain a permutation already present in offline atlas pixels. |
| 3 | CPU ASTC/BC decoding or MoltenVK; `nvn_astc.cpp:325`, `nvn_upload.cpp:69-98`, `nvn_bc.cpp` | The corrected 4096-square ASTC atlas matches native ImageIO decoding exactly on all RGB pixels. Mac native ASTC bypasses CPU decode; NVIDIA uses CPU ASTC decode. |
| 4 | 2D texture used in a cube slot; `nvn_pipeline.cpp:162-176`, `nvn_image.cpp:122-133` | Existing compatibility check rejects a cube view of a 2D image and supplies the dummy texture. This could affect lighting, but cannot explain the offline atlas permutation. |
| 5 | Static shader-accessor assumptions; `StaticGpuAccessor.cs:107-123` | Static 2D/RGBA8 answers remain a known limitation for queried typed/bindless resources. No shader change is justified by the evidenced texture-layout defect. |

## Offline verification

All private evidence is under `.local/units/RENDER-009/` in the main checkout,
outside the agent worktree and outside Git.

- `hypotheses-code-first.md` records the investigation before the new runs.
- `sdk-layout-disassembly.txt` records the getter/setter ABI check. No SDK
  instructions are included in this document, patch or tests.
- `texture-metadata.json` records selected original texture metadata;
  `packaged-layout-check.json` records the 9/27 mismatches.
- `atlas-bh16.ppm` and `atlas-bh8.ppm` retain the same original atlas decoded
  with the old and encoded block heights. PNG thumbnails are beside them.
- `atlas-reference.ktx`, `atlas-imageio.png`, `atlas-imageio.ppm` and
  `atlas-reference-metrics.json` retain the independent ImageIO check:
  **16,777,216 pixels, MAE 0, RMSE 0, maximum RGB channel error 0** against
  the runtime's existing decoder after correct untiling. This validates one
  observed ASTC atlas, not every compressed format or mode.
- The same check with the atlas's actual sRGB format also matches exactly:
  `atlas-runtime-srgb.ppm`, `atlas-reference-srgb.ktx`,
  `atlas-imageio-srgb.ppm`, `atlas-reference-srgb-metrics.json`.
- `route-reference/provenance.json` records read-only copies of existing Mac
  baseline captures from MAC-STUTTER-005. `09877.ppm` shows mottled armor on
  both profile-screen characters; `01197.ppm` shows the opening, and
  `11970.ppm`/`14044.ppm` show the chase. These are borrowed baseline evidence,
  not this unit's own reproduction or a paired before/after validation.
- `texture-fingerprints.json` indexes level-zero compressed bytes after old
  and corrected untiling for 980 supported compressed textures in 129 models
  from the private player archive. All corrected layouts untile successfully;
  185 have encoded height 8 versus inferred height 16. This is an offline
  corpus count, not a draw or gameplay coverage count. Some maps are constant
  and their pixels do not change despite a different block height.
- The specific chest-lettering decal is texture ID `4be056f1`, record 8 of
  the inspected body texture table: **1024x512, NVN format 0x46 (BC1 RGBA
  sRGB), 11 levels, packaged layout 0x403**. `decal-old.ktx` and
  `decal-correct.ktx` contain the same original blocks untiled at 16 and 8
  GOBs respectively. Native ImageIO-decoded PNGs beside them show split,
  duplicated letter regions in the former and coherent lettering in the
  latter. `decal-texture-metadata.json` retains the original-file association.
  This establishes the decal's layout defect independently of shader or GPU
  execution. The live draw association is recorded below.

## Regression tests and integration

Run:

```sh
python3 -m unittest discover -s tests -p 'test_astral_render_fix.py'
python3 -m unittest discover -s tests -p 'test_render_compare.py'
```

The fix test applies the patch after each complete Mac, Linux and Windows
series in temporary source copies. It compiles the production packaged-layout
region verbatim with a synthetic getter, then exercises the production
untiler with an independent byte-address tiler. It reproduces the old
16-GOB mistake, checks the second argument, present-zero and absent layouts,
unrelated layout bits, all invalid height values, 32-GOB layouts, full mip
chains, arrays and odd sizes. It syntax-checks the complete changed translation
unit in both profiles and checks default-profile region identity. Existing
local pinned sources and Vulkan headers are required; no downloads, game,
GPU, cloud credentials or VM are used in these tests.

`tools/render_compare.py` reads 8-bit binary RGB PPM captures and reports MAE,
RMSE, PSNR, maximum channel error and the fraction of changed pixels, optionally
within an explicit ROI. It rejects differing dimensions and does no automatic
alignment or resizing. `--max-mae` supplies an explicit pass/fail limit; without one, `passed` is null.
Scene, pose, exposure and capture timing must be controlled: pixel differences
alone do not certify visual correctness. Six tests cover hand-calculated
metrics, ROI stride, PPM parsing and actual CLI success/failure behavior.

The lead must append this exact line to **each** of `series.macos`,
`series.linux` and `series.windows`:

```text
astral-render-fix.patch
```

This worker does not modify series files. The patch is applied manually to
private builds. Independent exact-head review and landing belong to the lead;
the brief forbids this worker from commissioning nested reviews. Review is
pending, not waived.

## GPU verification

### Mac: reproduced and fixed on Apple M5 Pro

Fresh, separate save roots and a fixed input script produced the reported
artifacts in `runs/baseline-profile-02/data/frames/10440.ppm` and removed them
in `runs/fixed-profile-02/data/frames/10440.ppm`. Both show the same Given Name
view: the old frame has rectangular dark face patches, fractured grey armor
and broken lettering; the corrected frame has clean skin, smooth uniform
materials and coherent chest lettering. Frame `09840.ppm` in each run also
shows the improvement on **both** gender choices.

These are real Apple M5 Pro GPU runs through MoltenVK, headless and muted,
launched through the mandatory Mac game lock. Each run was bounded at 485 s;
both supervision receipts report `control_passed=true`, verified cleanup and
no remaining descendants. Each run retains its exact `NX_INPUT_SCRIPT`,
source preparation and environment in private JSON/log files.
`runs/fixed-current-03` repeats the corrected route
against the Mac patch stack at main `0ec6141`, including the independently landed audio
and shader-cache changes; its 485.31 s receipt also passes cleanup. Its frame
`10440.ppm` retains the clean face and uniform. No audio-device timing claim
is made from these headless Mac runs. Captures use the standard generated
variant; a separate 60 fps variant capture remains a lead integration check,
although both variants use this same NVN texture path.

`material-draw-evidence.json` links the live 1024x512 format-0x46 decal to
texture object `71046dd9e8`, slot t3 in draws **4648538-4648539**, VS
`db15acac51e41c47`, FS `b9f883abd94a2e6e`. Initialization logs change only the
reported layout height from 16 to 8 for this texture's geometry, allocation
and swizzle. The fragment SPIR-V has 2D and cube image types, eight sample
operations and no image reads/writes; `spirv-val --target-env vulkan1.2`
passes. Its SHA-256 and disassembly remain private. This association uses
unique decal geometry/format plus the original decoded lettering: the raw
texture-dump budget captured earlier background preloads, so a byte-hashed
**live** decal match is not claimed.

Private comparisons include `comparisons/face-profile-before-after-reference.png`
(the 18 s reference uses a different submenu), `comparisons/profile-before-after.png` and
`comparisons/gender-before-after-reference.png`; the latter is ordered before,
after, public reference. The reference was explicitly resized from 1280x720
to 1600x900 with Lanczos. Against its 12 s frame, female body ROI
`1020,270,250,410` MAE improves **32.093 to 22.022** and male body ROI
`380,265,260,415` improves **34.265 to 18.786**. Codec, exposure and idle pose
differences remain, so these numbers indicate improvement rather than exact
pixel equivalence. Raw sources and ROI records are retained in
`comparisons/reference-metrics.json` and `comparisons/comparison-manifest.json`.

### Regression observations and limits

Title, opening and chase captures were inspected. The opening research-room
materials remain coherent, while the chase rider's uniform is corrected;
no new visual failure was observed in these samples. Quantitative results
from `tools/render_compare.py` are retained privately:

| Comparison | MAE | Interpretation |
| --- | ---: | --- |
| Title frame 00360, full frame | 0.755912 | Small movie/particle timing differences; left-wall ROI MAE 0.0000889, max error 1. |
| Profile 10440, background ROI 650,400,350,350 | 0.001116 | Max error 1; zero changed pixels at tolerance 2. |
| Opening 01080, full frame | 6.218959 | Same research-room shot; character animation differs. |
| Opening 01080, static-room ROI 0,0,400,200 | 0.938217 | Camera/lighting phase is not perfectly locked. |
| Chase 13920, full frame | 30.061680 | Different moving camera/traffic phase; not a regression pass/fail oracle. |

`comparisons/mac-metrics.json`, `title-short-metrics.json` and the opening/
chase contact sheets retain the measurements and frames. The scripted route
controls inputs, not guest/movie scheduling; exact temporal alignment and a
reference-quality chase regression gate remain open. This is sampled visual
verification, not an assertion that every scene or shader is correct.

### Windows: layout defect reproduced on NVIDIA L4

The VM ran the actual Vulkan renderer on NVIDIA L4 (Vulkan 1.4), headless and
muted, with a fresh save root per run. Canonical Windows builds apply the full
36-patch Windows series to the pinned runtime; all **400** compile commands
were checked for `NX_ASTRAL_STRICT=1`, including HID. Only the render patch
differs between the valid before and after binaries. Their SHA-256 hashes are
retained in `windows-binary-metadata.json`. GPU builds use the stack prepared
at main `0ec6141`. After rebasing onto main `15fff99`, an offline source check
confirms matching corrected objects/upload/format/BC/ASTC/tiling/image/pipeline
source. Seven actual Windows files match byte-for-byte; objects differs only
in CRLF and an extra blank line in the excluded default branch from an earlier
whitespace-only patch revision. `latest-render-source-check.json` records this
comparison and the source hashes.
This does not substitute for the lead's final combined-stack hardware check.

`windows-canonical-data-check.json` confirms **10,045 of 10,045 input files**
match the Mac manifest by size and SHA-256, with zero missing or mismatched
files. The shared upload's different event archive was replaced only in this
unit's private input tree, using the owner's original archive; shared inputs
were left untouched. Build, source preparation and data verification records
are private. Earlier preparatory binaries lacking the strict profile were
rejected and supply no rendering evidence.

`windows-runs/baseline-canonical-03/data/frames/01560.ppm` reproduces the dirty
uniforms on both gender choices; `01680.ppm` shows Kaede's blotched close-up.
The baseline was stopped after its hypothesis was confirmed: **301.93 s,
exit 99, reaped=true**, with an explicit stop-reason record and executable/PID
check. The corrected `fixed-canonical-profile-05` run retains clean materials
on both choices at frame **10440**, also copied in `windows-profile-probe/`.
Its bounded receipt is **780.54 s, timed_out=true, exit 1, reaped=true**; exit
1 is the controller's intentional timeout termination, not natural gameplay
completion. The script reached the male profile after the clean gender view;
two clock-timed corrected runs selected the male. A private input-only
probe then selected Kaede after the actual gender screen was visible; its
close-up evidence is recorded below.

`comparisons/windows-gender-before-after-reference.png` is ordered before,
after, reference. The same explicit female-body ROI against the resized 12 s
reference improves from **MAE 34.647 to 22.362**. This independently demonstrates
the layout correction through NVIDIA's CPU ASTC decode/native BC path, rather
than only Mac's native ASTC path. Windows and Mac capture timing differs;
frame indices are not interchangeable. Title/opening samples are retained in
`windows-runs/fixed-canonical-03` and the comparison contact sheets. No
Windows audio-device or controller hardware acceptance is claimed here.

The last Windows close-up uses a **private input-only probe**, not a new
shipping runtime feature. A file-controlled button hook in the private
`platform_win.cpp` selected Female only after the gender screen was observed.
The incremental build recompiled only that platform file and reused all
corrected NVN renderer objects; source/hash checks and the private hook script
are retained. No shader, texture or rendering state was forced. This harness
is excluded from the committed patch and scope files.

`windows-after-profile.ppm` is frame **16080** of
`fixed-adaptive-female-07`: the same Given Name view as baseline frame 01680
has clean skin, smooth armor and coherent red lettering.
`windows-after-confirm-face-19920.ppm` confirms the clean extreme face
close-up after profile confirmation. The bounded run receipt reports
**1000.68 s, timed_out=true, exit 1, reaped=true**. The exact observed control
sequence is retained in `adaptive-presses.jsonl`; primary frame provenance is
in `windows-after-profile-provenance.json`.

Private images `comparisons/windows-profile-before-after-reference.png` and
`comparisons/windows-face-chest-before-after.png` retain the visual proof.
For the paired Given Name frames, background ROI `650,400,350,350` MAE is
**0.000966**, maximum channel error **1**, zero changed pixels at tolerance 2.
The full-frame MAE **13.4983** measures the intended material change plus idle
pose, not a fidelity threshold. The probe reached the post-profile dialogue
before its bound, but **did not capture an after-chase frame on Windows**;
that regression check was open in the original RENDER-009 report. The
RENDER-009B chase follow-up below records its disposition.

Public reference footage: [Shroom Room, female character creation](https://www.youtube.com/watch?v=lorHQChDchs),
12 s (both character choices) and 18 s (female face and upper uniform).
The downloaded excerpt and extracted frames remain private. Its public
publisher/platform provenance is not an independent hardware capture made by
this worker.

## RENDER-009B: bounded chase follow-up

This split reuses the accepted implementation from commits `543aa95`,
`fc7acce`, `70aea49`, `4e9c9b6` and `e5ce387`. No shipping runtime or comparison-tool
change was needed for the follow-up. Private evidence added by this split is
under `.local/units/RENDER-009/chase-009B/` in the main checkout.

### Mac chase evidence reused

No new Mac game was launched. The existing corrected
`runs/fixed-current-03/data/frames/13080.ppm` through `14400.ppm` show real
motorcycle gameplay, including tunnel turns, firing effects, traffic, dialogue
and the rider's uniform. These came from the corrected `astral-after-current`
binary, SHA-256
`3a071d3738019ada07180deb3d3a97691c31c13a4b62311330c3dee878afcfea`,
whose patch SHA-256 matches this branch's
`cb8f1751563a91b22a6a60a99d2546af7f55d602f1a45cdf5048b962a1c480ba`.
`current-macos-preparation.json` records the manually applied patch on the
`0ec6141` Mac stack. The original lock-wrapped headless run's receipt records
485.312584 s, `control_passed=true`, `cleanup_verified=true`, and no remaining
descendants. This is reuse of earlier physical Apple GPU execution, not an
exact-current-main combined-stack run or a new audio timing test.

`chase-009B/mac-chase-manifest.json` hashes the reused frames;
`reuse-binary-identities.json` rechecks the executable and patch hashes.
`mac-chase-before-after.png` compares the original pre-fix
`runs/baseline-profile-02` to `runs/fixed-current-03`, at frames 13320, 13440,
13920 and 14280. The same raw pairs were measured with the committed
`tools/render_compare.py`, without resizing, alignment or a pass threshold:

| Frame | Full-frame MAE | Rider ROI MAE (`650,410,210,280`) |
| --- | ---: | ---: |
| 13320 | 32.548143 | 46.180476 |
| 13440 | 12.584623 | 16.361842 |
| 13920 | 29.922066 | 23.434320 |
| 14280 | 28.403363 | 28.811899 |

`mac-metrics.json` and the individual CLI JSON files retain all results,
including the earlier corrected `fixed-profile-02` build. The smaller raw
13440 difference accompanies visually comparable tunnel-turn shots; dialogue
and the positions of the moving lane markers still differ. Even the HUD
moves by several pixels with the animation. These metrics are observations
(`passed:null`), not a numerically certified regression gate. The rider's
material regions are coherent in the corrected captures, and no new visual
failure was observed in these sampled scenes. Red fragmented credit glyphs
occur in both the pre-fix and corrected chase sequences; that pre-existing
artifact is not fixed or attributed to this texture-layout change.

### Windows capture setup

The follow-up reuses this unit's canonical corrected Windows build and private
inputs, without modifying another unit's processes or directories. A first
114.556 s attempt missed the title input while the VM was busy. A second
642.381 s attempt recorded outside XInput events and returned through the load
menus; neither attempt is chase evidence. The load route also has a second
confirmation that defaults to **No**; selecting **Yes** is required. These
routing observations do not establish a save-loading or rendering defect.

For the retained capture, the existing private input-only probe was isolated
from XInput while `NX_RENDER_INPUT_FILE` is set, and a combined ZL+ZR input was
added to that private hook. The build recompiled only `platform_win.cpp` and
relinked. All **400 non-platform object files** have identical SHA-256 hashes
before and after, including every NVN renderer object. The private executable
is `astral-render-isolated-input-probe.exe`, SHA-256
`33f5e57598eda572539814b79d60c7638890bddfdec575e295b94e3e5825e2b1`.
This is an input harness, not a shipping code change or a hardware-controller
acceptance test. `chase-009B-isolated-build-receipt.json` and
`chase-009B-render-objects-before.json` retain the build identity check.

The capture is `C:\acr\units\RENDER-009\runs\chase-009B-03`, using a copy of
`fixed-adaptive-female-07/data/user/save` and separate input/frame/log paths.
It sets `NX_HEADLESS=1`, `NX_MUTE=1`, `NX_DUMP_FRAMES=120` and the strict texture
profile, and runs below normal priority. The input script, executable hash,
source save path and process identity are in its `config.json` and
`process.json`; observed control actions are in `chase-009B-presses.jsonl`.
The isolated run's `data/input_record.txt` has no outside controller events.

### Windows chase captured on NVIDIA L4

`chase-009B/windows-run-03/data/frames/22440.ppm` through `24840.ppm`
retain **21 consecutive frame dumps**, spaced 120 presents apart. They show
motorcycle gameplay, tunnel turns, traffic, firing/explosion effects, dialogue
and tutorial controls. The female rider has coherent blue/grey material maps
and readable back lettering. The same run also repeats the clean female
profile and post-confirmation face close-up. No shader or material state was
forced. This is actual NVIDIA L4 Vulkan execution, not a unit-test result.

The controller explicitly stopped the owned game after this sample, rather
than waiting for its 1,800 s bound: **1,688.297080 s, exit 4294967295,
`timed_out=false`, `reaped=true`, 207 total dumps**. The exit is intentional
`Stop-Process`, not natural completion. `stop-reason.json` records the exact
owned PID/executable identity check and reason. `cleanup-check.json` records
zero remaining RENDER-009 game processes; three other units' games remained
running and were not stopped. The copied frame/log archive is
`chase-009B-capture.zip`; its extracted `chase-manifest.json` verifies size and
SHA-256 for all **28 payload files**. The extracted private directory includes
the original run config, process record, controller receipt and logs.

`windows-chase-indexed.png` shows every retained frame, without filtering out
bad samples. `chase-mac-before-after-windows.png` has pre-fix Mac, corrected
Mac and corrected Windows columns. Pairs were selected by visible tunnel and
credit phases; they are not time-locked. All are original 1600x900 captures.
The committed `tools/render_compare.py` measured the raw pairs without any
resizing or geometric alignment:

| Pre-fix Mac frame | Corrected Windows frame | Full-frame MAE | Rider ROI MAE (`650,410,210,280`) |
| --- | --- | ---: | ---: |
| 13440 | 23040 | 30.655260 | 29.905408 |
| 13920 | 23280 | 35.285802 | 37.414507 |
| 14160 | 23400 | 35.604474 | 49.881207 |
| 14400 | 23640 | 38.429606 | 54.153282 |

`windows-metrics.json` and individual CLI JSON files retain these comparisons
and the corresponding corrected-Mac versus corrected-Windows measurements.
These are **cross-platform** comparisons against the available pre-fix Mac
chase footage; no Windows pre-fix chase capture exists. Dialogue, camera,
particles, traffic and capture timing differ, so all reports deliberately
have `passed:null`. A numerical no-regression threshold is not claimed.

### Chase gate at the end of the first follow-up

The missing Windows chase capture is now supplied, and the character-material
correction holds in the observed chase samples on both GPUs. A completely
clean chase-regression gate is **not** established: Windows frames including
23400 and 23880 show hard-edged road/bike occlusion or geometry regions. Red
fragmented credit glyphs are also visible, as in the earlier Mac pre-fix and
corrected captures. The geometry observation cannot be attributed to this
layout patch from the available cross-platform baseline, and is retained
rather than hidden or called a passing image. No shipping code was changed
in response to an unproven attribution.

The reused Windows renderer was built on the canonical `0ec6141` stack; it
predates the later main draw/fence/alpha changes. The lead should test that
current combined stack and, if the geometry issue remains, compare a Windows
before/after chase before assigning it to the material fix. Phase-locked
quantitative chase acceptance, the combined 60 fps variant, series integration
and independent exact-head review remain separate follow-ups. This split
performed no nested review and did not waive the lead's review requirement.

## RENDER-009B round 2: Windows pre-fix chase attribution

**The road/bike occlusion artifacts predate `astral-render-fix.patch`.** The
pre-fix Windows captures at **23400 and 23880** already have hard-edged dark
foreground road regions and missing or occluded motorcycle parts. The fixed
`chase-009B-03` frames have this same class of defect. This answers the round-2
attribution question; it does not declare the chase visually correct or identify
the underlying cause of the remaining defect. No shipping renderer, shader,
test or series file was changed in this round.

### Controlled baseline build

The reused fixed executable was `astral-render-isolated-input-probe.exe`,
SHA-256 `33f5e57598eda572539814b79d60c7638890bddfdec575e295b94e3e5825e2b1`.
Reversing only `astral-render-fix.patch` in its existing private source and
rebuilding with one compiler job produced `astral-render-isolated-before.exe`,
SHA-256 `ccdf7c1cc6580ecec119349be69f3b0b11ef6efa52f29aefa4f4324621dad518`.
The rebuild took **38.510 s** and exited 0. SHA-256 checks of all **401 object
files** show that only `nvn_objects.cpp.obj` changed; the other **400** are
identical, including the isolated input hook and all other renderer objects.
The fixed source file was restored after creating the baseline executable.
This preserves the original fixed capture's `0ec6141` renderer stack rather
than mixing later main changes into one side of the comparison.

Private evidence is under `.local/units/RENDER-009/chase-009B-round2/` in the
main checkout. `extracted/chase-009B-round2/build-receipt.json`,
`objects-fixed.json`, `objects-baseline.json` and `build-baseline.log` retain
the build identities and the exact changed-object check.

### Capture protocol and termination

Before building or launching, `Get-Process astral*` identified other units'
running games. None was stopped or modified. The new baseline capture is
`C:\acr\units\RENDER-009\runs\chase-009B-baseline-05`. It uses a separate copy
of the same `fixed-adaptive-female-07` save seed, the same data junctions and
texture profile, headless/muted execution, below-normal process priority and
`NX_DUMP_FRAMES=120`. External XInput events remain disabled by the identical
private input hook. No Mac game was launched in this round; the earlier Mac
before/after chase evidence remains the explicitly identified reused evidence.

The fixed run's observed button sequence and holds were replayed at the most
recent dumped-frame number preceding each original input. A startup guard
delayed START until the initial B script had finished: START occurred at frame
720 instead of 600; all remaining **28 inputs** occurred at their target
frame numbers. This is the same route, not a frame-locked deterministic replay.
Random name, dialogue, camera, traffic and effects can differ. An earlier
133.518 s attempt stayed on the title screen after its START overlapped the
startup script; it was explicitly stopped and is not chase evidence.

The completed baseline run retained **207 dumps**, including all **21 frames
22440–24840** at 120-present intervals. The controller explicitly terminated
its own process upon reaching 24840: **1440.831 s, exit 1,
`timed_out=false`, `reaped=true`, 29 inputs sent**. Exit 1 is the deliberate
Python `Popen.kill()` termination, not a natural game exit or a crash claim.
The process inventory after completion contains no RENDER-009 game.

`baseline-capture.zip` contains the raw frames, logs, configuration, process and
termination receipts, input observations, object hashes and manifest. Its
extracted layout preserves `runs/chase-009B-baseline-05/` and
`chase-009B-round2/`. All data remains private and outside Git.

### Same-range comparisons and result

All **58 payload files** passed size and SHA-256 verification after transfer.
`tools/render_compare.py` measured all 21 same-numbered pre-fix/fixed pairs at
their original **1600x900** resolution, without resizing or alignment: full
frame, rider ROI `650,410,210,280`, foreground ROI `0,600,1600,300` and tutorial
ROI `1180,380,360,230`, for **84 comparisons**. `metrics.json` and individual
`baseline-<frame>-<region>.json` files retain every result. All reports have
`passed:null`; no numerical no-regression threshold is claimed.

| Windows before/fixed frame | Full-frame MAE | Rider MAE | Foreground MAE |
| --- | ---: | ---: | ---: |
| 23400 | 24.988703 | 45.457324 | 17.116340 |
| 23880 | 34.927884 | 58.333889 | 20.748111 |

`reported-frames-before-after-full.png` contains both reported frames in
full-size pre-fix/fixed columns. `all-21-before-after-indexed.png` retains
every requested pair as explicitly scaled preview thumbnails. Raw originals
are beside the extracted receipts and in the earlier
`chase-009B/windows-run-03/data/frames/` directory.

In pre-fix 23400, a hard horizontal foreground boundary and angular road
regions accompany an incomplete motorcycle silhouette. In pre-fix 23880,
large angular road regions and missing rear-wheel/body regions are visible
again. These occur without the material patch, on the same Windows/NVIDIA
renderer stack. Character material scrambling is additionally reproduced in
the baseline profile captures; the fixed samples retain the earlier clean
material correction. The remaining chase occlusion defect is therefore
**pre-existing**, rather than evidence that this patch introduced it.

This is actual headless NVIDIA L4 Vulkan execution. The two required unittest
commands separately validate the patch and comparison tool; unit tests do not
establish GPU fidelity. Current-main combined-stack testing, the 60 fps
variant and diagnosis of the pre-existing road/bike defect remain follow-ups.
The lead still owns series integration, independent exact-head review and
landing. No nested review was commissioned or waived in this round.

## RENDER-FID-021: Windows depth and fragment-output candidates

This follow-up targets the **pre-existing** File 01 road/bike occlusion and
dark enemy remnants documented above, independently of the packaged-layout
correction. `astral-depth-fidelity.patch` follows `astral-render-fix.patch`.
The implementation is original code informed by the MIT-licensed
[Puddz/AstralChain-PC comparison revision](https://github.com/Puddz/AstralChain-PC/tree/d627f49d2fc3469d38cd329aa08eb0de8b9eed83):
`astral_chain/runtime/las/nvn/vulkan/exec.c:3289–3293,3330–3338` and
`third_party/LASRecomp/runtime/nvn/maxwell/translate.c:1758–1766,1840–1843`.
No Puddz executable or script was run and no game-version offsets were copied.

WIN-REPLAY-024 integrates the patch immediately after `astral-render-fix.patch`
in all three platform series. Only `NX_ASTRAL_STRICT && _WIN32` defaults to exact
EQUAL with zero synthetic EQUAL slack. The fragment-mask, half-expansion and
precise-vertex candidates default off and require their individual switch set
to `1`; their separate visual contributions remain unverified. Metal, Linux
and other profiles retain their previous rendering policy.

| Candidate / switch | Behavior and disable path |
| --- | --- |
| Exact depth, `NX_EXACT_EQUAL` | Keep guest EQUAL instead of replacing no-write EQUAL with LEQUAL; remove its synthetic units/slope slack. Guest polygon offset and other compare functions remain in effect. `NX_EXACT_EQUAL=0` restores the previous relaxation and slack; `NX_EQUAL_SLACK=0` independently removes only the old slack. |
| Fragment attachments, `NX_FRAG_OUTPUT_MASK=1` (opt-in, unverified) | Use the existing SPIR-V reflection's fragment output locations, including arrays, to intersect guest channel masks. No fragment stage means no color writes. Canonical effective masks enter the pipeline key **before** either cache lookup. `NX_FRAG_OUTPUT_MASK=0` restores guest masks without the intersection. |
| Half precision, `NX_HALF_BITS=1` (opt-in, unverified) | Expand vertex `GLSL.std.450 UnpackHalf2x16` into binary16-to-binary32 bit operations, with exact subnormal conversion and preserved signs, infinities and NaN payloads. This removes the half-unpack operation whose NVIDIA precision provenance Puddz identifies. `NX_HALF_BITS=0` restores the original modules. |
| Vertex arithmetic, `NX_VERTEX_PRECISE=1` (opt-in, unverified) | Add missing NoContraction decorations to separate vertex float arithmetic, matching the intent of Puddz's precise Position. Explicit fused instructions and existing decorations are preserved. `NX_VERTEX_PRECISE=0` restores the original contraction policy. |

Options are read once per process, so attribution requires separate launches.
The existing `NX_INVARIANT` override stays off by default: inspected owned
vertex modules already have invariant Position, and enabling the inherited
helper duplicates that decoration. No extra invariant decoration is added.
The shader inventory found **532 vertex modules, 32 using half unpacking,
zero with RelaxedPrecision decorations and zero with NoContraction**.
All **32/32** half-using vertex modules pass `spirv-val --target-env vulkan1.1`
after the half expansion and precise vertex arithmetic together. The expanded
corpus check validates **532/532 baseline and 532/532 candidate vertex modules**,
with **zero new validation failures**. Shader bytes and validation output remain private.

The other correctness rows in `agent/PC-GAP-001:docs/PUDDZ_GAP_ANALYSIS.md`
were considered. C3's blanket depth initialization lacks an established guest
clear/alias contract; C4 requires typed draw-time translator variants; C5 is
an existing, independently gated overlay; C6 requires coordinated multisample
images/pipelines/resolves; C7 needs raw-copy/format consistency. C8–C12 cover
clocking, audio, counters and diagnostics rather than a cheap, established
occlusion correction. None is silently activated in this patch.

### Offline checks and private evidence

`tests/test_astral_depth_fidelity.py` composes all three complete platform
series, checks the depth patch at its insertion point before successors,
compiles every changed translation unit in the strict profile,
and executes the shipped compare and mask helpers. A synthetic fragment
SPIR-V module exercises sparse locations, an output array and a depth built-in
through the actual reflection implementation. Sentinel checks cover missing
attachments and vertex-only passes. A second synthetic module validates the
emitted SPIR-V and interprets its actual instructions for **131,072 lane
conversions**, covering every binary16 encoding in each lane. Windows default
and disable-switch fixtures and non-Windows defaults are executed separately.
These CPU/compiler checks do not establish visual correctness on NVIDIA.

Private evidence belongs to
`.local/units/RENDER-FID-021/`:
`RESUME.md`, `shader-probe-counts.json`, `shader-validation.json`,
`vertex-validation.json`,
`shader-probe/`, `shader-patched/` and the isolated Windows build/run receipts.
Windows outputs are confined to `C:\acr\units\RENDER-FID-021\`.
The brief prohibits nested reviews; independent review of the final committed
head belongs to the parent and has not been claimed or waived here.

### Windows build receipts

The isolated Windows 30 fps build reused `C:\acr\work\gen` read-only. The
accepted baseline is main `8310017`'s full Windows series; the candidate adds
only this patch. Both were rebuilt with **verified BelowNormal priority**:
baseline **452.76 s**, incremental candidate **4.89 s**. An earlier build's
untyped ctypes priority call failed; that attempt was rejected and the
baseline fully rebuilt before either binary was used for gameplay.
All **402/402** compile commands have `NX_ASTRAL_STRICT=1` and
`ffp-contract=off`. The generated main and SDK libraries are identical
between the accepted builds. Source-hash comparison finds exactly the new
header and three modified NVN translation units.

| Binary | SHA-256 |
| --- | --- |
| Baseline | `fcf1de4bccde30d2e381e5b4e1cba59bbfe3b639fa6d405432b74da777bd62c7` |
| Candidate | `2c044bdb3de088e6844677b10b7c6e3d60a286b2a00ef3fa41911c0e9cb86eae` |

Receipts: private `build-receipt.json`, `rebuild.log`, `verify-depth.log`
and `verify-render.log`. Windows hardware reports **NVIDIA L4, 596.86**.
Compilation and SPIR-V validation do not establish the road/bike fix.

The provided shader cache contains **731 fragment modules**: 723 declare
location 0 only, seven locations 0–1, and one locations 0–2. No inspected
location declaration lacks a direct/access-chain store. This supports using
the existing reflected declarations; it does not establish which attachments
an affected draw binds. Private `fragment-output-inventory.json` retains the
inventory, without putting shader bytes in Git.

The required builder suite currently has **53/55 passing tests** in the
assigned worktree. The two failures are integration metadata: the shared
native-order fixture stops at render-fix, and the owned Windows list lacks
the proposed line. Neither file is within this unit's scope. Private
`series-integration-proposal.patch` extends
`tests/test_astral_shader_cache.py:NATIVE_ORDER` and inserts the Windows line;
a temporary archived-repository test with that proposal passes **55/55**
(`verify-integration-proposal.log`). The proposal is uncommitted handoff
material, not a claim that the assigned head passes that integration gate.

### Initial VM scene checks

The owner marker was observed at **17:16:21Z**, with **8,701 RomFS files /
10,309,045,725 bytes** present. Runs use copied saves and isolated writable
roots; originals stay untouched. The controller checks `astral*`, acquires a
CREATE_NEW busy-marker lease that denies competing writes, and stops/reaps its
own PID at 270 seconds. Every completed run below reports zero remaining
games and a released lease. Exit 1 is the controller's deliberate termination.

| Run | Observed scope | Bounded elapsed |
| --- | --- | ---: |
| `baseline01` | Title/load-menu calibration | 270.672 s |
| `baseline02` | Title, opening lab cutscene, character close-ups | 270.406 s |
| `candidate01` | Same input schedule; all four candidates enabled together | 270.500 s |
| `baseline03` | Completed-save route; deliberately stopped before the documented 8 GiB guard issue | 95.734 s |
| `baseline04` | Completed-save HQ, PC and File 01/Rush selector; diagnostic guard 16 GiB | 270.734 s |
| `base-next-b-1` | Automated HQ/PC/File 01 route; actual game-written autosave retained | 270.593 s |
| `seed-next-1` | Direct resume of that autosave into the opening lab | 270.406 s |
| `seed-skip-1` | Cutscene skip reaches character setup | 270.391 s |
| `seed-road-1` | Baseline reaches highway chase, movement and rapid fire | 270.719 s |
| `cand-road-1` | Same save/settings/input sequence, all four candidates enabled | 270.625 s |
| `ablate-eq-1` | Candidate with only `NX_EXACT_EQUAL=0`; other three parts enabled | 270.469 s |
| `ablate-mask-1` | Only `NX_FRAG_OUTPUT_MASK=0`; navigation failed, latest captures remain at title; excluded from chase attribution | 235.313 s |

The title and lab/face samples render coherently on the combined candidate.
`comparisons/closeup-03720.png` retains the same-present-index close-ups;
`baseline02-contact.png` records the baseline lab sequence. There is no
pixel-identity claim: poses, camera motion and credit timing differ despite
the common frame-indexed XInput schedule. `tools/render_compare.py` measured
six raw **1600x900** pairs without resizing/alignment or a pass threshold:

| Present index | Full-frame MAE |
| --- | ---: |
| 600 (title) | 1.504234 |
| 3000 | 43.958333 |
| 3300 | 38.131133 |
| 3600 | 19.189533 |
| 3720 (close-up) | 30.209106 |
| 4200 | 21.493454 |

These differences are not a quality score or a numerical no-regression gate.
Private `early-comparisons.json`, `comparisons/baseline02-candidate01-*.json`,
the two `*-selected/` directories, timing JSONL and run receipts retain the
inputs and limitations. Headless/muted runs establish neither device audio
nor physical-controller acceptance. The later chase results are recorded below.

The completed save's HQ/PC route and its higher diagnostic process guard are
documented in `ASTRAL_PLAYTHROUGH.md`; increasing that guard is not a memory
fix. `baseline05` was refused before game launch because WIN-PERF-020 held
the shared lease. Its empty preparation directory is not gameplay evidence.

### Matched-wall-time highway captures

The later runs reached the chase within the 270-second bound. The completed
save's PC/File 01 route produced an actual game-written checkpoint; a stable
before/copy/after hash check preserved its nine files in private
`collected-navigation/seeds/file01-rush/`. No save bytes were edited. Both chase
runs load that same checkpoint, use the same frame-triggered XInput sequence,
and retain the same 30 fps generation, 1600x900 output, headless/muted mode,
16 GiB diagnostic guard and five-second capture interval. The four candidate
parts were implemented and built together before the first GPU candidate run;
no runtime code changed between these scene checks.

Private `chase-baseline/` and `chase-candidate/` contain 15 raw RGB PPM frames
each plus full logs, input receipts and readback timing. `chase-comparisons.json`
and `comparisons/chase-*.json` record `tools/render_compare.py` results for
**195–265 seconds**, paired every five seconds. Capture wall times differ by
**0–0.23 s**. Full-frame MAE ranges **24.117934–62.488579**, without alignment,
resizing or a pass threshold. Game/camera phase differs despite common inputs;
these metrics measure differences, not correctness or an exact-scene oracle.
`comparisons/chase-210s.png` shows baseline left/candidate right, and the two
`chase-*-contact.png` sheets show the entire sampled interval.

Visual inspection finds fewer large, flat, hard-edged road regions and more
complete motorcycle geometry in the combined candidate. Dark debris remains
visible during enemy hits; disappearance of the reported dark remnants is
**not established**. This is an observed improvement, not complete fidelity
acceptance. Separate switch attribution is recorded only for completed
ablation runs. `chase-evidence-receipt.json` retains binary hashes, raw-frame
hashes and timing limits. Both chase processes were deliberately stopped,
reaped and released their leases; their full logs contain zero matching
fatal/device-loss/shader-rejection/pipeline-failure diagnostics.

`navigation-evidence.zip` preserves 54 private metadata/save files (519,644
bytes, SHA-256 `033cc8ea2fa8c2b8c4d76aa488403e6302a5126784dc5f19b169e55f56b465ce`).
The retained `RESUME.md`, controller helpers and routes describe how to resume
without repeating manual HQ navigation. None of these game-derived captures
or saves belongs in Git.

The `ablate-eq-1` interval restores the large flat road regions and visibly
missing motorcycle surfaces while the other three candidates remain enabled.
This supports the **exact EQUAL/synthetic-slack bundle** as necessary for the
observed road/bike improvement. It does not distinguish compare relaxation
from synthetic bias independently. Private `ablate-eq-1/`,
`ablate-eq-1-contact.png`, `ablate-eq-1-comparisons.json` and
`comparisons/ablate-eq-1-*.json` retain 15 raw 195–265-second captures, the
combined-versus-ablation comparisons and the process/environment receipts.
The combined/ablation wall-time deltas are at most **0.24 s**, again without
phase locking or a quality threshold.

The mask-disable attempt was stopped after its latest capture showed the
title instead of chase gameplay. Its cause is not established; it is **not**
evidence of a rendering regression or of the mask's contribution. Private
`ablate-mask-1/` retains eight 195–230-second raw frames and the full receipts
and logs. Half-expansion and precise-vertex disable runs were not launched:
the shared-lease waits consumed the available window, and the launch cutoff
left enough time to reap games and preserve evidence. The combined candidate
ran all four parts on NVIDIA, but individual mask/half/precise attribution,
dark-remnant resolution and complete fidelity acceptance remain open.

At closeout, all owned games and waiters had exited, the owned lease was
released, and the private run options were restored to the combined defaults.
`STOP-WAIT` intentionally prevents unattended further launches; remove it only
when resuming an explicitly coordinated VM run. The assigned branch still
needs the two lead-owned integration edits described above and independent
parent review. No branch was pushed and no public build or release was made.

### WIN-REPLAY-024: integrated defaults on the G4

The follow-up cherry-picks `ce6fe86` and integrates the depth overlay in all three
series. Exact EQUAL and removal of its synthetic slack are the Windows default.
`NX_FRAG_OUTPUT_MASK=1`, `NX_HALF_BITS=1` and `NX_VERTEX_PRECISE=1` remain separate,
unverified opt-ins; none is enabled in the following confirmation. Metal and
Linux retain their prior policy. The source fixtures additionally execute the
actual raster slack function with exact EQUAL on/off, zero slack, GREATER opt-in
and depth-write guards, as well as the existing SPIR-V and reflection checks.

The final Windows dynamic-60-cap executable is SHA-256
`62eeb029be7ea75e3cb33679aeedb0ef33c404c4caea68534cd1de6d865d82be`.
It uses the same imported control header and generated main/SDK archives as
WIN-RESIDENT-023, rebuilt on the G4. Its complete composed public runtime matches
147 build-receipt source hashes. The unchanged iteration-2 control executable is
`b9d27b853b0fd39da9325693cfb6bff3a9a5f817b0d3f828b32614b9f0af05ca`.

Private raw frame pair, under `.local/units/WIN-REPLAY-024/`:

- Before: `runs/g4-step0-on-B/frames/20941.ppm` (and PNG preview).
- Final defaults: `runs/replay-control-C2/frames/20941.ppm` (and PNG preview).
- Hashes, executable identity and limitations: `depth-frame-pair.json`,
  `native-source-v2-verification.json`, each run's `receipt.json` and `config.json`.

Both captures follow the same route at its 375-second confirmation point. The
final-default frame shows the rear motorcycle body, rear wheel and textured
road where the iteration-2 frame has missing motorcycle surfaces and large flat
road regions. The final process leaves all four fidelity switches unset and all
five new replay flags off; the previous residency/narrowing/flight/chunk settings
are held on in both runs. A targeted machine/user/process environment check
finds no inherited fidelity overrides. This confirms the requested road/bike
correction on native G4 Vulkan with the final defaults.

Additional native confirmations retain the road and complete motorcycle with
all old/new performance switches off (`runs/validation-off-K/frames/12781.png`)
and with them on (`runs/validation-on-L/frames/15541.png`). The SDK validation
layer is active in both. The F2/L effective-process environment receipts confirm
that none of the three opt-in shader candidates or exact/slack overrides is
inherited. These observations extend the road/bike check; they do not establish
matched-pose pixel identity or broad shader fidelity.

Vehicle, camera and animation phases differ despite the matching present index;
this pair is not a pixel-identity test. The lab still shows pre-existing red
credit/text remnants. Their resolution, attribution of the three opt-in shader
candidates, broad fidelity and matched-pose acceptance remain open. Performance
switch measurements, native verification, validation limits and the remaining
bottleneck are recorded in [Windows performance](ASTRAL_WINDOWS_PERF.md).
Independent exact-head review and landing remain parent-owned; no nested review
or public publication is claimed.
