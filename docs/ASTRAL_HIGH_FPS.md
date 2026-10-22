# Experimental Dynamic FPS port (FPS-007)

Astral Chain **1.0.0 only**, main build ID `ED2026B20685971F8B332095A7FF80FF`.
This is an opt-in lift-time port. The default builder and launcher retain their existing 30/60 choices.
Gameplay acceptance and cutscene sync are separate gates; see the evidence table below.

## Source and timing contract

Adapted from [yogesh1239/AstralChain-Dynamic-FPS v1.1.1](https://github.com/yogesh1239/AstralChain-Dynamic-FPS/tree/79965b4df077f64b27b74456d0db88c6afac5bbe),
MIT, copyright (c) 2026 yogesh1239. Full notice: [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
Upstream credits the original Static 60 FPS patch author (see THIRD_PARTY_NOTICES.md). Its README, technical notes, both cap variants and
v1.1 -> v1.1.1 cutscene removal were inspected. Upstream emulator reports do not establish native runtime acceptance.

The existing [60 fps patch](ASTRAL_60FPS.md) already measures real elapsed time; it has a **minimum** step of 0.5,
not a fixed delta. At 120 fps that floor can double world speed. Dynamic mode replaces that controller path:

```
step = clamp(elapsed_ms * (30 / 1000) * eligible_positive_correction, 1/16, 2)
remainder += step
whole_ticks = trunc(remainder)
remainder -= whole_ticks
```

The cutscene flag disables the existing correction override, rather than enabling a fixed step. The first sample
starts at step 1 and clears the remainder. Step is published at controller `+0xd0`, fractional remainder at `+0xd4`,
whole 30 Hz ticks at `+0xd8`. Below 15 fps the 2-tick maximum still slows the world; above 480 fps the positive
floor would accelerate it, so the runtime retains a 480 fps safety ceiling even when unlocked.

One hundred hooks cover signed input/action countdowns, saturating buffer banks, hit-stop delay/duration, count-up
windows, pad repeat and rumble. Whole-tick zero transitions retain the game's flags and fire once, including
2-tick frames. Non-flag-setting bank/count-up helpers preserve incoming NZCV. Leaf clock/rumble paths preserve LR;
other BL callers' LR-saving prologues are checked. Camera smoothing uses `1 - powf(1 - alpha, step)`, preserving the
30 fps result and alpha endpoints. Two pre-existing integer-conversion consumers read whole ticks directly.

Three 1.0.1 sites have no corresponding 1.0.0 operation: the `+0x46b66c` input bank counter and two freeze-phase
cue-delay operations. They are deliberately omitted, rather than mapped by a guessed constant delta. Other
manager fields also differ between versions. The private address map records instruction neighborhoods and these
omissions. Credits and smaller camera counters remain unaudited, as upstream documents.

## Safety and code-cave lifting

`tools/astral_fps_dynamic.py` checks **111 replaced original words** (112 with optional cutscene carry), structural dependencies and the build ID
before producing output. It refuses mixed/already-patched inputs, unexpected text/rodata layouts and output aliases
of the source, including symlinks/hardlinks. Output is atomically replaced. All NSO segment sizes and SHA-256 hashes
are recomputed; module metadata, rodata and data are preserved.

Original text ends at `0x9f85f0`, rodata begins at `0x9f9000`. The new cave starts at that text end and **extends the
NSO text segment itself**, without moving rodata or data. This is essential: emulator-style writes into padding
outside the declared text range would not be lifted. Branch displacements and cave bounds are checked. No existing
function body is reused as a cave. Private emitted-code tests execute timer and counter helpers, rather than
assuming that instruction coverage proves their behavior.

## Selecting a build

The new tool accepts `--mode 30`, `60-fixed`, `dynamic-60-cap` or `dynamic-unlocked`. Here `60-fixed` names the
existing five-site 0.5-floor variant, retained byte-for-byte; it is not a newly introduced fixed time source.

Prepare a separate private NSO from the pristine dump:

```sh
python3 tools/astral_fps_dynamic.py --mode dynamic-60-cap --check <private-exefs>/main
python3 tools/astral_fps_dynamic.py --mode dynamic-60-cap <private-exefs>/main <private-work>/main-dynamic.nso
```

Lift the resulting NSO using the prepared, pinned recompiler environment, with the existing main base:

```sh
<build>/work/venv/bin/python -m recomp <private-work>/main-dynamic.nso <private-work>/gen/main \
  --name main --base 0x4000000000
```

Run from the prepared lift source directory, or set its path in `PYTHONPATH`. Copy the existing private `gen/sdk`
into this separate `gen` tree. Configure the prepared runtime with `-DNX_GEN_DIR=<private-work>/gen`,
`-DNX_MAIN_VARIANT_LIST=` and **matching** `-DNX_ASTRAL_FPS_MODE=dynamic-60-cap` (or `dynamic-unlocked`), then build
`astral` with `nice` and bounded jobs. Runtime mode values `30` and `60-fixed` preserve legacy pacing; `legacy` is
the unchanged default. Invalid modes and dynamic builds sharing a legacy FPS sibling are refused by CMake.
There is no automatic NSO/runtime mode inference: the person preparing the explicit build must match them. Dynamic binaries show their actual build mode in the
launcher and refuse legacy FPS sibling re-exec, even if an old `astral-60fps` is still beside them.

This manual build route is intentional within FPS-007's file scope: `tools/acr_build.py` and launcher settings are
outside scope. `acr_build.py --fps` still accepts only 30/60; `NX_FPS=120` does not select a dynamic build. Integrating
the new mode into the one-command stage cache and packaging remains a follow-up, not a supported hidden environment
switch that could reuse stale lifted code.

`NX_DYNAMIC_FPS_CAP=40` forces a drop for testing; `120` selects a 120 fps limit for the unlocked build. Valid limits
are 15..480; capped mode never exceeds 60. Malformed values, zero and out-of-range values use the mode's ceiling.
`NX_DISPLAY_HZ=120` may be needed for the runtime's other vsync events; it cannot defeat the dynamic 60 cap.
`NX_NO_FRAME_LIMIT` cannot bypass dynamic mode's safety ceiling; dynamic pacing preserves its deadline and prevents catch-up bursts above 480 Hz. These limits are present-return pacing, not proof
of a display mode, rendered frame rate or correct gameplay.


The minimum-spacing timestamp is taken at the end of the pacer, after diagnostics. A CPU fixture executes the
production function for 620 presents with a simulated 30 ms diagnostic stall at present 600. The earlier timestamp
allowed the next two returns to be 0 ns apart; the corrected function retains at least 2,083,334 ns spacing.
The fixture also checks exact unstalled deadline cadence and the unchanged legacy `NX_NO_FRAME_LIMIT` bypass.
Native tables below identify their snapshots; they precede this final timestamp hardening unless stated otherwise.

## Evidence and remaining gates

Private evidence root: `$ACS_ROOT/.local/units/FPS-007/` (ignored).
All derived files, captures, copied saves and executable snapshots remain ignored there. Owner build is read-only.
Every Mac game launch uses `.local/bin/mac-game-lock`; its current policy forces headless/muted execution.
That closes the Mac audio device and substitutes a timer. **Mac headless audio dumps cannot establish real-device
underruns or speaker/display A/V sync.** Dump/logic-clock results below are explicitly separate. The existing HUD
"Speed" percentage is FPS-derived and is not a dynamic world-speed measurement; probes sum the actual stored step.

The following Mac M5 Pro/MoltenVK measurements use immutable, privately instrumented snapshots. They predate
main's AUDIO-006 timer fallback fix; they measure the FPS code and raw counters, not acceptance of the final
combined runtime. Fresh private save copies and the same Python-constructed input sequence were used, with
B presses at 10/11/12 seconds to normalize the loaded button state. Title = 10..24 s, chase = 48..76 s,
on-foot = 118..138 s. FPS is actual controller calls divided by wall duration. World ratio is
`sum(stored_step) / (30 * wall_seconds)`. Scene time is cut 1 -> cut 12, excluding boot/loading.

| Native Mac check | 30 baseline | Dynamic 60 + carry | Unlocked cap 120 + carry | Verdict |
|---|---:|---:|---:|---|
| Title FPS / world ratio | 30.000 / 1.00000007 | 60.000 / 0.99999996 | 113.525 / 0.99999978 | PASS clock; 120 not sustained |
| Chase FPS / world ratio | 29.929 / 0.99763605 | 58.998 / 0.99957134 | 66.841 / 0.99999992 | PASS mean speed within 0.25%; loading hitches remain |
| On-foot FPS / world ratio | 30.000 / 1.00000608 | 56.445 / 0.99999991 | 64.882 / 0.99999987 | PASS clock; not combat |
| Chase cut 1 -> 12 | 20.600017 s | 20.600636 s | 20.598101 s | PASS relative event duration within one render frame |
| ZL buffer `+0x13a8`, 15 ticks | 499.379 / 500.267 ms | 491.180 / 483.773 ms | 493.665 / 496.450 ms | PASS raw lifetime within one authored 33.3 ms tick |
| Camera blend equation, maximum absolute error | raw alpha; reference | 4.50e-8 | 5.82e-8 | PASS native coefficients; camera feel unaccepted |
| Legion summon/recall/Sync Attack | not reached | not reached | not reached | OPEN; a retained input is not move success |
| Actual combat timing | not reached | not reached | not reached | OPEN; route reached chase/on-foot, collided during exploration |
| Physical display presentation | headless | headless | headless | BLOCKED; no physical 120 Hz result |
| Device A/V at scene cuts | unavailable | unavailable | unavailable | OPEN; see capture limitations below |

Chase scene transitions relative to the first observed transition (seconds). All three visit the same
12 scene indices/lengths; all relative differences are under one authored 30 Hz tick. This is logic-event
timing, rather than a timestamp for the first visible pixel on a physical display.

| Scene entered | 30 | Dynamic 60 + carry | Unlocked cap 120 + carry |
|---|---:|---:|---:|
| 1 | 0.000000 | 0.000000 | 0.000000 |
| 2 | 1.266709 | 1.266658 | 1.271003 |
| 3 | 3.066094 | 3.071619 | 3.079837 |
| 4 | 7.932955 | 7.925368 | 7.934628 |
| 5 | 10.199988 | 10.191021 | 10.208004 |
| 6 | 12.499794 | 12.490363 | 12.498087 |
| 7 | 14.833357 | 14.831225 | 14.851083 |
| 8 | 17.566632 | 17.558670 | 17.567936 |
| 9 | 18.299989 | 18.292501 | 18.307973 |
| 10 | 18.732703 | 18.726013 | 18.735549 |
| 11 | 19.266604 | 19.267198 | 19.272355 |
| 12 | 20.600017 | 20.600636 | 20.598101 |

A separate native **legacy five-site 60** control reproduced the likely input-window defect: the same 15-tick ZL
buffer expired after **249.913 / 243.555 ms**, versus 499.379 / 500.267 ms at 30. Its unchanged camera alpha was
0.300000012 at a roughly 0.5 step; maximum error against the normalized equation was 0.136660031.
Dynamic mode retained the buffer's authored duration and applied the normalized blend. This isolates two concrete
improvements without claiming the Legion itself was unlocked or exercised.

The final-pacing native forced-cap probe (`NX_DYNAMIC_FPS_CAP=40`, with AUDIO-006's timer fix) measured
**40.002 fps** at the title and **39.890 fps** during the chase. World ratios were **0.99999992** and
**0.99881655**, respectively; chase cut duration was **20.600858 s**. PASS variable-speed behavior under a real
render-rate drop. Individual >66.7 ms hitches still hit the inherited 2-tick limit (worst one-second chase ratio
0.966562), so below-15-fps recovery is not claimed. This is present/controller timing, not physical 40 Hz display
acceptance. Private evidence: `forced40-final-clock-v6`; an earlier stricter-pacing 38.628-fps probe is retained
separately and is not the final pacer.

Private reproduction/evidence: `native-comparison.json`, `aggregate_native.py`, `onfoot-route.txt`, per-run
`script.txt`, `env.json`, `console.log`, `receipt.json`, and immutable snapshot SHA-256 lists.
The table uses `baseline30-av-final`, `dynamic60-final-pacing`, `unlocked120-carry-route1`,
`legacy60-window-control` and `forced40-final-clock-v6`.

| Offline / implementation gate | Result |
|---|---|
| Private 1.0.0 build ID and original words | PASS, 111 sites (112 with carry), structural guards; private address map |
| Timer, emitted AArch64, synthetic 3 seconds at 15/30/40/60/120/480 | PASS, world ratios 0.99999994..1.00000000; 40 fps = 90 whole ticks |
| Countdown/bank register + NZCV semantics | PASS, 180 emitted-code cases; private `emulate_helpers.json` |
| Camera equation | PASS, 20 emitted-code cases; private `emulate_helpers.json` |
| Packaging / one-command builder integration | OPEN; explicit private build only |
| Independent review | PARENT GATE; no nested review requested or claimed |

The initial full dynamic lift handled **2,571,122 instructions, 27,818 functions, zero unhandled**. That is a
compiler coverage result, not a gameplay result. The earlier private aborted probe was a different five-site
experiment and is not evidence for this port. Independent review belongs to the parent; the unit brief forbids
nested reviews. No independent review is claimed here.

## Cutscene synchronization

The mod's v1.1 whole-tick cutscene workaround was removed in v1.1.1 because motion smeared. This port excludes it.
The optional **`--cutscene-clock carry`** corrects fractional progress at the actual scene boundary instead:

```sh
python3 tools/astral_fps_dynamic.py --mode dynamic-60-cap --cutscene-clock carry \
  <private-exefs>/main <private-work>/main-dynamic-carry.nso
```

Default remains `original` while A/V acceptance is pending. Carry requires a dynamic mode. It checks the original
boundary and epilogue instructions, replaces `main+0x8ac3fc`, and emits nine instructions inside the lifted cave.
It changes no audio playback rate, global clock, pause flag or seek/reset method. It preserves smooth fractional
updates on every render frame.

In 1.0.0, scene progress is an authored-frame coordinate. The original boundary clamps overshoot to `length - 1`,
then clears the fraction on the next render. At 30 fps this spends the inclusive final authored frame. At higher
rates that final render costs less than a whole authored frame, and both clamps discard partial time. Carry waits
until `progress >= length`, advances the scene, and transfers `progress - length` into it. A pause cannot advance
this comparison; whole-tick stepping is unnecessary. End-of-sequence clamping and explicit seek/reset paths stay
as authored. Pause/seek regressions still need native acceptance.

The first native 60 fps chase shows all 12 original transitions from exact last-index values to fraction zero.
The carry chase instead shows, for example, `0:65.561439514 -> 1:0.070198059` (length 66, step 0.508756220) and
`1:37.721290588 -> 2:0.232299805` (length 38, step 0.511007786). Those are real Mac game-process observations,
not simulated values. Their unhandled-instruction count is zero (27,820 functions / 2,571,137 handled instructions).

Executing the original and replacement AArch64 boundary code over the 12 observed scene lengths gives:

| Rate | Original duration | Carry duration | Authored duration |
|---|---:|---:|---:|
| 30 | 22.800 s | 22.800 s | 22.800 s |
| 40 | 22.775 s | 22.800 s | 22.800 s |
| 60 | 22.600 s | 22.800 s | 22.800 s |
| 120 | 22.500 s | 22.800 s | 22.800 s |

These duration rows are **synthetic machine-code execution**, not measured audio sync. Private evidence:
`emulate-cutscene.json`, `combat-explore-carry/console.log`, `main-dynamic-carry-checked.nso` (byte-identical to the
native probe's lifted input), and snapshot hashes. Audio sample/wall timestamps, frame timestamps and waveform
correlation are reported below. A constant device/display latency or a renderer starvation problem
would remain a different issue; this patch specifically repairs scene-boundary drift.


### Packet-timestamped native A/V drift (headless only)

The v6 snapshots include the cumulative audio fallback clock from AUDIO-006, now on main. They add private
per-packet sample/wall timestamps (1,024-frame blocks), plus existing frame dumps every 0.1 s. The Mac clock
epoch was independently bracket-checked: `steady_clock` lies between two `CLOCK_UPTIME_RAW` reads in all eight
trials (`clock-epoch.log`). Audio and logic-cut timestamps therefore share an observed epoch.

For each cut, a four-second 30-fps reference waveform excerpt is matched near the corresponding dynamic cut
using normalized correlation at 4 kHz. The audio packet timestamps map sample index to wall time, including
gaps; sample-zero plus WAV duration is not used as a wall clock. Negative offset means the cut is earlier
relative to the matched 30-fps audio. The table subtracts each run's first-cut offset to measure accumulated
drift without attributing startup/queue phase to the boundary patch. It is **not an absolute lip-sync test**.

| Scene entered | 60 before carry, drift ms | 60 carry, drift ms | Unlocked carry, drift ms |
|---|---:|---:|---:|
| 1 | +0.00 | +0.00 | +0.00 |
| 2 | -14.50 | +0.25 | -11.25 |
| 3 | -30.75 | -14.75 | -7.25 |
| 4 | -54.75 | +5.00 | -14.25 |
| 5 | -58.00 | -2.75 | +5.00 |
| 6 | -63.00 | -3.00 | +1.75 |
| 7 | -53.50 | -3.00 | -5.25 |
| 8 | -87.00 | -8.25 | -12.25 |
| 9 | -96.75 | -3.25 | +0.50 |
| 10 | -112.75 | -4.75 | -11.25 |
| 11 | -129.25 | +2.50 | -15.25 |
| 12 | -143.00 | -15.50 | -4.75 |

Measured final drift is **-143.00 ms before**, **-15.50 ms with carry at 60**, and **-4.75 ms with unlocked carry**.
The raw first/last offsets against the 30-fps waveform were +152.50/+9.50 ms, -22.50/-38.00 ms and
-10.75/-15.50 ms respectively. Correlations were 0.973..0.984, 0.912..0.969 and 0.894..0.954; maximum
packet-bracket excess was 4.54 ms. These results support repaired cumulative timing on this route.
The scene observer is a logic event; the 0.1 s frame dumps alone do not give frame-exact picture timing.
Burst frame captures and real-device/display timing remain separate gates.

Evidence: `av30-clock-v6-av-comparison.json`, `analyze_av.py`, `snapshot-audio-v6-hashes.json`,
`av30-clock-v6`, `av60-before-clock-v6`, `av60-carry-clock-v6`, `av120-carry-clock-v6`. The earlier sparse
probe logged only every 76,800 samples, despite its intended 4,800-sample modulus; its 120..240 ms timestamp
bracket excess made it unsuitable for A/V claims. Its rejected results remain in `av-comparison.json`.


### Windows device probe limitation

An isolated Windows baseline build compiled and ran against the real VB-Cable waveOut sink. Its 133-second
WASAPI loopback was 48 kHz stereo float, RMS 0.018228 and peak 0.271118. Four two-second waveform probes from
our pre-device PCM matched loopback with correlations 0.952..0.995 and consistent sample offsets; a repeated-music
excerpt was ambiguous and is not a timing calibration. This establishes audio from this game process reaching
the VM endpoint, not speaker/display sync or glitch-free playback.

The exported frame sample was black and the baseline obtained no 12-cut chase trace. The private VM inputs still
lacked 23 BK2 movies; the cause of the missing route/picture was not isolated. An earlier asset-load crash was
caused by copied macOS `._` sidecars; only those six files in this unit's private VM input copy were removed.
Dynamic-before and carry executables both compiled after forcing recompilation of changed generated sources
(preserved copy timestamps must not let Ninja reuse baseline objects). Their SHA-256 receipts and compile logs
are retained. The dynamic device run then timed out after 600 seconds waiting for another unit's game, which
was left untouched. Windows dynamic gameplay/A/V acceptance is therefore OPEN.

These private probes allowed real waveOut audio while headless and preferred cached readback memory; neither
capture-only change is included in the production FPS patch. Evidence exported to the Mac:
`windows-evidence/{receipt.json,console.log,audio.wav,loopback.wav,loopback.log,loopback-analysis.json,
loopback-source-matches.json,build-before-receipt.json,build-carry-receipt.json,build-before.log,build-carry.log}`.
No VM resource, firewall, credential or other unit's files were changed.


### Frame-dump check of six visible cuts

The v8 thumbnail probe writes 320x180 PPMs from the real GPU readback and timestamps their completion.
Consecutive presents around camera changes were inspected visually in all four runs. Six common hard cuts
(4, 6, 7, 8, 10, 12) were retained before calculating picture/audio offsets. Weapon flashes, fast foreground
motion and coarse/nonconsecutive pairs made the other automatic maxima unsuitable; those rows were excluded
consistently, with raw captures and the selection policy retained. The full-size v7 burst was rejected because
its readback/output disturbed frame timing. Capture helpers and thumbnail changes are private diagnostics only.

These offsets use the **first completed readback containing the new shot**, matched against 30-fps audio
with packet/sample timestamps. Negative means picture earlier than the corresponding 30-fps reference.
They include render/readback latency and are not physical display/speaker offsets. The chase averaged
29.96 fps (reference), 57.47 (before), 59.33 (carry) and 37.97 (unlocked cap 120) during these capture-heavy runs.
The last mode is a variable-rate A/V check, not evidence of 120 fps presentation.

| Visible cut | Before carry, offset ms | Carry 60, offset ms | Unlocked carry, offset ms | Carry drift gate |
|---|---:|---:|---:|---|
| 4 | -58.25 | -22.75 | -37.00 | PASS: each within 33.3 ms of its first retained cut |
| 6 | -50.00 | -15.25 | -16.00 | PASS: each within 33.3 ms of its first retained cut |
| 7 | -44.50 | -15.25 | -25.25 | PASS: each within 33.3 ms of its first retained cut |
| 8 | -69.00 | -25.25 | -40.50 | PASS: each within 33.3 ms of its first retained cut |
| 10 | -98.50 | -20.50 | -61.75 | PASS: each within 33.3 ms of its first retained cut |
| 12 | -97.25 | -27.75 | -66.50 | PASS: each within 33.3 ms of its first retained cut |

From visible cut 4 to cut 12, accumulated picture/audio drift was **-39.00 ms before**, **-5.00 ms with
carry at 60**, and **-29.50 ms with unlocked carry**. The before run exceeded one authored tick at cuts 10/12;
both carry runs stayed within that drift gate on all six retained cuts. Correlations were 0.829..0.985,
and packet-bracket excess stayed within 4.96 ms. Frame quantization, startup/queue phase, runtime hitches and
the unmeasured real output device remain material limits; this is not a blanket cutscene-sync acceptance.

The implementation repairs lost fractional scene time without whole-30-fps stepping. Enabling it by default
still requires a windowed, real-device repeat, pause/seek/scene-end checks and independent review.
No audio-clock correction is added on top of AUDIO-006's timer fix in this unit.

Private evidence: `verified-pixel-cuts.json`, `pixel-selection-policy.json`, `pixel-cut-timestamps.json`,
`burst30-v8-picture-av-comparison.json`, `analyze_pixel_cuts.py`, `analyze_av.py`,
`snapshot-audio-v8-hashes.json`, per-run `burst-requests.json`, `process.json`, `receipt.json`,
`console.log`, `audio.wav` and frame PPMs. The reviewed image galleries are also retained.

### Open acceptance and observed limitations

- No first-combat comparison or successful Legion summon/recall/Sync Attack was obtained. The second route
  exploration reached the highway-rescue area; a later 600-second attempt logged a normal quit at 117.109 s
  before its planned movement. The cause of that quit was not established; no FPS regression is inferred.
- Physical Mac display/audio timing is blocked by the enforced headless policy. Windows dynamic device capture
  was blocked by another active unit and the baseline did not yield a valid picture/scene trace.
- Unlock is capped at 480 for timing safety, and rates below 15 can still lose world time at the 2-tick ceiling.
  Credits, minor camera counters, full battle timing, pause/seek, final-scene behavior and long sessions remain open.
- The final FPS NSO bytes match the native tested snapshot after stronger input guards. The combined current
  main runtime is integration/syntax tested; the GPU runs use the explicitly identified private snapshots.
- The one-command builder/cache/packaging integration and independent other-model review belong to follow-ups.


### Repeat with the final pacing timestamp

After the diagnostic-stall correction, `dynamic60-final-v9-route` completed **140.178 s, exit 0** on the Mac.
Title/chase/on-foot rates were **59.998 / 58.249 / 55.550 fps**; measured world ratios were
**0.99999987 / 0.99865536 / 0.99999990**. The 15-tick ZL buffers lasted **493.758 / 495.307 ms**,
and maximum camera-equation error was **4.74e-8**. Cut 1 -> 12 took **20.592123 s**, within one authored tick
of the 30-fps reference's 20.600017 s. Chase hitches still reached the inherited 2-tick ceiling
(worst one-second ratio 0.962600); the 0.1345% mean shortfall is not hidden by the HUD's FPS-derived speed.

This repeat used the final pacer and identical carry NSO, plus the described private observers. Snapshot SHA-256:
`98a2e282b53d9342f6407728014d85a3fa9b9a2df74c3274f3142ecedeb2f89a`.
The NSO remains byte-identical to the earlier tested carry input after stronger original-word guards:
`4c1eb4a0295341711fbea366e4dd688310a24c15d11daa712db1623c8ed6deed`.
Evidence: `snapshot-final-v9-hashes.json`, `dynamic60-final-v9-route/{process.json,receipt.json,console.log}`,
`native-comparison.json`. A/V was not repeated after this last pacing hardening; its real-device gate remains open.
