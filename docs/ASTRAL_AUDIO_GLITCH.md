# Audio glitch measurements (AUDIO-006 / AUDIO-WIN-010)

`tools/audio_glitch_check.py` analyzes recordings without external Python packages.
Its signal events are candidates, not an assertion that a musical transient or a
pause is a defect. Original WAVs, game captures, generated code and saves stay in
ignored private storage.

## Run the detector

```sh
python3 tools/audio_glitch_check.py recording.wav -o report.json
python3 tools/audio_glitch_check.py recording.wav --timestamps recording.wav.jsonl -o report.json
```

On Windows, the same command can use `py` or `python` in place of `python3`.
Existing WAV recordings need no sidecar for signal analysis.

The reader supports little-endian RIFF integer PCM (8, 16, 24 and 32 bits), IEEE
float (32 and 64 bits), and Windows WAVE_FORMAT_EXTENSIBLE PCM/float. Unknown RIFF
chunks are skipped. Compressed WAV, RF64, big-endian RIFX, non-finite floats and
truncated sample data fail with exit code 2. A valid report returns 0 even when it
contains candidates; an event count is not an automated pass/fail judgment.

The JSON includes:

- `rms_over_time`: 10 ms RMS windows, per-channel RMS and combined dBFS (`null`
  means negative infinity). `--window-ms` controls resolution.
- `events`: every detected signal candidate with zero-based frame and second
  offsets. Channels are zero-based. Silence gaps require every channel
  below −60 dBFS peak amplitude for at least 20 ms, with activity above −45 dBFS
  peak amplitude on both sides within 250 ms. Leading/trailing silence and one
  silent channel are excluded. Runs are tracked per frame across RMS windows, so
  a 1,024-frame dropout is detected even when it straddles the window boundaries.
- `click`: adjacent-sample deltas exceeding both 0.2 full scale and eight times
  the local channel's median absolute delta. Outliers within 2 ms are grouped.
  This avoids treating a clean high-frequency tone as crackle, but percussion
  and edit boundaries can still match. `--delta-floor` and `--delta-ratio`
  change those thresholds.
- `clipping`: consecutive samples at the positive or negative PCM rail, or at
  or beyond ±1 for float input, with exact sample counts per channel. Full-scale
  samples are measurable; the audible cause remains a candidate.
- `timing`: effective production rate, cumulative drift and every block arriving
  more than 5 ms later than its sample count predicts. The comparison uses block
  starts relative to the first captured sound, excluding boot time and the
  duration of the final block. It is a delivery measurement, not calibration of
  the hardware sample clock. Without timestamps it explicitly reports
  `unavailable` rather than guessing drift from the WAV header.
- `host_events`: callback starvation, with exact missing frame counts, callback
  monotonic timestamps and time relative to the first captured PCM block. Startup
  empty-queue events are classified separately. These times need not equal WAV
  positions because the WAV excludes host-generated zeroes. Lost telemetry
  counts and a truncated final JSONL line are explicit in `timing`.

## Capture and patch composition

Set `NX_AUDIO_DUMP=/absolute/private/audio.wav` and
`NX_AUDIO_DUMP_SECONDS=0` for a full session. The existing stream remains
48 kHz stereo PCM16 from the first nonzero block. Its companion
`audio.wav.jsonl` records `{type:"pcm",frame,frames,monotonic_ns,source}`;
source 1 is AudioOut, source 2 is the renderer mix. Additional fields carry
cumulative host counters. A killed process can leave up to about 0.25 s outside
the WAV header's last fix-up; timestamps beyond that declared frame span are
excluded from the drift calculation. Only an incomplete final JSONL line is
ignored, and that is reported.

