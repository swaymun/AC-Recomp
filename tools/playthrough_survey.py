#!/usr/bin/env python3
"""Private headless surveys. No chapter unlocks or reachability inferred from boot.

run uses a private data root prepared by the caller (immutable asset links are OK;
user/ and frames/ must be local). analyze consumes a JSON manifest of run records.
All image processing uses the standard library, including binary PPM contact sheets.
"""
import argparse
from array import array
from contextlib import contextmanager
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import wave

FILES = [('01', 'Startup'), ('02', 'Awake'), ('03', 'Link'), ('04', 'Siege'),
         ('05', 'Accord'), ('06', 'Complicit'), ('07', 'Wild'), ('08', 'Peace'),
         ('09', 'Salvation'), ('10', 'Madness'), ('11', 'Reckoning'),
         ('12', 'Rebirth'), ('epilogue', 'Epilogue')]
PATTERNS = {
    'fatal': r'\bFATAL\b|\bCRASH: exception\b|access violation|segmentation fault|VK_ERROR_DEVICE_LOST',
    'gpu_hang': r'GPU hang|Caused GPU Hang Error',
    'render_error': r'upload buffer full|shader .+ rejected|invalid texture format',
    'resource_limit': r'memory: .+over the .+limit .+stopping',
    'stub': r'\bunimplemented\b|\bstub(?:bed)?\b',
    'missing_shader': (r'missing.{0,40}shader|shader.{0,160}(?:missing|not found)'
                       r'|nvn: shader .+: no .+\.spv\b|nvn: no .+results\.tsv'),
    'audio': r'underrun|audio.{0,40}(?:error|fail)|device.{0,20}lost',
}

# This adapter is built only beside a private executable copy. The surveyed
# Windows executable imports XINPUT1_4 ordinal 2 (XInputGetState). It never sends
# input to Windows or another process; only the file named by this process's
# NX_SURVEY_PAD_FILE is read. The eight-byte acknowledgement binds the writer to
# the exact process which loaded this DLL. No driver or system DLL is changed.
PAD_PROXY_SOURCE = r'''#include <windows.h>
struct Pad { WORD buttons; BYTE lt, rt; SHORT lx, ly, rx, ry; };
struct State { DWORD packet; Pad pad; };
#pragma pack(push, 1)
struct Report { char magic[4]; DWORD packet; ULONGLONG expires; Pad pad; };
#pragma pack(pop)
static_assert(sizeof(Pad) == 12 && sizeof(State) == 16 && sizeof(Report) == 28);
extern "C" __declspec(dllexport) DWORD WINAPI XInputGetState(DWORD index, State* out) {
    if (!out) return ERROR_BAD_ARGUMENTS;
    *out = {};
    if (index != 0) return ERROR_DEVICE_NOT_CONNECTED;
    wchar_t path[1024];
    DWORD n = GetEnvironmentVariableW(L"NX_SURVEY_PAD_FILE", path, 1019);
    if (!n || n >= 1019) return ERROR_DEVICE_NOT_CONNECTED;
    static LONG acknowledged = 0;
    if (InterlockedCompareExchange(&acknowledged, 1, 0) == 0) {
        wchar_t ack[1024];
        for (DWORD i = 0; i <= n; ++i) ack[i] = path[i];
        ack[n] = L'.'; ack[n+1] = L'a'; ack[n+2] = L'c'; ack[n+3] = L'k'; ack[n+4] = 0;
        HANDLE f = CreateFileW(ack, GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (f != INVALID_HANDLE_VALUE) {
            DWORD data[2] = {0x31444150, GetCurrentProcessId()}, wrote = 0;
            WriteFile(f, data, sizeof(data), &wrote, nullptr); CloseHandle(f);
        }
    }
    HANDLE f = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                           nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (f == INVALID_HANDLE_VALUE) return ERROR_SUCCESS;
    Report r{}; DWORD read = 0;
    BOOL ok = ReadFile(f, &r, sizeof(r), &read, nullptr); CloseHandle(f);
    if (!ok || read != sizeof(r) || r.magic[0] != 'A' || r.magic[1] != 'C' || r.magic[2] != 'R' || r.magic[3] != 'P')
        return ERROR_SUCCESS;
    FILETIME ft; GetSystemTimeAsFileTime(&ft);
    ULARGE_INTEGER ticks; ticks.LowPart = ft.dwLowDateTime; ticks.HighPart = ft.dwHighDateTime;
    ULONGLONG now = (ticks.QuadPart - 116444736000000000ULL) / 10000;
    out->packet = r.packet + (now > r.expires ? 1 : 0);
    if (now <= r.expires) out->pad = r.pad;
    return ERROR_SUCCESS;
}
'''
PAD_FORMAT = '<4sIQHBBhhhh'
PAD_BUTTONS = dict(A=0x2000, B=0x1000, X=0x8000, Y=0x4000, L=0x100, R=0x200,
                   UP=1, DOWN=2, LEFT=4, RIGHT=8, PLUS=0x10, MINUS=0x20,
                   LSTICK=0x40, RSTICK=0x80)


