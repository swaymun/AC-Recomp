"""CPU regression of the streamed audio dump overlay (astral-audio-dump.patch).

The overlay is applied at the end of the native overlay order (after astral-perf-hud.patch) on a fresh copy of the
pinned public runtime. The production WavStream (runtime/src/wav_stream.h) writes samples in uneven chunks; a forked
child is killed (_exit, no close, no stdio flush) mid-stream and its file must still carry a valid header whose sizes
match the last periodic fix-up. The composed hle_audio.cpp then runs on a muted host (no audio device, as NX_MUTE):
AudioOut buffers and the renderer mix are dumped from the first sound, the 10 s default is kept, NX_AUDIO_DUMP_SECONDS
limits or (0) lifts it, and only one source owns the file. The default profile's preprocessed hle_audio.cpp must be
unchanged. Synthetic samples only; no game, audio device or network is used.
"""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import prepare_runtime as runtime
import test_astral_shared_font as font
from test_nvn_window_depth import preprocessed

BEFORE = ('astral-shared-font.patch', 'astral-swkbd.patch', 'astral-perf-hud.patch')
OVERLAY = 'astral-audio-dump.patch'

STREAM_FIXTURE = r'''
#include <cassert>
#include <cstdio>
#include <iostream>
#include <string>
#include <vector>
#include <sys/wait.h>
#include <unistd.h>
#include "wav_stream.h"
using nx::WavStream;
std::vector<int16_t> signal(size_t frames) {
    std::vector<int16_t> s(frames * 2);
    for (size_t k = 0; k < frames; k++) s[2 * k] = int16_t(k * 7), s[2 * k + 1] = int16_t(~(k * 7));
    return s;
}
// Writes `total` frames in chunks of 1, 7, 240, 1000, 333, ... then, in "kill" mode, ends the process without a
// close or any flush, the way a killed runtime does.
int writer(const char* path, size_t total, uint64_t limit, uint32_t every, bool kill) {
    WavStream w;
    if (!w.open(path, limit, every)) return 3;
    std::vector<int16_t> s = signal(total);
    const size_t chunks[] = {1, 7, 240, 1000, 333, 4096, 13};
    size_t at = 0;
    for (int k = 0; at < total; k++) {
        size_t n = std::min(chunks[k % 7], total - at);
        bool more = w.write(s.data() + at * 2, n);
        at += n;
        if (!more) break;
    }
    if (kill) _exit(0);
    w.close();
    return 0;
}
int main(int argc, char** argv) {
    if (argc != 6) return 2;
    std::string mode = argv[1];
    const char* path = argv[2];
    size_t total = std::stoull(argv[3]);
    uint64_t limit = std::stoull(argv[4]);
    uint32_t every = uint32_t(std::stoul(argv[5]));
    if (mode == "kill") {
        pid_t child = fork();
        if (child == 0) writer(path, total, limit, every, true);
        int status = 0;
        waitpid(child, &status, 0);
        return WIFEXITED(status) ? WEXITSTATUS(status) : 4;
    }
    if (mode == "close") return writer(path, total, limit, every, false);
    if (mode == "edge") {  // open alone: a valid empty file; an unwritable path fails cleanly
        WavStream w;
        assert(w.open(path, 0, every) && w.is_open() && w.frames() == 0);
        FILE* f = std::fopen(path, "rb");
        unsigned char h[44];
        assert(std::fread(h, 1, 44, f) == 44 && std::fgetc(f) == EOF);
        std::fclose(f);
        assert(h[4] == 36 && h[5] == 0 && h[40] == 0 && h[41] == 0);
        int16_t s[4] = {1, 2, 3, 4};
        assert(w.write(s, 2) && w.frames() == 2);
        w.close();
        assert(!w.is_open() && !w.write(s, 2));
        WavStream bad;
        assert(!bad.open("/nonexistent-dir-for-test/x.wav", 0) && !bad.is_open() && !bad.write(s, 2));
        assert(WavStream::kMaxFrames == (0xffffffffull - 36) / 4);
        std::cout << "PASS edge: empty file valid from open; close final; unwritable path refused; u32 cap\n";
        return 0;
    }
    return 2;
}
'''


