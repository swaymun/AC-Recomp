# Private File-by-File survey

PLAYTHROUGH-013, 2026-10-20. **Scene coverage is partial: all Windows Files 01–12;
Mac File 12 HQ, plus reused opening-prologue samples. No complete File/combat pass is claimed.**
Windows File 03 has reference-supported missing/fragmented world geometry. Mac File 12 has severe
scene corruption and a separate GPU-hang repeat. File 03 Loss and File 04 Identity/White/Arm have
unreached loading-stall samples. All 12 numbered Windows Files have at least one observed scene checkpoint; many other
checkpoints, all complete Files/combat paths and the epilogue remain unverified.

All game data, saves, executables, captures, contact sheets and raw logs stay outside Git under
`.local/units/PLAYTHROUGH-013/` (abbreviated **U/**), and on
the VM under `C:\acr\units\PLAYTHROUGH-013\`. This document contains no game images.
Independent review of the exact final head remains the parent's gate; this brief forbids nested
worker reviews. No owner-installed files/saves, other units, cloud resources or public repository
were modified. No release or launch acceptance is asserted. Closeout at **11:56:24Z** found **zero** unit
game/Python processes on Windows, zero copied survey-game processes on Mac and zero remaining
downloaded-reference directories (`closeout-checks.json`). Private survey outputs are retained.

## Per-File status

“Reached” means an observed selection/identity followed by an actual loaded scene. It does not
mean every case, material, combat sequence or the whole File passed. Save-menu/result labels alone
are insufficient: the completed save already contains CLEAR results.

| File | Name | Windows observation | Mac observation |
|---|---|---|---|
|01|Startup|Reached Rush prologue and highway motorcycle tutorial; sampled lab shading matches original footage|Reused lab samples only; explicit chapter-entry marker unverified|
|02|Awake|Reached Initiation title and Neuron Command Room; no confirmed visual defect in sampled sequence|Not reached|
|03|Link|Reached Arrow/Astral Plane, **world geometry failure**; Loss stalls at 80% on two binaries|Not reached|
|04|Siege|Reached Regroup/Harmony Square and forward movement; Identity, White and Arm stall at 80%|Not reached|
|05|Accord|Reached Contact station; player/NPC/world animate; coat-material candidate only|Not reached|
|06|Complicit|Reached Deceit/Pursue Douglas; large tan planes/fragmented world geometry; reference pending|Not reached|
|07|Wild|Reached Caught cell-room dialogue with Akira; Warfare stalls at 80%|Not reached|
|08|Peace|Reached Axe/Find Akira; variable pink world-visibility candidate; camera responds|Not reached|
|09|Salvation|Reached Overflow/Stop the homunculus; early visibility improves in later frames; Showdown and Alert stall at 80%|Not reached|
|10|Madness|Reached Hal/Olive safehouse; large bright floor region is an unconfirmed candidate|Slot label recognized only|
|11|Reckoning|Reached Uprising cutscene and Ark/ARI interior; forward traversal from 40 m to 10 m; ending untested|Not reached|
|12|Rebirth|Reached HQ and PC File Select menu|Reached HQ with severe corruption; separate GPU hang during load|
|—|Epilogue|Not reached; no separate numbered File asserted|Not reached|

Names, first checkpoints and location planning use only the
[GameFAQs contents/walkthrough headings](https://gamefaqs.gamespot.com/switch/258621-astral-chain/faqs/78145/introduction).
First-entry targets were Rush/highway, Initiation/Neuron, Loss/infirmary, Identity/HQ,
Gifts/ARI, Communication/Zone09, Caught/cells, Redemption/Grand Avenue, Declaration/Harmony Square,
Fugitives/safehouse, Uprising/ARI and Rebirth/Olive cases. Later checkpoints were prioritized when
openings stalled, to cover more distinct environments efficiently.

## Ranked distinct issues

1. **Mac File 12 scene corruption and a real GPU hang, on the copied older build.**
   `U/mac-file12-confirm/data/frames/01800.ppm`, **65.221 s**, first shows corrupted HQ;
   `02760.ppm`, **97.330 s**, shows white/magenta/color garbage across character and room while
   PC/Legatus Terminal and the Olive-cases HUD remain readable. This sample ended at its
   **100.131 s** supervisor limit, code 0, peak **4.52 GiB**. A separate pristine-save repeat,
   `mac-file-select/`, naturally exited **4** at **59.988 s**: `console.log:7198` reports
   **710,643,880 bytes** uploaded in one submit;7199 is Metal `Caused GPU Hang Error`;
   7200–7201 report `GPU hang (vkWaitForFences): stopping`. Last frame01680 is at **56.696 s**.
   This is actual driver/runtime hang evidence. The executable is a private owner-build copy,
   **not** the graphics owner's latest fix. Reproduce this checkpoint on that final candidate.
2. **Windows File 03 / Arrow has missing/fragmented world geometry.**
   `U/phase-v2-f03-c05-r2-file03-ch05/data/frames/06000.ppm`, parent **482.485 s**, shows the
   “Follow the Legion” HUD/player but much platform/wall geometry is missing or fragmented.
   [Original Switch spawn at 02:03:09](https://www.youtube.com/watch?v=xcx_xuK96VY&t=7389s)
   has a broad tiled platform, wall and red formations. Pastel sky color itself is expected;
   the missing world is the observed failure. Reference 360p/female-player differences limit fine-detail
   comparison. The map and System menus respond; this is a visual failure, not a GPU hang.
   **33 valid frames**, **412.672 s** mix, and **zero** matched diagnostic faults in the interval
   show why clean logs cannot clear rendering. RENDER-009/NVN owners should reproduce; this unit
   did not duplicate root-cause work. Sample uses the newer `f3ca818a…` binary below.
3. **Two Windows C++ exceptions during initial completed-save loading.**
   `U/file-01-opening-r1/console.log:2356`: `CRASH: exception e06d7363 at KERNELBASE.dll+c7d9a`.
   Natural exit **3765269347 /0xE06D7363** at **135.484 s**,11 frames; context includes
   `main+9c8a30` and `main+3e001c (nnMain+e1c)`. `file-01-opening-r2/` repeats at **130.625 s**.
   Both occur during initial **File 12 HQ load**, before intended File 01 selection. They are
   not File 01 scene crashes. They occurred in paired loading runs; concurrency/memory is a
   hypothesis, not a diagnosed cause. Later capture jobs are serial.
4. **One alternate Windows executable fails before rendering.**
   `U/win-completed-probe/`, a 68,409,344-byte WIN-VALIDATE-003 copy, exits 1 at **0.547 s**;
   `console.log:23`: `FATAL: logger: missing live process`. Zero frames/audio. Treat this as
   binary/bootstrap compatibility evidence, not a File 12 scene defect. A separate retired baseline
   startup probe logs **38 stub occurrences across both logs** (including missing `hid` service,
   `hid` commands 128/101/121 and applet/Logger commands); none reaches a scene. The fresh
   replay intervals have zero matched stub/missing-shader messages. These counts do not prove
   every runtime service or shader path is implemented.
5. **Chapter-specific 80% loading stalls, without a proven hard hang.**
   File 03 Loss: old candidate **44 frames/197.785 s** marker interval; newer candidate
   **49 frames/225.989 s**, also never enters the scene. File 04 Identity: **90 frames/388.471 s**;
   newer Arm: **56 frames/279.766 s**. These durations include entry menus, not solely 80% time.
   The last samples remain at 80% with animated waveforms; host presents continue around 30 fps.
   File 04 White, File 07 Warfare and File 09 Showdown/Alert also remain at 80% in their
   sampled intervals; their alternative Regroup/Caught/Overflow entries reach scenes.
   All tracked diagnostic counts are zero. Last Loss opens include a movie, event package and
   stream WEM; White and Showdown also end after `event/event.pkz` and
   `sound/stream/921830580.wem` opens (`loading-last-opens.json`). These are debugging leads,
   not proof of a blocked file or a cause. Arrow entry proves File 03 is not wholly
   unreachable. All these attempts ended by requested/supervised stops, not unexplained crashes.
6. **The default 8 GiB process guard blocks the completed save.**
   `U/win-single-trigger/` exits 3 at **117.562 s**: `8.02 GB is over the 8.0 GB limit`.
   Loading frame01800 is at **98.187 s**. This is a protective resource stop. With a 12 GiB guard,
   `win-file12-12gb/` reaches HQ at02040/**157.344 s**, then PC/File Select at03000; peak
   **10.42 GiB**, steady about 7.43 GiB. Before retry, VM free physical memory was
   **27,308,400 KiB /33,550,696 KiB** total. Subsequent serial runs use a 16 GiB process guard;
   per-process guards do not establish a safe VM-wide parallel budget.
7. **Audio signal candidates; device delivery remains unverified.**
   Full `tools/audio_glitch_check.py` on File 01 lab mix (**316.672 s**) finds **680 click
   candidates**, **205 rail-run events**, **444 left+489 right=933** rail-clipped samples,
   no silence events; first click at mix **1.813396 s**. These can include intentional
   transients. Bike and File 02 intervals each have 6 click candidates and zero rail samples.
   `U/file01-lab-audio-glitch.json` and per-phase `audio-glitch.json` retain exact signal times.
   Headless Windows `platform_win.cpp:327–328` returns before XAudio2 creation, just as Mac
   headless/mute closes its device. Logs say `no audio device, timer pacing only`; VB-Cable
   cannot override this branch. Host probe is inactive. Do not interpret zero host counters
   as measured zero underruns. Real-device timing/A-V sync/listening belongs to AUDIO-WIN-010.
8. **Lower-confidence observations and rejected candidates.**
   File 10 safehouse02520/**231.829 s** has a large bright floor region; no matched reference
   establishes a missing texture. File 05 player coat has triangular patches, but public-save
   costume customization is unknown. File 01 coat/face patchiness and animated red credit glyphs
   match [original footage](https://www.youtube.com/watch?v=Sn1WRBm9iG8&t=194s) and were cleared
   as standalone defects. Highway black/yellow pieces at26880 are textured impact debris.
   Black title/fade/loading samples are not failures. An older RENDER-009 Windows baseline
   (`win-render-load/`) produced no first frame in 160.063 s and was retired as a startup-stall
   candidate, not a proven hang.

   Additional reviewed candidates: File 06 `04920.ppm` at parent **416.062 s** shows large tan
   planes and distorted structures around the player/yellow drone. Local Parakeet fallback located
   nearby original rooftop footage (captions disabled), but its progress/camera state differs;
   this is not a reference-confirmed defect. File 08 `05520.ppm` at **434.594 s** shows pink world
   occlusion/fragmented floor while HUD/player remain visible. A 1 s RX22000 camera pulse is logged;
   parent `v2-f08-c05/snapshots/05640.png`, **443.625 s**, is after that pulse and shows a changed
   view. That extra frame is outside the closed 25-frame segment. A nearby [original Find Akira view at 07:50](https://www.youtube.com/watch?v=UE8fMs91q5Y&t=470s)
   has a broad coherent platform. Exact spawn/camera matching remains open; intended pink sky alone
   is not the defect candidate. Captions were disabled, so this was a visual-only comparison. File 06/08 candidates must be distinguished from deliberately shifting Astral Plane scenery.
   File 09 Overflow `03600.ppm` at **247.547 s** initially shows pink occlusion/fragmented
   floor without HUD. By `04920.ppm`/**346.766 s**, the active Stop the homunculus HUD and
   substantially more world geometry are visible. Streaming, transition or intended world motion
   have not been ruled out: this is not a confirmed persistent defect. RX18000 for 1 s was
   acknowledged; camera response is unproven.

   File 07 Caught cell dialogue is visible in `phase-v2-f07-c01-file07-ch01/data/frames/05640.ppm`
   at parent **386.641 s**; cell bars, player/Akira and subtitles render without the Mac-style
   full-scene corruption. Clothing/armor mottling remains a candidate pending a matched reference.
   All downloaded reference media, audio and transcripts have been deleted; written observations remain.

## Private evidence index

Final aggregate: **32 evidence records, 977 valid sampled frames, zero truncated frames,
6,218.752 s of mixed audio, 30 per-run sheets and 12 per-File sheets**. Frame totals include
**39 reused Mac prologue frames**, selection and loading. A record can be a sliced interval
from an existing run; 32 records does not mean 32 distinct native launches. All 12 numbered
Windows Files have a reviewed scene checkpoint, without full-File/combat acceptance.
`final-counts.json`, `final-manifest.json` and `final-survey/summary.json` retain the numbers.

Paths below are relative to U/. Counts include selection, loading and scene frames; they are
not counts of gameplay-only frames. Every transferred ZIP is checked against per-file SHA256.
Contact-sheet JSON sidecars map up to 24 tiles to exact source PPMs.
The combined `final-survey/file-NN-contact.ppm` sheets group all valid run frames for that File;
they include menus/loading and do not establish scene reachability.

| File/checkpoint | Private interval/run | Frames | Mix seconds |
|---|---|---:|---:|
|01prologue|phase-p01-file01-ch01|45|316.672|
|01highway|phase-p02-file01-bike|8|118.016|
|02Initiation|phase-s02-file02-ch01|17|147.456|
|03Loss, old/new|phase-auto-f03-c01-file03-ch01 / phase-v2-f03-c01-file03-ch01|44/49|189.696/217.856|
|03Arrow|phase-v2-f03-c05-r2-file03-ch05|33|412.672|
|04Identity/Arm|phase-auto-f04-c01-file04-ch01 / phase-v2-f04-c06-file04-ch06|90/56|372.736/280.064|
|04Regroup (scene reached)|phase-v2-f04-c04-file04-ch04|22|240.384|
|04White|phase-v2-f04-c02-file04-ch02|56|274.432|
|05Contact|phase-v2-f05-c07-file05-ch07|31|211.456|
|06Deceit|phase-v2-f06-c09-file06-ch09|22|243.712|
|07Caught|phase-v2-f07-c01-file07-ch01|31|242.176|
|07Warfare (loading only)|phase-v2-f07-c04-file07-ch04|55|275.200|
|08Axe|phase-v2-f08-c05-file08-ch05|25|238.848|
|09Showdown (loading only)|phase-v2-f09-c05-file09-ch05|56|276.736|
|09Overflow (scene reached)|phase-v2-f09-c03-file09-ch03|24|208.384|
|09Alert (loading only)|phase-v2-f09-c02-file09-ch02|55|263.424|
|10safehouse|win-file10-direct|23|234.752|
|11Uprising|win-select-01 (actualFile 11)|47|391.680|
|11Ark/ARI|phase-v2-f11-c03-file11-ch03|34|239.104|
|12HQ, Windows|win-file12-12gb|27|282.624|
|12HQ, Mac|mac-file12-confirm|23|86.272|

`final-survey/` contains the combined reviewed aggregate; each newly collected phase also
has `analysis/contact-00.png` and JSON/Markdown reports. Segment markers and initial per-phase
analyses retain the driver's pending-review state. `final-manifest.json` and per-phase
`human-review.json` hold the later reviewed decisions; raw markers, captures and logs stay unchanged.
Raw parent receipts, controls, frame
observations and PCM sidecars remain beside their private run. Reused RENDER-009 Mac baseline/fixed
lab samples contain 20+19=39 frames from 85.210/85.199 s runs; those are reused evidence, not fresh
runs or proof of the latest fix. Full-File traversal, gallery models and epilogue remain open.

Ark selector01920 leads to ARI/Follow Akira04080 at parent **268.094 s**. Three 2 s
LY30000 pulses advance the target distance from **40 m to 10 m** by05880/**362.344 s**.
Akira and fallen figures become visible; the supervisor ends before reaching Akira. No final
battle or ending is claimed.

Regroup selector02760 is followed by Harmony Square04080 at parent **313.765 s**,
then a closer street/NPC view05280 at **444.078 s**. Four acknowledged forward pulses
(1.5 s LY20000 and three 2 s LY30000) total **7.5 s**. This is native synthetic-input
traversal evidence; physical-pad and whole-File acceptance remain open.

## Saves, binaries and method

Runtime save patches confine/map/flush files; they do not define progress fields/checksums.
No guessed save bytes were edited. The [public NX_Saves index](https://github.com/Viren070/NX_Saves/blob/main/index.md)
provided the completed save, retained only privately. Archive 246,316 bytes, SHA256
`b95e872e16424fec4f5082c5eff68afd8cc89489c80ec76a61b2899005380076`;
GameData.dat 14,404,544 bytes plus eight SlotData files 1,382,016 bytes each. The guest recognizes
slot A/File 12 and slot B/File 10 and exposes Files 01–11 in replay. Each run copies the pristine save.
Recognized menus and some working checkpoints do not establish full save-version compatibility;
loading stalls may involve runtime or save/progress compatibility, and remain undiagnosed.
The owner-installed app/assets were read-only sources; owner's saves were never used in round2.
Windows UPLOAD_OK was observed at07:17:30Z before its game runs.

Early working Windows executable: WIN-BUILD-002 player-native copy, **68,095,488 bytes**.
Newer candidate: read-only AUDIO-WIN-010 copy at09:40:53Z, **68,101,120 bytes**, SHA256
`f3ca818ad3d031571609114bdc55e4bc7286c6461aff0bcf5a8f49539f09e942`.
`audio-candidate-provenance.json` proves source/copy equality. These binaries were not built from
this survey-tool commit, and their results are not exact-build acceptance for the eventual merge.
Mac uses a private app copy, headless/muted through `mac-game-lock` and nice; no later Mac game
launch followed the GPU hang. Windows uses actual VM/NVIDIA execution; input is synthetic. Live hardware observation at
11:32:13Z records Apple M5 Pro and NVIDIA L4, driver 596.86, WDDM, 23,034 MiB
(`hardware-observation.json`). These identities do not establish device-audio or physical-pad acceptance.

The standard-library tool provides isolated preparation, bounded runs/batches, frame/log/WAV
analysis, contact sheets, explicit stop requests and chapter segment extraction:

```sh
python tools/playthrough_survey.py prepare --run PRIVATE_RUN --assets PRIVATE_ASSETS --save PRIVATE_SAVE
python tools/playthrough_survey.py run --run PRIVATE_RUN --binary PRIVATE_BINARY \
  --seconds 1200 --every 120 --memory-gb 16 --controlled-pad --trace-fs --record-input
python tools/playthrough_survey.py pad --run PRIVATE_RUN --buttons A --hold 0.2
python tools/playthrough_survey.py begin-segment --run PRIVATE_RUN --out PRIVATE_SEGMENT \
  --file 03 --chapter 5 --selection-frame 3120
python tools/playthrough_survey.py end-segment --segment PRIVATE_SEGMENT --end-frame 6960 \
  --reach-evidence "observed File 03 Arrow selection and loaded FollowLegion scene"
python tools/playthrough_survey.py stop --run PRIVATE_RUN --reason "bounded sample complete"
python tools/playthrough_survey.py analyze PRIVATE_MANIFEST.json --out PRIVATE_SUMMARY
```

Use profile Default for prepared saves. Only
immutable asset directories are linked; writable roots/saves are local. Every Mac game command
acquires the required lock; Mac batches allow only one game. Do not bypass the lock wrapper.

`build-pad-proxy --out NEW_PRIVATE_DIR --compiler INSTALLED_CLANG_CL --vsdevcmd INSTALLED_VSDEVCMD`
builds original app-local XInput1.4/ordinal2 adapter code. Place an unchanged private executable
and SDL DLL beside it. Reports are bound to an exact PID acknowledgment, expire to neutral and
release in a finally block. No system DLL, global/virtual controller or desktop key is changed.
`pad` uses a per-run OS writer lock and records button/axis input. Four native Windows fixture
cases passed: A+ZL mapping, expired/malformed neutralization and disconnected slot1.

A private Mac-side Vision OCR driver verifies headless PPM menu states. OCR is a navigation aid;
human scene review remains mandatory. Verified bootstrap: titleZL+ZR; Load; slotA; load data;
play-style confirmationLEFT,A; HQ PC A; File Select A. L/R pages Files, DOWN chooses chapters.
Standard entry is A,A,LEFT,A. [Unchained](https://www.nintendo.com/jp/switch/ab48a/dual-action/battle.html)
entry from the replay modal is A,DOWN,A,UP,UP,A,LEFT,A; actual UI4440/4560 in the Arrow run
confirms Unchained/unlimited revivals. Subsequent fresh-save samples used it. These are not Standard
combat/60fps timing acceptance measurements.

Segments preserve selector proof plus post-marker frame mtimes, byte-offset log slices and the
WAV frame interval, without modifying source saves/captures. Times in `frames.jsonl` are approximate
parent-process wall anchors (about 0.5 s polling), not guest PTS; frame names are present indices.
Time limits, static menus and loading percentages alone never prove a hang. Diagnostics count
occurrences in both logs, which can duplicate one event. Reached manifests require nonempty
observed proof; driver intent/directory labels never establish coverage.

A duplicate local driver collided before File 03 selection in `v2-f03-c05`; native prepare refused
a second root. That attempt was explicitly canceled at 144.046 s and excluded. The clean r2 captured
Arrow. Its later manual menu pause caused a 45 s SSH-driver timeout; raw logs and the independently
closed scene interval are retained. Abort/report CLEAR values inherit the completed save and
are never counted as fresh completion. Unstarted early sweep jobs are cancellations, not failures.
The private sweep now holds an OS master lock. The first controlled01 process predates explicit
stop support; its PID-checked `stop-intent.json` explains its deliberate 1936.516 s/code4294967295 end.

## Audio timing and verification gates

The quick analyzer uniformly samples at most 250,000 PCM16 values per mix for peak/RMS/silence/
near-clipping candidates; short glitches can be missed. Full signal reports reuse the existing
`tools/audio_glitch_check.py` at nice 10. No audible-output/device-delivery claim follows from them.

Newer Loss PCM: 10,212 complete blocks span 217.881982 s against 217.834667 s sample starts:
**−47.315 ms /−217.161 ppm**,19 deliveries more than 5 ms late. `timer-production.json` derives these
from PCM records wholly inside the extracted WAV, subtracting source frame offsets while retaining
original `source_frame`/monotonic timestamps. It measures production, not hardware playback. Derived PCM-only reports do not establish a host
backend: the underlying analyzer may default its backend label when no host header is supplied;
`host_probe_active:false`, unavailable device clock and explicit `device_timing_verified:false`
are the acceptance-relevant fields.
Host probe inactive means host-event coverage unavailable, even when cumulative counters are zero.
Ark has 11,208 complete PCM blocks over 239.082325 s; production drift is **+0.342 ms /+1.429 ppm**,
with five deliveries more than 5 ms late. Its full signal scan has **8 click candidates, zero rail
clipping**. Neither result verifies delivery to a physical/virtual audio device.

`python3 -m unittest discover -s tests -p 'test_playthrough_survey.py'` passes **22** offline tests (latest post-rebase result in `U/verify-final.log`):
synthetic diagnostics/PPMs, conservative reach/hang classification, real fixture children/timeouts,
isolated save batches, segment extraction, controller release/locking, stop receipts and multi-run per-File contact aggregation. Windows
also passes the independent-process writer rejection/recovery test (**1 test, 0.510 s**), and the
four native adapter fixtures. These test tooling, not complete gameplay. All actual game observations
above come from native Mac or Windows VM execution, not fixture tests.

Open gates: untested checkpoints/materials, full traversal,
combat and epilogue; rerun visual failures on the final graphics build; device-audio/listening;
physical-controller behavior; independent review of the exact committed head; final served/player
acceptance. Current coverage is not a percentage of game completeness or release readiness.