`astral-audio-dump.patch` provides the sidecar and a bounded single-producer,
single-consumer diagnostic queue. `astral-audio-fix.patch` instruments Mac/Linux
SDL callbacks. The callback does no diagnostic allocation, file I/O, waits or
logging. Queue overflow increments `lost_host_events`; a partial trace cannot
claim complete host-event coverage. Headless and `NX_MUTE` use timer pacing,
so they cannot validate audible device delivery. AUDIO-006 did not instrument
Windows XAudio2. The AUDIO-WIN-010 extension below adds processing-pass and
sample-cursor diagnostics; a pass-entry deficit still needs loopback evidence
before it can be called a playback dropout.

The series files are owned by other units. SERIES-INT-012 added the overlay to
`series.macos` and `series.linux`. The Windows integration owner must also place
this line immediately after `astral-audio-dump.patch` in `series.windows`:

```text
astral-audio-fix.patch
```

The private build applied the overlay manually. All additions are Astral-strict;
the default profile's preprocessed audio source remains unchanged.

## Evidence and remaining gates

The timer fallback used a relative wait per packet. On this Mac, 2,928 sounding
1,024-frame blocks exposed 62.443 s of PCM against 71.595 s of monotonic elapsed
time: **−9.152 s drift (−127,835 ppm)**. The new `AudioClock` uses absolute
cumulative sample deadlines, resetting on stop and rebasing after a delay larger
than one packet. The second 75 s headless run measured 69.739 s of PCM against
69.789 s elapsed: **−0.0502 s (−719 ppm)**, a 99.45% reduction in accumulated
deficit. This fixes timer fallback drift; it does not change the successful
hardware-device submission path. Remaining stalls and rebases remain visible.

The deterministic C++ regression advances 1,000 5 ms packets with 1 ms of work
after every wake: the resulting deadline is exactly 5 s rather than 6 s. It also
checks stop/reset and rebasing after an idle gap. The composed HLE still releases
and dumps the same synthetic AudioOut packets with the fix applied.

## Measured Mac sessions

Host: Apple M5 Pro, arm64 macOS. These are private native game executions with
real SDL output for windowed sessions, not synthetic audio. All sounding sessions
used AudioOut (`audio: device output (48 kHz stereo s16)` and `dumping the AudioOut
output`), not the renderer mix.

| Run | Captured PCM | Delta-outlier groups | Rail runs / clipped samples L,R | Silence candidates | Late PCM blocks | SDL zero-fill callbacks | Production drift |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| baseline-30, windowed, 260 s bound | 255.744 s | 640 | 171 / 259,530 | 0 | 5 | 0 | +2.027 ms |
| baseline-60, windowed, 260 s bound | 256.768 s | 134 | 0 / 0,0 | 1 | 160 | 0 | +0.345 ms |
| fixed-30, windowed, 300 s bound | 297.984 s | 37 | 0 / 0,0 | 1 | 52 | 0 | −0.405 ms |
| fixed-60-load, windowed, 300 s bound | 295.936 s | 683 | 149 / 394,396 | 0 | 1,934 | 0 | −24.261 ms |
| baseline-timer, headless, 75 s bound | 62.464 s | 0 | 0 / 0,0 | 0 | 234 | N/A | −9,152.351 ms |
| fixed-timer, headless, 75 s bound | 69.888 s | 0 | 0 / 0,0 | 0 | 12 | N/A | −50.199 ms |

The stress run used 18 owned `yes` workers at nice 10. A 41 s process sample
measured 929.4% aggregate CPU (about 9.3 cores), in addition to the game and other
host work. It recorded **13,937 host callbacks, zero missing frames and zero lost
host events**. Its 1,934 late PCM blocks included a 675.166 ms late arrival at 0.384 s of PCM.
The SDL callback inserted no zeroes. A downstream device gap is still possible if
the callback itself is delayed; zero-fill counters alone cannot rule that out. The last
visible scene was the lab film; the window became inactive and frame readbacks
stopped after 60 s. Attempts to advance did not visibly change it. This is
explicitly audio stress coverage, not a verified chase under load. All 18 load
workers were terminated and reaped; every game supervisor verified cleanup.

