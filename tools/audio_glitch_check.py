#!/usr/bin/env python3
"""Stream a PCM/float RIFF WAV into a conservative, timestamped JSON glitch report.

Pure stdlib. Candidate signal anomalies are not proof of an audible defect. A pre-device
NX_AUDIO_DUMP omits host-inserted silence; pass its .jsonl sidecar to see host underruns.
"""
import argparse
import bisect
import collections
import json
import math
from pathlib import Path
import statistics
import struct
import sys


class WavReader:
    """Bounded RIFF reader, including Windows WAVE_FORMAT_EXTENSIBLE and IEEE float."""
    def __init__(self, path):
        self.file = open(path, 'rb')
        try:
            header = self.file.read(12)
            if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
                raise ValueError('expected little-endian RIFF WAVE (RF64/RIFX are unsupported)')
            physical = self.file.seek(0, 2)
            end = min(physical, struct.unpack_from('<I', header, 4)[0] + 8)
            self.file.seek(12)
            fmt = data = None
            while self.file.tell() + 8 <= end:
                name, size = struct.unpack('<4sI', self.file.read(8))
                offset = self.file.tell()
                if offset + size > end:
                    raise ValueError('truncated WAV chunk')
                if name == b'fmt ':
                    if size < 16 or size > 65536:
                        raise ValueError('invalid fmt chunk size')
                    fmt = self.file.read(size)
                if name == b'data' and data is None:
                    data = (offset, size)
                self.file.seek(offset + size + (size & 1))
            if fmt is None or data is None:
                raise ValueError('WAV needs fmt and data chunks')
            tag, self.channels, self.rate, byte_rate, align, bits = struct.unpack_from('<HHIIHH', fmt)
            self.valid_bits = bits
            if tag == 0xfffe:
                if len(fmt) < 40 or struct.unpack_from('<H', fmt, 16)[0] < 22:
                    raise ValueError('short extensible fmt')
                self.valid_bits = struct.unpack_from('<H', fmt, 18)[0] or bits
                guid = fmt[24:40]
                if guid[4:] != bytes.fromhex('00001000800000aa00389b71'):
                    raise ValueError('unsupported extensible subformat GUID')
                tag = struct.unpack_from('<I', guid)[0]
            if not (1 <= self.channels <= 32 and 1 <= self.rate <= 768000):
                raise ValueError('invalid channel count or sample rate')
            if (tag == 1 and bits not in (8, 16, 24, 32)) or (tag == 3 and bits not in (32, 64)) or tag not in (1, 3):
                raise ValueError('only integer PCM 8/16/24/32 or IEEE float 32/64 is supported')
            if not 1 <= self.valid_bits <= bits or (tag == 3 and self.valid_bits != bits):
                raise ValueError('invalid valid-bits count')
            self.width, self.align, self.bits, self.tag = bits // 8, align, bits, tag
            if align != self.channels * self.width or byte_rate != self.rate * align or data[1] % align:
                raise ValueError('inconsistent WAV frame geometry')
            self.frames = data[1] // align
            self.remaining = self.frames
            self.file.seek(data[0])
            self.clip_high = 1.0 if tag == 3 else 1.0 - 2.0 ** (1 - self.valid_bits)
            self.trailing_bytes = physical - (data[0] + data[1])
        except BaseException:
            self.file.close()
            raise

    def read(self, frames):
        n = min(frames, self.remaining)
        raw = self.file.read(n * self.align)
        if len(raw) != n * self.align:
            raise ValueError('truncated PCM data')
        self.remaining -= n
        if self.tag == 3:
            values = [x[0] for x in struct.iter_unpack('<f' if self.width == 4 else '<d', raw)]
            if not all(math.isfinite(v) for v in values):
                raise ValueError('non-finite floating point sample')
            return values
        if self.width == 1:
            return [(v - 128) / 128.0 for v in raw]
        scale = float(1 << (self.bits - 1))
        if self.width in (2, 4):
            return [v[0] / scale for v in struct.iter_unpack('<h' if self.width == 2 else '<i', raw)]
        return [int.from_bytes(raw[k:k + 3], 'little', signed=True) / scale for k in range(0, len(raw), 3)]