def pad_report(buttons, packet, expires, sticks=(0, 0, 0, 0)):
    names = {b.upper() for b in buttons}
    if names - (PAD_BUTTONS.keys() | {'ZL', 'ZR'}):
        raise ValueError('unknown Nintendo pad button')
    if len(sticks) != 4 or any(not -32768 <= s <= 32767 for s in sticks):
        raise ValueError('stick values must be signed 16-bit values')
    bits = 0
    for name in names:
        bits |= PAD_BUTTONS.get(name, 0)
    return struct.pack(PAD_FORMAT, b'ACRP', packet & 0xffffffff, expires,
                       bits, 255 if 'ZL' in names else 0, 255 if 'ZR' in names else 0, *sticks)


def write_pad(path, data):
    temp = path.with_suffix('.new')
    if path.is_symlink() or temp.is_symlink():
        raise ValueError('controller files must not be symlinks')
    temp.write_bytes(data)
    os.replace(temp, path)


@contextmanager
def controller_lock(path):
    """OS-owned per-run lock; a crashed writer cannot leave a stale exclusive lock."""
    if path.is_symlink():
        raise ValueError('controller lock must not be a symlink')
    with path.open('a+b') as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('another controller writer is active for this run') from error
        try:
            yield
        finally:
            stream.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def pad(args):
    root = Path(args.run).resolve()
    with controller_lock(root/'controller.lock'):
        if (root/'receipt.json').exists():
            raise ValueError('run has already ended')
        process = json.loads((root/'process.json').read_text())
        ack = (root/'controller.bin.ack').read_bytes()
        if not process.get('controlled_pad') or ack != struct.pack('<4sI', b'PAD1', process['pid']):
            raise ValueError('input adapter has not acknowledged this exact process')
        if not 0 < args.hold <= 2:
            raise ValueError('button hold must be greater than zero and at most two seconds')
        path = root/'controller.bin'
        old = struct.unpack(PAD_FORMAT, path.read_bytes())
        packet = (old[1]+2) & 0xffffffff  # also differs from the old report's expired/released packet
        start = time.time()
        report = pad_report(args.buttons, packet, int((start+args.hold)*1000),
                            (args.lx, args.ly, args.rx, args.ry))
        write_pad(path, report)
        try:
            time.sleep(args.hold)
        finally:
            write_pad(path, pad_report([], packet+1, int(time.time()*1000)+1000))
        released = time.time()
        with (root/'controls.jsonl').open('a') as log:
            log.write(json.dumps(dict(unix=start, pid=process['pid'], buttons=args.buttons,
                                      hold=args.hold, packet=packet, released_unix=released,
                                      sticks=[args.lx, args.ly, args.rx, args.ry], note=args.note))+'\n')
        return 0