WAV duration and timestamp span can differ slightly after a killed writer because
WAV and JSONL buffering have different last flushes. Drift uses only timestamps
covered by the WAV header. The first instrumentation binaries lack the later
`host_probe_active` and callback-total fields; their actual device path is proven
by the device log, sustained completed AudioOut buffers and the compiled callback
probe. The fixed-30 run recorded **13,995 actual callbacks, zero missing frames,
and zero lost host events** through its final recorded PCM block.

The fixed-30 run and baseline-60 run visibly reached the Audio name, dialogue
intro and motorcycle chase. Normal 30 fps logs show interval 2 and normal 60 fps
logs interval 1. Screens and scripted/manual input journals are retained. Some
unscripted input and foreground changes were observed, so these are not identical
waveform A/B routes. This does not affect the per-run measurements or the separate
headless clock comparison.

### Cause classification and limits

- **Confirmed fix:** cumulative timer-fallback slowdown from relative waits.
  The successful hardware submission path does not use that fallback.
- **Measured callback zero-fill:** none in the completed normal captures.
  There was a 40.589 ms late PCM arrival at 117.525 s in baseline-60. Neither
  a late producer buffer nor a zero-fill count establishes whether the downstream
  hardware played continuously; callback-interval telemetry was added after the
  stress run exposed this observability limit.
- **Source-signal candidates:** the baseline-30 loud lab-film passage contains
  full-scale PCM and numerous delta outliers. They are already in the pre-device
  dump; callback starvation cannot create them there. Most are not at packet
  boundaries (only 2 of the first 277 groups begin within one sample of a
  1,024-frame boundary). A reference-console recording or listening comparison is
  still needed to distinguish musical transients/mastering from a guest-mixer or
  decode defect. No speculative gain reduction or smoothing was applied.
- **Scene-transition silence candidates:** baseline-60 has 94.8835–96.9164 s;
  fixed-30 has 29.8933–32.0631 s, the latter coinciding with recorded PLUS input at
  29.86 s. Both are source PCM silence during lab-film/setup transitions, with
  zero host missing frames. They remain candidates, not confirmed dropouts.
- **AUDIO-006 speaker loopback and Windows hardware:** not recorded. Real Mac callback
  execution is verified; this is not an acoustic-output certification. Windows
  float/extensible inputs and all detector logic are synthetic-test coverage.

Every signal event is listed in `runs/<name>/report.json` under `events`, with
sample-exact click/clip positions and sample-threshold silence timestamps. Every
late block is listed under `timing.late_buffers`, and every captured host underrun
under `host_events`. Callback scheduling warnings also appear there as
`host_late_callback`: inter-callback time exceeding the previous request
duration plus a 20 ms margin. This is a scheduling warning, not a claim of an
acoustically measured dropout; an intentional device pause or SDL batching can
also produce such a warning. The files also contain the entire RMS timeline. Their source
WAV, JSONL, input script, manual input journal, `guest.log`, `receipt.json` and
frame captures remain alongside each report.

Private root: `.local/units/AUDIO-006/`.
The owner's installed build and saves are read-only inputs; each run has a new
private writable data root and save directory. Every game launch uses
`.local/bin/mac-game-lock` and the owned-process supervisor.

Independent review belongs to the parent after this worker's exact committed
head is returned. No nested review was started, as required by the unit brief.

The initial private `composition.json` confirms the full Mac/Linux/Windows patch orders
apply with the manual insertion. All five audio and host source
files in that Mac composition exactly match those compiled for the original fixed
runs. The later callback-interval extension has a separate build receipt and synthetic
callback verification. Its planned 75 s hardware follow-up could not obtain the
shared Mac lock for over 45 minutes; only the idle waiter was canceled. It is
**not hardware-verified**. The lead must schedule that capture and a full chase
under CPU load when the Mac is available.
`build-receipt.json` retains those hashes, patch hashes, binary hashes and the
build command. Linux callbacks were exercised against a fake SDL stream on Mac;
Linux and Windows device behavior was not run by this unit.

