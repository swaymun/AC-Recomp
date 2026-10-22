#!/usr/bin/env python3
"""Drive an owned Windows desktop validation session over SSH; stdlib only.

No credentials, provisioning, game assets or guest input hooks. Output is private.
Commands return receipts, never inferred gameplay acceptance. Inspect the captures.
"""
import argparse
import array
import base64
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import struct
import subprocess
import sys
import time

UNIT = 'WIN-VALIDATE-003'
REMOTE = rf'C:\acr\units\{UNIT}'
HELPERS = r'C:\acr\units\WIN-SETUP-001\src\tools\win'
PAD_PYTHON = r'C:\acr\units\WIN-SETUP-001\pad-venv\Scripts\python.exe'
BUTTONS = set('A B X Y START BACK DPAD_UP DPAD_DOWN DPAD_LEFT DPAD_RIGHT LEFT_SHOULDER RIGHT_SHOULDER LEFT_THUMB RIGHT_THUMB GUIDE'.split())


def ps(value):
    """PowerShell single-quoted literal, including apostrophes and Unicode."""
    return "'" + str(value).replace("'", "''") + "'"


def owned_remote(path):
    p, root = PureWindowsPath(path), PureWindowsPath(REMOTE)
    if '..' in p.parts or not p.is_relative_to(root):
        raise ValueError(f'remote output/executable must be under {REMOTE}')
    return str(p)


def default_private(root):
    """Keep linked worktrees' evidence in the common checkout's ignored unit store."""
    root = Path(root).resolve()
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--git-common-dir'],
                            capture_output=True, text=True, check=True)
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = root / common
    return common.resolve().parent / '.local' / 'units' / UNIT


def game_children(parent, processes):
    """Only this launcher's direct FPS children, never a process-name sweep."""
    exe = PureWindowsPath(owned_remote(parent['Executable']))
    siblings = {exe}
    if exe.name.lower() in ('astral.exe', 'astral-60fps.exe'):
        siblings.update(exe.with_name(name) for name in ('astral.exe', 'astral-60fps.exe'))
    return [p for p in processes
            if p['ParentPID'] == parent['PID'] and p['PID'] != parent['PID']
            and p['SessionId'] == parent['SessionId']
            and p['Executable'] and PureWindowsPath(p['Executable']) in siblings
            and int(p['Created']) >= int(parent['Created'])]