def db(value):
    return 20 * math.log10(value) if value > 0 else None  # JSON null is -infinity


def timing_report(path, rate, frames):
    """Read block-start timestamps, never compare whole process lifetime with trimmed PCM."""
    if path is None:
        return {'status': 'unavailable', 'reason': 'no timestamps; sample rate is header-declared only'}, []
    first = last = None
    events, late, positions = [], [], []
    production = []
    count = 0
    truncated_tail = False
    previous_frame = previous_ns = None
    backend = 'sdl_callback'
    submit_failures = 0
    with open(path, encoding='utf-8') as f:
        for line_number, line in enumerate(f, 1):
            try:
                item = json.loads(line)
                kind = item['type']
                if kind == 'pcm':
                    frame, ns = item['frame'], item['monotonic_ns']
                    backend = item.get('host_backend', backend)
                    failures = item.get('host_submit_failures', 0)
                    if type(failures) is not int or failures < submit_failures:
                        raise ValueError('submit failure counts must be nonnegative and not decrease')
                    submit_failures = failures
                    if (type(frame) is not int or type(ns) is not int or frame < 0 or ns < 0 or
                            (previous_frame is not None and (frame <= previous_frame or ns < previous_ns))):
                        raise ValueError('PCM timestamps must increase in frame and not decrease in time')
                    previous_frame, previous_ns = frame, ns
                    if frame >= frames:
                        continue  # killed dump: sidecar can extend beyond last WAV header fixup
                    if first is None:
                        first = item
                    if last is not None:
                        expected = (frame - last['frame']) / rate
                        elapsed = (ns - last['monotonic_ns']) / 1e9
                        if elapsed - expected > .005:
                            late.append({'kind': 'late_buffer', 'classification': 'late_pcm_delivery',
                                         'confidence': 'measured_timestamp', 'start_frame': frame,
                                         'start_seconds': frame / rate,
                                         'arrival_seconds': (ns - first['monotonic_ns']) / 1e9,
                                         'late_seconds': elapsed - expected})
                    last = item
                    production.append({key: item[key] for key in ('frame', 'monotonic_ns', 'frames') if key in item})
                    count += 1
                elif kind == 'device':
                    played, ns = item['played_frame'], item['monotonic_ns']
                    if (type(played) is not int or type(ns) is not int or played < 0 or ns < 0 or
                            (positions and (played < positions[-1]['played_frame'] or ns < positions[-1]['monotonic_ns']))):
                        raise ValueError('device positions must not decrease in frame or time')
                    positions.append({'played_frame': played, 'monotonic_ns': ns})
                elif kind == 'completion':
                    ns, duration = item['monotonic_ns'], item['duration_ns']
                    if type(ns) is not int or ns < 0 or type(duration) is not int or duration < 0:
                        raise ValueError('invalid completion timing')
                    events.append({'kind': 'host_slow_completion', 'classification': 'slow_completion_handler',
                                   'confidence': 'measured_timestamp', 'monotonic_ns': ns,
                                   'duration_seconds': duration / 1e9})
                elif kind == 'host' and item.get('missing_frames', 0) > 0:
                    startup = item.get('startup', False)
                    events.append({'kind': 'host_underrun', 'classification': 'startup_empty_queue' if startup else
                                   'device_callback_starvation', 'confidence': 'measured_counter',
                                   'host_frame': item['frame'], 'monotonic_ns': item['monotonic_ns'],
                                   'missing_frames': item['missing_frames'],
                                   'duration_seconds': item['missing_frames'] / rate,
                                   'underrun_callbacks': item.get('underrun_callbacks')})
                if kind == 'host' and item.get('late_callback_ns', 0) > 0:
                    events.append({'kind': 'host_late_callback', 'classification': 'delayed_host_callback',
                                   'confidence': 'measured_timestamp', 'host_frame': item['frame'],
                                   'monotonic_ns': item['monotonic_ns'],
                                   'late_seconds': item['late_callback_ns'] / 1e9})
            except json.JSONDecodeError as error:
                if not line.endswith('\n'):
                    truncated_tail = True  # killed buffered writer; only the final incomplete line is ignored
                    break
                raise ValueError(f'invalid timing JSONL line {line_number}: {error}') from error
            except (ValueError, TypeError, KeyError) as error:
                raise ValueError(f'invalid timing JSONL line {line_number}: {error}') from error
    for e in events:
        e['backend'] = backend
        if backend == 'xaudio2_processing_pass' and e['kind'] == 'host_underrun':
            e['classification'] = ('startup_processing_deficit' if e['classification'] == 'startup_empty_queue'
                                   else 'xaudio2_pass_entry_deficit')
            e['confidence'] = 'measured_deficit_not_loopback_drop'
    if first:
        for e in events:
            e['seconds_from_first_pcm'] = (e['monotonic_ns'] - first['monotonic_ns']) / 1e9
    # Rejected packets remain in the pre-device WAV but never advance SamplesPlayed.
    # A single origin subtraction no longer maps the two sample timelines in that case.
    cursor_mapping = ('unavailable_rejected_packets' if submit_failures else
                      'available' if first and type(first.get('host_submitted_frames')) is int else
                      'unavailable_no_origin')
    if cursor_mapping == 'available':
        origin = first['host_submitted_frames']
        for position in positions:
            position['pcm_frame'] = position['played_frame'] - origin
            position['pcm_seconds'] = position['pcm_frame'] / rate
            position['seconds_from_first_pcm'] = (position['monotonic_ns'] - first['monotonic_ns']) / 1e9
    device_clock = {'status': 'unavailable'}
    sounding_positions = [p for p in positions if first and last and
                          first['monotonic_ns'] <= p['monotonic_ns'] <= last['monotonic_ns'] and
                          p.get('pcm_frame', -1) >= 0]
    if len(sounding_positions) > 1:
        start, end = sounding_positions[0], sounding_positions[-1]
        elapsed = (end['monotonic_ns'] - start['monotonic_ns']) / 1e9
        if elapsed > 0:
            seconds = (end['played_frame'] - start['played_frame']) / rate
            device_clock = {'status': 'measured', 'domain': 'XAudio2 consumed samples before endpoint latency',
                            'startup_excluded': True, 'timestamp_span_seconds': elapsed, 'sample_span_seconds': seconds,
                            'drift_seconds': seconds - elapsed}
    details = {'host_backend': backend, 'device_cursor_mapping': cursor_mapping,
               'device_clock': device_clock, 'device_positions': positions,
               'pcm_positions': production, 'pcm_records': count, 'ignored_truncated_tail': truncated_tail, 'late_buffers': late,
               'late_buffer_threshold_seconds': .005,
               'host_counters': {key: last.get(key) if last else None for key in
                                 ('host_probe_active', 'host_underrun_callbacks', 'host_missing_frames',
                                  'lost_host_events', 'host_callbacks', 'host_requested_frames',
                                  'host_late_callbacks', 'host_submit_failures', 'host_completed_buffers',
                                  'host_max_completion_ns', 'host_max_release_ns',
                                  'host_max_release_lock_ns', 'host_max_release_event_ns')}}
    counters = details['host_counters']
    details['host_event_coverage'] = ('incomplete' if counters['lost_host_events'] or truncated_tail else
                                      'through_last_pcm_record' if counters['host_probe_active'] else 'unavailable')
    if count < 2 or last['monotonic_ns'] <= first['monotonic_ns']:
        return {'status': 'insufficient_timestamps', **details}, events
    elapsed = (last['monotonic_ns'] - first['monotonic_ns']) / 1e9
    audio_seconds = (last['frame'] - first['frame']) / rate
    return {'status': 'measured', 'domain': 'PCM production, not device playback clock', **details,
            'timestamp_span_seconds': elapsed, 'audio_span_seconds': audio_seconds,
            'effective_rate_hz': (last['frame'] - first['frame']) / elapsed,
            'drift_seconds': audio_seconds - elapsed, 'drift_ppm': (audio_seconds / elapsed - 1) * 1e6}, events


