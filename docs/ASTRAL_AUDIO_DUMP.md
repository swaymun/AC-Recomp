# Astral streamed audio dump

`runtime/patches/astral-audio-dump.patch` extends `NX_AUDIO_DUMP` in `runtime/src/hle_audio.cpp` for Astral (strict)
builds. The dump is streamed to the WAV while the game runs, can cover the whole session, and also captures AudioOut,
whose functions Astral's main imports (`docs/AUDIOOUT_RUNTIME.md`).

## Overlay order

Apply it last:

1. `NATIVE_ORDER` (`tests/test_nvn_window_depth.py`)
2. `astral-nvn-window-depth.patch`, `astral-nvn-bc-zero-fill.patch`, `astral-nvn-cube-storage.patch`
3. `astral-shared-font.patch`, `astral-swkbd.patch`
4. `astral-perf-hud.patch`
5. **`astral-audio-dump.patch`**

It changes only `hle_audio.cpp`, which comes from `astral-audio.patch` in `NATIVE_ORDER`, and adds
`runtime/src/wav_stream.h`. It does not depend on the swkbd or HUD overlays and applies with or without them.

## Use

| variable | effect |
|---|---|
| `NX_AUDIO_DUMP=<file.wav>` | Dump the mixed output, s16 stereo 48 kHz, from the first non-silent block. |
| `NX_AUDIO_DUMP_SECONDS=<N>` | Seconds to keep. Unset means 10, the old default. `0` means the whole session, up to the WAV limit of about 6.2 hours. |

- **What is captured:** the PCM itself, either AudioOut buffers in play order (the player thread) or the AudioRenderer's
  final mix (`render_submit`), before it reaches the host device. It is captured even with `NX_MUTE=1`, in headless
  runs, with no device, or with the Mac's output muted. The file is created on the first sound.
- **One source per file:** the first path to produce sound owns the file. A sound from the other path is ignored.
- **Streaming:** samples go to the file as they are produced (`WavStream`). The RIFF and `data` sizes are fixed up and
  flushed every 0.25 s of audio, at the limit, and at a normal exit (`atexit`). A process killed with `kill -9`, a
  crash or `_exit` still leaves a playable WAV. Its header covers everything up to the last fix-up, so at most the
  last 0.25 s is missing. The macOS window close and Cmd-Q end through `_exit`, so they fall in that case too.
- **Logs:** `audio: dumping the <AudioOut output|renderer mix> to <file>, <N s|the whole session>` at the start, and
  `audio: wrote <file> (<frames> frames)` when the limit is reached. A file that cannot be created is logged and
  ignored.

With `NX_AUDIO_DUMP_SECONDS` unset, the renderer path writes the same 10 s from the first sound as the old in-memory
dump did. The difference is that the file now appears at once and grows, instead of appearing after 10 s.

The default (non-Astral) profile is unchanged. Every change is under `#if defined(NX_ASTRAL_STRICT)`, so it keeps the
old 10 s in-memory renderer dump and its preprocessed `hle_audio.cpp` is identical.

## Tests

`tests/test_astral_audio_dump.py` (with `tests/test_astral_audio_dump.cpp`) applies the overlay at the end of the
order on a fresh pinned runtime.

| area | what is checked |
|---|---|
| `WavStream` | Writes 50,000 frames in uneven chunks. A forked child then ends with `_exit`: no close and no stdio flush. Its file has a valid header whose sizes equal the last periodic fix-up exactly, with identical samples. A closed file has exact sizes. A limit cuts mid-chunk and finalises the header even if the writer is killed afterwards. Opening alone gives a valid empty WAV, an unwritable path is refused, and the u32 cap holds. |
| Composed `hle_audio.cpp`, muted host | Has no audio device, like `NX_MUTE`. AudioOut buffers are played through the real HLE registry. The test checks that the silent first buffer is skipped, that the whole session is kept with `SECONDS=0`, and that the renderer cannot take over the file. The renderer mix gives exactly 10 s by default and 1 s with `SECONDS=1`. An unwritable path is harmless, and without `NX_AUDIO_DUMP` no file appears. |
| Build | Strict Mac-profile and default syntax with `-Werror`, and identical default preprocessing. |

## Limits

- **No game run yet.** Whether Astral sounds through AudioOut or the renderer was not observed here. Both are covered.
- **Limits:**
  - Files stop at about 6.2 hours, the u32 `data` size.
  - Only 48 kHz stereo s16 is dumped. That is the only mode the runtime's AudioOut accepts and what the renderer mixes.
