# Astral Chain 60 fps mode (experimental)

Astral Chain runs at 30 fps: the game opens its NVN window with present interval 2 (`nvn: window ...: 3 textures
(3 active), present interval 2`). In every runtime log so far it never changes that interval
(`600 of the last 600 presents at interval >= 2`).

## In-app setting

The game's code is lifted to C++ ahead of time, so the frame rate is a property of the binary. A default build makes
two (`runtime/patches/astral-fps-variant.patch`):

- `AC-Recomp.app/Contents/MacOS/astral`: 30 fps, the game as shipped;
- `AC-Recomp.app/Contents/MacOS/astral-60fps`: the same runtime with `main` lifted a second time from the 60 fps copy
  below (`<out>/work/gen-60fps/main`).

Only the generated files that differ compile again: `tools/acr_build.py` writes `<out>/work/runtime/main-60fps.list`
(on Astral Chain 1.0.0, two of 207 files), and the CMake target `astral-60fps` links the objects of `astral`, `game_sdk`
and every other `game_main` object. Measured on an M5 Pro with `--jobs 4`: the lift stage took 62 s instead of 37 s,
the build stage 91 s instead of 88 s; the app grows by 56 MB.

The launcher's **Settings > Frame rate** row (30, or 60 (experimental)) is saved as `fps = 30|60` in `settings.ini`.
The .app wrapper (`Contents/MacOS/AC-Recomp`) reads `NX_FPS`, else that key, and starts `astral-60fps` for 60 when it
exists. When the player changes the row in the launcher, PLAY re-executes the other binary with the same arguments
and `NX_SKIP_LAUNCHER=1` (`launcher::reexec`, `launcher::fps_variant`; the hook is shared with any other
re-exec-on-PLAY need). A Metal HUD the process turned on from the settings is decided again by the new image.
Headless and scripted runs never switch: run the binary you want directly.