def analyze(path, *, timestamps=None, window_ms=10.0, silence_db=-60.0, active_db=-45.0,
            gap_ms=20.0, context_ms=250.0, delta_floor=0.2, delta_ratio=8.0):
    options = (window_ms, gap_ms, context_ms, delta_floor, delta_ratio)
    if (not all(math.isfinite(v) and v > 0 for v in options) or
            not all(math.isfinite(v) for v in (silence_db, active_db)) or not silence_db < active_db <= 0):
        raise ValueError('invalid detector thresholds')
    wav = WavReader(path)
    try:
        size = max(1, round(wav.rate * window_ms / 1000))
        rms, events = [], []
        previous = [None] * wav.channels
        clips = [None] * wav.channels
        clicks = [None] * wav.channels
        clipped_samples = [0] * wav.channels
        total_sq, peak, at = 0.0, 0.0, 0
        merge_frames = max(1, round(wav.rate * .002))
        silent = 10 ** (silence_db / 20)
        active = 10 ** (active_db / 20)
        context_frames = wav.rate * context_ms / 1000
        minimum_gap = math.ceil(wav.rate * gap_ms / 1000)
        quiet_start, quiet_before, last_active = None, -1, -1
        pending_gaps = []

        def finish_clip(ch):
            span = clips[ch]
            if span:
                events.append({'kind': 'clipping', 'classification': 'full_scale_samples', 'confidence': 'candidate',
                               'channel': ch, 'start_frame': span[0], 'end_frame': span[1] + 1,
                               'samples': span[1] - span[0] + 1})
                clips[ch] = None

        def finish_click(ch):
            if clicks[ch]:
                events.append(clicks[ch])
                clicks[ch] = None

        while wav.remaining:
            values = wav.read(size)
            n = len(values) // wav.channels
            channel_rms = []
            quiet_frames, active_frames = [True] * n, [False] * n
            for ch in range(wav.channels):
                samples = values[ch::wav.channels]
                sq = sum(v * v for v in samples)
                total_sq += sq
                channel_rms.append(math.sqrt(sq / n))
                deltas = [abs(b - a) for a, b in zip(samples, samples[1:])]
                # Local robust baseline prevents clean high-frequency tones being reported as clicks.
                baseline = statistics.median(deltas) if deltas else 0.0
                threshold = max(delta_floor, baseline * delta_ratio)
                for i, v in enumerate(samples):
                    frame = at + i
                    magnitude = abs(v)
                    peak = max(peak, magnitude)
                    if magnitude > silent:
                        quiet_frames[i] = False
                    if magnitude >= active:
                        active_frames[i] = True
                    if v >= wav.clip_high or v <= -1.0:
                        clipped_samples[ch] += 1
                        if clips[ch] is None:
                            clips[ch] = [frame, frame]
                        else:
                            clips[ch][1] = frame
                    else:
                        finish_clip(ch)
                    if previous[ch] is not None:
                        delta = abs(v - previous[ch])
                        if delta > threshold:
                            e = clicks[ch]
                            if e and frame - e['end_frame'] > merge_frames:
                                finish_click(ch)
                                e = None
                            if e is None:
                                e = {'kind': 'click', 'classification': 'sample_delta_outlier',
                                     'confidence': 'candidate', 'channel': ch, 'start_frame': frame,
                                     'end_frame': frame + 1, 'outlier_deltas': 0, 'max_delta': 0.0,
                                     'threshold': threshold}
                                clicks[ch] = e
                            e['end_frame'] = frame + 1
                            e['outlier_deltas'] += 1
                            e['max_delta'] = max(e['max_delta'], delta)
                    previous[ch] = v
            # Track all-channel quiet runs across chunk boundaries. Whole RMS windows would miss a
            # single 1024-frame (21.3 ms) dropout whenever its edges straddle two 10 ms windows.
            for i, quiet in enumerate(quiet_frames):
                frame = at + i
                if quiet and quiet_start is None:
                    quiet_start, quiet_before = frame, last_active
                if not quiet and quiet_start is not None:
                    if (frame - quiet_start >= minimum_gap and quiet_before >= 0 and
                            quiet_start - quiet_before <= context_frames):
                        pending_gaps.append((quiet_start, frame))
                    quiet_start = None
                if active_frames[i]:
                    for start, end in pending_gaps:
                        if frame - end <= context_frames:
                            events.append({'kind': 'silence_gap', 'classification': 'silence_inside_active_passage',
                                           'confidence': 'candidate', 'start_frame': start, 'end_frame': end})
                    pending_gaps.clear()
                    last_active = frame
            rms.append({'start_frame': at, 'end_frame': at + n, 'start_seconds': at / wav.rate,
                        'rms': math.sqrt(sum(v * v for v in channel_rms) / wav.channels),
                        'channel_rms': channel_rms})
            at += n
        for ch in range(wav.channels):
            finish_clip(ch)
            finish_click(ch)
        for e in events:
            e['start_seconds'] = e['start_frame'] / wav.rate
            e['end_seconds'] = e['end_frame'] / wav.rate
        events.sort(key=lambda e: (e['start_frame'], e['kind'], e.get('channel', -1)))
        timing, host_events = timing_report(timestamps, wav.rate, wav.frames)
        counts = collections.Counter(e['kind'] for e in events + host_events + timing.get('late_buffers', []))
        for row in rms:
            row['dbfs'] = db(row['rms'])
        return {'schema': 1, 'input': str(path), 'format': {'sample_rate_hz': wav.rate, 'channels': wav.channels,
                'bits_per_sample': wav.bits, 'encoding': 'float' if wav.tag == 3 else 'PCM',
                'frames': wav.frames, 'duration_seconds': wav.frames / wav.rate,
                'bytes_after_declared_data': wav.trailing_bytes},
                'thresholds': {'window_ms': size / wav.rate * 1000, 'silence_dbfs': silence_db,
                'active_dbfs': active_db, 'minimum_gap_ms': gap_ms, 'context_ms': context_ms,
                'silence_metric': 'per-frame peak across all channels',
                'delta_floor': delta_floor, 'delta_median_ratio': delta_ratio},
                'summary': {'rms': math.sqrt(total_sq / (wav.frames * wav.channels)) if wav.frames else 0.0,
                'peak': peak, 'clipped_samples_by_channel': clipped_samples, 'event_counts': dict(counts)},
                'rms_over_time': rms, 'events': events, 'timing': timing, 'host_events': host_events,
                'limitations': ['Signal events are candidates; intentional transients and pauses may match.',
                'Pre-device PCM omits host-inserted silence; host counters require a timing sidecar.',
                'Production timestamps measure delivery drift, not hardware sample-clock error.',
                'Silence boundaries use the sample amplitude threshold; no resampling is performed.']}
    finally:
        wav.file.close()


