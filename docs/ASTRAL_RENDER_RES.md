# Higher internal resolution (lift-time patch)

Astral Chain 1.0.0 renders docked at a fixed 1600x900 (handheld 1280x720) with dynamic resolution between
1440x810 and 1600x900. The sizes are instruction immediates in main, not answers from the system:
the runtime's `NX_RENDER_RES` (am `GetDefaultDisplayResolution`) is never consulted. As in MacNativeGames' TOTK
`patch_render_res`/`patch_output_res` (MIT; idea only, no code taken), the simple fix is to change those immediates so the
engine allocates its own scene targets, window textures and crop at the larger size.

Because the game is statically recompiled, "patching instructions" happens before lifting:
`tools/astral_render_res.py` rewrites the words in a copy of the player's own main NSO, and `tools/acr_build.py
--render-res WxH` lifts that copy instead of `exefs/main`. The runtime still loads the original NSO for data; only
text words change, and lifted code never reads its own instructions.

> 16:9 sizes are recommended; sizes above 2560x1440 are untested.

## Usage

```
python3 tools/acr_build.py --nsp ... --keys ... --out <dir> --render-res 2560x1440 [--graphics-memory-mib N]
```

- Limits: even width and height, from 1600x900 to 4095x4095 (the `cmp` sites take a 12-bit immediate).
- The option is part of the lift stage's inputs, so setting or changing it reruns lift and the later stages. The lift now
  keeps byte-identical generated files untouched, so the C++ build recompiles only the two changed files
  (`code_081.cpp`, `code_084.cpp`) and relinks. Without the option nothing changes (recorded inputs stay the same).
- The patcher checks the NSO build id and every original word first and refuses the whole patch on any mismatch
  (another version, an already patched file). It writes an uncompressed NSO (flags cleared, same segment layout).
- With `--fps 60` (docs/ASTRAL_60FPS.md) the 60 fps patch is applied first. This patch then runs on that copy and
  checks its own words; the two touch disjoint sites. The combination is unit-tested and has not been run in-game.
- It uses `lz4` when importable, otherwise a pure-Python LZ4 block decoder. On the real main both produced
  identical output, and the pure path took 0.2 s.

## Sites (main, module-relative; 1.0.0 build id `ED2026B20685971F8B332095A7FF80FF`)

| offset | original word | instruction | meaning | patched to |
|---|---|---|---|---|
| 0x4093D4 | 5280C809 | mov w9,#0x640 | graphics init: docked width (csel with 0x500 handheld; flag `0x20000000` from 0x9acc70 selects) | W |
| 0x4093E0 | 52807089 | mov w9,#0x384 | graphics init: docked height (with 0x2d0) → 0x409dc0 / 0x409f70 / 0x40a0d0 create the targets | H |
| 0x40AF74 | 7119001F | cmp w0,#0x640 | DRS setup: main target width (0x9bc120 reads `tex->width`) == docked? slot 0 | W |
| 0x40AF78 | 52807088 | mov w8,#0x384 | DRS slot 0 (max) docked height | H |
| 0x40AF98 | 5280B409 | mov w9,#0x5a0 | DRS slot 1 (min) docked width 1440 | W (locked, no dynamic res) |
| 0x40AF9C | 7119001F | cmp w0,#0x640 | docked test, slot 1 | W |
| 0x40AFA4 | 52806556 | mov w22,#0x32a | DRS slot 1 (min) docked height 810 (w22 is also slot 2's docked height) | H |
| 0x40AFC0 | 7119001F | cmp w0,#0x640 | docked test, slot 2 | W |
| 0x40B8F4 | 5280C809 | mov w9,#0x640 | operation-mode change: re-created targets, docked width | W |
| 0x40B904 | 52807089 | mov w9,#0x384 | same, docked height | H |
| 0x42E5F0 | 5280C808 | mov w8,#0x640 | docked display-size getter (`*x0 = 1600`) | W |
| 0x42E5F8 | 52807088 | mov w8,#0x384 | same (`*x1 = 900`); handheld twin at 0x42E610 | H |
| 0x409EA0 | 52A26C08 | mov w8,#0x13600000 | `Graphic::Startup` config: graphics memory budget, 310 MiB | 310 + 160·(W·H/1440000 − 1) MiB, rounded up |

Handheld values (1280x720, DRS 1024x630) and the 1280x720 family created at 0x40af1c / 0x40a04c are left alone.
The bloom chain (800x450 … 50x28) follows the scene size.

### How they were found

- Searched main's text for MOVZ `#0x640` / `#0x384` pairs within 0x20 bytes, and for `cmp #0x640`, then disassembled
  each hit with the lift venv's capstone.
