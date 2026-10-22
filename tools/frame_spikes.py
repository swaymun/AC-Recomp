#!/usr/bin/env python3
"""Summarize NX_FRAME_LOG telemetry; all times are host monotonic, in nanoseconds.

Example: python3 tools/frame_spikes.py nx.log --fps 30 --end-frame 3600
Compilation events are attributed by interval overlap, never log-line adjacency.
The first present (interval_ms=0) is excluded. Histograms alone are insufficient.
"""
import argparse
import bisect
import json
import math
from pathlib import Path
import re
import sys

FRAME = re.compile(r'shader-cache frame index=(\d+) ts_ns=(\d+) interval_ms=([\d.eE+-]+)')
COMPILE = re.compile(r'shader-cache compile kind=(\w+) start_ns=(\d+) end_ns=(\d+)(?: phase=(\w+))?')


def parse_log(text):
    frames, events = [], []
    for line_number, line in enumerate(text.splitlines(), 1):
        if 'shader-cache frame ' in line:
            match = FRAME.search(line)
            if not match:
                raise ValueError(f'malformed frame telemetry on line {line_number}')
            index, timestamp, interval = int(match[1]), int(match[2]), float(match[3])
            if not math.isfinite(interval) or interval < 0:
                raise ValueError(f'invalid interval on line {line_number}')
            if frames and (index <= frames[-1]['index'] or timestamp <= frames[-1]['ts_ns']):
                raise ValueError(f'non-increasing frames on line {line_number}; analyze each run separately')
            frames.append(dict(index=index, ts_ns=timestamp, interval_ms=interval))
        elif 'shader-cache compile ' in line:
            match = COMPILE.search(line)
            if not match or int(match[3]) < int(match[2]):
                raise ValueError(f'malformed compilation telemetry on line {line_number}')
            events.append(dict(kind=match[1], start_ns=int(match[2]), end_ns=int(match[3]),
                               phase=match[4] or 'runtime'))
    if not frames:
        raise ValueError('no per-frame telemetry; run with NX_FRAME_LOG=1 (histograms cannot supply spike counts)')
    return frames, events


def percentile(values, p):
    position = (len(values) - 1) * p
    low = int(position)
    return values[low] + (values[min(low + 1, len(values) - 1)] - values[low]) * (position - low)


def summarize(text, budget_ms=1000 / 30, start_frame=0, end_frame=None):
    if not math.isfinite(budget_ms) or budget_ms <= 0:
        raise ValueError('budget must be finite and positive')
    if start_frame < 0 or end_frame is not None and end_frame < start_frame:
        raise ValueError('invalid inclusive frame range')
    frames, events = parse_log(text)
    selected = [f for f in frames if f['interval_ms'] > 0 and f['index'] >= start_frame
                and (end_frame is None or f['index'] <= end_frame)]
    if not selected:
        raise ValueError('no measured intervals in selected frame range')
    values = sorted(f['interval_ms'] for f in selected)
    events.sort(key=lambda e: e['start_ns'])
    starts = [e['start_ns'] for e in events]
    spikes = []
    for f in selected:
        if f['interval_ms'] <= 2 * budget_ms and f['interval_ms'] <= 100:
            continue
        end = f['ts_ns']
        begin = end - round(f['interval_ms'] * 1e6)
        overlaps = [dict(e, overlap_ms=(min(end, e['end_ns']) - max(begin, e['start_ns'])) / 1e6)
                    for e in events[:bisect.bisect_left(starts, end)] if e['end_ns'] > begin]
        spikes.append(dict(f, above_2x=f['interval_ms'] > 2 * budget_ms,
                           above_100ms=f['interval_ms'] > 100, compilation=overlaps))
    # Report whole-log compilation separately: boot/prewarm may precede the first present.
    total_by_kind, total_by_phase = {}, {}
    selected_compile_ms = 0.0
    lo = selected[0]['ts_ns'] - round(selected[0]['interval_ms'] * 1e6)
    hi = selected[-1]['ts_ns']
    for e in events:
        ms = (e['end_ns'] - e['start_ns']) / 1e6
        total_by_kind[e['kind']] = total_by_kind.get(e['kind'], 0.0) + ms
        total_by_phase[e['phase']] = total_by_phase.get(e['phase'], 0.0) + ms
        selected_compile_ms += max(0, min(hi, e['end_ns']) - max(lo, e['start_ns'])) / 1e6
    return dict(schema=1, budget_ms=budget_ms, intervals=len(selected), first_frame=selected[0]['index'],
                last_frame=selected[-1]['index'], above_2x=sum(f['interval_ms'] > 2 * budget_ms for f in selected),
                above_100ms=sum(f['interval_ms'] > 100 for f in selected), longest_ms=values[-1],
                p50_ms=percentile(values, .5), p95_ms=percentile(values, .95), p99_ms=percentile(values, .99),
                compile_events=len(events), total_compile_ms=sum(total_by_kind.values()),
                compile_ms_by_kind=total_by_kind, compile_ms_by_phase=total_by_phase,
                selected_interval_compile_ms=selected_compile_ms,
                spikes_with_compilation=sum(bool(s['compilation']) for s in spikes), spikes=spikes)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    budget = parser.add_mutually_exclusive_group()
    budget.add_argument('--fps', type=float, default=None)
    budget.add_argument('--budget-ms', type=float, default=None)
    parser.add_argument('--start-frame', type=int, default=0)
    parser.add_argument('--end-frame', type=int)
    args = parser.parse_args(argv)
    try:
        if args.fps is not None and (not math.isfinite(args.fps) or args.fps <= 0):
            raise ValueError('fps must be finite and positive')
        budget_ms = args.budget_ms if args.budget_ms is not None else 1000 / (args.fps or 30)
        result = summarize(args.log.read_text(errors='replace'), budget_ms, args.start_frame, args.end_frame)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    json.dump(result, sys.stdout, indent=2, allow_nan=False)
    print()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