def frame_timing_report(path, timing, rate):
    """Join dumped-frame readiness with PCM production and XAudio2 consumption.

    This measures software queue lead at each captured frame; it cannot establish
    lip sync without matched content events and display/endpoint latency calibration.
    """
    pcm, device = timing.get('pcm_positions', []), timing.get('device_positions', [])
    p_times = [p['monotonic_ns'] for p in pcm]
    d_times = [p['monotonic_ns'] for p in device]
    rows = []
    previous_ns = previous_frame = -1
    with open(path, encoding='utf-8') as f:
        for line_number, line in enumerate(f, 1):
            try:
                row = json.loads(line)
                frame, ns = row['frame'], row['readback_ready_ns']
                if (type(frame) is not int or type(ns) is not int or frame <= previous_frame or
                        ns < 0 or ns < previous_ns):
                    raise ValueError('frame timestamps must increase')
                previous_frame, previous_ns = frame, ns
            except (ValueError, TypeError, KeyError) as error:
                raise ValueError(f'invalid frame JSONL line {line_number}: {error}') from error
            entry = {'frame': frame, 'readback_ready_ns': ns, 'status': 'unavailable'}
            p, d = bisect.bisect_right(p_times, ns) - 1, bisect.bisect_right(d_times, ns) - 1
            if p >= 0 and 0 <= d < len(device) - 1 and 'pcm_frame' in device[d]:
                before, after = device[d], device[d + 1]
                span = after['monotonic_ns'] - before['monotonic_ns']
                entry['device_bracket_seconds'] = span / 1e9
                if span > 50000000:
                    # A stalled/lost callback interval is precisely where a uniform
                    # sample-progress assumption would hide the behavior being measured.
                    entry['reason'] = 'device_cursor_gap'
                    rows.append(entry)
                    continue
                fraction = (ns - before['monotonic_ns']) / span if span else 0
                played = before['pcm_frame'] + fraction * (after['pcm_frame'] - before['pcm_frame'])
                produced = pcm[p]['frame'] + pcm[p].get('frames', 0)
                entry.update(status='measured', seconds_from_first_pcm=(ns - p_times[0]) / 1e9,
                             consumed_pcm_seconds=played / rate, produced_pcm_seconds=produced / rate,
                             production_lead_seconds=(produced - played) / rate,
                             device_bracket_seconds=span / 1e9)
            rows.append(entry)
    return {'domain': 'frame readback readiness versus XAudio2 consumed samples before endpoint latency',
            'maximum_device_bracket_seconds': .05,
            'frames': rows, 'limitation': 'Queue lead is not a content-based A/V sync measurement or scanout timestamp.'}