`--fps 30` or `--fps 60` (or `NX_FPS` in the build's environment) builds only that frame rate, as before:

    python3 tools/acr_build.py --out <dir> --fps 60          # or: NX_FPS=60 python3 tools/acr_build.py --out <dir>

Such a build has one binary, `astral`, with its rate compiled into the launcher (`NX_SINGLE_FPS`): the Frame rate
row shows that rate, "60 (this build)", whatever `settings.ini` says, and explains that it cannot change.
`--render-res` patches both lifts. A default build of another version of the game (the 60 fps patch checks the
1.0.0 build id) does not fail: it prints a note and builds 30 fps only, as `--fps 30` would.

The re-exec continues the same session: it sets `NX_REEXEC=1`, and the log code then appends to `nx.log` instead of
moving it to `nx.log.prev`, as after a Metal HUD restart.

## The patched lift input

`tools/astral_fps60.py` patches five instructions in a private copy of the player's `exefs/main`
(`<out>/work/lift-fps60/main`, which is game-derived and never goes in Git). Before it writes anything, it checks
the build id and every original word. The lift then reads that copy. The runtime still loads the unpatched
`exefs/main` for data, because text bytes are never executed from it. The stage cache records the choice, so
switching between `--fps 30` and `--fps 60` relifts `main` and rebuilds the stages after it. No runtime patch is
needed: see "Runtime side" below.

Supported: **Astral Chain 1.0.0 only**, main NSO build id `ED2026B20685971F8B332095A7FF80FF`. Any other build is
refused, naming the first mismatch.

## How the game times a frame (1.0.0, module-relative offsets)

- **Game loop** `main+0x3df720`. Once per frame it does three things:
  - It calls the game-speed controller `main+0x907a10(speed, s0 = 1.0, w1 = variable)`. `w1` is
    `1 & ~(flag >> 30)`, so frames with bit 30 of a global flag set (cutscenes) are fixed-step.
  - It calls `main+0x9c9c70(1)`, which stores the "vsync mode" in the graphics system at `main+0xcc9daf0 + 0x420`.
  - It runs the frame.
- **Present interval.** `main+0x9c5350`, the graphics system's per-frame function, compares the mode at `+0x420`
  with the cached `+0x424`. When they differ, it calls the window's present-interval setter
  (`[main+0xda8c60]`, nvnWindowSetPresentInterval) with `mode == 0 ? 1 : mode == 1 ? 2 : 0`. The window builder
  in `main+0x9d2450` (`main+0x9d2bb4`) maps the configured mode the same way. Mode 1 means interval 2, which is
  30 fps.
- **Game speed.** The controller object (`[main+0xd9e998]`) is initialised by `main+0x907700(30.0)`, which sets
  `+0xdc = 30/1000`. Each frame it does the following:
  - It measures the time since the last frame with GetSystemTick, in ms (×1000.0 from `main+0xb46ba4`).
  - It multiplies that by `+0xdc` to get a step in **units of 1/30 s**.
  - It subtracts a carry and clamps the step to **[1.0, 2.0]**. Below the minimum, it stores the minimum and keeps
    the difference as carry.
  - It stores the step at `+0xd0`. `main+0x907b40` multiplies `+0xd0` down a chain of time scales that the game
    logic reads.
  - Fixed-step frames (`w1 == 0`) store the argument `s0 = 1.0` instead.
  - The debug override at `main+0x893410` reads a float at `main+0xd93c5c`, initialised to -1.0, which is
    inactive.

At 60 fps, the measured step is 0.5. The 1.0 minimum would then run the game at double speed, and fixed-step
cutscenes would also run at double speed.

## The patch

| Site (main+) | Original | Patched | Meaning |
|---|---|---|---|
| `0x3df7c0` | `0x320003e0` mov w0, #1 | `0x52800000` mov w0, #0 | Vsync mode 0. The game itself calls nvnWindowSetPresentInterval(window, 1) on the next frame. |
| `0x907a70` | `0x340001d5` cbz w21, #0x907aa8 | `0xd503201f` nop | Fixed-step (cutscene) frames take the measured step too. |
| `0x907af4` | `0x1e2e1001` fmov s1, #1.0 | `0x1e2c1001` fmov s1, #0.5 | The minimum step compare. |
| `0x907b00` | `0x1e2e1001` fmov s1, #1.0 | `0x1e2c1001` fmov s1, #0.5 | Carry = minimum - measured. |
| `0x907b0c` | `0x32091be8` mov w8, #0x3f800000 | `0x52a7e008` mov w8, #0x3f000000 | Store the minimum step (0.5). |

The 2.0 maximum is unchanged. Below 15 fps the game slows down, as it does on the console. The steps stay
real-time, so a frame that misses 60 just takes a larger step (the game's own variable-step design). At a steady
30 fps the patched build behaves like the original. The original words are facts about the binary, like the
offsets in the format profile. They are not game content.

## References and how the sites were found

All the community patches target **1.0.1** (build id `4B159F0F7A360669738390EE8657B4F0`). None of them apply to
1.0.0 as is. Their ideas and offsets were used to find the 1.0.0 equivalents: the game-speed function is 0x161a0
lower in 1.0.0, the graphics code 0x161d0 lower and .bss 0x1a000 lower. No community code or patch files are
included.

- Community research on 1.0.1 identified the speed clamp (1.0.1 `0x91dc94/0x91dca0/0x91dcac`), the vsync-mode
  argument (1.0.1 `0x3e39d0`, our `0x3df7c0`), the 2.0 maximum, the fixed cutscene step `fmov s8` (1.0.1
  `0x3e397c`, our `0x3df76c`), the cutscene `nop` (1.0.1 `0x91dc10`, our `0x907a70`) and the interval field
  (`[main+0xccb7af0]+0x420`). Only the locations were used; no patch text or code was copied.
- MacNativeGames' TotK `game_patches.c` (https://github.com/ly05010419/MacNativeGames, MIT). It provided the
  pattern: a table of `{offset, original, replacement, meaning}`, every site checked before any is written, the
  game's own present-interval minimum lowered from 2 to 1, and a real-time frame step. Astral Chain already measures
  real time, so it only needs its clamp lowered, not a new step source.
- Bayonetta 2 recomp (https://github.com/K0NL/B2recomp, GPL-3.0; ideas only): a hand-checked list of per-frame
  counters that advance only on whole 60 Hz ticks, and holding cinematic shots to the audio.

## Runtime side

- `nvnWindowSetPresentInterval` (runtime `nvn_queue.cpp`) records the interval and logs
  `nvn: window present interval 2 -> 1`. `pace_present` returns each present no earlier than
  `interval × display_period_ns()` after the previous one. That period is 16.67 ms unless `NX_DISPLAY_HZ` is set,
  so interval 1 paces at 60 fps whatever the host display's refresh rate. Do not combine 60 fps with
  `NX_DISPLAY_HZ` > 60: the 0.5 minimum would run the game fast.
- The Wonder-specific governor (`frame_time_probe`, `NX_FPS_CAP`, `NX_MAX_INTERVAL`) only acts at Wonder's call
  site and does nothing for Astral Chain. The perf HUD (`NX_PERF_HUD`) computes game speed as FPS × interval / 60,
  so it reads correctly at interval 1.

## Risks and what to check

- **Frame-counted logic.** Anything that counts frames instead of reading the scaled time (UI timers, some effects,
  input repeat, hit-stop, physics substeps) would run up to 2× fast. The community patches touch nothing else, and
  their users report working gameplay. That is evidence, not proof.
- **Cutscenes.** With the `nop`, cutscenes follow real time and should stay in step with streamed audio and
  movies. A hitch makes a cutscene skip ahead (a step of up to 2.0) instead of slowing down. The alternative is the
  fixed 0.5 step (`main+0x3df76c` `fmov s8, #1.0` → `#0.5`, word `0x1e2e1008` → `0x1e2c1008`)
  and keeping the cutscene `cbz`. That is exact at a steady 60, but it slows cutscenes and desyncs audio whenever
  60 is missed.
- **Performance.** The host has to finish a frame (CPU lift and GPU replay) in 16.7 ms. Otherwise the game runs at
  a variable 40-60 fps at correct speed. Prefer `NX_PERF_HUD=1` to measure it.
- **Audio.** Audio runs on its own clock (audout and the audio renderer), so it is independent of the frame rate.
  Watch for crackle if the main thread starves the audio threads.

## Proposed test runs (run by the lead, not on a shared Mac while another game run is active)

1. Build: `python3 tools/acr_build.py --out <dir> --fps 60` (or reuse a 30 fps build directory: the lift and
   later stages rebuild). It must print `60 fps: patching 5 instructions of main for the lift`.
2. A short run with `NX_PERF_HUD=1`. Expect `nvn: window present interval 2 -> 1` within the first frames, and
   `N of the last 600 presents at interval >= 2` near 0.
3. Speed checks against a 30 fps build on the same save:
   - the title-screen and menu animation durations;
   - a timed walk between two landmarks;
   - the in-game clock or a cutscene's length against its audio (stopwatch or a screen capture);
   - a battle (Legion chain, hit-stop, timers).
4. A cutscene check: lip sync and music cues stay aligned. If not, try the alternative above.