class VM:
    def __init__(self, host='acr-win', ssh='ssh'):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', host):
            raise ValueError('invalid SSH host alias')
        self.host, self.ssh = host, ssh

    def run(self, script, timeout=60):
        encoded = base64.b64encode(('$ErrorActionPreference="Stop"\n' + script).encode('utf-16le')).decode('ascii')
        result = subprocess.run([self.ssh, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', self.host,
                                 'powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(f'SSH/PowerShell exit {result.returncode}: {result.stderr.strip()}\n{result.stdout.strip()}')
        return result.stdout.strip()

    def write(self, path, text):
        path = owned_remote(path)
        payload = text.encode('utf-8')
        # Windows OpenSSH rejects oversized encoded command lines before PowerShell
        # starts. Keep each UTF-16/base64 command comfortably below its 32K limit.
        result = ''
        for offset in range(0, max(1, len(payload)), 4096):
            blob = base64.b64encode(payload[offset:offset+4096]).decode('ascii')
            if offset == 0:
                script = (f"New-Item -ItemType Directory -Force (Split-Path {ps(path)}) | Out-Null\n"
                          f"[IO.File]::WriteAllBytes({ps(path)}, [Convert]::FromBase64String('{blob}'))")
            else:
                script = (f"$b=[Convert]::FromBase64String('{blob}')\n"
                          f"$f=[IO.File]::Open({ps(path)},[IO.FileMode]::Append,[IO.FileAccess]::Write)\n"
                          'try{$f.Write($b,0,$b.Length)}finally{$f.Dispose()}')
            result = self.run(script)
        return result

    def interactive(self, script, logs):
        try:
            return json.loads(self.run(script))
        except RuntimeError as error:
            # The setup helper can observe pid.txt while Set-Content still owns it.
            # Recover that exact task, never launch a second copy after an ambiguous start.
            match = re.search(re.escape(logs) + r'\\([a-f0-9]{32})\\(?:pid|session-id)\.txt', str(error))
            if not match:
                raise
            return self.recover(logs + '\\' + match[1])

    def recover(self, directory):
        directory = owned_remote(directory)
        ident = PureWindowsPath(directory).name
        if not re.fullmatch('[a-f0-9]{32}', ident):
            raise ValueError('invalid helper job directory')
        code = (f'$d={ps(directory)}\n'
                '$request=Get-Content "$d\\request.json" -Raw | ConvertFrom-Json\n'
                '$child=0; $session=0\n'
                'for($i=0;$i -lt 30;$i++){try{$child=[int](Get-Content "$d\\pid.txt" -ErrorAction Stop); '
                '$session=[int](Get-Content "$d\\session-id.txt" -ErrorAction Stop); '
                'if($child -gt 0 -and $session -gt 0){break}}catch{}; Start-Sleep -Milliseconds 100}\n'
                'if(!$child -or !$session){throw "Incomplete interactive receipt"}\n'
                '[pscustomobject]@{PID=$child;SessionId=$session;TaskName="ACR-interactive-'
                + ident + '";JobDirectory=$d;Stdout="$d\\stdout.log";Stderr="$d\\stderr.log";'
                'ExitCodeFile="$d\\exit-code.txt";Executable=$request.FilePath} | ConvertTo-Json -Compress')
        return json.loads(self.run(code))

    def launch(self, exe, cwd, logs, environment=None, arguments=''):
        for path in (exe, cwd, logs):
            owned_remote(path)
        env = environment or {}
        if any((not k.startswith('NX_') and k != 'SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS') or any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD')) for k in env):
            raise ValueError('only non-secret NX_ and the SDL background-pad hint supported')
        table = '@{' + ';'.join(f'{ps(k)}={ps(v)}' for k, v in env.items()) + '}'
        job = self.interactive("if(Get-Process astral,astral-60fps -ErrorAction SilentlyContinue | Where-Object SessionId -gt 0){throw 'A desktop game is already running; preserve the other session'}\n"
                          f"$j=& {ps(HELPERS + chr(92) + 'run_interactive.ps1')} -FilePath {ps(exe)} "
                          f"-WorkingDirectory {ps(cwd)} -LogDirectory {ps(logs)} -Environment {table} "
                          f"-Arguments {ps(arguments)}\n$j | ConvertTo-Json -Compress", logs)
        if job['SessionId'] <= 0 or job['PID'] <= 0:
            raise RuntimeError('not an interactive child')
        job['Executable'] = exe
        # Bind the saved receipt now, including after interactive() recovers a
        # publication race. Never derive the original identity during stop().
        # The helper holds the launch handle through publishing exit-code.txt;
        # refuse an exited job rather than binding a subsequently recycled PID.
        job['Created'] = self.run(
            f"$p=Get-Process -Id {int(job['PID'])} -ErrorAction Stop\n"
            "try{\n$null=$p.Handle\n"
            f"$c=Get-CimInstance Win32_Process -Filter 'ProcessId={int(job['PID'])}'\n"
            f"if(!$c -or $p.HasExited -or (Test-Path {ps(owned_remote(job['ExitCodeFile']))}) "
            f"-or $p.Path -ne {ps(exe)} -or $p.SessionId -ne {int(job['SessionId'])} "
            f"-or $c.ExecutablePath -ne {ps(exe)} -or $c.SessionId -ne {int(job['SessionId'])})"
            "{throw 'Launch identity unavailable; retain helper job for inspection'}\n"
            "$c.CreationDate.ToUniversalTime().Ticks.ToString()\n"
            "}finally{$p.Dispose()}")
        if not job['Created'].isdigit() or int(job['Created']) <= 0:
            raise RuntimeError('invalid launch creation time')
        return job

    def task(self, script, name):
        """Write and launch an owned PowerShell job in the console."""
        path = owned_remote(REMOTE + '\\' + name + '.ps1')
        focus = ("$targets=@(Get-Process astral,astral-60fps -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "
                 + ps(REMOTE + '\\*') + " -and $_.MainWindowHandle -ne 0 })\n"
                 "if(!$targets.Count){throw 'No owned visible desktop game; refusing input/capture'}\n"
                 "Add-Type -TypeDefinition " + ps('using System; using System.Runtime.InteropServices; public class AcrValidationFocus { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y); }') + "\n"
                 "[AcrValidationFocus]::SetCursorPos(0,0) | Out-Null\n"
                 "$targets | ForEach-Object { [AcrValidationFocus]::SetForegroundWindow($_.MainWindowHandle) | Out-Null; "
                 "Write-Output (\"ACR game target PID=\"+$_.Id+\" path=\"+$_.Path) }\n")
        self.write(path, '$ErrorActionPreference="Stop"\n' + focus + script)
        # The executable is a system program, but the script and all outputs belong to this unit.
        job = self.interactive(f"$j=& {ps(HELPERS + chr(92) + 'run_interactive.ps1')} -FilePath powershell.exe "
                          f"-WorkingDirectory {ps(REMOTE)} -LogDirectory {ps(REMOTE + chr(92) + 'jobs')} "
                          f"-Arguments {ps('-NoProfile -ExecutionPolicy Bypass -File ' + chr(34) + path + chr(34))}\n"
                          '$j | ConvertTo-Json -Compress', REMOTE + '\\jobs')
        if job['SessionId'] <= 0:
            raise RuntimeError('not a console task')
        return job

    def status(self, job):
        for k in ('Stdout', 'Stderr', 'ExitCodeFile'):
            owned_remote(job[k])
        return json.loads(self.run(f"$p=Get-Process -Id {int(job['PID'])} -ErrorAction SilentlyContinue\n"
            f"[pscustomobject]@{{Running=[bool]$p; ExitCode=$(if(Test-Path {ps(job['ExitCodeFile'])})"
            f"{{[IO.File]::ReadAllText({ps(job['ExitCodeFile'])}).Trim()}}else{{$null}}); "
            f"WorkingSet=$(if($p){{$p.WorkingSet64}}else{{$null}}); "
            f"Stdout=$(if(Test-Path {ps(job['Stdout'])}){{Get-Content {ps(job['Stdout'])} -Tail 12 | Out-String}}); "
            f"Stderr=$(if(Test-Path {ps(job['Stderr'])}){{Get-Content {ps(job['Stderr'])} -Tail 12 | Out-String}})"
            '} | ConvertTo-Json -Compress'))

    def wait(self, job, timeout=60):
        deadline = time.monotonic() + timeout
        while True:
            result = self.status(job)
            if not result['Running'] and result['ExitCode'] is not None:
                if result['ExitCode'] != '0':
                    raise RuntimeError('Interactive job failed: ' + json.dumps(result))
                return result
            if time.monotonic() >= deadline:
                raise TimeoutError('Interactive job still running; preserve its receipt')
            time.sleep(.2)

    def stop(self, job):
        exe = owned_remote(job['Executable'])  # helper processes are not stopped by this command
        task = job['TaskName']
        if not re.fullmatch(r'ACR-interactive-[a-f0-9]{32}', task):
            raise ValueError('invalid task receipt')
        pid, session = int(job['PID']), int(job['SessionId'])
        if pid <= 0 or session <= 0:
            raise ValueError('invalid desktop process receipt')
        created = str(job.get('Created', ''))
        if not created.isdigit() or int(created) <= 0:
            raise ValueError('receipt lacks original creation time; refusing stop')
        before = self.game_processes(pid)
        parent = next((p for p in before if p['PID'] == pid), None)
        if parent is None:
            # An old receipt cannot prove the ancestry of an orphan after PID reuse.
            # Fail closed rather than reporting success with possible gameplay alive.
            if game_children(job, before):
                raise RuntimeError('Launcher absent with possible owned child; cannot verify ancestry')
        else:
            if (PureWindowsPath(parent['Executable'] or '') != PureWindowsPath(exe)
                    or parent['SessionId'] != session
                    or str(parent['Created']) != created):
                raise RuntimeError('PID identity changed; refusing stop')
            tracked = {p['PID']: p for p in game_children(parent, before)}
            # End the launcher first so it cannot spawn after our last inventory.
            # It waits for the variant; stopping it does not terminate the variant.
            self.stop_process(parent)
            after = self.game_processes(pid)
            if any(p['PID'] == pid for p in after):
                raise RuntimeError('Launcher PID still present or reused; refusing child stop')
            for child in game_children(parent, after):
                old = tracked.get(child['PID'])
                if old is not None and old != child:
                    raise RuntimeError('Child PID identity changed; refusing stop')
                tracked[child['PID']] = child
            for child in tracked.values():
                self.stop_process(child)
            remaining = self.game_processes(pid)
            if any(p['PID'] == pid for p in remaining) or game_children(parent, remaining):
                raise RuntimeError('Owned game remains; retaining task receipt')
        return self.run(
            f"if(Get-ScheduledTask -TaskName {ps(task)} -ErrorAction SilentlyContinue){{"
            f"Unregister-ScheduledTask -TaskName {ps(task)} -Confirm:$false}}\nWrite-Output 'Stopped owned game task'")

    def game_processes(self, pid):
        """Snapshot the receipt PID and direct children, including stable identities."""
        code = (f"$rows=@(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)} OR ParentProcessId={int(pid)}' | "
                "ForEach-Object { [pscustomobject]@{PID=[int]$_.ProcessId;ParentPID=[int]$_.ParentProcessId;"
                "SessionId=[int]$_.SessionId;Executable=$_.ExecutablePath;"
                "Created=$_.CreationDate.ToUniversalTime().Ticks.ToString()} })\n"
                "ConvertTo-Json -InputObject $rows -Compress")
        return json.loads(self.run(code))

    def stop_process(self, process):
        """Revalidate against the snapshot and kill through a pinned process handle."""
        exe = owned_remote(process['Executable'])
        pid, session = int(process['PID']), int(process['SessionId'])
        created, parent = int(process['Created']), int(process['ParentPID'])
        return self.run(
            f"$p=Get-Process -Id {pid} -ErrorAction SilentlyContinue\n"
            "if($p){try{\n"
            # Opening the handle before the CIM query keeps this process identity
            # pinned even if it exits and Windows later reuses its numeric PID.
            "$null=$p.Handle\n"
            f"$c=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'\n"
            "if(!$p.HasExited){\n"
            f"if(!$c -or $p.Path -ne {ps(exe)} -or $p.SessionId -ne {session} "
            f"-or $c.ExecutablePath -ne {ps(exe)} -or $c.SessionId -ne {session} "
            f"-or $c.ParentProcessId -ne {parent} "
            f"-or $c.CreationDate.ToUniversalTime().Ticks -ne {created})"
            "{throw 'PID identity changed; refusing stop'}\n"
            "$p.Kill(); if(!$p.WaitForExit(15000)){throw 'Game termination timed out'}\n"
            "}\n}finally{$p.Dispose()}}")


def pad_script(states, normalise=False, settle_ms=0):
    """Complete states; releases between B presses back out of nested menus.

    Xbox B is Switch A with the default Nintendo layout. Xbox A is Switch B/back.
    Normalisation is only for a visually identified menu, never a scene detector.
    """
    if type(settle_ms) is not int or not 0 <= settle_ms <= 60000:
        raise ValueError('invalid settle interval')
    out = [{'ms': settle_ms}] if settle_ms else []
    if normalise:
        for _ in range(3):
            out.extend([{'buttons': ['A'], 'ms': 140}, {'ms': 300}])
    for state in states:
        if not isinstance(state, dict) or set(state) - {'buttons', 'ms', 'left_trigger', 'right_trigger', 'lx', 'ly', 'rx', 'ry'}:
            raise ValueError('unknown pad fields')
        if set(state.get('buttons', [])) - BUTTONS:
            raise ValueError('unknown Xbox button')
        for k, lo, hi in [('ms', 1, 60000), ('left_trigger', 0, 255), ('right_trigger', 0, 255),
                          ('lx', -32768, 32767), ('ly', -32768, 32767), ('rx', -32768, 32767), ('ry', -32768, 32767)]:
            value = state.get(k, 100 if k == 'ms' else 0)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f'invalid {k}')
        out.append(dict(state, ms=state.get('ms', 100)))
    out.append({'ms': 250})  # release before EOF/disconnect
    return ''.join(json.dumps(s, separators=(',', ':')) + '\n' for s in out)


def wav_metrics(path, silence_db=-60):
    """PCM16 or float32 (including WASAPI extensible) WAV, streaming bounded memory.

    Silence is an all-channel frame below the threshold; clipping counts individual
    samples at either full-scale limit. Music/SFX identity needs listening.
    """
    threshold = 10 ** (silence_db / 20)
    with Path(path).open('rb') as f:
        if f.read(4) != b'RIFF':
            raise ValueError('requires RIFF WAV')
        f.read(4)
        if f.read(4) != b'WAVE':
            raise ValueError('requires WAVE')
        fmt = None
        while header := f.read(8):
            if len(header) != 8:
                raise ValueError('truncated chunk')
            kind, size = struct.unpack('<4sI', header)
            if kind == b'fmt ':
                raw = f.read(size)
                if len(raw) < 16:
                    raise ValueError('short format')
                tag, channels, rate, _, align, bits = struct.unpack_from('<HHIIHH', raw)
                if tag == 0xfffe:
                    if len(raw) < 40:
                        raise ValueError('short extensible format')
                    tag = struct.unpack_from('<H', raw, 24)[0]
                if (tag, bits) not in ((1, 16), (3, 32)) or channels < 1 or rate < 1 or align != channels * bits // 8:
                    raise ValueError('requires PCM16 or float32')
                fmt = tag, channels, rate, align
            elif kind == b'data':
                if not fmt:
                    raise ValueError('data before format')
                tag, channels, rate, align = fmt
                if size % align:
                    raise ValueError('partial PCM frame')
                remaining, total, square, peak, clipped, longest, silence = size, 0, 0.0, 0.0, 0, 0, 0
                while remaining:
                    raw = f.read(min(remaining, align * 16384))
                    if not raw or len(raw) % align:
                        raise ValueError('truncated audio')
                    remaining -= len(raw)
                    values = array.array('h' if tag == 1 else 'f')
                    values.frombytes(raw)
                    if sys.byteorder != 'little':
                        values.byteswap()
                    scale = 32768 if tag == 1 else 1
                    for i in range(0, len(values), channels):
                        frame_peak = 0.0
                        for sample in values[i:i+channels]:
                            v = sample / scale
                            if not math.isfinite(v):
                                raise ValueError('nonfinite audio sample')
                            square += v*v
                            frame_peak = max(frame_peak, abs(v))
                            clipped += (sample <= -32768 or sample >= 32767) if tag == 1 else abs(v) >= 1.0
                            total += 1
                        peak = max(peak, frame_peak)
                        silence = silence + 1 if frame_peak <= threshold else 0
                        longest = max(longest, silence)
                rms = math.sqrt(square / total) if total else 0
                return {'frames': total // channels, 'duration_s': total / channels / rate,
                        'channels': channels, 'sample_rate': rate, 'rms': rms,
                        'rms_dbfs': 20*math.log10(rms) if rms else None, 'peak': peak,
                        'clipped_samples': clipped, 'longest_silence_s': longest / rate,
                        'silence_threshold_dbfs': silence_db}
            else:
                f.seek(size, 1)
            if size & 1:
                f.seek(1, 1)
    raise ValueError('no audio data')


def memory_metrics(samples):
    rows = [(float(s['elapsed_s']), int(s['working_set'])) for s in samples]
    if len(rows) < 2 or any(t < 0 or v < 0 for t, v in rows) or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError('need increasing, nonnegative memory samples')
    ts, vs = zip(*rows)
    mt, mv = sum(ts)/len(ts), sum(vs)/len(vs)
    slope = sum((t-mt)*(v-mv) for t, v in rows) / sum((t-mt)**2 for t in ts)
    return {'samples': len(rows), 'duration_s': ts[-1]-ts[0], 'first_bytes': vs[0], 'last_bytes': vs[-1],
            'min_bytes': min(vs), 'max_bytes': max(vs), 'slope_mib_per_min': slope*60/(1 << 20),
            'interpretation': 'working-set trend only; does not establish absence of a leak'}


def sample_memory(vm, job, seconds, interval, private):
    samples, start = [], None
    # A failed/restarted soak must not inherit a successful predecessor's summary.
    (private/'memory-summary.json').unlink(missing_ok=True)
    try:
        while True:
            status = vm.status(job)
            if not status['Running']:
                raise RuntimeError('game exited during memory measurement')
            now = time.monotonic()
            if start is None:
                start = now  # the observed first sample, after the initial SSH request
            samples.append({'elapsed_s':now-start, 'working_set':status['WorkingSet']})
            (private/'memory-samples.json').write_text(json.dumps(samples, indent=2))
            if now-start >= seconds:
                break
            time.sleep(min(interval, seconds-(now-start)))
        result = memory_metrics(samples)
        (private/'memory-summary.json').write_text(json.dumps(result, indent=2))
        return result
    finally:
        (private/'memory-samples.json').write_text(json.dumps(samples, indent=2))


def log_metrics(text):
    pattern = re.compile(r'vk: frame (\d+) presented \((-?\d+)\), ([\d.]+) fps \(last ([\d.]+) s\), ([\d.]+) average; worst ([\d.]+) ms')
    rows = [{'frame': int(m[1]), 'result': int(m[2]), 'fps': float(m[3]), 'window_s': float(m[4]),
             'average_fps': float(m[5]), 'worst_ms': float(m[6])} for m in pattern.finditer(text)]
    swaps = re.findall(r'(?:vkCreateSwapchainKHR|nvn/vk: swapchain) [^\r\n]+', text)
    replay = []
    for match in re.finditer(r'nvn/vk: per frame over (\d+): ([\d.]+) fps, ([^\r\n]+)', text):
        replay.append({'frames':int(match[1]), 'fps':float(match[2]), 'details':match[3]})
    return {'swapchains': swaps, 'frame_windows': rows, 'nvn_replay_windows': replay,
            'fatal_or_crash_lines': [l for l in text.splitlines() if re.search(r'\b(?:FATAL|CRASH):', l)],
            'memory_guard_lines': [l for l in text.splitlines() if re.search(r'^memory: .*over.*limit.*stopping', l)],
            'audio_device_lines': [l for l in text.splitlines() if 'device output' in l or 'no audio device' in l],
            'note': 'present counters require a successful swapchain and visual scene confirmation; no inferred route acceptance'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', default='acr-win')
    p.add_argument('--ssh', default='ssh')
    p.add_argument('--private', type=Path, help='ignored unit output directory (default: common Git checkout)')
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('preflight')
    prepare = sub.add_parser('prepare')
    prepare.add_argument('--source', default=r'C:\acr\data')
    prepare.add_argument('--extract', help='alternate completed private extract directory')
    logs = sub.add_parser('logs')
    logs.add_argument('path', type=Path)
    launch = sub.add_parser('launch')
    launch.add_argument('--exe', required=True)
    launch.add_argument('--profile', default='WindowsValidation')
    launch.add_argument('--launcher', action='store_true')
    launch.add_argument('--name', default='game')
    pad = sub.add_parser('pad')
    pad.add_argument('script', type=Path)
    pad.add_argument('--normalise', action='store_true')
    pad.add_argument('--settle-ms', type=int, default=15000, help='new-pad enumeration wait; 1000 suffices for native game XInput')
    pad.add_argument('--name', default='pad')
    capture = sub.add_parser('capture')
    capture.add_argument('--seconds', type=int, default=45)
    capture.add_argument('--name', default='capture')
    still = sub.add_parser('still')
    still.add_argument('--name', default='still')
    status = sub.add_parser('status')
    status.add_argument('name')
    wait = sub.add_parser('wait')
    wait.add_argument('name')
    wait.add_argument('--timeout', type=int, default=60)
    stop = sub.add_parser('stop')
    stop.add_argument('name', default='game', nargs='?')
    collect = sub.add_parser('collect')
    collect.add_argument('remote')
    audio = sub.add_parser('audio')
    audio.add_argument('wav', type=Path)
    sample = sub.add_parser('sample')
    sample.add_argument('--seconds', type=int, default=600)
    sample.add_argument('--interval', type=int, default=10)
    sample.add_argument('--name', default='game')
    args = p.parse_args()
    if args.command == 'logs':
        print(json.dumps(log_metrics(args.path.read_text(errors='replace')), indent=2)); return
    if args.command == 'audio':
        print(json.dumps(wav_metrics(args.wav), indent=2)); return
    private = (args.private or default_private(Path(__file__).resolve().parents[1])).resolve()
    if '.local' not in private.parts or private.name != UNIT:
        p.error('private output must be an ignored .local unit directory')
    private.mkdir(parents=True, exist_ok=True)
    name = getattr(args, 'name', 'job')
    if not re.fullmatch('[A-Za-z0-9_-]+', name):
        p.error('invalid receipt name')
    receipt = private / (name + '.json')
    vm = VM(args.host, args.ssh)
    result = None
    if args.command == 'preflight':
        result = vm.run("Get-Content C:\\acr\\setup-status.txt\nTest-Path C:\\acr\\data\\UPLOAD_OK\nquery user\n"
                        "Get-Process astral* -ErrorAction SilentlyContinue | Select-Object Id,SessionId,Path | ConvertTo-Json")
    elif args.command == 'prepare':
        source = PureWindowsPath(args.source)
        extract = PureWindowsPath(args.extract) if args.extract else source / 'extract'
        for path in (source, extract):
            if '..' in path.parts or not path.is_relative_to(PureWindowsPath(r'C:\acr')):
                p.error('input paths must be private C:\\acr paths')
        data = REMOTE + '\\data'
        lines = [f'New-Item -ItemType Directory -Force {ps(data)} | Out-Null']
        for child in ('analysis', 'exefs', 'extract', 'spirv', 'shared-fonts'):
            target = str(extract if child == 'extract' else source / child)
            dest = data + '\\' + child
            lines += [f'if(!(Test-Path {ps(target)})){{throw "missing {child}"}}',
                      f'if(Test-Path {ps(dest)}){{if((Get-Item {ps(dest)}).Target -ne {ps(target)})'
                      '{throw "existing data member differs; refusing replacement"}}else{'
                      f'New-Item -ItemType Junction -Path {ps(dest)} -Target {ps(target)} | Out-Null}}']
        lines += [f'Copy-Item {ps(str(source / "astral.profile"))} {ps(data + chr(92) + "astral.profile")}',
                  f'Get-ChildItem {ps(data)} | Select-Object Name,Target | ConvertTo-Json']
        result = vm.run('\n'.join(lines))
    elif args.command == 'launch':
        if not re.fullmatch('[A-Za-z0-9 _-]{1,32}', args.profile) or args.profile == 'Default':
            p.error('use a named fresh save profile')
        data = REMOTE + '\\data'
        env = {'NX_DATA_ROOT': data, 'NX_NVN_REAL': '1', 'NX_NVN_FORMAT_PROFILE': data + '\\astral.profile',
               'NX_SHARED_FONT_DIR': data + '\\shared-fonts', 'NX_ASSET_DIR': REMOTE + '\\src\\assets\\launcher',
               'NX_SAVE_PROFILE': args.profile, 'NX_PLAYER_NAME': 'WindowsValidation'}
        if args.launcher:
            # Scheduled recorder/controller consoles can temporarily own foreground focus.
            env['SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS'] = '1'
        else:
            env['NX_SKIP_LAUNCHER'] = '1'
        result = vm.launch(args.exe, REMOTE, REMOTE + '\\jobs', env)
        receipt.write_text(json.dumps(result, indent=2))
    elif args.command == 'pad':
        path = REMOTE + '\\' + name + '.jsonl'
        vm.write(path, pad_script([json.loads(l) for l in args.script.read_text().splitlines() if l.strip()], args.normalise, args.settle_ms))
        result = vm.task(f'& {ps(PAD_PYTHON)} {ps(HELPERS + chr(92) + "gamepad.py")} {ps(path)}\nexit $LASTEXITCODE', name)
        receipt.write_text(json.dumps(result, indent=2))
    elif args.command == 'still':
        out = REMOTE + '\\' + name + '.png'
        result = vm.task('ffmpeg -hide_banner -loglevel error -f lavfi -i ddagrab=framerate=15 '
                        '-frames:v 1 -vf hwdownload,format=bgra -y ' + ps(out) + '\nexit $LASTEXITCODE', name)
        receipt.write_text(json.dumps(result, indent=2))
        vm.wait(result, 30)
        subprocess.run(['scp', '-q', args.host+':'+out.replace('\\', '/'), str(private)], check=True)
    elif args.command == 'capture':
        if not 1 <= args.seconds <= 3600:
            p.error('capture duration must be 1..3600')
        out = REMOTE + '\\' + name
        result = vm.task(f'& {ps(HELPERS + chr(92) + "capture.ps1")} -Seconds {args.seconds} -OutputDirectory {ps(out)}', name)
        receipt.write_text(json.dumps(result, indent=2))
    elif args.command == 'wait':
        if not 1 <= args.timeout <= 3600:
            p.error('wait timeout must be 1..3600')
        result = vm.wait(json.loads(receipt.read_text()), args.timeout)
    elif args.command in ('status', 'stop'):
        job = json.loads(receipt.read_text())
        result = vm.status(job) if args.command == 'status' else vm.stop(job)
    elif args.command == 'collect':
        remote = owned_remote(args.remote)
        result = subprocess.run(['scp', '-q', '-r', args.host + ':' + remote.replace('\\', '/'), str(private)], check=True).returncode
    elif args.command == 'sample':
        if not 1 <= args.interval <= 60 or not 1 <= args.seconds <= 3600:
            p.error('sample bounds: seconds 1..3600, interval 1..60')
        job = json.loads(receipt.read_text())
        result = sample_memory(vm, job, args.seconds, args.interval, private)
    print(result if isinstance(result, str) else json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