def compare_reports(reference, capture, *, anchor_seconds=2.0, stride_seconds=10.0, search_seconds=1.0):
    """Align RMS envelopes, reporting file-relative delay and unmatched windows.

    This is deliberately a coarse comparison, not sample-clock calibration or an A/V
    sync verdict. WASAPI recorder padding and gain changes can also reduce correlation.
    """
    ref, got = reference['rms_over_time'], capture['rms_over_time']
    step = reference['thresholds']['window_ms'] / 1000
    if capture['thresholds']['window_ms'] != reference['thresholds']['window_ms']:
        raise ValueError('reference and capture need identical RMS window sizes')
    width = max(4, round(anchor_seconds / step))
    stride = max(width, round(stride_seconds / step))
    radius = max(1, round(search_seconds / step))
    a = [w['rms'] for w in ref]
    b = [w['rms'] for w in got]
    anchors = []
    offset = None
    def match(start, lo, hi):
        values = a[start:start + width]
        mean = sum(values) / width
        centered = [v - mean for v in values]
        energy = sum(v * v for v in centered)
        if energy < 1e-10 or max(values) < 10 ** (-45 / 20):
            return None  # no discriminating signal: do not align silence
        best = None
        for pos in range(max(0, lo), min(len(b) - width, hi) + 1):
            target = b[pos:pos + width]
            average = sum(target) / width
            target_energy = sum((v - average) ** 2 for v in target)
            if target_energy < 1e-10:
                continue
            score = sum(v * (w - average) for v, w in zip(centered, target)) / math.sqrt(energy * target_energy)
            if best is None or score > best[0]:
                best = (score, pos)
        return best
    for start in range(0, len(a) - width + 1, stride):
        lo, hi = (0, len(b) - width) if offset is None else (start + offset - radius, start + offset + radius)
        result = match(start, lo, hi)
        if result is None:
            anchors.append({'reference_seconds': start * step, 'status': 'insufficient_signal'})
            continue
        score, pos = result
        accepted = score >= .8
        anchors.append({'reference_seconds': start * step, 'capture_seconds': pos * step,
                        'offset_seconds': (pos - start) * step, 'correlation': score,
                        'status': 'matched' if accepted else 'unmatched'})
        if accepted:
            offset = pos - start
    matched = [a for a in anchors if a['status'] == 'matched']
    for previous, current, following in zip(matched, matched[1:], matched[2:]):
        # A one-anchor excursion that immediately returns is ambiguous: repeated
        # music can correlate well at a wrong lag. Keep the candidate in the report
        # but do not let it relabel a nearby source pause as a new device dropout.
        if (abs(previous['offset_seconds'] - following['offset_seconds']) <= 2 * step + 1e-9 and
                abs(current['offset_seconds'] - previous['offset_seconds']) > 5 * step and
                following['reference_seconds'] - previous['reference_seconds'] <= 2 * stride * step + 1e-9):
            current['status'] = 'ambiguous_offset_excursion'
    matched = [a for a in anchors if a['status'] == 'matched']
    change = matched[-1]['offset_seconds'] - matched[0]['offset_seconds'] if len(matched) > 1 else None
    gaps = []
    for event in capture['events']:
        if event['kind'] != 'silence_gap':
            continue
        entry = {'capture_start_seconds': event['start_seconds'], 'capture_end_seconds': event['end_seconds'],
                 'classification': 'unaligned_capture_gap'}
        if matched:
            # Use the nearest anchor: cumulative delay need not be constant after a stall.
            near = min(matched, key=lambda a: abs(a['capture_seconds'] - event['start_seconds']))
            distance = abs(near['capture_seconds'] - event['start_seconds'])
            entry['nearest_anchor_distance_seconds'] = distance
            if distance > (stride + width) * step:
                entry['reason'] = 'no_nearby_matched_anchor'
                gaps.append(entry)
                continue
            t = event['start_seconds'] - near['offset_seconds']
            end = event['end_seconds'] - near['offset_seconds']
            source_gap = any(e['kind'] == 'silence_gap' and
                             e['start_seconds'] <= end + step and e['end_seconds'] >= t - step
                             for e in reference['events'])
            entry.update(reference_start_seconds=t, reference_end_seconds=end,
                         classification=('outside_reference_coverage' if t < 0 or end > len(a) * step else
                                         'source_silence_candidate' if source_gap else 'loopback_only_candidate'))
        gaps.append(entry)
    return {'status': 'aligned' if matched else 'unavailable', 'method': 'normalized RMS envelope correlation',
            'resolution_seconds': step, 'anchor_seconds': width * step, 'minimum_correlation': .8,
            'maximum_gap_anchor_distance_seconds': (stride + width) * step,
            'offset_domain': 'capture file time minus reference file time', 'anchors': anchors,
            'offset_change_seconds': change, 'capture_silence_candidates': gaps,
            'limitations': ['Repeated audio may produce ambiguous matches; inspect anchors against the scene.',
                           'An isolated offset excursion is retained as ambiguous and excluded from gap mapping.',
                           'An offset change includes recorder padding, resampling and device/producer stalls.',
                           'This comparison does not establish cutscene A/V synchronization.']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav', type=Path)
    parser.add_argument('--frame-timestamps', type=Path, help='frames/timing.jsonl from the same game run')
    parser.add_argument('--reference', type=Path, help='pre-device WAV to compare against this loopback recording')
    parser.add_argument('--timestamps', type=Path, help='NX_AUDIO_DUMP .jsonl sidecar (optional)')
    parser.add_argument('-o', '--output', type=Path, help='default: JSON on stdout')
    parser.add_argument('--window-ms', type=float, default=10)
    parser.add_argument('--silence-db', type=float, default=-60)
    parser.add_argument('--active-db', type=float, default=-45)
    parser.add_argument('--gap-ms', type=float, default=20)
    parser.add_argument('--context-ms', type=float, default=250)
    parser.add_argument('--delta-floor', type=float, default=.2)
    parser.add_argument('--delta-ratio', type=float, default=8)
    args = parser.parse_args(argv)
    try:
        report = analyze(args.wav, timestamps=args.timestamps, window_ms=args.window_ms, silence_db=args.silence_db,
                         active_db=args.active_db, gap_ms=args.gap_ms, context_ms=args.context_ms,
                         delta_floor=args.delta_floor, delta_ratio=args.delta_ratio)
        if args.frame_timestamps:
            report['frame_timing'] = frame_timing_report(args.frame_timestamps, report['timing'],
                                                       report['format']['sample_rate_hz'])
        if args.reference:
            reference = analyze(args.reference, window_ms=args.window_ms, silence_db=args.silence_db,
                                active_db=args.active_db, gap_ms=args.gap_ms, context_ms=args.context_ms,
                                delta_floor=args.delta_floor, delta_ratio=args.delta_ratio)
            report['reference_comparison'] = compare_reports(reference, report)
        result = json.dumps(report, allow_nan=False, separators=(',', ':')) + '\n'
        if args.output:
            args.output.write_text(result, encoding='utf-8')
        else:
            sys.stdout.write(result)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(2, f'audio_glitch_check: {error}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