def parse_wav(path):
    data = Path(path).read_bytes()
    assert len(data) >= 44, len(data)
    riff, riff_size, wave, fmt, fmt_size, tag, channels, rate, byte_rate, align, bits, chunk, size = struct.unpack(
        '<4sI4s4sIHHIIHH4sI', data[:44])
    assert (riff, wave, fmt, chunk) == (b'RIFF', b'WAVE', b'fmt ', b'data')
    assert (fmt_size, tag, channels, rate, byte_rate, align, bits) == (16, 1, 2, 48000, 192000, 4, 16)
    return {'riff': riff_size, 'size': size, 'file': len(data), 'pcm': data[44:]}


def signal(frames):
    """The fixture's signal: int16_t(k * 7) and int16_t(~(k * 7)), the low 16 bits of each."""
    return b''.join(struct.pack('<HH', (k * 7) & 0xffff, ~(k * 7) & 0xffff) for k in range(frames))


def last_fixup(total, every):
    """Frames covered by the fixture writer's last periodic fix-up (chunk sizes as in STREAM_FIXTURE)."""
    chunks, at, since, last, k = (1, 7, 240, 1000, 333, 4096, 13), 0, 0, 0, 0
    while at < total:
        n = min(chunks[k % 7], total - at)
        at, since, k = at + n, since + n, k + 1
        if since >= every:
            last, since = at, 0
    return last


def ramp(first, frames):
    return b''.join(struct.pack('<hh', first + k, -(first + k)) for k in range(frames))