def build_pad_proxy(args):
    if sys.platform != 'win32':
        raise ValueError('the isolated input adapter builds only on Windows')
    root = Path(args.out).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError('adapter output must be a new or empty private directory')
    compiler, setup = Path(args.compiler).resolve(), Path(args.vsdevcmd).resolve()
    for p in [root, compiler, setup]:
        if re.search(r'["%!\r\n&|<>^]', str(p)):
            raise ValueError('unsafe batch path')
    if not compiler.is_file() or not setup.is_file():
        raise ValueError('provide the installed clang-cl and VsDevCmd paths')
    root.mkdir(parents=True, exist_ok=True)
    (root/'survey-pad.cpp').write_text(PAD_PROXY_SOURCE)
    (root/'survey-pad.def').write_text('LIBRARY XINPUT1_4\nEXPORTS\n XInputGetState @2\n')
    command = (f'@echo off\r\ncall "{setup}" -arch=x64 >nul\r\nif errorlevel 1 exit /b 1\r\n'
               f'"{compiler}" /nologo /O2 /LD /MD /W4 survey-pad.cpp /link '
               '/OUT:xinput1_4.dll /DEF:survey-pad.def /IMPLIB:xinput1_4.lib\r\n')
    (root/'build.cmd').write_text(command, newline='')
    result = subprocess.run(['cmd.exe', '/d', '/s', '/c', str(root/'build.cmd')], cwd=root,
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (root/'proxy-build.log').write_text(result.stdout)
    if result.returncode or not (root/'xinput1_4.dll').is_file():
        raise RuntimeError('adapter build failed; inspect private proxy-build.log')
    return 0


def read_ppm(path):
    raw = Path(path).read_bytes()
    # Consume exactly one raster separator, never strip pixel whitespace.
    match = re.match(rb'P6\s+(?:#[^\n]*\n\s*)*(\d+)\s+(\d+)\s+255(\r\n|\s)', raw)
    if not match:
        raise ValueError('expected 8-bit P6 PPM')
    w, h = map(int, match.group(1, 2))
    pixels = raw[match.end():]
    if w < 1 or h < 1 or len(pixels) != w*h*3:
        raise ValueError('truncated or invalid PPM raster')
    return w, h, pixels


def inspect_frame(path):
    w, h, p = read_ppm(path)
    stride = max(1, w*h//10000)
    sample = [p[i*3:i*3+3] for i in range(0, w*h, stride)]
    black = sum(max(c) < 12 for c in sample)/len(sample)
    magenta = sum(c[0] > 180 and c[1] < 65 and c[2] > 180 for c in sample)/len(sample)
    return dict(path=str(path), black_fraction=round(black, 4),
                magenta_fraction=round(magenta, 4),
                flags=(['mostly_black_candidate'] if black > .95 else []) +
                      (['magenta_candidate'] if magenta > .25 else []))


def contact_sheet(paths, output):
    """At most 24 evenly spaced frames; sidecar maps tile to exact source path."""
    paths = list(paths)
    if not paths:
        return None
    chosen = [paths[round(i*(len(paths)-1)/max(1, min(24, len(paths))-1))]
              for i in range(min(24, len(paths)))]
    tw, th, cols = 240, 135, 4
    width, height = tw*cols, th*math.ceil(len(chosen)/cols)
    pixels = bytearray(width*height*3)
    for n, path in enumerate(chosen):
        w, h, src = read_ppm(path)
        for y in range(th):
            for x in range(tw):
                a = ((y*h//th)*w+x*w//tw)*3
                b = (((n//cols)*th+y)*width+(n%cols)*tw+x)*3
                pixels[b:b+3] = src[a:a+3]
    output = Path(output)
    output.write_bytes(f'P6\n{width} {height}\n255\n'.encode()+pixels)
    output.with_suffix('.json').write_text(json.dumps([str(p) for p in chosen], indent=2))
    return str(output)


def audio_info(path):
    if not path.exists():
        return None
    try:
        with wave.open(str(path)) as stream:
            info = dict(seconds=stream.getnframes()/stream.getframerate(),
                        channels=stream.getnchannels(), rate=stream.getframerate(),
                        sample_width=stream.getsampwidth(), bytes=path.stat().st_size)
            if stream.getsampwidth() != 2:
                info['signal_note'] = 'Signal metrics currently support 16-bit PCM only'
                return info
            stride = max(1, math.ceil(stream.getnframes()*stream.getnchannels()/250000))
            offset = count = zeros = near_clip = peak = squared = 0
            while True:
                raw = stream.readframes(32768)
                if not raw:
                    break
                values = array('h', raw)
                if sys.byteorder != 'little':
                    values.byteswap()
                sampled = values[(-offset) % stride::stride]
                offset += len(values)
                for value in sampled:
                    absolute = abs(value)
                    peak = max(peak, absolute)
                    squared += value*value
                    zeros += absolute <= 1
                    near_clip += absolute >= 32760
                count += len(sampled)
            if count:
                info.update(sampled_values=count, sample_stride=stride, peak=peak/32768,
                            rms=math.sqrt(squared/count)/32768,
                            near_zero_fraction=zeros/count, near_clip_fraction=near_clip/count,
                            flags=(['silent_mix_candidate'] if zeros/count > .999 and info['seconds'] >= 5 else [])+
                                  (['clipping_mix_candidate'] if near_clip/count > .01 else []),
                            signal_note='Uniformly sampled mix; candidates need listening/context; no device-timing proof')
            return info
    except (OSError, wave.Error, EOFError) as error:
        return dict(error=str(error))


def analyze_record(record, output, index):
    root = Path(record['run']).resolve()
    receipt_path = root/'receipt.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    timeline_path = root/'frames.jsonl'
    timeline = {}
    if timeline_path.exists():
        for line in timeline_path.read_text().splitlines():
            event = json.loads(line)
            timeline[event['name']] = event
    hits = {key: [] for key in PATTERNS}
    for log in sorted(root.glob('*.log')):
        for n, line in enumerate(log.read_text(errors='replace').splitlines(), 1):
            for key, pattern in PATTERNS.items():
                if line.startswith('astral strict boot:'):
                    continue  # Policy banner says instructions remain fatal; no fault occurred.
                if re.search(pattern, line, re.I):
                    hits[key].append(dict(path=str(log), line=n, text=line[:400]))
    frames = sorted((root/'data/frames').glob('*.ppm'))
    metrics, invalid = [], []
    for frame in frames:
        try:
            metric = inspect_frame(frame)
            metric['capture'] = timeline.get(frame.name, {})
            metrics.append(metric)
        except ValueError as e:
            invalid.append(dict(path=str(frame), error=str(e)))
    valid = [Path(m['path']) for m in metrics]
    reached = record.get('reached') is True and bool(str(record.get('reach_evidence') or '').strip())
    termination = receipt.get('termination', 'unknown')
    resource_limit = bool(hits['resource_limit'])
    gpu_hang = bool(hits['gpu_hang'])
    crashed = bool(hits['fatal']) or (not resource_limit and not gpu_hang and termination == 'exited' and receipt.get('returncode', 0) != 0)
    # Time-limit termination is NOT hang evidence; a static menu is valid behavior.
    hang = gpu_hang or bool(str(record.get('hang_evidence') or '').strip())
    status = 'launch_failed' if record.get('launch_returncode') and not receipt else (
              'crashed' if crashed else ('resource_limit' if resource_limit else (
              'hang' if hang else ('reached' if reached else 'not_verified'))))
    reviewed_issues = []
    for issue in record.get('visual_issues', []):
        frame = (root/issue['frame']).resolve()
        if not frame.is_relative_to(root) or not frame.is_file() or not issue['description'].strip():
            raise ValueError('reviewed visual issues need a local frame and nonempty description')
        reviewed_issues.append(dict(issue, frame=str(frame)))
    return dict(file=record['file'], platform=record.get('platform', 'unknown'), status=status,
                phase=record.get('phase', 'unspecified'),
                reached=reached, reach_evidence=record.get('reach_evidence'),
                segment=json.loads((root/'segment.json').read_text()) if (root/'segment.json').exists() else None,
                hang_evidence=record.get('hang_evidence'), receipt=receipt,
                hits=hits, hit_counts={k: len(v) for k, v in hits.items()},
                frames=len(frames), invalid_frames=invalid, frame_metrics=metrics,
                contact_sheet=contact_sheet(valid, output/f'contact-{index:02d}.ppm'),
                visual_issues=reviewed_issues,
                audio=audio_info(root/'audio.wav'), visual_review=record.get('visual_review', 'pending'),
                timestamp_note='Frame names are present indices, not elapsed seconds. Use logs/manual observations.')


def analyze(manifest, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records = json.loads(Path(manifest).read_text())
    results = [analyze_record(r, output, i) for i, r in enumerate(records)]
    issues = []
    for result in results:
        if result['audio'] and result['audio'].get('flags'):
            issues.append(dict(rank=3, kind='audio_mix_candidate', file=result['file'],
                               platform=result['platform'], phase=result['phase'], repro=result['audio']))
        for issue in result['visual_issues']:
            issues.append(dict(rank=2, kind='reviewed_visual_issue', file=result['file'],
                               platform=result['platform'], phase=result['phase'], repro=issue))
        for severity, kind in [(1, 'fatal'), (1, 'gpu_hang'), (1, 'resource_limit'),
                               (2, 'render_error'), (2, 'missing_shader'), (3, 'audio'), (4, 'stub')]:
            # Group repeated identical messages; retain first repro and total counts.
            distinct = {}
            for hit in result['hits'][kind]:
                key = re.sub(r'0x[0-9a-f]+|\d+', '#', hit['text'], flags=re.I)
                distinct.setdefault(key, hit)
            for hit in distinct.values():
                issues.append(dict(rank=severity, kind=kind, file=result['file'],
                                   platform=result['platform'], phase=result['phase'], repro=hit))
        for frame in result['frame_metrics']:
            if frame['flags']:
                issues.append(dict(rank=5, kind='visual_candidate', file=result['file'],
                                   platform=result['platform'], phase=result['phase'], repro=frame))
    file_contacts = []
    for file, name in FILES:
        paths = [Path(frame['path']) for result in results if result['file'] == file
                 for frame in result['frame_metrics']]
        file_contacts.append(dict(file=file, name=name, frames=len(paths),
            contact_sheet=contact_sheet(paths, output/f'file-{file}-contact.ppm')))
    report = dict(schema=1, results=results, issues=sorted(issues, key=lambda i:i['rank']),
                  file_contacts=file_contacts,
                  coverage=[dict(file=f, name=n, runs=sum(r['file']==f for r in results),
                                 reached=any(r['file']==f and r['reached'] for r in results)) for f,n in FILES])
    (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    lines = ['# Private playthrough survey', '', '| File | Name | Runs | Reached |', '|---|---|---:|---|']
    lines += [f"| {r['file']} | {r['name']} | {r['runs']} | {r['reached']} |" for r in report['coverage']]
    lines += ['', '## Per-File contact sheets', '',
              'Sheets combine sampled run frames, including menus/loading; they do not prove scene entry.', '']
    lines += [f"- File {r['file']}: {r['frames']} valid frames; contact {r['contact_sheet']}"
              for r in file_contacts if r['contact_sheet']]
    lines += ['', '## Run evidence', '']
    for r in results:
        lines.append(f"- File {r['file']} / {r['platform']}: {r['status']}; phase {r['phase']}; {r['frames']} frames; "
                     f"hits {r['hit_counts']}; contact {r['contact_sheet']}; review: {r['visual_review']}")
    lines += ['', '## Ranked candidate issues', '']
    for issue in report['issues']:
        lines.append(f"- Rank {issue['rank']}: {issue['kind']}, File {issue['file']}, "
                     f"{issue['platform']}, phase {issue['phase']}: {json.dumps(issue['repro'])}")
    lines += ['', 'Candidate flags require human review; black fades and static menus are not failures.']
    (output/'summary.md').write_text('\n'.join(lines)+'\n')
    return report


def begin_segment(args):
    """Mark a chapter interval without copying writable saves or immutable assets."""
    root, output = Path(args.run).resolve(), Path(args.out).resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError('segment output must be fresh and outside its source run')
    if not (root/'process.json').is_file() or args.selection_frame < 0:
        raise ValueError('segment needs a supervised run and nonnegative selection frame')
    output.mkdir(parents=True)
    (output/'data/frames').mkdir(parents=True)
    offsets = {n:(root/n).stat().st_size for n in ['nx.log', 'console.log'] if (root/n).is_file()}
    audio_start = None
    if (root/'audio.wav').exists():
        with wave.open(str(root/'audio.wav')) as audio:
            audio_start = audio.getnframes()
    marker = dict(source_run=str(root), file=args.file, chapter=args.chapter,
                  selection_frame=args.selection_frame, start_unix=time.time(),
                  log_offsets=offsets, audio_start_frame=audio_start)
    (output/'segment.json').write_text(json.dumps(marker, indent=2)+'\n')
    return 0


def end_segment(args):
    output = Path(args.segment).resolve()
    path = output/'segment.json'
    marker = json.loads(path.read_text())
    if 'end_unix' in marker:
        raise ValueError('segment already ended')
    root = Path(marker['source_run']).resolve()
    if output.is_relative_to(root) or args.end_frame < marker['selection_frame']:
        raise ValueError('invalid segment source or frame range')
    marker.update(end_unix=time.time(), end_frame=args.end_frame,
                  reached=bool(args.reach_evidence.strip()), reach_evidence=args.reach_evidence.strip() or None,
                  frames_filter='selection frame plus frames modified since segment start')
    for name, offset in marker['log_offsets'].items():
        with (root/name).open('rb') as stream:
            stream.seek(offset)
            (output/name).write_bytes(stream.read())
            marker.setdefault('log_end_offsets', {})[name] = stream.tell()
    chosen = set()
    for frame in sorted((root/'data/frames').glob('*.ppm')):
        if frame.is_symlink() or not frame.resolve().is_relative_to(root):
            raise ValueError('segment frames must be local to source run')
        index = int(frame.stem)
        if index == marker['selection_frame'] or (index <= args.end_frame and
                marker['start_unix'] <= frame.stat().st_mtime <= marker['end_unix']):
            shutil.copy2(frame, output/'data/frames'/frame.name)
            chosen.add(frame.name)
    events = []
    for line in (root/'frames.jsonl').read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue  # Live timeline can end in a partially written line.
        if event['name'] in chosen:
            events.append(event)
    (output/'frames.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    marker['frames'] = len(chosen)
    if marker['audio_start_frame'] is not None:
        try:
            with wave.open(str(root/'audio.wav')) as audio:
                marker['audio_end_frame'] = audio.getnframes()
                start = min(audio.getnframes(), marker['audio_start_frame'])
                audio.setpos(start)
                pcm = audio.readframes(audio.getnframes()-start)
                params = audio.getparams()
            with wave.open(str(output/'audio.wav'), 'wb') as audio:
                audio.setparams(params)
                audio.writeframes(pcm)
        except (OSError, wave.Error, EOFError) as error:
            marker['audio_note'] = str(error)
    path.write_text(json.dumps(marker, indent=2)+'\n')
    return 0


def request_stop(args):
    """Ask only this run's supervisor to end its own child and preserve a receipt."""
    root = Path(args.run).resolve()
    if (root/'receipt.json').exists():
        return 0  # Already achieved: preserve the original end and reason.
    process = json.loads((root/'process.json').read_text())
    if not str(args.reason).strip():
        raise ValueError('stop reason must be nonempty')
    request = root/'stop-request.json'
    if request.exists():
        if json.loads(request.read_text()).get('pid') != process['pid']:
            raise ValueError('stop request belongs to a different process')
        return 0
    with request.open('x') as stream:
        json.dump(dict(pid=process['pid'], reason=args.reason,
                       requested_utc=datetime.now(timezone.utc).isoformat()), stream)
    return 0


def run(args):
    if args.seconds <= 0 or args.every <= 0:
        raise ValueError('duration and frame interval must be positive')
    memory_gb = getattr(args, 'memory_gb', 8)
    if not 1 <= memory_gb <= 16:
        raise ValueError('memory guard must be 1..16 GiB; budget parallel jobs separately')
    root = Path(args.run).resolve()
    data = root/'data'
    if not data.is_dir() or data.is_symlink():
        raise ValueError('prepare a private local run/data directory first')
    for p in [data/'user', data/'frames']:
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            raise ValueError('writable save/frame directories must stay inside run')
    if (data/'user').exists():
        for p in (data/'user').rglob('*'):
            if p.is_symlink() or not p.resolve().is_relative_to(root):
                raise ValueError('nested writable save links are not allowed')
    if (root/'receipt.json').exists() or (data/'frames').exists():
        raise ValueError('refusing to mix evidence with an earlier run')
    if sys.platform == 'darwin' and not args.locked:
        lock = str(Path(__file__).resolve().parents[1]/'.local/bin/mac-game-lock')
        return subprocess.call([lock, '--wait', str(getattr(args, 'lock_wait', 20)), '--', 'nice', '-n', '10', sys.executable,
                                str(Path(__file__).resolve()), *sys.argv[1:], '--locked'])
    env = {k:v for k,v in os.environ.items() if not k.startswith('NX_')}
    env.update(NX_DATA_ROOT=str(data), NX_NVN_REAL='1', NX_HEADLESS='1', NX_SKIP_LAUNCHER='1',
               NX_LOG=str(root/'nx.log'), NX_DUMP_FRAMES=str(args.every),
               NX_NVN_FORMAT_PROFILE=str(data/'astral.profile'),
               NX_SHARED_FONT_DIR=str(data/'shared-fonts'), NX_SAVE_PROFILE=args.profile,
               NX_AUDIO_DUMP=str(root/'audio.wav'), NX_AUDIO_DUMP_SECONDS='0',
               NX_MEM_LIMIT_GB=str(memory_gb),
               NX_INPUT_SCRIPT=args.input)
    if sys.platform == 'darwin':
        env['NX_MUTE'] = '1'
    if getattr(args, 'trace_fs', False):
        env['NX_TRACE_FS'] = '1'
    if getattr(args, 'record_input', False):
        env['NX_INPUT_RECORD'] = str(root/'physical-input.txt')
    controlled_pad = getattr(args, 'controlled_pad', False)
    if controlled_pad:
        write_pad(root/'controller.bin', pad_report([], 0, 0))
        env['NX_SURVEY_PAD_FILE'] = str(root/'controller.bin')
    start = time.monotonic()
    started_utc = datetime.now(timezone.utc).isoformat()
    seen = set()
    def record_frames(timeline):
        for frame in sorted((data/'frames').glob('*.ppm')):
            if frame.name in seen:
                continue
            # First observation is an approximate wall-clock anchor, not a guest
            # presentation timestamp. Raster validity is checked by analyze.
            stat = frame.stat()
            timeline.write(json.dumps(dict(name=frame.name, observed_seconds=round(time.monotonic()-start, 3),
                modified_unix=stat.st_mtime, bytes=stat.st_size))+'\n')
            timeline.flush()
            seen.add(frame.name)
    with (root/'console.log').open('w') as log, (root/'frames.jsonl').open('w') as timeline:
        process = subprocess.Popen([str(Path(args.binary).resolve())], cwd=root, env=env,
                                   stdout=log, stderr=subprocess.STDOUT)
        (root/'process.json').write_text(json.dumps(dict(pid=process.pid,
            binary=str(Path(args.binary).resolve()), controlled_pad=controlled_pad), indent=2))
        stop_requested = False
        try:
            while process.poll() is None:
                stop_path = root/'stop-request.json'
                if stop_path.exists():
                    try:
                        stop_requested = json.loads(stop_path.read_text()).get('pid') == process.pid
                    except (OSError, ValueError):
                        pass  # A writer may still be completing its request.
                    if stop_requested:
                        raise subprocess.TimeoutExpired(process.args, args.seconds)
                remaining = args.seconds-(time.monotonic()-start)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, args.seconds)
                try:
                    process.wait(timeout=min(.5, remaining))
                except subprocess.TimeoutExpired:
                    pass
                record_frames(timeline)
            rc = process.returncode
            termination = 'exited'
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                rc = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                rc = process.wait()
            termination = 'requested_stop' if stop_requested else 'time_limit'
        record_frames(timeline)
    (root/'receipt.json').write_text(json.dumps(dict(returncode=rc, termination=termination,
        elapsed=time.monotonic()-start, started_utc=started_utc,
        input_script=args.input, save_profile=args.profile, frame_interval=args.every,
        memory_limit_gb=memory_gb,
        physical_input_record_enabled=getattr(args, 'record_input', False),
        controlled_pad=controlled_pad,
        binary=str(Path(args.binary).resolve()),
        platform=sys.platform, device_timing_valid=False,
        audio_timing_note='Verify real device activation separately; headless alone is not device timing proof'), indent=2)+'\n')
    return 0


def prepare(args):
    """Create isolated writable state; link only the immutable input directories."""
    root, assets, save = Path(args.run).resolve(), Path(args.assets).resolve(), Path(args.save).resolve()
    if root.exists():
        raise ValueError('run directory already exists; choose a fresh evidence directory')
    names = ['analysis', 'exefs', 'extract', 'spirv', 'shared-fonts']
    if not all((assets/n).is_dir() for n in names) or not (assets/'astral.profile').is_file():
        raise ValueError('asset root is incomplete')
    if not save.is_dir() or any(p.is_symlink() or not p.resolve().is_relative_to(save)
                                for p in save.rglob('*')):
        raise ValueError('save source must be a directory without symlinks')
    data = root/'data'
    data.mkdir(parents=True)
    for name in names:
        target = (assets/name).resolve()
        if sys.platform == 'win32':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(data/name), str(target)], check=True)
        else:
            (data/name).symlink_to(target, target_is_directory=True)
    shutil.copy2(assets/'astral.profile', data/'astral.profile')
    shutil.copytree(save, data/'user/save')
    return 0


def batch(args):
    """Run prepared, independent plans. Labels express intent, never proof of reach."""
    plans = json.loads(Path(args.plan).read_text())
    if not isinstance(plans, list) or not plans or not 1 <= args.jobs <= 4:
        raise ValueError('provide a nonempty plan and 1..4 jobs')
    roots = [str(Path(p['run']).resolve()) for p in plans]
    if len(set(roots)) != len(roots):
        raise ValueError('each plan must use a separate run directory')
    if any(not Path(p).is_dir() for p in roots):
        raise ValueError('prepare all run directories before batching')
    if any(Path(a).is_relative_to(Path(b)) for a in roots for b in roots if a != b):
        raise ValueError('batch run directories must not overlap')
    if sys.platform == 'darwin' and args.jobs != 1:
        raise ValueError('Mac batches must be serial; each launch still uses mac-game-lock')
    def launch(plan):
        command = [sys.executable, str(Path(__file__).resolve()), 'run', '--run', plan['run'],
                   '--binary', plan['binary'], '--seconds', str(plan.get('seconds', 90)),
                   '--every', str(plan.get('every', 150)), '--profile', plan.get('profile', 'Default'),
                   '--input', plan.get('input', ''), '--lock-wait', str(plan.get('lock_wait', 20))]
        command.extend(['--memory-gb', str(plan.get('memory_gb', 8))])
        if plan.get('trace_fs'):
            command.append('--trace-fs')
        if plan.get('record_input'):
            command.append('--record-input')
        if plan.get('controlled_pad'):
            command.append('--controlled-pad')
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (Path(plan['run'])/'launch.log').write_text(result.stdout)
        return dict(file=plan['file'], platform=plan.get('platform', sys.platform), run=plan['run'],
                    reached=False, reach_evidence='Not reviewed; plan label is intended destination only',
                    launch_returncode=result.returncode, visual_review='pending')
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(launch, plans))
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    manifest = output/'manifest.json'
    manifest.write_text(json.dumps(records, indent=2)+'\n')
    analyze(manifest, output)
    return int(any(r['launch_returncode'] for r in records))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('analyze'); a.add_argument('manifest'); a.add_argument('--out', required=True)
    b = sub.add_parser('batch'); b.add_argument('plan'); b.add_argument('--out', required=True)
    b.add_argument('--jobs', type=int, default=1)
    d = sub.add_parser('prepare'); d.add_argument('--run', required=True)
    d.add_argument('--assets', required=True); d.add_argument('--save', required=True)
    c = sub.add_parser('build-pad-proxy'); c.add_argument('--out', required=True)
    c.add_argument('--compiler', required=True); c.add_argument('--vsdevcmd', required=True)
    c = sub.add_parser('begin-segment'); c.add_argument('--run', required=True)
    c.add_argument('--out', required=True); c.add_argument('--file', required=True)
    c.add_argument('--chapter', type=int, required=True); c.add_argument('--selection-frame', type=int, required=True)
    c = sub.add_parser('end-segment'); c.add_argument('--segment', required=True)
    c.add_argument('--end-frame', type=int, required=True); c.add_argument('--reach-evidence', default='')
    c = sub.add_parser('stop'); c.add_argument('--run', required=True)
    c.add_argument('--reason', default='survey sample complete')
    c = sub.add_parser('pad'); c.add_argument('--run', required=True)
    c.add_argument('--buttons', nargs='*', default=[]); c.add_argument('--hold', type=float, default=.08)
    c.add_argument('--note', default='manual survey input')
    for axis in ['lx', 'ly', 'rx', 'ry']: c.add_argument('--'+axis, type=int, default=0)
    r = sub.add_parser('run'); r.add_argument('--run', required=True); r.add_argument('--binary', required=True)
    r.add_argument('--seconds', type=float, default=90); r.add_argument('--every', type=int, default=150)
    r.add_argument('--profile', default='Default'); r.add_argument('--input', default='')
    r.add_argument('--lock-wait', type=float, default=20, help='Mac lock wait, seconds; no game starts until acquired')
    r.add_argument('--trace-fs', action='store_true', help='log guest file opens to diagnose menu/save loading')
    r.add_argument('--memory-gb', type=int, default=8, help='per-game memory guard (1..16 GiB); default 8')
    r.add_argument('--record-input', action='store_true', help='record physical pad input before script contributions')
    r.add_argument('--controlled-pad', action='store_true', help='enable a private file-driven Windows input adapter')
    r.add_argument('--locked', action='store_true', help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.command == 'run':
        return run(args)
    if args.command == 'prepare':
        return prepare(args)
    if args.command == 'batch':
        return batch(args)
    if args.command == 'build-pad-proxy':
        return build_pad_proxy(args)
    if args.command == 'begin-segment':
        return begin_segment(args)
    if args.command == 'end-segment':
        return end_segment(args)
    if args.command == 'stop':
        return request_stop(args)
    if args.command == 'pad':
        result = pad(args)
        print((Path(args.run)/'controls.jsonl').read_text().splitlines()[-1])
        return result
    report = analyze(args.manifest, args.out)
    print(json.dumps(dict(runs=len(report['results']), issues=len(report['issues']))))
    return 0

if __name__ == '__main__':
    sys.exit(main())