- Cross-checked against community research on **1.0.1** (build id `4B159F0F7A360669…`; none of it targets
  1.0.0). Its offsets are not ours: 1.0.1 `0x4328C0` ↔ 1.0.0 `0x42E5F0` (−0x42D0), `0x40D5E4` ↔ `0x4093D4`,
  `0x40FB04` ↔ `0x40B8F4` and the DRS block `0x40F184…0x40F1D0` ↔ `0x40AF74…0x40AFC0` (−0x4210). It was used
  only for knowledge (which sites, and that locking DRS min = max is the established "no dynamic res"
  variant); no patch text or code was copied. A mipmap LOD bias (`0x9ED178`), anisotropic filtering and the
  frame rate are not ported here.
- The memory site: the first 2560x1440 attempt crashed 1 s in with a null dereference in nnMain+780. The game's
  error string at main+0xb6b0bc, logged on the 0x409d88 failure path, reads
  `ERROR : Graphic::Startup() FAILED. No Graphic Memory`. 0x409dc0 builds the startup config, and the
  `0x13600000` field is the budget. With 560 MiB it boots.

## Evidence (private, under this worktree's ignored `.local/rr/`)

These runs used the finished player build `.local/acr-smoke-152`, read-only. Its lift was redone with the patched
main, the changed files were compiled with the build's own compile command, `libgame_main.a` was copied with the
changed members replaced, and the result was relinked into a copied app. Each run was headless, 55 s,
with `NX_DUMP_FRAMES=60`.

| run | result |
|---|---|
| stock (smoke-152 `smoke.log`) | crop 1600x900; dumps 1600x900; 30 fps |
| 2560x1440, memory 310 MiB (`run1.log`) | crop 2560x1440, then **Graphic::Startup failed → SIGSEGV** after 1 s |
| 1920x1080, memory 310 MiB (`run-1080.log`) | crop 1920x1080, 27 dumps of 1920x1080, 30.0 fps, exit 0 |
| 2560x1440, memory 560 MiB (`run-1440.log`) | crop 2560x1440, 27 dumps of **2560x1440**, 30.0 fps, fence wait ~5.9 ms (stock ~4.6), exit 0 |

The PNGs in `cmp/` (stock, 1080, 1440, frames 600 and 1560) show the same opening scene filling the whole frame.
Per-quadrant mean brightness matches stock to within 1 level, and the larger frames are visibly sharper.
The lift of the patched main reported `handled 2569151, unhandled 0`. Only `code_081.cpp` and `code_084.cpp` differ
from the stock lift, at exactly the listed immediates.

## Risks and limits

- **Fixed at build time.** The size is baked in at lift time, so the launcher's resolution setting (`NX_RENDER_RES`)
  does not change it. To make it a runtime setting, a follow-up could turn the `mov` sites into PC-relative literal
  loads from text padding that the runtime fills from `NX_RENDER_RES`. The `cmp` sites would also need rework,
  because `cmp #imm` cannot read memory.
- **Short test only.** Testing covered the first 55 s (the opening) at 1080p and 1440p. Nothing past that was
  tested: menus, cutscenes, gameplay, mode changes (0x40B8F4), screenshots or captures. Some UI or post-process
  passes may still assume 1600x900; none was visible in the dumps.
- **Rough memory formula.** The 160 MiB per extra 1600x900 is a heuristic. 310 MiB fails and 560 MiB works at 1440p.
  3200x1800 (790 MiB) and 4K were not run. `--graphics-memory-mib` overrides the value. Host process memory
  was 2.13 GB stock, 2.19 GB at 1080p and 2.31 GB at 1440p, against an 8 GB limit.
- **No dynamic resolution.** DRS is locked (min = max), as the community "no dynamic res" patches do. GPU cost
  rises with the pixel count. On this Mac, 1440p still held 30 fps in the opening.
- **1.0.0 only.** Any other main is refused by build id and by the original words.