class AstralAudioDumpTests(unittest.TestCase):
    def test_streamed_wav_and_muted_session(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        out, source, _ = font.stack_source(self, 'astral-audio-dump')
        for name in BEFORE:
            font.apply(self, source, name)
        stacked = runtime.source_fingerprint(source)
        patch = font.apply(self, source, OVERLAY)
        applied = runtime.source_fingerprint(source)
        self.assertEqual(sorted(k for k in set(applied) | set(stacked) if applied.get(k) != stacked.get(k)),
                         ['runtime/src/hle_audio.cpp', 'runtime/src/wav_stream.h'])
        src = source / 'runtime/src'
        includes = ['-I', str(source / 'runtime/include'), '-I', str(src)]
        env = {k: v for k, v in os.environ.items() if not k.startswith('NX_')}

        # ---- WavStream: chunks, periodic fix-ups, a killed writer, the limit, close ----
        stream = out / 'stream'
        stream.mkdir()
        (stream / 'fixture.cpp').write_text(STREAM_FIXTURE)
        build = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wextra', '-Werror', *includes,
                                str(stream / 'fixture.cpp'), '-o', str(stream / 'run')],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

        def run(*args):
            r = subprocess.run([str(stream / 'run'), *map(str, args)], cwd=stream, capture_output=True, text=True,
                               timeout=60, env=env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return r.stdout

        print(run('edge', stream / 'edge.wav', 0, 0, 1000), end='')
        total = 50_000
        full = signal(total)
        # Killed after 50000 frames with a fix-up every 12000: the header covers what the last fix-up saw (the
        # fix-up runs after the chunk that crosses each 12000), all of it on disk and identical to what was written.
        run('kill', stream / 'kill.wav', total, 0, 12000)
        w = parse_wav(stream / 'kill.wav')
        self.assertEqual(w['riff'], 36 + w['size'])
        self.assertEqual(w['size'] % 4, 0)
        self.assertEqual(w['size'], 4 * last_fixup(total, 12000))
        self.assertLess(w['size'], 4 * total)
        self.assertLessEqual(44 + w['size'], w['file'])
        self.assertEqual(w['pcm'][:w['size']], full[:w['size']])
        frames_seen = w['size'] // 4
        print(f'PASS killed writer: header valid, {frames_seen} of {total} frames covered by the last fix-up, '
              f'{w["file"] - 44} bytes on disk')
        # The same writer closed: exact sizes. A limit cuts the last chunk and closes the file.
        run('close', stream / 'close.wav', total, 0, 12000)
        w = parse_wav(stream / 'close.wav')
        self.assertEqual((w['size'], w['riff'], w['file']), (4 * total, 36 + 4 * total, 44 + 4 * total))
        self.assertEqual(w['pcm'], full)
        run('kill', stream / 'limit.wav', total, 10_001, 12000)  # killed after the limit closed it: still exact
        w = parse_wav(stream / 'limit.wav')
        self.assertEqual((w['size'], w['file']), (4 * 10_001, 44 + 4 * 10_001))
        self.assertEqual(w['pcm'], full[:4 * 10_001])
        print('PASS closed writer: exact sizes and samples; NX_AUDIO_DUMP_SECONDS-style limit cuts mid-chunk')

        # ---- the composed hle_audio.cpp on a muted host ----
        session = out / 'session'
        session.mkdir()
        build = subprocess.run([compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1',
                                *includes, str(ROOT / 'tests/test_astral_audio_dump.cpp'), '-o', str(session / 'run')],
                               capture_output=True, text=True, timeout=180)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)

        def session_run(mode, extra):
            r = subprocess.run([str(session / 'run'), mode], cwd=session, capture_output=True, text=True, timeout=60,
                               env={**env, 'NX_MUTE': '1', **extra})
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn('PASS', r.stdout)
            print(r.stdout, end='')
            return r.stderr

        log = session_run('audioout', {'NX_AUDIO_DUMP': 'audioout.wav', 'NX_AUDIO_DUMP_SECONDS': '0'})
        w = parse_wav(session / 'audioout.wav')
        expect = ramp(1, 3072)  # the three sounding buffers; the silent first one and the renderer frame are not there
        self.assertEqual((w['size'], w['riff'], w['file']), (len(expect), 36 + len(expect), 44 + len(expect)))
        self.assertEqual(w['pcm'], expect)
        self.assertIn('dumping the AudioOut output to audioout.wav, the whole session', log)

        log = session_run('renderer', {'NX_AUDIO_DUMP': 'renderer.wav'})  # NX_AUDIO_DUMP_SECONDS unset: 10 s
        w = parse_wav(session / 'renderer.wav')
        expect = b''.join(ramp(1 + (k * 240) % 30000, 240) for k in range(2000))
        self.assertEqual((w['size'], w['file']), (48000 * 10 * 4, 44 + 48000 * 10 * 4))
        self.assertEqual(w['pcm'], expect)
        self.assertIn('wrote renderer.wav (480000 frames)', log)

        session_run('seconds', {'NX_AUDIO_DUMP': 'seconds.wav', 'NX_AUDIO_DUMP_SECONDS': '1'})
        w = parse_wav(session / 'seconds.wav')
        self.assertEqual(w['size'], 48000 * 4)
        self.assertEqual(w['pcm'], b''.join(ramp(1 + (k * 240) % 30000, 240) for k in range(200)))

        log = session_run('fail', {'NX_AUDIO_DUMP': str(session / 'missing-dir/x.wav')})
        self.assertIn('NX_AUDIO_DUMP: cannot create', log)
        session_run('unset', {})
        self.assertEqual(sorted(p.name for p in session.glob('*.wav')), ['audioout.wav', 'renderer.wav', 'seconds.wav'])
        print('PASS muted session: AudioOut and renderer dumps from the first sound, 10 s default, 1 s and whole '
              'session, single owner, unwritable path harmless')

        # ---- syntax (strict, Mac profile, and default) and the unchanged default profile ----
        name = src / 'hle_audio.cpp'
        for flags in (['-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1'], []):
            check = subprocess.run([compiler, '-std=c++20', '-Wall', '-Wextra', '-Wno-unused-parameter', '-Werror',
                                    *flags, *includes, '-fsyntax-only', str(name)], capture_output=True, text=True,
                                   timeout=120)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        patched = preprocessed(compiler, includes, name)
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patch)], check=True, capture_output=True)
        self.assertEqual(patched, preprocessed(compiler, includes, name), 'default profile differs')
        print('PASS hle_audio.cpp: strict/default syntax with -Werror; default profile preprocesses identically')
        shutil.rmtree(out)  # reached only when every assertion passed; a failure keeps the copy as evidence


if __name__ == '__main__':
    unittest.main()
