"""Synthetic end-to-end signal tests; no third-party packages or game audio."""
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import audio_glitch_check as check


class AudioGlitchCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'signal.wav'
        self.rate = 48000

    def write(self, frames, channels=2, width=2, rate=48000):
        with wave.open(str(self.path), 'wb') as w:
            w.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
            raw = bytearray()
            for frame in frames:
                for v in frame:
                    if width == 1:
                        raw.append(max(0, min(255, round(v * 128 + 128))))
                    else:
                        scale = 1 << (width * 8 - 1)
                        raw.extend(max(-scale, min(scale - 1, round(v * scale))).to_bytes(width, 'little', signed=True))
            w.writeframes(raw)

    def tone(self, seconds=1, hz=440, channels=2):
        return [[.3 * math.sin(2 * math.pi * hz * k / self.rate)] * channels
                for k in range(round(self.rate * seconds))]

    def test_clean_tones_low_and_high_frequency(self):
        for hz in (440, 10000, 19000):
            with self.subTest(hz=hz):
                self.write(self.tone(hz=hz))
                r = check.analyze(self.path)
                self.assertEqual(r['events'], [])
                self.assertAlmostEqual(r['summary']['rms'], .3 / math.sqrt(2), places=4)
                self.assertEqual(len(r['rms_over_time']), 100)
                self.assertEqual(r['timing']['status'], 'unavailable')

    def test_bounded_gap_and_unbounded_silence(self):
        frames = [[0, 0]] * 4800 + self.tone(.2) + [[0, 0]] * 2400 + self.tone(.2) + [[0, 0]] * 4800
        self.write(frames)
        gaps = [e for e in check.analyze(self.path)['events'] if e['kind'] == 'silence_gap']
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0]['start_seconds'], .3)
        # The following sine begins with one zero sample, which belongs to the quiet run.
        self.assertEqual(gaps[0]['end_frame'], 16801)
        self.write([[0, 0]] * 48000)
        self.assertEqual(check.analyze(self.path)['events'], [])

    def test_one_silent_channel_is_not_output_gap(self):
        frames = self.tone(.2)
        for f in frames:
            f[1] = 0
        self.write(frames)
        self.assertEqual(check.analyze(self.path)['events'], [])

    def test_single_audioout_buffer_gap_across_rms_windows(self):
        frames = self.tone(.2)
        start = 4321  # deliberately misaligned to both the 10 ms window and AudioOut packet
        frames[start:start + 1024] = [[0, 0]] * 1024
        self.write(frames)
        for window in (1, 10, 100):
            r = check.analyze(self.path, window_ms=window)
            gaps = [e for e in r['events'] if e['kind'] == 'silence_gap']
            self.assertEqual(len(gaps), 1)
            self.assertEqual(gaps[0]['start_frame'], start)
            self.assertEqual(gaps[0]['end_frame'], start + 1024)

    def test_click_in_one_channel_at_window_boundary(self):
        frames = self.tone()
        frames[24000][1] = .9
        self.write(frames)
        events = check.analyze(self.path)['events']
        clicks = [e for e in events if e['kind'] == 'click']
        self.assertEqual(len(clicks), 1)
        self.assertEqual(clicks[0]['channel'], 1)
        self.assertEqual(clicks[0]['start_frame'], 24000)
        self.assertEqual(clicks[0]['outlier_deltas'], 2)

    def test_clipping_samples_and_runs(self):
        frames = self.tone()
        frames[12000:12010] = [[1, -1]] * 10
        self.write(frames)
        r = check.analyze(self.path)
        clips = [e for e in r['events'] if e['kind'] == 'clipping']
        self.assertEqual(len(clips), 2)
        self.assertEqual(r['summary']['clipped_samples_by_channel'], [10, 10])
        self.assertEqual(clips[0]['samples'], 10)

    def test_integer_encodings_and_partial_window(self):
        for width in (1, 2, 3, 4):
            self.write(self.tone(.013, channels=1), channels=1, width=width)
            r = check.analyze(self.path)
            self.assertEqual(r['format']['frames'], 624)
            self.assertEqual(len(r['rms_over_time']), 2)
            self.assertEqual(r['events'], [])

    def float_wav(self, values, extensible=False):
        if extensible:
            fmt = struct.pack('<HHIIHHHHI', 0xfffe, 1, 48000, 192000, 4, 32, 22, 32, 4)
            fmt += bytes.fromhex('0300000000001000800000aa00389b71')
        else:
            fmt = struct.pack('<HHIIHH', 3, 1, 48000, 192000, 4, 32)
        data = b''.join(struct.pack('<f', v) for v in values)
        body = b'WAVEfmt ' + struct.pack('<I', len(fmt)) + fmt + b'JUNK\x02\x00\x00\x00xx'
        body += b'data' + struct.pack('<I', len(data)) + data
        self.path.write_bytes(b'RIFF' + struct.pack('<I', len(body)) + body)

    def test_windows_float_and_extensible(self):
        for extensible in (False, True):
            self.float_wav([f[0] for f in self.tone(.1)], extensible)
            r = check.analyze(self.path)
            self.assertEqual(r['format']['encoding'], 'float')
            self.assertEqual(r['events'], [])
        self.float_wav([float('nan')])
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            check.analyze(self.path)

    def test_drift_and_measured_host_underrun(self):
        self.write(self.tone(2))
        meta = self.path.with_suffix('.jsonl')
        records = [{'type': 'host', 'frame': 0, 'monotonic_ns': 900000000, 'missing_frames': 128,
                    'startup': True, 'underrun_callbacks': 1},
                   {'type': 'pcm', 'frame': 0, 'monotonic_ns': 1000000000},
                   {'type': 'host', 'frame': 1024, 'monotonic_ns': 1500000000, 'missing_frames': 256,
                    'underrun_callbacks': 2, 'late_callback_ns': 25000000},
                   {'type': 'pcm', 'frame': 48000, 'monotonic_ns': 2010000000}]
        meta.write_text('\n'.join(json.dumps(r) for r in records))
        report = check.analyze(self.path, timestamps=meta)
        self.assertAlmostEqual(report['timing']['drift_seconds'], -.01)
        self.assertAlmostEqual(report['timing']['effective_rate_hz'], 48000 / 1.01)
        self.assertEqual(report['host_events'][0]['classification'], 'startup_empty_queue')
        self.assertEqual(report['host_events'][1]['classification'], 'device_callback_starvation')
        self.assertAlmostEqual(report['host_events'][1]['seconds_from_first_pcm'], .5)
        self.assertEqual(report['host_events'][2]['kind'], 'host_late_callback')
        self.assertAlmostEqual(report['host_events'][2]['late_seconds'], .025)
        self.assertEqual(len(report['timing']['late_buffers']), 1)
        self.assertAlmostEqual(report['timing']['late_buffers'][0]['late_seconds'], .01)
        with meta.open('a') as f:
            f.write('\n{"type":"pcm",')
        report = check.analyze(self.path, timestamps=meta)
        self.assertTrue(report['timing']['ignored_truncated_tail'])
        self.assertEqual(report['timing']['pcm_records'], 2)
        meta.write_text('{"type":"pcm","frame":0,"monotonic_ns":2}\n'
                        '{"type":"pcm","frame":1,"monotonic_ns":1}\n')
        with self.assertRaisesRegex(ValueError, 'timestamps'):
            check.analyze(self.path, timestamps=meta)

    def test_windows_deficit_is_distinct_from_inserted_silence(self):
        self.write(self.tone(.1))
        meta = self.path.with_suffix('.jsonl')
        records = [{'type': 'host', 'frame': 0, 'monotonic_ns': 1, 'missing_frames': 480,
                    'startup': True},
                   {'type': 'host', 'frame': 480, 'monotonic_ns': 10000001, 'missing_frames': 128},
                   {'type': 'pcm', 'frame': 0, 'monotonic_ns': 20000001,
                    'host_backend': 'xaudio2_processing_pass', 'host_probe_active': True,
                    'host_callbacks': 2, 'lost_host_events': 0},
                   {'type': 'pcm', 'frame': 1024, 'monotonic_ns': 41333334,
                    'host_backend': 'xaudio2_processing_pass', 'host_probe_active': True,
                    'host_callbacks': 4, 'lost_host_events': 1}]
        meta.write_text(''.join(json.dumps(r) + '\n' for r in records))
        report = check.analyze(self.path, timestamps=meta)
        self.assertEqual(report['timing']['host_backend'], 'xaudio2_processing_pass')
        self.assertEqual(report['timing']['host_event_coverage'], 'incomplete')
        self.assertEqual(report['host_events'][0]['classification'], 'startup_processing_deficit')
        self.assertEqual(report['host_events'][1]['classification'], 'xaudio2_pass_entry_deficit')
        self.assertEqual(report['host_events'][1]['confidence'], 'measured_deficit_not_loopback_drop')
        self.assertAlmostEqual(report['host_events'][1]['duration_seconds'], 128 / 48000)

    def test_device_cursor_origin_drift_and_invalid_regression(self):
        self.write(self.tone(.1))
        meta = self.path.with_suffix('.jsonl')
        records = [{'type': 'device', 'played_frame': 1024, 'monotonic_ns': 1000000000},
                   {'type': 'pcm', 'frame': 0, 'monotonic_ns': 1000000000,
                    'host_submitted_frames': 1024},
                   {'type': 'device', 'played_frame': 2048, 'monotonic_ns': 1031333333},
                   {'type': 'pcm', 'frame': 1024, 'monotonic_ns': 1031333333}]
        meta.write_text(''.join(json.dumps(r) + '\n' for r in records))
        result = check.analyze(self.path, timestamps=meta)['timing']
        self.assertEqual(result['device_positions'][0]['pcm_frame'], 0)
        self.assertAlmostEqual(result['device_positions'][1]['pcm_seconds'], 1024 / 48000)
        self.assertAlmostEqual(result['device_clock']['drift_seconds'], -.01)
        records[2]['played_frame'] = 1
        meta.write_text(''.join(json.dumps(r) + '\n' for r in records))
        with self.assertRaisesRegex(ValueError, 'device positions'):
            check.analyze(self.path, timestamps=meta)

    def test_frame_timestamp_join_is_explicitly_queue_timing(self):
        path = self.path.with_suffix('.frames.jsonl')
        path.write_text('{"frame":1,"readback_ready_ns":1005000000}\n'
                        '{"frame":2,"readback_ready_ns":1100000000}\n')
        timing = {'pcm_positions': [{'frame': 0, 'frames': 1024, 'monotonic_ns': 1000000000}],
                  'device_positions': [{'pcm_frame': 0, 'monotonic_ns': 1000000000},
                                       {'pcm_frame': 480, 'monotonic_ns': 1010000000}]}
        report = check.frame_timing_report(path, timing, 48000)
        row = report['frames'][0]
        self.assertEqual(row['status'], 'measured')
        self.assertAlmostEqual(row['consumed_pcm_seconds'], .005)
        self.assertAlmostEqual(row['production_lead_seconds'], (1024 - 240) / 48000)
        self.assertEqual(report['frames'][1]['status'], 'unavailable')
        self.assertIn('not a content-based A/V', report['limitation'])
        timing['device_positions'][1]['monotonic_ns'] = 1100000000
        report = check.frame_timing_report(path, timing, 48000)
        self.assertEqual(report['frames'][0]['status'], 'unavailable')
        self.assertEqual(report['frames'][0]['reason'], 'device_cursor_gap')
        self.assertAlmostEqual(report['frames'][0]['device_bracket_seconds'], .1)
        self.assertNotIn('production_lead_seconds', report['frames'][0])
        path.write_text('{"frame":1,"readback_ready_ns":-1}\n')
        with self.assertRaisesRegex(ValueError, 'frame timestamps'):
            check.frame_timing_report(path, timing, 48000)
        path.write_text('{"frame":1,"readback_ready_ns":1}\n'
                        '{"frame":1,"readback_ready_ns":2}\n')
        with self.assertRaisesRegex(ValueError, 'frame timestamps'):
            check.frame_timing_report(path, timing, 48000)

    def test_rejected_packets_invalidate_linear_device_cursor_mapping(self):
        self.write(self.tone(.1))
        meta = self.path.with_suffix('.jsonl')
        records = [
            {'type': 'pcm', 'frame': 0, 'frames': 1024, 'monotonic_ns': 1000000000,
             'host_submitted_frames': 1024, 'host_submit_failures': 0},
            {'type': 'device', 'played_frame': 1024, 'monotonic_ns': 1000000000},
            {'type': 'pcm', 'frame': 1024, 'frames': 1024, 'monotonic_ns': 1031333333,
             'host_submitted_frames': 1024, 'host_submit_failures': 1},
            {'type': 'device', 'played_frame': 2048, 'monotonic_ns': 1031333333},
        ]
        meta.write_text(''.join(json.dumps(r) + '\n' for r in records))
        timing = check.analyze(self.path, timestamps=meta)['timing']
        self.assertEqual(timing['device_cursor_mapping'], 'unavailable_rejected_packets')
        self.assertEqual(timing['host_counters']['host_submit_failures'], 1)
        self.assertTrue(all('pcm_frame' not in p for p in timing['device_positions']))
        frames = self.path.with_suffix('.frames.jsonl')
        frames.write_text('{"frame":1,"readback_ready_ns":1010000000}\n')
        report = check.frame_timing_report(frames, timing, self.rate)
        self.assertEqual(report['frames'][0]['status'], 'unavailable')
        for bad in (-1, True, 1.5):
            records[0]['host_submit_failures'] = bad
            meta.write_text(''.join(json.dumps(r) + '\n' for r in records))
            with self.assertRaisesRegex(ValueError, 'submit failure counts'):
                check.analyze(self.path, timestamps=meta)
        records[0]['host_submit_failures'] = 2
        meta.write_text(''.join(json.dumps(r) + '\n' for r in records))
        with self.assertRaisesRegex(ValueError, 'submit failure counts'):
            check.analyze(self.path, timestamps=meta)

    def test_completion_duration_is_timestamped_separately(self):
        self.write(self.tone(.1))
        meta = self.path.with_suffix('.jsonl')
        meta.write_text('{"type":"pcm","frame":0,"monotonic_ns":1000000000}\n'
                        '{"type":"completion","monotonic_ns":1010000000,"duration_ns":115000000}\n'
                        '{"type":"pcm","frame":1024,"monotonic_ns":1130000000,'
                        '"host_completed_buffers":3,"host_max_completion_ns":115000000,'
                        '"host_max_release_lock_ns":14000000,"host_max_release_event_ns":101000000}\n')
        report = check.analyze(self.path, timestamps=meta)
        event = report['host_events'][0]
        self.assertEqual(event['kind'], 'host_slow_completion')
        self.assertAlmostEqual(event['seconds_from_first_pcm'], .01)
        self.assertAlmostEqual(event['duration_seconds'], .115)
        self.assertEqual(report['timing']['host_counters']['host_max_completion_ns'], 115000000)
        self.assertEqual(report['timing']['host_counters']['host_max_release_lock_ns'], 14000000)
        self.assertEqual(report['timing']['host_counters']['host_max_release_event_ns'], 101000000)

    def test_production_probe_patch_handoff(self):
        import shutil
        compiler = shutil.which('clang++') or shutil.which('c++')
        if not compiler or not shutil.which('git'):
            self.skipTest('C++ compiler and git required for production header integration')
        directory = Path(self.tmp.name)
        source = directory / 'runtime/src'
        source.mkdir(parents=True)
        patch = (ROOT / 'runtime/patches/astral-audio-dump.patch').read_text()
        section = patch.split('+++ b/runtime/src/audio_probe.h\n', 1)[1].split('diff --git ', 1)[0]
        header = ''.join(line[1:] for line in section.splitlines(True)
                         if line.startswith('+') and not line.startswith('+++'))
        (source / 'audio_probe.h').write_text(header)
        result = subprocess.run(['git', 'apply', '--include=runtime/src/audio_probe.h', '--include=runtime/src/audio_completion.h',
                                 str(ROOT / 'runtime/patches/astral-audio-fix.patch')],
                                cwd=directory, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        fixture = directory / 'probe.cpp'
        fixture.write_text(r'''#include <cassert>
#include <iostream>
#include "audio_probe.h"
int main() {
    using namespace nx::audio_probe;
    enabled = true;
    callback(480, 128, 1000000000);
    position(1024, 1000000000);
    submitted = true;
    callback(480, 0, 1010000000);
    callback(480, 64, 1050000000);
    Event e;
    assert(pop(e) && e.startup && e.missing_frames == 128 && !e.device_position);
    assert(pop(e) && e.device_position && e.played_frame == 1024);
    assert(pop(e) && !e.startup && e.missing_frames == 64 && e.late_ns == 30000000);
    assert(!pop(e) && callbacks == 3 && missing == 192 && late_callbacks == 1);
    completion(500, 1051000000);
    assert(!pop(e));
    completion(2000000, 1052000000);
    assert(pop(e) && e.completion_ns==2000000 && e.monotonic_ns==1052000000);
    assert(!pop(e) && completed_buffers==2 && max_completion_ns==2000000);
    for (unsigned k=0; k<kCapacity+5; ++k) position(k, 1060000000+k);
    assert(lost == 6);
    unsigned count=0;
    while (pop(e)) { assert(e.device_position); ++count; }
    assert(count == kCapacity-1);
    std::cout << "PASS production probe: startup/deficit/late/cursor/overflow\n";
}
''')
        binary = directory / 'probe'
        result = subprocess.run([compiler, '-std=c++20', '-I', str(source), str(fixture), '-o', str(binary)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS production probe', result.stdout)

        # Compile the actual patched Windows submit function with a rejecting API.
        # This checks ownership rollback without needing a Windows SDK or audio device.
        patch = (ROOT / 'runtime/patches/astral-audio-fix.patch').read_text()
        section = patch.split('+++ b/runtime/src/platform_win.cpp\n', 1)[1].split('diff --git ', 1)[0]
        patched = ''.join(line[1:] for line in section.splitlines(True) if line.startswith((' ', '+')))
        body = patched.split('bool audio_submit(', 1)[1].split('uint32_t audio_queued()', 1)[0]
        function = 'bool audio_submit(' + body
        callback = 'void OnBufferEnd(' + patched.split('void STDMETHODCALLTYPE OnBufferEnd(', 1)[1].split(
            'void STDMETHODCALLTYPE OnVoiceProcessingPassStart', 1)[0]
        callback = callback.replace('noexcept override', 'noexcept')
        fixture.write_text(r'''#include <cassert>
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <utility>
#include <vector>
#include "audio_probe.h"
#include "audio_completion.h"
using HostPacket = nx::audio_completion::Packet;
#define NX_ASTRAL_STRICT 1
#define FAILED(value) ((value)<0)
using UINT32 = uint32_t;
struct XAUDIO2_BUFFER { UINT32 AudioBytes; const uint8_t* pAudioData; void* pContext; };
struct Sink {
    bool reject = true;
    XAUDIO2_BUFFER last{};
    int SubmitSourceBuffer(XAUDIO2_BUFFER* b) { last=*b; return reject ? -1 : 0; }
};
std::atomic<uint32_t> g_queued{0};
Sink* g_voice = nullptr;
nx::audio_completion::Queue g_completed;
uint64_t monotonic_ns() { static uint64_t now=1; return now++; }
using namespace nx;
''' + function + callback + r'''
int main() {
    uint8_t samples[8]={1,2,3,4,5,6,7,8};
    assert(!audio_submit(samples,8,nullptr) && g_queued==0);
    Sink sink; g_voice=&sink;
    for (int n=0;n<10;++n) assert(!audio_submit(samples,8,nullptr) && g_queued==0);
    assert(audio_probe::submit_failures==10);
    assert(!audio_probe::submitted && audio_probe::submitted_frames==0);
    sink.reject=false;
    assert(audio_submit(samples,8,reinterpret_cast<void*>(12)) && g_queued==1);
    auto* packet=static_cast<HostPacket*>(sink.last.pContext);
    assert(packet->first==reinterpret_cast<void*>(12) && packet->second[7]==8);
    assert(audio_probe::submitted && audio_probe::submitted_frames==2);
    assert(audio_probe::submit_failures==10);
    audio_probe::enabled=true;
    OnBufferEnd(packet);
    assert(g_queued==1); // capacity stays reserved until the release worker frees PCM
    assert(audio_probe::completed_buffers==1);
    assert(g_completed.take()==packet && packet->next==nullptr);
    assert(packet->second[7]==8 && g_completed.take()==nullptr);
    delete packet; // the fixture stands in for the worker, never the device callback
}
''')
        result = subprocess.run([compiler, '-std=c++20', '-I', str(source), str(fixture), '-o', str(binary)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_deferred_completion_queue_preserves_order_during_blocked_release(self):
        import shutil
        compiler = shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            self.skipTest('C++ compiler unavailable')
        directory = Path(self.tmp.name) / 'completion'
        directory.mkdir()
        patch = (ROOT / 'runtime/patches/astral-audio-fix.patch').read_text()
        section = patch.split('+++ b/runtime/src/audio_completion.h\n', 1)[1].split('diff --git ', 1)[0]
        (directory / 'audio_completion.h').write_text(
            ''.join(line[1:] for line in section.splitlines(True)
                    if line.startswith('+') and not line.startswith('+++')))
        fixture = directory / 'completion.cpp'
        fixture.write_text(r'''#include <cassert>
#include <chrono>
#include <future>
#include <thread>
#include "audio_completion.h"
int main() {
    using namespace nx::audio_completion;
    for (unsigned phase = 0; phase != 2; ++phase) {
    Queue queue;
    std::promise<void> blocked, unblock;
    auto gate = unblock.get_future();
    auto consumer = std::async(std::launch::async, [&] {
        unsigned expected = 0;
        while (expected != 10000) {
            Packet* p = queue.take();
            if (!p) { std::this_thread::yield(); continue; }
            while (p) {
                auto* next = p->next;
                assert(reinterpret_cast<uintptr_t>(p->first) == expected);
                assert(p->second.size() == 8 && p->second[0] == expected % 256);
                if (!expected) { blocked.set_value(); if (!phase) gate.wait(); }
                delete p;
                p = next;
                ++expected;
            }
        }
        assert(queue.take() == nullptr);
    });
    queue.push(new Packet(nullptr, std::vector<uint8_t>(8, 0)));
    blocked.get_future().wait();
    // A stalled guest release must not block the device's completion publisher.
    auto producer = std::async(std::launch::async, [&] {
        for (uintptr_t n = 1; n != 10000; ++n)
            queue.push(new Packet(reinterpret_cast<void*>(n), std::vector<uint8_t>(8, n % 256)));
    });
    const bool independent = producer.wait_for(std::chrono::seconds(2)) == std::future_status::ready;
    unblock.set_value();
    producer.get();
    consumer.get();
    assert(independent);
    }
}
''')
        binary = directory / 'completion'
        result = subprocess.run([compiler, '-std=c++20', '-pthread', '-I', str(directory),
                                 str(fixture), '-o', str(binary)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def envelope_report(self, values, events=()):
        return {'rms_over_time': [{'rms': v} for v in values], 'events': list(events),
                'thresholds': {'window_ms': 10}}

    def test_loopback_alignment_delay_gain_and_inserted_gap(self):
        import random
        rng = random.Random(481)
        source = [.05 + rng.random() * .2 for _ in range(3600)]
        # 170 ms startup delay, then a 30 ms inserted gap at source 15 s.
        capture = [0] * 17 + [v * .5 for v in source[:1500]] + [0] * 3 + [v * .5 for v in source[1500:]]
        events = [{'kind': 'silence_gap', 'start_seconds': 15.17, 'end_seconds': 15.20}]
        result = check.compare_reports(self.envelope_report(source), self.envelope_report(capture, events))
        self.assertEqual(result['status'], 'aligned')
        self.assertAlmostEqual(result['anchors'][0]['offset_seconds'], .17)
        self.assertAlmostEqual(result['anchors'][2]['offset_seconds'], .20)
        self.assertAlmostEqual(result['offset_change_seconds'], .03)
        self.assertEqual(result['capture_silence_candidates'][0]['classification'], 'loopback_only_candidate')
        # An observed source silence must not become a new device-only gap.
        source_event = {'kind': 'silence_gap', 'start_seconds': 15, 'end_seconds': 15.03}
        result = check.compare_reports(self.envelope_report(source, [source_event]),
                                       self.envelope_report(capture, events))
        self.assertEqual(result['capture_silence_candidates'][0]['classification'], 'source_silence_candidate')

    def test_loopback_alignment_refuses_silence_and_unrelated_signal(self):
        import random
        rng = random.Random(24)
        source = [.05 + rng.random() * .2 for _ in range(400)]
        capture = [.05 + rng.random() * .2 for _ in range(400)]
        result = check.compare_reports(self.envelope_report(source), self.envelope_report(capture))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['anchors'][0]['status'], 'unmatched')
        result = check.compare_reports(self.envelope_report([0] * 400), self.envelope_report([0] * 400))
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['offset_change_seconds'])
        self.assertEqual(result['anchors'][0]['status'], 'insufficient_signal')

    def test_loopback_excursion_and_preroll_are_not_confirmed_device_gaps(self):
        import random
        rng = random.Random(521)
        source = [.05 + rng.random() * .2 for _ in range(4200)]
        # A two-second patch has a different delay, then returns to its old
        # alignment. Keep that observation, but do not treat it as an established
        # new lag for classifying nearby gaps.
        capture = [0] * 100 + source.copy()
        capture[2150:2350] = source[2000:2200]
        events = [{'kind': 'silence_gap', 'start_seconds': .2, 'end_seconds': .3}]
        report = check.compare_reports(self.envelope_report(source), self.envelope_report(capture, events))
        middle = next(a for a in report['anchors'] if a['reference_seconds'] == 20)
        self.assertEqual(middle['status'], 'ambiguous_offset_excursion')
        self.assertAlmostEqual(middle['offset_seconds'], 1.5)
        self.assertEqual(report['capture_silence_candidates'][0]['classification'], 'outside_reference_coverage')

    def test_loopback_gap_is_not_classified_using_a_stale_anchor(self):
        import random
        rng = random.Random(41)
        source = [.1 + rng.random() * .2 for _ in range(400)] + [.0001] * 5600
        capture = [0] * 100 + source
        event = {'kind': 'silence_gap', 'start_seconds': 50, 'end_seconds': 51}
        report = check.compare_reports(self.envelope_report(source), self.envelope_report(capture, [event]))
        gap = report['capture_silence_candidates'][0]
        self.assertEqual(gap['classification'], 'unaligned_capture_gap')
        self.assertEqual(gap['reason'], 'no_nearby_matched_anchor')
        self.assertNotIn('reference_start_seconds', gap)

    def test_cli_json_and_invalid_file_exit_code(self):
        self.write(self.tone(.1))
        out = self.path.with_suffix('.json')
        r = subprocess.run([sys.executable, str(ROOT / 'tools/audio_glitch_check.py'), str(self.path), '-o', str(out)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(out.read_text())['schema'], 1)
        self.path.write_bytes(b'bad WAV')
        r = subprocess.run([sys.executable, str(ROOT / 'tools/audio_glitch_check.py'), str(self.path)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn('RIFF', r.stderr)

    def test_empty_truncated_and_invalid_thresholds(self):
        self.write([])
        self.assertEqual(check.analyze(self.path)['summary']['rms'], 0)
        self.write(self.tone(.01))
        self.path.write_bytes(self.path.read_bytes()[:-2])
        with self.assertRaisesRegex(ValueError, 'truncated'):
            check.analyze(self.path)
        with self.assertRaisesRegex(ValueError, 'threshold'):
            check.analyze(self.path, window_ms=float('nan'))

    def test_short_gap_threshold_and_channel_delta_independence(self):
        frames = self.tone(.5)
        # Loud/high-frequency left channel must not mask an isolated click in the right.
        for k, frame in enumerate(frames):
            frame[0] = .6 * math.sin(2 * math.pi * 10000 * k / self.rate)
        frames[12000][1] = .9
        self.write(frames)
        clicks = [e for e in check.analyze(self.path)['events'] if e['kind'] == 'click']
        self.assertEqual(len(clicks), 1)
        self.assertEqual(clicks[0]['channel'], 1)
        self.write(self.tone(.1) + [[0, 0]] * 480 + self.tone(.1))
        self.assertFalse(any(e['kind'] == 'silence_gap' for e in check.analyze(self.path)['events']))


if __name__ == '__main__':
    unittest.main()