`final-source-receipt.json` confirms the final committed patch text, including
context-only whitespace normalization, reproduces all five compiled audio/host
sources exactly. Callback interval warnings remain an explicit hardware follow-up;
zero callback-inserted frames must not be promoted to a claim of continuous
speaker playback. Required detector and composed-runtime checks passed (12 Python
detector tests and the C++ integration suite).

## Windows device diagnostics (AUDIO-WIN-010)

The fix overlay now instruments the Windows XAudio2 source voice when
`NX_AUDIO_DUMP` is enabled. It retains the bounded callback-to-dump queue:
no file I/O, allocation, waits or logging were added to the processing callback.
The callback records the default 10 ms processing quantum, its monotonic arrival,
`BytesRequired / 4`, and `GetState().SamplesPlayed`. The latter is consumed source
PCM, before the endpoint's playback latency. Startup is identified separately.
Here startup means before the first accepted device submission; a later deliberate
pause can also produce pass-entry deficits and needs route context.

`host_backend="xaudio2_processing_pass"` distinguishes these records from SDL.
XAudio2's `BytesRequired` describes a deficit at processing-pass entry; the
producer could still submit data before that pass consumes it. Consequently the
detector classifies these as `xaudio2_pass_entry_deficit`, with confidence
`measured_deficit_not_loopback_drop`, rather than calling them confirmed silence
insertions. The existing `missing_frames`/`host_missing_frames` field names are
retained for sidecar compatibility. See Microsoft's
[processing-pass callback contract](https://learn.microsoft.com/en-us/windows/win32/api/xaudio2/nf-xaudio2-ixaudio2voicecallback-onvoiceprocessingpassstart)
and [sample-cursor definition](https://learn.microsoft.com/en-us/windows/win32/api/xaudio2/ns-xaudio2-xaudio2_voice_state).

Each `device` record contains `played_frame` and `monotonic_ns`. Each PCM record
also carries `host_submitted_frames`, measured before the current packet's device
submission. Their difference aligns the XAudio2 cursor with the WAV, including
when leading silent packets were excluded from the WAV. The report keeps every
cursor in `timing.device_positions`, and measures cursor progress during the
sounding timestamp span in `timing.device_clock`. Startup idle time is excluded.
This measures consumed-sample progress; it does not calibrate the endpoint clock.

The overlay also handles a rejected Windows `SubmitSourceBuffer`: it rolls back
the queued-buffer count, frees the host copy, and returns false so AudioOut's
existing timer fallback releases the packet. Previously the return value was
ignored: repeated rejections could fill a phantom queue and block the producer.
This is a checked error-path correction; an actual API rejection must be reported
separately from a synthetic rejection test. `host_submit_failures` records rejected
submissions. A rejected packet remains in the pre-device dump without advancing
the device cursor, so the detector disables the single-origin PCM/cursor mapping
when this counter is nonzero. It retains the raw cursor records and reports
`device_cursor_mapping="unavailable_rejected_packets"`; frame queue-lead rows
then remain unavailable instead of reporting a misleading offset. Older sidecars
without the counter cannot establish that there were no rejected submissions.

`OnBufferEnd` also records its duration. Calls longer than 1 ms emit a timestamped
`completion` event; PCM rows contain `host_completed_buffers` and
`host_max_completion_ns`. A Windows repeat measured 142.3624 ms and 120.3069 ms
inside this handler. It previously called the guest release function synchronously,
which acquires AudioOut and kernel locks, and freed the PCM allocation on the
XAudio2 engine thread.

The strict Windows path now publishes the already allocated packet to an
intrusive atomic queue. A dedicated process-lifetime worker releases guest buffers
and frees PCM in completion order. Publishing takes no guest lock, allocates
nothing and does not wait for the release worker. Completed packets remain in
`audio_queued()` until the worker frees their host PCM. It decrements that count
before notifying the guest producer, preserving the existing wake-up order and
bound on host PCM storage. The platform has no audio close/reopen API. The worker's
maximum release duration is reported separately as `host_max_release_ns`; it does
not write to the callback's single-producer diagnostic ring. A blocked guest
release can still exhaust the submitted audio, so removing engine-thread blocking
does not by itself prove uninterrupted output.
Two further maxima separate waiting for the AudioOut lock
(`host_max_release_lock_ns`) from signaling the guest event
(`host_max_release_event_ns`). These are aggregate durations, not timestamped
events or proof of which thread held the contended lock.

### Comparing source and loopback

```sh
python3 tools/audio_glitch_check.py game.wav --timestamps game.wav.jsonl \
  --frame-timestamps data/frames/timing.jsonl -o game-report.json
python3 tools/audio_glitch_check.py loopback/audio.wav --reference game.wav \
  -o loopback-report.json
```

`--reference` compares 10 ms RMS envelopes using normalized correlation over
2 s anchors at 10 s intervals. It searches the first usable anchor across the
capture, then searches within 1 s of the last accepted delay. The report includes
every anchor's file-relative offset, correlation and matched/unmatched status;
silence or a constant envelope cannot establish an alignment. Correlation below
0.8 is not accepted. A gain difference does not change the normalized score.
`offset_change_seconds` is the difference between first and last accepted
anchors, at the stated window resolution, not a clock-accuracy specification.
Repeated music can produce ambiguous matches, so inspect the anchor sequence
against the route and scene before drawing a conclusion.
An isolated offset excursion that returns to the previous offset at the next
anchor is retained as `ambiguous_offset_excursion` and excluded from mapping.
This is a conservative ambiguity check, not proof of an incorrect match. Gaps
outside source coverage, or farther from an accepted anchor than one stride plus
one anchor duration (12 s by default), remain unaligned. Low-signal sections must
not inherit an arbitrarily old alignment.

Every loopback silence candidate is timestamped again under
`reference_comparison.capture_silence_candidates`. An overlapping source silence
is classified separately from a `loopback_only_candidate`. The latter can still
be a capture artifact: the WIN-SETUP-001 WASAPI helper fills gaps using callback
arrival wall time, so scheduling jitter can insert padding even during continuous
playback. AUDIO-WIN-010's private copy additionally saves the raw received PCM and
a per-callback journal (`audio.raw.wav` and `audio.wav.capture.jsonl`). Comparing
both variants separates recorder padding from silence actually received in PCM;
these private recorder changes are not a landed change to the VM helpers.

### Frame timing and A/V limits

Every successful strict-profile frame dump now appends `frame` and
`readback_ready_ns` to `frames/timing.jsonl`. This uses the same monotonic clock as
the audio sidecar and is sampled before writing the image. It measures GPU fence /
readback readiness, not the display's scanout time. The frame file and its timing
sidecar remain private game captures.

`--frame-timestamps` joins each frame to the latest produced PCM block and
interpolates between the two surrounding XAudio2 sample cursors. Each row includes
the PCM production lead, the consumed PCM position and the cursor bracket's
duration. Rows outside a recorded cursor bracket, or inside a bracket wider than
50 ms, explicitly remain unavailable. Interpolating across a long callback stall
would assume uniform playback during the very interval being investigated.
This makes software queue delay at an inspected scene cut measurable. It is
**not a content-based A/V offset**: full cutscene sync acceptance also needs
matched picture/sound landmarks and display/endpoint latency calibration.

### Windows measurements, 2026-10-20

These are windowed XAudio2 runs in the VM's interactive console session 2,
using the default **CABLE Input (VB-Audio Virtual Cable)** endpoint, 48 kHz stereo.
They exercise real Windows device scheduling and WASAPI capture; they do not
measure physical speakers or display scanout. All evidence below is private under
`.local/units/AUDIO-WIN-010/`, with the full captures in `runs/<run>/`. Each run has
`config.json`, `receipt.json`, guest logs, game/loopback/raw WAVs, JSONL timing,
frame dumps, and timestamped detector reports. The header-declared WAV span is
used after time-bounded termination; partial final sidecar records are reported.

The first three runs used the instrumented pre-deferral runtime:

| Run | Mode / source PCM duration | Source click / clipping / silence candidates | Pass-entry deficits (startup / post-start) | Late device callbacks | Producer drift / device-cursor drift |
|---|---|---:|---:|---:|---:|
| `device-30b` | 30 / 232.448 s | 346 / 146 / 1 | 1 / 0 | 2 | −243.526 / −230.087 ms |
| `route-30` | 30 / 412.928 s | 0 / 0 / 0 | 0 / 1 (32 frames) | 0 | +4.978 / +0.224 ms |
| `route-60` | legacy 60 executable / 348.160 s | 322 / 137 / 0 | 73 / 1 (256 frames) | 2 | −205.073 / −235.845 ms |

No rejected submissions or lost diagnostic events were counted. Late producer
blocks were 1,619 / 2,861 / 2,774 respectively, using the detector's 5 ms threshold.
That count includes 1,024-frame producer packets arriving on a 10 ms device
quantum; it must not be equated with audible starvation. Source clipped samples
were 343/420 (left/right) in `device-30b`, zero in `route-30`, and 265/362 in
`route-60`. Musical transients and full-scale source samples remain candidates,
not established mixer defects.

In `device-30b`, raw loopback contains digital-zero interiors at
**28.197979–28.307979 s (110 ms)** and **29.327979–29.457979 s (130 ms)**.
The source WAV does not contain these gaps. The associated delayed processing
callbacks occur 22.950750 and 24.099347 s after the first PCM timestamp, late by
115.542 and 133.631 ms. These clock domains differ because source dumping skips
leading silence. The WASAPI callback journal links both gaps to received buffers
with **zero recorder-padding bytes**; the trimmed gap interiors contain 10,368
and 12,288 exact zero samples. Evidence: `gap-sample-verification.json`.
RMS alignment near these startup passages is insufficient, so the detector
conservatively retains them as unaligned; the diagnosis uses the raw samples,
callback journal and device timing together.

The padded recorder additionally reported a 45.083 ms gap at
27.291188–27.336271 s absent from raw PCM. In `route-30`, 53 padded silence
candidates reduce to three raw candidates: two precede source coverage, and the
last low-level passage (370.002167–375.080000 s) lacks a nearby accepted anchor.
Its interior contains nonzero samples, peaking at 0.0009765625, so it is **not**
reported as a confirmed five-second dropout. `route-60` has 179 padded versus two
raw silence candidates; its accepted RMS alignment does not cover the later
gaps. It also overlapped a separate session-0 game and is not an isolated
performance or dynamic-FPS acceptance run.

`completion-probe-30` repeated the early route with completion-duration telemetry.
The existing `OnBufferEnd` handler took **142.3624 ms** and **120.3069 ms** on two
calls (monotonic starts 12466287895300 and 12467436801500 ns), with two late
processing callbacks, one startup deficit, no rejected submissions and no lost
events. Raw loopback has corresponding 140 ms and 110 ms gaps at
26.395667–26.535667 s and 27.555667–27.665667 s; its 83.456 s source dump has no
silence, click or clipping candidates. Device-cursor drift is −250.274 ms.
This localizes the engine stall to completion work; it does not by itself
identify which guest mutex or OS scheduling interval caused the wait.

After deferring release, `deferred-probe-30` recorded 83.200 s of source PCM:
**late device callbacks 2 → 0; maximum completion callback
142.3624 → 0.0379 ms**. The release worker still reached **182.225 ms**.
It counted 23 post-start pass-entry deficits totaling 10,272 frames (**214 ms**),
with no startup deficits, submission failures or lost events. Raw loopback
contains exact-zero interiors at 28.775229–28.855896 s (**80.667 ms**) and
29.922563–30.055896 s (**133.333 ms**), summing to the same 214 ms.
Source PCM has no silence, click or clipping candidates; device-cursor drift is
−214.124 ms and production drift −205.594 ms. Evidence:
`runs/deferred-probe-30/`, `deferred-gap-verification.json`.

Thus the engine-thread blocking is fixed, while guest-release starvation remains.
The increased deficit count does not by itself mean a regression: the engine can
now run its callbacks during the guest stall, whereas previously the callback
itself was blocked. Both runs still have two raw dropouts; their total duration
was 250 ms before and 214 ms after under different concurrent VM load. That is
not an isolated benchmark or a claim of glitch-free output.

The final split-duration instrumentation ran in `checkpoint-after-60`.
Its console check passed; this unit's process started at 09:19:01 UTC, then a
different unit launched another console game at 09:19:02. On discovering the
overlap, this unit stopped its own game, pad and capture. `overlap-abort.json`
records the exclusion: **do not use this run for loopback attribution, chase
acceptance or a comparative performance result**.

Its per-process diagnostic counters still localize a release stall:
`host_max_release_ns=175011000`,
`host_max_release_event_ns=174993199`, and
`host_max_release_lock_ns=471400`. Thus the measured guest `event_signal` call
accounts for virtually all of the 175.011 ms release-worker delay, whereas
acquiring the AudioOut lock peaked at 0.4714 ms. Completion callbacks stayed below
0.0099 ms, with zero late callbacks. In the composed runtime, `event_signal`
acquires the runtime's emulated-kernel mutex `g_k` and notifies guest synchronization
waiters. These
measurements identify that call path, not the mutex owner or the division between
lock waiting, wakeup work and OS descheduling. Investigating those kernel critical
sections is the next root-cause task; increasing audio buffering would only mask
the stall and add latency. Evidence: `overlap-60-timing.jsonl` and the run receipt.

The opening-film picture timing remains substantially wrong. In `device-30b`,
the spoken “Understood” landmark begins at approximately source PCM 54.80 s.
Frame 1840 still shows the preceding speaker at consumed PCM 99.384 s; frame
1876 shows the corresponding Brenda subtitle at 101.414 s. The subtitle transition
therefore trails that speech by **44.584–46.614 s**, using 2 s frame spacing and
local word-timestamp transcription. This is a content/subtitle landmark, not a
calibrated lip-sync or scene-cut measurement. Median produced-versus-consumed PCM
lead is only 77.110 ms, so ordinary audio queue latency cannot explain that
discrepancy. Evidence: `runs/device-30b/{asr.json,game-report.json,data/frames/}`,
`dialogue.png`; the rendering log reports roughly 17–18 fps in this portion.
The rendering/game-timeline diagnosis and scene-cut acceptance remain open.

Two earlier subtitle onsets were subsequently located by local OCR and checked
visually in the preceding/present frame pair:

| Speech landmark | Approximate source speech onset | Checked frames | Picture/subtitle lag bracket |
|---|---:|---|---:|
| Prime | 39.440 s | 1301 / 1339 | 29.958–31.962 s |
| Activity | 42.880 s | 1446 / 1481 | 34.522–36.482 s |
| Understood | 54.800 s | 1840 / 1876 | 44.584–46.614 s |

The first-to-third lag increases by **12.622–16.656 s** over approximately
15.360 s of source speech timing. This supports a progressing picture/subtitle
timeline problem rather than just a constant startup delay. Authored subtitle
cue offsets and ASR uncertainty are not calibrated, so these remain content
landmarks, not frame-exact scene cuts. Evidence:
`subtitle-av-landmarks.json`, `subtitle-ocr.jsonl`, and the retained frame PNGs.

The issue also remains after callback deferral. In `checkpoint-after-30`, visually
checked frame pairs 3248/3283 and 3822/3846 bracket the same first and third
subtitle onsets. Against source speech at 160.080 and 175.520 s, their lag brackets
are **21.724–23.723 s** and **51.974–53.915 s**. This is a separate route/load
sample, not a controlled performance comparison with the earlier run. It verifies
that eliminating long device callbacks did not resolve the picture/subtitle
timeline problem. Evidence: `after-subtitle-av-landmarks.json`,
`runs/checkpoint-after-30/asr.json`, and `after-landmark-*.png`.

Fresh-start captures reached the title, opening film and name/gender UI but did
not establish a complete route into the chase. A separate checkpoint attempt
copied another unit's save read-only into this unit's private profile and verified
the load menus. It is not evidence of completing the fresh-start route. No owner
save was modified.

The completed checkpoint captures also have detector reports. `checkpoint-30`
spent most of its 353.536 s source span in title/load menus: zero pass-entry
deficits or late callbacks, maximum completion 0.1512 ms, and device-cursor drift
−0.0073 ms over 353.420 s. Its two raw silence candidates precede source coverage.
This steady-menu result is not a gameplay gate. `checkpoint-after-30` reached the
opening film after load confirmation: 233.216 s source PCM, 61 deficits
(two startup, 59 post-start; 26,592 frames total), zero late callbacks, maximum
completion 0.0386 ms, maximum release-worker duration 32.3855 ms, and device-cursor
drift −534.162 ms. Its source has 291 click candidates and no clipping or silence
candidates. Raw gap candidates include 40.430000–40.576375 s and a cluster at
207.403042–208.066375 s, all individually timestamped in the report. Their causes
are not all established by the release-duration maximum; source-producer delays
and load transitions also require investigation. Neither checkpoint run proves
chase coverage.

Verification boundaries:

- The final guarded `chase-seed-30` attempt ran from 10:07:08 to 10:10:10 UTC
  without another console game. The copied FPS checkpoint and timed input route
  did not establish chase coverage: sampled frames and final frame 2820 show
  the title screen. Its 172.800 s source span has no click, clipping or silence
  candidates. There were two startup processing deficits (960 frames total),
  zero post-start deficits, zero late device callbacks, and zero lost events or
  rejected submissions. Maximum completion/release/event/AudioOut-lock durations
  were 0.0625/18.2265/18.2071/0.4345 ms. Device-cursor drift was +0.3176 ms over
  172.7096824 s; production drift was +1.7922 ms. The detector separately reports
  1,267 production-interval warnings above 5 ms (maximum 31.6515 ms), which did
  not translate into post-start device deficits in this title-screen sample.
  Six padded-loopback silence candidates reduce to one raw candidate preceding
  source coverage. Reports retain every candidate timestamp. The forced-stop
  WAV tail is excluded and event coverage is marked incomplete accordingly.
  Evidence: `runs/chase-seed-30/`, `chase-contact.png`, `chase-final.png`.
- All ten attempts are retained locally, with 25 detector reports: eight
  completed source/padded/raw capture sets, one failed boot excluded, and one
  console-overlapped attempt used only for per-process diagnostic evidence.
  `evidence-index.json` records report hashes and receipts. At 10:13:19 UTC,
  `closeout-processes.json` found no remaining game, controller, capture or
  waiting launcher processes owned by this unit. No Mac game was launched.
- Real Windows VB-Cable evidence verifies the callback deferral and the remaining
  starvation; it is not physical speaker/display acceptance.
- Rejected-submission rollback, ordered completion publication with a blocked
  consumer, cursor-gap rejection and conservative correlation handling have
  deterministic tests. No real `SubmitSourceBuffer` rejection was observed.
- Kernel event-signaling delays, other producer/load stalls, a complete chase
  repeat in both modes, and frame-exact scene-cut A/V remain open. The subtitle
  drift warrants a repeat with the FPS unit's dynamic timing implementation;
  changing audio pitch or adding queue latency is not a demonstrated remedy.
- Independent review and Windows series integration belong to the parent run.
  This worker did not perform a nested review or waive those gates.
