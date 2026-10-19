#!/usr/bin/env python3
"""Bounded, owned-only UIKit trace prerequisite. No startup acceptance."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import selectors
import secrets
import math
import subprocess
import sys
import time
import threading
import uuid

BUNDLE = 'local.acs.ios-host-002'
OWNED = {
    'iPhone': ('883683CC-F98A-4B53-9FC8-F02E60A52F30', 'com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro'),
    'iPad': ('6D9DC697-AFFB-4C27-A8A7-44A83AA3B367', 'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-11-inch-M5-12GB'),
}
RUNTIME = 'com.apple.CoreSimulator.SimRuntime.iOS-26-5'


def main_checkout(start):
    """The primary checkout owning private .local evidence, also when run from a linked worktree."""
    marker = start / '.git'
    if marker.is_file():
        text = marker.read_text().strip()
        if text.startswith('gitdir:'):
            gitdir = Path(text[len('gitdir:'):].strip())
            if gitdir.parent.name == 'worktrees' and gitdir.parent.parent.name == '.git':
                return gitdir.parent.parent.parent
    return start


# Repository checkout holding the private .local evidence (ACS_ROOT, else the primary checkout).
ACS_ROOT = Path(os.environ.get('ACS_ROOT') or main_checkout(Path(__file__).resolve().parents[1]))
SIMULATOR_DEVICES = Path(os.environ.get('ACS_SIMULATOR_DEVICES') or
                         Path.home() / 'Library/Developer/CoreSimulator/Devices')
PREVIOUS = Path(ACS_ROOT / '.local/orchestrate/2026-10-18-recovery/worktrees/IOS-SCENE-003/.local/orchestrate/2026-10-18-recovery/ios-scene-003')
REFERENCE = 'run-20261018T100608Z-3688fd'
BUILD_SHA = '7800120551da9ec519e00aaa905b5f21a8399c034de3bf168eae75fae1b1d338'
APP_FILES = {'ACSHost': BUILD_SHA,
    'Info.plist': '4841a3805959c5d85f7a16843dd4c30e1aacdce634c25a9a6cd0571bf62bade0',
    '_CodeSignature/CodeResources': '44abb488c97513d2fe1d90a61ab16ddea720fd54fd26c0b7db9acbf78d312821'}
SOURCE_HEAD = 'f5a29c0af81b0f92b97fee8792c3abc52c1bf7d1'
# Pinned from the preserved experiment summary and independently hashed inputs.
SOURCE_SHA256 = {'ports/ios/App.mm': '0385abd01fb35044c008fedb77426c2dae87c648c888def882da4488a79f03cf',
 'ports/ios/InputBridge.h': 'a72c9d6e774b2fc12af38b076ff9bb9e9dc5c7f10b3c1bc1ce5160071ed5f7c6',
 'ports/ios/InputBridge.cpp': 'd645810eaa8f0802fd7af2d08f9c2aceff01a397adb1bdbe959b4dd47c91aa70',
 'ports/ios/Info.plist': '4841a3805959c5d85f7a16843dd4c30e1aacdce634c25a9a6cd0571bf62bade0',
 'scripts/check-ios-host': '6bad49e5075245b5fbff367e4c8bf5b565130a9235a84b978c5920b0a5c4f861',
 'tests/test_ios_input.cpp': 'f358329d33d736c2eaa122abb383179ee1630361fd9de4eaf7d3988f039feecf'}
INSPECTED_SHA256 = {'report.json': '301efbb1ec1efdc359bbd8d47e2998499bb1bcd3f42bc3c5cbf6f7618d873526',
 'carried.diff': '5d00f972d25f0c9f0996911c1b138f948a6ecd602f2604dab9df9e69fd4b9505',
 'successor.diff': '4daaa6e7b0bb6318b0b9ce14d546cdda6683d0a2361d1d19d2c601f21fccd925',
 'run-20261018T100608Z-3688fd/summary.json': '5fc264ec0eb29d8a4016303613c7b73ca8c6dcb34521e5a67ec30ac7b0ca796b',
 'run-20261018T100608Z-3688fd/commands.log': '065bb3fc9bbe160deaf4ab7ef886c05e25c4146dbba01aaf5a39d1cba7eeff95',
 'run-20261018T100139Z-674a95/summary.json': '1ba435c0daf72435a17bd5aa567a7cdff5f5d9f8c94ccc8ecc48c83246025a74'}
TRANSPORT = Path(ACS_ROOT / '.local/orchestrate/2026-10-18-recovery/worktrees/IOS-TRANSPORT-004/.local/ios-transport')
TRANSPORT_SHA = 'ae2662a4bf82682b604858ea60e931600356dc0ef854720d435f992031ae8943'
MAX_TIMEOUT = 30
FILTERED_UNIT = 'IOS-COLLECTOR-FILTERED-007'
COLLECTOR_PREDECESSOR = TRANSPORT.parent.parent.parent / 'IOS-COLLECTOR-006'
COLLECTOR_HEAD = '1ea1c66e454f35280a82a2f6808a593eaca093c9'
COLLECTOR_DELIVERY_SHA = '7afd5b41a7498591ebcd25192e548d43006d1414ed53393551d33ab7bbb82d1d'
COLLECTOR_PINS = {
    'tools/diagnose_ios_scene.py': 'fe0b31d4befb6dee03dab756165ccabd4bc9f7c1ff46a97e8a8d931b84f4a38a',
    '.local/ios-collector-006/live/receipt.json': '937df12b84229319d42eedcc9474f346d672d508cdf51ec7b79c7f12c9a46d30',
    '.local/ios-collector-006/live/collector-source.py': '8818318f9f5bc96cca82cc4217228775705559d54f4dfff73102f16333ebcde2',
    '.local/ios-collector-006/closeout/receipt.json': '8928c720849f1b96929752b5c997d1d0c881ce958275b3a8f22a66bf2462848f',
}


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')
    path.chmod(0o600)


class Runner:
    """Each child has its own process group and a hard <=30 second deadline."""
    def __init__(self, directory, popen=subprocess.Popen):
        self.directory = directory
        self.popen = popen
        self.commands = []

    def start(self, argv, timeout=15):
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise ValueError('argv must be a nonempty string list')
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT:
            raise ValueError('child timeout outside (0,30]')
        rec = dict(argv=argv, started_at=utc(), timeout_seconds=timeout,
                   exit_code=None, timed_out=False)
        self.commands.append(rec)
        rec['output'] = f'command-{len(self.commands):03}.json'
        handle = {'rec': rec, 'started': time.monotonic(), 'proc': None, 'error': b''}
        try:
            handle['proc'] = self.popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       start_new_session=True)
        except OSError as exc:
            handle['error'] = str(exc).encode()
        return handle

    @staticmethod
    def failure(rec, message):
        rec.setdefault('primary_failure', message)
        rec.setdefault('errors', []).append(message)

    def supervise(self, handle):
        """Keep the child unreaped as the PGID reservation; never wait for EOF forever.

        WNOWAIT matters: reaping the leader before signalling permits PID/PGID reuse.
        Escaped sessions and simctl's service-side processes are outside this group.
        """
        rec, proc = handle['rec'], handle['proc']
        pid = proc.pid
        rec.update(pid=pid, pgid=pid, signals=[], pipe_eof={}, output_truncated=False,
                   descendant_outcome='escaped descendants unknown')
        buffers = {'stdout': bytearray(), 'stderr': bytearray()}
        hashes = {name: hashlib.sha256() for name in buffers}
        totals = {name: 0 for name in buffers}
        # A fixed byte cap also bounds memory; continue draining/discarding on overflow.
        cap = 8 * 1024 * 1024
        deadline = handle['started'] + min(rec['timeout_seconds'], MAX_TIMEOUT - 0.5)
        hard_end = deadline + 0.5
        rec['supervisor_bound_seconds'] = min(rec['timeout_seconds'], MAX_TIMEOUT - 0.5) + 0.5
        selector = selectors.DefaultSelector()
        reserved = False
        signalled = False
        exited = False

        def terminate(reason):
            nonlocal signalled
            if signalled:
                return
            signalled = True
            event = dict(at=utc(), signal='SIGKILL', reason=reason, escalation='hard bound; no graceful wait')
            rec['signals'].append(event)
            if not reserved:
                event['outcome'] = 'refused unsafe process-group identity'
                self.failure(rec, event['outcome'])
                return
            try:
                os.killpg(pid, signal.SIGKILL)
                event['outcome'] = 'sent to reserved owned group'
                rec['descendant_outcome'] = 'owned group signalled; escaped descendants unknown'
            except ProcessLookupError:
                event['outcome'] = 'group absent'
            except OSError as exc:
                event['outcome'] = str(exc)
                # Darwin may report EPERM for an already empty group. Do not turn
                # that into proof of absence; EOF and group outcome are separate.
                rec['descendant_outcome'] = 'group signal failed; descendants unknown'
                rec.setdefault('errors', []).append('group signal: ' + str(exc))

        try:
            if type(pid) is not int or pid <= 1 or pid == os.getpgrp():
                raise ValueError('unsafe process-group identity')
            # The waitable PID remains ours even if a very short-lived command
            # is already a zombie (Darwin then rejects getpgid/getsid).
            status = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if status is None:
                try:
                    if os.getpgid(pid) != pid or os.getsid(pid) != pid:
                        raise ValueError('unsafe process-group identity')
                except ProcessLookupError:
                    if os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                        raise ValueError('process identity disappeared without reserved child exit')
            reserved = True
            rec['ownership'] = 'new session/group; leader reserved with WNOWAIT'
            for name in buffers:
                pipe = getattr(proc, name)
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, name)
            while True:
                now = time.monotonic()
                if not exited:
                    status = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                    if status is not None:
                        exited = True
                        rec['child_exit_observed_at'] = utc()
                        terminate('immediate child exited; close any owned descendants')
                if now >= deadline and (not exited or selector.get_map()) and not rec['timed_out']:
                    rec['timed_out'] = True
                    self.failure(rec, 'execution/pipe deadline exceeded')
                    terminate('execution/pipe deadline')
                if not selector.get_map() and exited:
                    break
                if now >= hard_end:
                    self.failure(rec, 'cleanup deadline: child or pipe completion unknown')
                    break
                for key, _ in selector.select(min(0.02, max(0, hard_end - now))):
                    chunk = os.read(key.fd, 65536)
                    name = key.data
                    if not chunk:
                        rec['pipe_eof'][name] = utc()
                        selector.unregister(key.fileobj)
                    else:
                        hashes[name].update(chunk)
                        totals[name] += len(chunk)
                        room = cap - len(buffers[name])
                        buffers[name].extend(chunk[:room])
                        if len(chunk) > room:
                            rec['output_truncated'] = True
                            if 'primary_failure' not in rec:
                                self.failure(rec, 'output byte cap exceeded')
        except (OSError, ValueError) as exc:
            self.failure(rec, str(exc))
            terminate('supervisor error')
        finally:
            terminate('supervisor finalization')
            # Neither close nor wait depends on descendants closing their copies.
            selector.close()
            for name in buffers:
                try:
                    getattr(proc, name).close()
                except OSError as exc:
                    self.failure(rec, 'pipe close: ' + str(exc))
            # poll reaps only now, after the last possible group signal.
            rec['exit_code'] = proc.poll()
            rec['pipe_complete'] = set(rec['pipe_eof']) == set(buffers)
            rec['eof_before_group_signal'] = (rec['pipe_complete'] and bool(rec['signals'])
                and all(at <= rec['signals'][0]['at'] for at in rec['pipe_eof'].values()))
            rec['observed_bytes'] = totals
            rec['raw_stdout_sha256'] = hashes['stdout'].hexdigest()
            rec['raw_stderr_sha256'] = hashes['stderr'].hexdigest()
            rec['retained_stdout_sha256'] = digest(bytes(buffers['stdout']))
            rec['retained_stderr_sha256'] = digest(bytes(buffers['stderr']))
            if not rec['pipe_complete']:
                self.failure(rec, 'pipe EOF unknown; retained output incomplete')
            rec['collector_complete'] = (rec['pipe_complete'] and not rec['output_truncated']
                                         and rec['exit_code'] is not None and 'primary_failure' not in rec)
        return bytes(buffers['stdout']), bytes(buffers['stderr'])

    def finish(self, handle, transform=None):
        rec, proc = handle['rec'], handle['proc']
        out, err = b'', handle['error']
        if proc is not None:
            if not isinstance(proc, subprocess.Popen):
                # Trusted test transport only; real processes always use nonblocking
                # descriptors and the reserved-group supervisor above.
                remaining = max(0.001, rec['timeout_seconds'] - (time.monotonic() - handle['started']))
                try:
                    out, err = proc.communicate(timeout=remaining)
                except subprocess.TimeoutExpired:
                    rec['timed_out'] = True
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    out, err = proc.communicate(timeout=2)
                rec['exit_code'] = proc.returncode
            else:
                out, err = self.supervise(handle)
        rec['ended_at'] = utc()
        rec.setdefault('raw_stdout_sha256', digest(out))
        rec.setdefault('raw_stderr_sha256', digest(err))
        text = out.decode('utf-8', 'replace')
        if transform:
            text = transform(text)
        result = {'stdout': text, 'stderr': err.decode('utf-8', 'replace')}
        name = rec['output']
        write(self.directory / name, result)
        rec['sha256'] = digest((self.directory / name).read_bytes())
        return rec, result

    def start_stream(self, argv, transform, timeout=30):
        # Drain immediately: a debug stream can fill a pipe before launch returns.
        handle = self.start(argv, timeout)
        def drain():
            try:
                handle['result'] = self.finish(handle, transform)
            except Exception as exc:
                handle['failure'] = exc
        handle['thread'] = threading.Thread(target=drain, daemon=True)
        handle['thread'].start()
        return handle

    def finish_stream(self, handle):
        remaining = max(0, handle['rec']['timeout_seconds'] + 1 - (time.monotonic() - handle['started']))
        handle['thread'].join(remaining)
        if handle['thread'].is_alive():
            raise ValueError('collector thread exceeded bounded join; outcome unknown')
        if 'failure' in handle:
            raise handle['failure']
        return handle['result']

    def run(self, argv, timeout=15, transform=None):
        return self.finish(self.start(argv, timeout), transform)


def require_ok(result):
    rec, output = result
    if rec['timed_out'] or rec['exit_code'] != 0 or rec.get('collector_complete') is False:
        raise ValueError(f'command unavailable: {rec["argv"]}; exit={rec["exit_code"]}; timeout={rec["timed_out"]}; collector={rec.get("primary_failure", "unspecified")}')
    return output['stdout'].strip()


def device(family, root):
    udid, kind = OWNED[family]
    path = root / udid
    data = plistlib.loads((path / 'device.plist').read_bytes())
    expected = {'UDID': udid, 'name': f'ACS IOS-HOST-002 {family}',
                'runtime': RUNTIME, 'deviceType': kind}
    if any(data.get(k) != v for k, v in expected.items()):
        raise ValueError('dedicated device identity mismatch')
    return path, data


def app_identity(app):
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    if info.get('CFBundleIdentifier') != BUNDLE or info.get('CFBundleExecutable') != 'ACSHost':
        raise ValueError('owned app identity mismatch')
    files = sorted(p for p in app.rglob('*') if p.is_file())
    if any(p.is_symlink() for p in app.rglob('*')):
        raise ValueError('symlink in app bundle')
    return {str(p.relative_to(app)): digest(p.read_bytes()) for p in files}


def predicate(executable):
    if '"' in str(executable) or '\\' in str(executable):
        raise ValueError('unsafe process path')
    return (f'(processImagePath == "{executable}") OR '
            f'((process == "SpringBoard" OR process == "runningboardd" OR process == "frontboardd") '
            f'AND eventMessage CONTAINS "{BUNDLE}")')


def filter_trace(text, executable):
    """Retain only scoped structured events; redact emails and other bundle IDs."""
    events = []
    malformed = 0
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            malformed += bool(line.strip())
            continue
        if not isinstance(item, dict):
            malformed += 1
            continue
        message = item.get('eventMessage', '')
        if not isinstance(message, str):
            continue
        if item.get('processImagePath') != str(executable) and BUNDLE not in message:
            continue
        safe = {k: item[k] for k in ('timestamp', 'processID', 'processImagePath', 'subsystem', 'category', 'eventMessage') if k in item}
        safe['eventMessage'] = re.sub(r'[\w.+-]+@[\w.-]+', '[redacted-email]', message)
        safe['eventMessage'] = re.sub(r'\b(?:com|net|org|local)\.[A-Za-z0-9_.-]+',
            lambda m: m[0] if m[0] == BUNDLE or m[0].startswith(BUNDLE + '-') or m[0].startswith('com.apple.') else '[redacted-bundle]', safe['eventMessage'])
        events.append(safe)
    return json.dumps({'events': events, 'non_json_lines': malformed})


def inspect_previous():
    summary = load(PREVIOUS / REFERENCE / 'summary.json')
    if summary['source_head'] != SOURCE_HEAD or summary['app_sha256'] != BUILD_SHA:
        raise ValueError('preserved build/source receipt mismatch')
    # Read the preserved source and actual build/install/launch argv, not external source.
    inspected = {}
    for name in ('report.json', 'carried.diff', 'successor.diff',
                 f'{REFERENCE}/summary.json', f'{REFERENCE}/commands.log',
                 'run-20261018T100139Z-674a95/summary.json'):
        inspected[name] = digest((PREVIOUS / name).read_bytes())
    app = PREVIOUS / REFERENCE / 'ACSHost.app'
    identity = app_identity(app)
    if identity != APP_FILES:
        raise ValueError('preserved executable hash mismatch')
    validate_hash_map(summary.get('source_sha256'), SOURCE_SHA256, 'source_sha256')
    validate_hash_map(inspected, INSPECTED_SHA256, 'inspected')
    return {'source_head': SOURCE_HEAD, 'build_sha256': BUILD_SHA,
            'source_sha256': summary['source_sha256'], 'inspected': inspected,
            'app_files': identity, 'app': str(app),
            'note': 'Installed rejected UIWindowScene experiment, not final reverted manifest.'}


def capture_family(family, runner, reference, root):
    udid = OWNED[family][0]
    rec = {'family': family, 'udid': udid, 'bundle': BUNDLE, 'started_at': utc(),
           'request_sent': 'unknown', 'acknowledged': 'unknown', 'scene_delegate': 'unknown',
           'status': 'blocked', 'launch_count': 0, 'processes': [], 'markers': [],
           'trace_command': None, 'cleanup': 'not_needed'}
    changed = False
    try:
        path, before = device(family, root)
        rec['initial_state'] = before['state']
        rec['final_state'] = before['state']  # Unchanged unless we attempt a boot.
        # Refuse to disturb an existing booted app/session; no hidden cold-start reset.
        if before['state'] != 1:
            raise ValueError('prerequisite: dedicated simulator must initially be Shutdown')
        apps = [p.parent for p in (path / 'data/Containers/Bundle/Application').glob('*/ACSHost.app/Info.plist')
                if plistlib.loads(p.read_bytes()).get('CFBundleIdentifier') == BUNDLE]
        if len(apps) != 1:
            raise ValueError('prerequisite: exactly one installed owned app')
        app = apps[0]
        rec['app'] = str(app)
        rec['app_files'] = app_identity(app)
        if rec['app_files'] != reference['app_files']:
            raise ValueError('installed app differs from preserved signed experiment')
        require_ok(runner.run(['codesign', '--verify', '--strict', '--verbose=2', str(app)], 10))
        changed = True  # A timed-out boot may still have changed the device.
        require_ok(runner.run(['xcrun', 'simctl', 'boot', udid], 20))
        help_rec, help_out = runner.run(['xcrun', 'simctl', 'spawn', udid, 'log', 'help', 'show'], 10)
        if help_rec['timed_out'] or help_rec['exit_code'] not in (0, 64):
            raise ValueError('simulator log help unavailable')
        help_text = help_out['stdout'] + help_out['stderr']
        if '--predicate' not in help_text or '--style' not in help_text:
            raise ValueError('prerequisite: simulator log show help lacks required filters')
        container = Path(require_ok(runner.run(['xcrun', 'simctl', 'get_app_container', udid, BUNDLE, 'data'], 10)))
        if not container.is_relative_to(path / 'data/Containers/Data/Application'):
            raise ValueError('owned data container escaped dedicated device')
        metadata = plistlib.loads((container / '.com.apple.mobile_container_manager.metadata.plist').read_bytes())
        if metadata.get('MCMMetadataIdentifier') != BUNDLE:
            raise ValueError('owned data container identity mismatch')
        token = 'IOS-TRANSPORT-004-' + family + '-' + uuid.uuid4().hex
        rec['token'] = token
        start = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S+0000')
        rec['launch_count'] = 1
        launch, _ = runner.run(['xcrun', 'simctl', 'launch', udid, BUNDLE, '--evidence-run', token], 12)
        rec['launch_command'] = runner.commands.index(launch)
        marker = container / 'Documents/startup.jsonl'
        if marker.exists():
            for line in marker.read_text().splitlines():
                item = json.loads(line)
                if item.get('evidence_run') == token:
                    rec['markers'].append(item)
            for pid in sorted({x['pid'] for x in rec['markers']}):
                if type(pid) is not int or pid <= 1:
                    raise ValueError('invalid owned app PID')
                result = runner.run(['/bin/ps', '-p', str(pid), '-o', 'pid=,comm=,args='], 5)
                text = require_ok(result)
                if str(app / 'ACSHost') not in text or token not in text:
                    raise ValueError('owned process identity mismatch')
                rec['processes'].append({'pid': pid, 'executable': str(app / 'ACSHost'), 'token': token,
                                         'command': runner.commands.index(result[0])})
        trace, output = runner.run(['xcrun', 'simctl', 'spawn', udid, 'log', 'show',
            '--start', start, '--style', 'ndjson', '--info', '--debug', '--predicate', predicate(app / 'ACSHost')],
            20, lambda text: filter_trace(text, app / 'ACSHost'))
        rec['trace_command'] = runner.commands.index(trace)
        trace_data = json.loads(output['stdout'])
        rec['trace_events'] = len(trace_data['events'])
        if not trace['timed_out'] and trace['exit_code'] == 0 and trace_data['events']:
            rec['status'] = 'collected_unknown'
            rec['reason'] = 'Owned trace retained; request/ack interpretation requires independent examination.'
        else:
            rec['reason'] = 'Scene tracing unavailable: timeout, tool failure, or no retained owned events.'
        if rec['processes'] and any(x.get('stage') == 'scene-connect' for x in rec['markers']):
            rec['scene_delegate'] = 'reached'
        rec['next_prerequisite'] = 'Obtain usable owned FrontBoard/UIKit scene-request and acknowledgement trace before any lifecycle fix.'
    except (ValueError, OSError, KeyError) as exc:
        rec['reason'] = str(exc)
        rec['next_prerequisite'] = 'Resolve the recorded owned-device/tool prerequisite; do not infer scene activation.'
    finally:
        if changed:
            # shutdown restores exactly our initially-shutdown simulator and all its owned children.
            # No terminate RPC retry, service kills, erasure, or other device operation.
            cleanup, _ = runner.run(['xcrun', 'simctl', 'shutdown', udid], 20)
            try:
                _, final = device(family, root)
                rec['final_state'] = final['state']
                rec['cleanup'] = 'restored' if cleanup['exit_code'] == 0 and not cleanup['timed_out'] and final['state'] == 1 else 'failed'
            except (ValueError, OSError):
                rec['cleanup'] = 'failed'
        rec['ended_at'] = utc()
    return rec


def collect(output):
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.exists() or any(output.parent.glob('command-*.json')):
        raise ValueError('refusing to overwrite prior diagnostic receipt')
    runner = Runner(output.parent)
    receipt = {'schema': 1, 'unit': 'IOS-TRANSPORT-004', 'bundle': BUNDLE,
               'started_at': utc(), 'runtime': '26.5', 'minimum_target': '26.0',
               'activation_claim': False, 'families': [], 'commands': runner.commands}
    try:
        receipt['reference'] = inspect_previous()
        require_ok(runner.run(['codesign', '--verify', '--strict', '--verbose=2', receipt['reference']['app']], 10))
        # Help inspection precedes choosing the bounded datastore method.
        runner.run(['xcrun', 'simctl', 'help', 'spawn'], 10)
        runner.run(['xcrun', 'simctl', 'help', 'launch'], 10)
        runner.run(['/usr/bin/log', 'help', 'show'], 10)
        root = Path.home() / 'Library/Developer/CoreSimulator/Devices'
        for family in OWNED:
            receipt['families'].append(capture_family(family, runner, receipt['reference'], root))
    finally:
        receipt['ended_at'] = utc()
        write(output, receipt)
        try:
            retain_journals(receipt, output.parent)
        except (ValueError, OSError, KeyError) as exc:
            receipt['journal_failure'] = str(exc)
        write(output, receipt)
    return receipt


def trace_observations(events):
    observations = {'open_request_received': [], 'frontboard_app_connection': [], 'server_scene_registration': []}
    for index, event in enumerate(events):
        message = event.get('eventMessage', '')
        if event.get('subsystem') != 'com.apple.FrontBoard':
            continue
        if f'Received request to open "{BUNDLE}"' in message:
            observations['open_request_received'].append(index)
        if f'[app<{BUNDLE}>:' in message and '] Connection established.' in message:
            observations['frontboard_app_connection'].append(index)
        if f'[app<{BUNDLE}>:' in message and '] Registered new scene:' in message:
            observations['server_scene_registration'].append(index)
    return observations


def retain_journals(receipt, directory):
    """Read existing owned files only; never starts an app or changes device state."""
    for family in receipt['families']:
        if family.get('launch_count') != 1:
            continue
        udid = family['udid']
        trace_index = family.get('trace_command')
        if trace_index is not None:
            command = receipt['commands'][trace_index]
            trace = json.loads(load(directory / command['output'])['stdout'])
            family['observations'] = trace_observations(trace['events'])
            if family['status'] == 'collected_unknown':
                family['next_prerequisite'] = 'Correlate app-sided UIKit scene transaction delivery/ack with the restored session ID; server app connection or scene registration is insufficient.'
        root = Path.home() / 'Library/Developer/CoreSimulator/Devices' / udid
        command = next(c for c in receipt['commands'] if c['argv'][:4] == ['xcrun', 'simctl', 'get_app_container', udid])
        container = Path(load(directory / command['output'])['stdout'].strip()).resolve()
        if not container.is_relative_to(root / 'data/Containers/Data/Application'):
            raise ValueError('journal container outside dedicated device')
        metadata = plistlib.loads((container / '.com.apple.mobile_container_manager.metadata.plist').read_bytes())
        if metadata.get('MCMMetadataIdentifier') != BUNDLE:
            raise ValueError('journal container identity mismatch')
        journal = {'family': family['family'], 'udid': udid, 'bundle': BUNDLE,
                   'token': family['token'], 'markers': [], 'activation': [], 'read_at': utc()}
        startup = container / 'Documents/startup.jsonl'
        if startup.exists():
            journal['startup_file_sha256'] = digest(startup.read_bytes())
            for line in startup.read_text().splitlines():
                item = json.loads(line)
                if item.get('evidence_run') == family['token']:
                    journal['markers'].append(item)
        for delay in (0, 1, 5, 10):
            file = container / f'Documents/activation-{delay}.json'
            if file.exists():
                item = load(file)
                if item.get('evidence_run') == family['token']:
                    journal['activation'].append({'name': file.name, 'sha256': digest(file.read_bytes()), 'value': item})
        name = family['family'] + '-journal.json'
        write(directory / name, journal)
        family['journal'] = {'path': name, 'sha256': digest((directory / name).read_bytes())}
        # Persisted token-correlated markers are evidence even after the app was stopped.
        # They do not supply a missing live process identity or scene acknowledgement.
        family['markers'] = journal['markers']
    return receipt


def trace_retained(output):
    """Correct/recollect a bounded historical query, with NO application launch."""
    receipt = verify_saved(output)
    if receipt['unit'] != 'IOS-TRANSPORT-004':
        raise ValueError('historical requery is not authorized for a delivery receipt')
    # Preserve the entire original observation before appending any receipts.
    archive = output.parent / ('before-trace-' + uuid.uuid4().hex + '.json')
    write(archive, receipt)
    runner = Runner(output.parent)
    runner.commands = receipt['commands']
    receipt['prior_receipt'] = {'path': archive.name, 'sha256': digest(archive.read_bytes())}
    root = Path.home() / 'Library/Developer/CoreSimulator/Devices'
    for family in receipt['families']:
        udid = family['udid']
        changed = False
        try:
            path, current = device(family['family'], root)
            if current['state'] != 1 or family['initial_state'] != 1:
                raise ValueError('historical query requires initially-shutdown owned simulator')
            app = Path(family['app'])
            if app_identity(app) != receipt['reference']['app_files']:
                raise ValueError('historical installed app identity changed')
            require_ok(runner.run(['codesign', '--verify', '--strict', '--verbose=2', str(app)], 10))
            launch = receipt['commands'][family['launch_command']]
            start = dt.datetime.fromisoformat(launch['started_at']).strftime('%Y-%m-%d %H:%M:%S+0000')
            end = dt.datetime.fromisoformat(family['ended_at']).strftime('%Y-%m-%d %H:%M:%S+0000')
            changed = True
            require_ok(runner.run(['xcrun', 'simctl', 'boot', udid], 20))
            command, output_data = runner.run(['xcrun', 'simctl', 'spawn', udid, 'log', 'show',
                '--start', start, '--end', end, '--style', 'ndjson', '--info', '--debug',
                '--predicate', predicate(app / 'ACSHost')], 20,
                lambda text: filter_trace(text, app / 'ACSHost'))
            family['trace_command'] = runner.commands.index(command)
            trace = json.loads(output_data['stdout'])
            family['trace_events'] = len(trace['events'])
            if command['exit_code'] == 0 and not command['timed_out'] and trace['events']:
                family['status'] = 'collected_unknown'
                family['reason'] = 'Historical owned events retained; request/ack remain unclassified.'
            else:
                family['status'] = 'blocked'
                family['reason'] = ('Historical scene trace unavailable: exit=' + str(command['exit_code'])
                    + ', timeout=' + str(command['timed_out']) + ', events=' + str(len(trace['events'])))
            family['next_prerequisite'] = 'Establish usable simulator unified-log datastore access for the owned launch interval before diagnosing scene transport.'
        except (ValueError, OSError, KeyError) as exc:
            family['status'] = 'blocked'
            family['reason'] = str(exc)
        finally:
            if changed:
                cleanup, _ = runner.run(['xcrun', 'simctl', 'shutdown', udid], 20)
                _, final = device(family['family'], root)
                family['final_state'] = final['state']
                family['cleanup'] = 'restored' if cleanup['exit_code'] == 0 and not cleanup['timed_out'] and final['state'] == 1 else 'failed'
            write(output, receipt)
    retain_journals(receipt, output.parent)
    write(output, receipt)
    return receipt


def validate_command(argv, families, reference):
    """Closed argv grammar; saved receipts cannot introduce extra device/process access."""
    if argv in (['/usr/bin/log', 'help', 'show'], ['/usr/bin/log', 'help', 'stream']):
        return
    apps = {reference.get('app')} | {f.get('app') for f in families}
    if len(argv) == 5 and argv[:4] == ['codesign', '--verify', '--strict', '--verbose=2'] and argv[4] in apps:
        return
    if len(argv) == 6 and argv[:3] == ['/bin/ps', '-ww', '-p'] and argv[4:] == ['-o', 'pid=,args=']:
        if any(str(p['pid']) == argv[3] for f in families for p in f['processes']) or any(
                str(m.get('pid')) == argv[3] and m.get('evidence_run') == f.get('token') for f in families for m in f['markers']):
            return
        raise ValueError('process query lacks owned process identity')
    if len(argv) == 5 and argv[:2] == ['/bin/ps', '-p'] and argv[3:] == ['-o', 'pid=,comm=,args=']:
        if any(str(p['pid']) == argv[2] for f in families for p in f['processes']) or any(
                str(m.get('pid')) == argv[2] and m.get('evidence_run') == f.get('token') for f in families for m in f['markers']):
            return
        raise ValueError('process query lacks owned process identity')
    if argv[:2] != ['xcrun', 'simctl']:
        raise ValueError('unknown diagnostic executable')
    if argv in (['xcrun', 'simctl', 'help', 'spawn'], ['xcrun', 'simctl', 'help', 'launch']):
        return
    if len(argv) < 4 or argv[3] not in {x[0] for x in OWNED.values()}:
        raise ValueError('unowned device')
    op, udid = argv[2:4]
    if op in ('boot', 'shutdown') and len(argv) == 4:
        return
    if argv[2:] == ['get_app_container', udid, BUNDLE, 'data']:
        return
    if op == 'launch' and len(argv) == 7 and argv[4:6] == [BUNDLE, '--evidence-run']:
        if any(f.get('token') == argv[6] and f['udid'] == udid for f in families):
            return
        raise ValueError('launch token mismatch')
    if argv[2:] in (['spawn', udid, 'log', 'help', 'show'], ['spawn', udid, 'log', 'help', 'stream']):
        return
    if argv[2:6] == ['spawn', udid, 'log', 'stream']:
        family = next(f for f in families if f['udid'] == udid)
        if argv[6:] == ['--style', 'ndjson', '--level', 'debug', '--timeout', '28', '--predicate', predicate(Path(family['app']) / 'ACSHost')]:
            return
        raise ValueError('unscoped live stream')
    if argv[2:6] == ['spawn', udid, 'log', 'show']:
        family = next(f for f in families if f['udid'] == udid)
        tail = argv[6:]
        if len(tail) < 2 or tail[0] != '--start':
            raise ValueError('trace interval missing')
        tail = tail[2:]
        if tail[:1] == ['--end']:
            tail = tail[2:]
        if tail == ['--style', 'ndjson', '--info', '--debug', '--predicate', predicate(Path(family['app']) / 'ACSHost')]:
            return
        raise ValueError('unscoped trace')
    raise ValueError('forbidden simulator operation/argv')


def validate_hash_map(value, expected, label):
    """Require the complete pinned input identity, not merely hash-shaped values."""
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'reference {label} keys missing or unexpected')
    for name, checksum in value.items():
        if not isinstance(checksum, str) or re.fullmatch(r'[0-9a-f]{64}', checksum) is None:
            raise ValueError(f'reference {label} malformed SHA-256: {name}')
        if checksum != expected[name]:
            raise ValueError(f'reference {label} hash mismatch: {name}')


def validate_restoration(family, commands):
    """Every attempted boot needs its own successful bounded shutdown receipt."""
    initial, final = family.get('initial_state'), family.get('final_state')
    if (type(initial) is not int or type(final) is not int
            or initial not in (1, 2, 3, 4) or final != initial):
        raise ValueError('owned device original/final state missing or inconsistent')
    actions = [c for c in commands if c['argv'][:2] == ['xcrun', 'simctl']
               and len(c['argv']) >= 4 and c['argv'][3] == family['udid']
               and c['argv'][2] in ('boot', 'shutdown', 'launch')]
    if family['cleanup'] == 'not_needed':
        if actions:
            raise ValueError('device-changing commands cannot claim cleanup not_needed')
        return
    if family['cleanup'] != 'restored' or initial != 1 or not actions:
        raise ValueError('owned device cleanup failed or restoration unsupported')
    pending = False
    restored = 0
    previous_end = None
    for command in actions:
        started = dt.datetime.fromisoformat(command['started_at'])
        ended = dt.datetime.fromisoformat(command['ended_at'])
        if previous_end is not None and started < previous_end:
            raise ValueError('device restoration command chronology inconsistent')
        previous_end = ended
        op = command['argv'][2]
        if op == 'boot':
            if pending:
                raise ValueError('earlier boot lacks successful shutdown')
            # Even a failed/timed-out boot may have changed the device.
            pending = True
        elif op == 'launch':
            if not pending:
                raise ValueError('launch outside owned boot/shutdown cycle')
        elif not pending:
            raise ValueError('shutdown lacks an owned boot attempt')
        elif command['exit_code'] == 0 and not command['timed_out']:
            pending = False
            restored += 1
    if pending or not restored:
        raise ValueError('owned device restoration lacks successful bounded shutdown')


def verify_saved(path):
    """Offline structural/integrity verification, never a transport success gate."""
    obj = load(path)
    if obj.get('schema') != 1 or obj.get('unit') not in ('IOS-TRANSPORT-004', 'IOS-SCENE-DELIVERY-005') or obj.get('bundle') != BUNDLE or obj.get('activation_claim') is not False:
        raise ValueError('invalid receipt identity or activation claim')
    ref = obj['reference']
    if ref.get('app') != str(PREVIOUS / REFERENCE / 'ACSHost.app'):
        raise ValueError('preserved app path mismatch')
    if ref['build_sha256'] != BUILD_SHA or ref['source_head'] != SOURCE_HEAD or ref['app_files'] != APP_FILES:
        raise ValueError('reference identity mismatch')
    validate_hash_map(ref.get('source_sha256'), SOURCE_SHA256, 'source_sha256')
    validate_hash_map(ref.get('inspected'), INSPECTED_SHA256, 'inspected')
    commands = obj['commands']
    if not isinstance(commands, list) or not commands:
        raise ValueError('commands missing')
    families = obj['families']
    for command in commands:
        if not 0 < command['timeout_seconds'] <= 30 or type(command['timed_out']) is not bool:
            raise ValueError('invalid command deadline')
        argv = command['argv']
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
            raise ValueError('malformed argv')
        validate_command(argv, families, ref)
        started = dt.datetime.fromisoformat(command['started_at'])
        ended = dt.datetime.fromisoformat(command['ended_at'])
        if started.utcoffset() != dt.timedelta(0) or ended.utcoffset() != dt.timedelta(0) or ended < started:
            raise ValueError('command UTC interval malformed')
        if command['exit_code'] is not None and type(command['exit_code']) is not int:
            raise ValueError('malformed command exit')
        name = command['output']
        if Path(name).name != name:
            raise ValueError('output escapes receipt directory')
        if (path.parent / name).is_symlink():
            raise ValueError('symlink receipt output')
        data = (path.parent / name).read_bytes()
        if digest(data) != command['sha256']:
            raise ValueError('retained output hash mismatch')
        payload = json.loads(data)
        if not all(isinstance(payload[k], str) for k in ('stdout', 'stderr')):
            raise ValueError('malformed retained command output')
    families = obj['families']
    if not isinstance(families, list) or {x['family'] for x in families} != set(OWNED) or len(families) != 2:
        raise ValueError('both families required')
    for family in families:
        udid = OWNED[family['family']][0]
        if family['udid'] != udid or family['bundle'] != BUNDLE:
            raise ValueError('family ownership mismatch')
        if family['request_sent'] != 'unknown' or family['acknowledged'] != 'unknown':
            raise ValueError('unreviewed trace cannot assert request/ack')
        if family['scene_delegate'] not in ('unknown', 'reached') or family['status'] not in ('blocked', 'collected_unknown'):
            raise ValueError('unknown evidence state')
        launches = [c for c in commands if c['argv'][:4] == ['xcrun', 'simctl', 'launch', udid]]
        if len(launches) > 1 or family['launch_count'] != len(launches):
            raise ValueError('launch bound mismatch')
        if 'app' in family:
            base = SIMULATOR_DEVICES / udid / 'data/Containers/Bundle/Application'
            app = Path(family['app'])
            if app.name != 'ACSHost.app' or app.parent.parent != base:
                raise ValueError('installed app path outside owned device')
            try:
                uuid.UUID(app.parent.name)
            except ValueError:
                raise ValueError('installed app container is not a UUID')
        if 'app_files' in family and family['app_files'] != ref['app_files']:
            raise ValueError('installed identity mismatch')
        index = family['trace_command']
        if index is not None:
            command = commands[index]
            if command['argv'][:6] not in (['xcrun', 'simctl', 'spawn', udid, 'log', 'show'], ['xcrun', 'simctl', 'spawn', udid, 'log', 'stream']):
                raise ValueError('trace command identity mismatch')
            trace = json.loads(load(path.parent / command['output'])['stdout'])
            if not isinstance(trace.get('events'), list) or type(trace.get('non_json_lines')) is not int:
                raise ValueError('malformed trace schema')
            for event in trace['events']:
                if not isinstance(event, dict) or not isinstance(event.get('eventMessage'), str):
                    raise ValueError('malformed trace event')
                image = event.get('processImagePath', '')
                # Old receipts conservatively redacted the owned '-default' suffix.
                # The exact query predicate plus system process identity still binds scope;
                # no scene ID or acknowledgement is reconstructed from that placeholder.
                if image != str(Path(family['app']) / 'ACSHost') and (Path(image).name not in ('SpringBoard', 'runningboardd', 'frontboardd') or not (BUNDLE in event['eventMessage'] or '[redacted-bundle]' in event['eventMessage'])):
                    raise ValueError('trace event ownership mismatch')
            if 'observations' in family and family['observations'] != trace_observations(trace['events']):
                raise ValueError('trace observation index mismatch')
            if family.get('trace_events') != len(trace['events']):
                raise ValueError('trace event count mismatch')
            if family['status'] == 'collected_unknown' and (not trace['events'] or command['exit_code'] != 0 or command['timed_out']):
                raise ValueError('failed diagnostics relabeled collected')
        elif family['status'] != 'blocked':
            raise ValueError('missing trace cannot be collected')
        if family['scene_delegate'] == 'reached' and (not family['processes'] or not any(x.get('stage') == 'scene-connect' and x.get('evidence_run') == family['token'] for x in family['markers'])):
            raise ValueError('scene delegate claim missing correlated app marker')
        for process in family['processes']:
            if type(process['pid']) is not int or process['pid'] <= 1 or process['executable'] != str(Path(family['app']) / 'ACSHost') or process['token'] != family['token']:
                raise ValueError('saved owned process mismatch')
            command = commands[process['command']]
            if command['argv'] not in (['/bin/ps', '-p', str(process['pid']), '-o', 'pid=,comm=,args='], ['/bin/ps', '-ww', '-p', str(process['pid']), '-o', 'pid=,args=']) or command['exit_code'] != 0 or command['timed_out']:
                raise ValueError('saved process command mismatch')
            text = load(path.parent / command['output'])['stdout']
            if process['executable'] not in text or process['token'] not in text:
                raise ValueError('saved process output mismatch')
        if 'journal' in family:
            journal_ref = family['journal']
            name = journal_ref['path']
            if Path(name).name != name or (path.parent / name).is_symlink():
                raise ValueError('journal path escape')
            data = (path.parent / name).read_bytes()
            if digest(data) != journal_ref['sha256']:
                raise ValueError('journal hash mismatch')
            journal = json.loads(data)
            if any(journal[k] != family[k] for k in ('family', 'udid', 'bundle', 'token', 'markers')):
                raise ValueError('journal identity mismatch')
            pids = {m['pid'] for m in journal['markers']}
            if len(pids) > 1 or any(type(pid) is not int or pid <= 1 for pid in pids):
                raise ValueError('journal PID identity mismatch')
            for item in journal['markers'] + [a['value'] for a in journal['activation']]:
                if item.get('evidence_run') != family['token'] or item.get('pid') not in pids:
                    raise ValueError('journal launch correlation mismatch')
        if not family.get('reason') or not family.get('next_prerequisite'):
            raise ValueError('missing observation/prerequisite')
        validate_restoration(family, commands)
    if 'prior_receipt' in obj:
        prior = obj['prior_receipt']
        if Path(prior['path']).name != prior['path'] or digest((path.parent / prior['path']).read_bytes()) != prior['sha256']:
            raise ValueError('prior receipt identity mismatch')
    if obj['unit'] == 'IOS-SCENE-DELIVERY-005':
        verify_delivery(obj, path.parent)
    return obj


def stream_args(udid, app):
    return ['xcrun', 'simctl', 'spawn', udid, 'log', 'stream', '--style', 'ndjson',
            '--level', 'debug', '--timeout', '28', '--predicate', predicate(app / 'ACSHost')]


def delivery_observations(family, events, journal):
    """Candidate indices only. No guessed text pattern asserts a transaction or ack."""
    pids = {p['pid'] for p in family['processes']}
    app_events = [i for i, e in enumerate(events) if e.get('processID') in pids
                  and e.get('processImagePath') == str(Path(family['app']) / 'ACSHost')]
    sessions = sorted({s['identifier'] for a in journal['activation']
                       for s in a['value'].get('sessions', [])})
    return {'system': trace_observations(events), 'app_event_indices': app_events,
            'persistent_sessions': sessions,
            'app_session_candidate_indices': [i for i in app_events
                if any(s in events[i]['eventMessage'] for s in sessions)],
            'app_delivery': 'unknown', 'app_acknowledgement': 'unknown'}


def capture_delivery(family, runner, reference, root, sleep=time.sleep):
    udid = OWNED[family][0]
    rec = dict(family=family, udid=udid, bundle=BUNDLE, started_at=utc(),
               request_sent='unknown', acknowledged='unknown', scene_delegate='unknown',
               status='blocked', launch_count=0, processes=[], markers=[],
               trace_command=None, cleanup='not_needed')
    changed = False
    stream = None
    try:
        path, before = device(family, root)
        rec.update(initial_state=before['state'], final_state=before['state'])
        if before['state'] != 1:
            raise ValueError('prerequisite: dedicated simulator must initially be Shutdown')
        apps = [p.parent for p in (path / 'data/Containers/Bundle/Application').glob('*/ACSHost.app/Info.plist')
                if plistlib.loads(p.read_bytes()).get('CFBundleIdentifier') == BUNDLE]
        if len(apps) != 1:
            raise ValueError('prerequisite: exactly one installed owned app')
        app = apps[0]
        rec.update(app=str(app), app_files=app_identity(app))
        if rec['app_files'] != reference['app_files']:
            raise ValueError('installed app differs from preserved signed experiment')
        require_ok(runner.run(['codesign', '--verify', '--strict', '--verbose=2', str(app)], 10))
        changed = True
        require_ok(runner.run(['xcrun', 'simctl', 'boot', udid], 20))
        help_rec, help_out = runner.run(['xcrun', 'simctl', 'spawn', udid, 'log', 'help', 'stream'], 10)
        rec['stream_help_command'] = runner.commands.index(help_rec)
        help_text = help_out['stdout'] + help_out['stderr']
        if help_rec['timed_out'] or help_rec['exit_code'] not in (0, 64) or not all(
                x in help_text for x in ('--predicate', '--level', 'debug', '--timeout', 'ndjson')):
            raise ValueError('prerequisite: simulator live debug stream/filter/deadline capability unavailable')
        container = Path(require_ok(runner.run(['xcrun', 'simctl', 'get_app_container', udid, BUNDLE, 'data'], 10)))
        if not container.is_relative_to(path / 'data/Containers/Data/Application'):
            raise ValueError('owned data container escaped dedicated device')
        metadata = plistlib.loads((container / '.com.apple.mobile_container_manager.metadata.plist').read_bytes())
        if metadata.get('MCMMetadataIdentifier') != BUNDLE:
            raise ValueError('owned data container identity mismatch')
        rec['token'] = 'IOS-SCENE-DELIVERY-005-' + family + '-' + uuid.uuid4().hex
        stream = runner.start_stream(stream_args(udid, app), lambda text: filter_trace(text, app / 'ACSHost'))
        # Subscription registration is not exposed by log; retain the full startup output.
        sleep(0.5)
        rec['launch_count'] = 1
        launch, _ = runner.run(['xcrun', 'simctl', 'launch', udid, BUNDLE, '--evidence-run', rec['token']], 12)
        rec['launch_command'] = runner.commands.index(launch)
        marker = container / 'Documents/startup.jsonl'
        marker_deadline = time.monotonic() + 2
        while True:
            rec['markers'] = [json.loads(line) for line in marker.read_text().splitlines()
                              if json.loads(line).get('evidence_run') == rec['token']] if marker.exists() else []
            if rec['markers'] or time.monotonic() >= marker_deadline:
                break
            sleep(0.05)
        pids = {m['pid'] for m in rec['markers']}
        if len(pids) != 1:
            raise ValueError('prerequisite: unique token-correlated live app PID unavailable')
        pid = pids.pop()
        if type(pid) is not int or pid <= 1:
            raise ValueError('invalid owned PID')
        identity = runner.run(['/bin/ps', '-ww', '-p', str(pid), '-o', 'pid=,args='], 5)
        verify_process_text(require_ok(identity), pid, str(app / 'ACSHost'), rec['token'])
        rec['processes'].append(dict(pid=pid, executable=str(app / 'ACSHost'), token=rec['token'],
                                     command=runner.commands.index(identity[0])))
        rec['observation_state'] = 'complete'
        rec['observation'] = dict(seconds=12, started_at=utc())
        started = time.monotonic()
        sleep(12)
        rec['observation'].update(ended_at=utc(), elapsed_seconds=time.monotonic() - started)
        # Verify the same PID/path/token after the complete interval, before shutdown.
        identity = runner.run(['/bin/ps', '-ww', '-p', str(pid), '-o', 'pid=,args='], 5)
        verify_process_text(require_ok(identity), pid, str(app / 'ACSHost'), rec['token'])
        rec['processes'].append(dict(pid=pid, executable=str(app / 'ACSHost'), token=rec['token'],
                                     command=runner.commands.index(identity[0])))
        retain_journals({'families': [rec], 'commands': runner.commands}, runner.directory)
        rec['reason'] = 'Live debug stream and full app interval retained; transaction delivery/ack not established.'
    except (ValueError, OSError, KeyError) as exc:
        rec['primary_failure'] = str(exc)
        rec['reason'] = str(exc)
    finally:
        try:
            if stream is not None:
                trace, output = runner.finish_stream(stream)
                rec['trace_command'] = runner.commands.index(trace)
                events = json.loads(output['stdout'])['events']
                rec['trace_events'] = len(events)
                rec['observations'] = trace_observations(events)
                if rec['launch_count'] and 'observation' not in rec:
                    rec['observation_state'] = 'unavailable'
                    rec['observation_unavailable_reason'] = 'No successful pre-interval live PID/path/token query was recorded.'
                if rec['launch_count'] and 'journal' not in rec:
                    try:
                        retain_journals({'families': [rec], 'commands': runner.commands}, runner.directory)
                    except (ValueError, OSError, KeyError) as exc:
                        rec.setdefault('primary_failure', 'journal retention failed: ' + str(exc))
                        rec['reason'] += '; journal unavailable: ' + str(exc)
                journal = load(runner.directory / rec['journal']['path']) if 'journal' in rec else {'activation': []}
                rec['delivery_observations'] = delivery_observations(rec, events, journal)
                if trace['exit_code'] != 0 or trace['timed_out'] or trace.get('collector_complete') is False:
                    failure = 'collector live stream failed: exit=' + str(trace['exit_code']) + '; timeout=' + str(trace['timed_out'])
                    rec.setdefault('primary_failure', failure)
                    rec['reason'] += '; ' + failure
        except (ValueError, OSError, KeyError) as exc:
            rec.setdefault('primary_failure', str(exc))
            rec['reason'] = rec.get('reason', rec['primary_failure']) + '; stream finalization failed: ' + str(exc)
        finally:
            rec['next_prerequisite'] = ('Obtain an app-side UIKit/FrontBoard scene-creation transaction and acknowledgement observer '
                'that exposes the persistent session ID and transaction ID in this pinned app; debug unified logs alone do not establish these semantics. '
                'A separately authorized debugger or instrumentation prerequisite is required before a lifecycle fix.')
            if rec.get('primary_failure'):
                rec['next_prerequisite'] = ('Collector blocked: ' + rec['primary_failure'] +
                    '. Split the collector/observation prerequisite; no further launch retry is authorized and no platform visibility limit is established.')
            if changed:
                cleanup, _ = runner.run(['xcrun', 'simctl', 'shutdown', udid], 20)
                try:
                    _, final = device(family, root)
                    rec['final_state'] = final['state']
                    rec['cleanup'] = 'restored' if cleanup['exit_code'] == 0 and not cleanup['timed_out'] and final['state'] == 1 else 'failed'
                except (ValueError, OSError):
                    rec['cleanup'] = 'failed'
        rec['ended_at'] = utc()
    return rec


def verify_process_text(text, pid, executable, token):
    # Unlimited-width args avoid macOS comm truncation; anchor PID and complete argv.
    pattern = rf'^\s*{pid}\s+{re.escape(executable)} --evidence-run {re.escape(token)}\s*$'
    if re.fullmatch(pattern, text) is None:
        raise ValueError('owned process PID/path/token mismatch')


def collect_delivery(output):
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.exists() or any(output.parent.glob('command-*.json')):
        raise ValueError('refusing to overwrite prior delivery receipt')
    # Verify the accepted predecessor, then retain its precise offline dependencies.
    prior_path = TRANSPORT / 'receipt.json'
    if digest(prior_path.read_bytes()) != TRANSPORT_SHA:
        raise ValueError('accepted predecessor receipt identity mismatch')
    prior = verify_saved(prior_path)
    directory = output.parent / 'predecessor'
    directory.mkdir(mode=0o700)
    names = {'receipt.json'} | {c['output'] for c in prior['commands']} | {f['journal']['path'] for f in prior['families']}
    if 'prior_receipt' in prior:
        names.add(prior['prior_receipt']['path'])
    for name in names:
        (directory / name).write_bytes((TRANSPORT / name).read_bytes())
        (directory / name).chmod(0o600)
    runner = Runner(output.parent)
    obj = dict(schema=1, unit='IOS-SCENE-DELIVERY-005', bundle=BUNDLE, activation_claim=False,
               runtime='26.5', minimum_target='26.0', started_at=utc(), families=[], commands=runner.commands,
               predecessor=dict(path='predecessor/receipt.json', sha256=TRANSPORT_SHA), reference=inspect_previous())
    try:
        runner.run(['/usr/bin/log', 'help', 'stream'], 10)
        root = Path.home() / 'Library/Developer/CoreSimulator/Devices'
        for family in OWNED:
            obj['families'].append(capture_delivery(family, runner, obj['reference'], root))
    finally:
        obj['ended_at'] = utc()
        write(output, obj)
    return obj


def verify_delivery(obj, directory):
    if obj.get('runtime') != '26.5' or obj.get('minimum_target') != '26.0':
        raise ValueError('delivery runtime/target identity mismatch')
    predecessor = obj.get('predecessor', {})
    if predecessor != {'path': 'predecessor/receipt.json', 'sha256': TRANSPORT_SHA}:
        raise ValueError('delivery predecessor identity mismatch')
    prior_path = directory / predecessor['path']
    if prior_path.is_symlink() or prior_path.parent.is_symlink() or digest(prior_path.read_bytes()) != TRANSPORT_SHA:
        raise ValueError('delivery predecessor hash mismatch')
    verify_saved(prior_path)
    commands = obj['commands']

    def reference(f, key):
        index = f.get(key)
        if type(index) is not int or not 0 <= index < len(commands):
            raise ValueError('missing/wrong command reference: ' + key)
        return commands[index]

    def timestamp(value):
        result = dt.datetime.fromisoformat(value)
        if result.utcoffset() != dt.timedelta(0):
            raise ValueError('delivery chronology requires UTC')
        return result

    for f in obj['families']:
        if f['status'] != 'blocked' or f['scene_delegate'] != 'unknown':
            raise ValueError('delivery cannot invent positive semantic state')
        helps = [c for c in commands if c['argv'] ==
                 ['xcrun', 'simctl', 'spawn', f['udid'], 'log', 'help', 'stream']]
        streams = [c for c in commands if c['argv'][:6] ==
                   ['xcrun', 'simctl', 'spawn', f['udid'], 'log', 'stream']]
        boots = [c for c in commands if c['argv'] == ['xcrun', 'simctl', 'boot', f['udid']]]
        shutdowns = [c for c in commands if c['argv'] == ['xcrun', 'simctl', 'shutdown', f['udid']]]
        help_c = None
        if helps or 'stream_help_command' in f or streams or f['launch_count']:
            help_c = reference(f, 'stream_help_command')
            if len(helps) != 1 or help_c is not helps[0]:
                raise ValueError('live capability command reference mismatch')
            if (not boots or not shutdowns or
                    timestamp(boots[0]['ended_at']) > timestamp(help_c['started_at']) or
                    timestamp(help_c['ended_at']) > timestamp(shutdowns[0]['started_at'])):
                raise ValueError('live capability outside owned boot/shutdown')
        if not streams and not f['launch_count']:
            # Failed help is legitimate preflight evidence, never platform acceptance.
            if f.get('trace_command') is not None or 'observation' in f or f['processes']:
                raise ValueError('preflight blocker has contradictory observation')
            continue
        trace = reference(f, 'trace_command')
        text = load(directory / help_c['output'])
        if (help_c['exit_code'] not in (0, 64) or help_c['timed_out'] or
                not all(x in text['stdout'] + text['stderr']
                        for x in ('--predicate', '--level', 'debug', '--timeout', 'ndjson'))):
            raise ValueError('live capability evidence missing')
        if (len(streams) != 1 or trace is not streams[0] or
                trace['argv'] != stream_args(f['udid'], Path(f['app'])) or
                timestamp(help_c['ended_at']) > timestamp(trace['started_at']) or
                timestamp(trace['ended_at']) > timestamp(shutdowns[0]['started_at'])):
            raise ValueError('live stream chronology outside capability/shutdown')
        if not f['launch_count']:
            if 'observation' in f or f['processes']:
                raise ValueError('stream without launch has contradictory observation')
            continue
        launch = reference(f, 'launch_command')
        if launch['argv'] != ['xcrun', 'simctl', 'launch', f['udid'], BUNDLE, '--evidence-run', f['token']]:
            raise ValueError('delivery launch reference mismatch')
        if (timestamp(trace['started_at']) > timestamp(launch['started_at']) or
                timestamp(trace['ended_at']) < timestamp(launch['ended_at']) or
                timestamp(trace['ended_at']) < timestamp(launch['started_at']) + dt.timedelta(seconds=12)):
            raise ValueError('live stream does not enclose launch and observation')
        if not f.get('journal'):
            raise ValueError('delivery requires retained journal')
        journal = load(directory / f['journal']['path'])
        journal_time = timestamp(journal['read_at'])
        if journal_time < timestamp(launch['started_at']) + dt.timedelta(seconds=12):
            raise ValueError('failure journal retained before full interval')
        state = f.get('observation_state')
        if state == 'unavailable':
            if f['processes'] or 'observation' in f or f.get('observation_unavailable_reason') != 'No successful pre-interval live PID/path/token query was recorded.':
                raise ValueError('contradictory unavailable observation')
            pids = {str(m['pid']) for m in journal['markers']}
            for c in commands:
                if c['argv'][:3] == ['/bin/ps', '-ww', '-p'] and c['argv'][3] in pids and c['exit_code'] == 0 and not c['timed_out']:
                    raise ValueError('successful live query contradicts unavailable observation')
        elif state == 'complete':
            obs = f.get('observation', {})
            if not all(k in obs for k in ('started_at', 'ended_at', 'seconds', 'elapsed_seconds')):
                raise ValueError('observation interval missing')
            start, end = (timestamp(obs[k]) for k in ('started_at', 'ended_at'))
            if obs['seconds'] != 12 or not 12 <= obs['elapsed_seconds'] < 13 or not 12 <= (end-start).total_seconds() < 13:
                raise ValueError('delivery requires full equal 12-second observation')
            if len(f['processes']) != 2 or f['processes'][0]['pid'] != f['processes'][1]['pid']:
                raise ValueError('delivery requires same live PID at both boundaries')
            before, after = [reference(p, 'command') for p in f['processes']]
            if not (timestamp(launch['ended_at']) <= timestamp(before['started_at']) <=
                    timestamp(before['ended_at']) <= start <= end <=
                    timestamp(after['started_at']) <= timestamp(after['ended_at']) <=
                    timestamp(trace['ended_at']) <= timestamp(shutdowns[0]['started_at'])):
                raise ValueError('live stream/PID/observation chronology inconsistent')
            for p in f['processes']:
                c = reference(p, 'command')
                verify_process_text(load(directory / c['output'])['stdout'].strip(), p['pid'], p['executable'], f['token'])
            if journal_time < timestamp(after['ended_at']):
                raise ValueError('journal retained before complete interval')
        else:
            raise ValueError('observation state missing')
        events = json.loads(load(directory / trace['output'])['stdout'])['events']
        if f['delivery_observations'] != delivery_observations(f, events, journal):
            raise ValueError('delivery correlation mutation')


def collector_failure(rec, message):
    rec.setdefault('primary_failure', message)
    rec.setdefault('errors', []).append(message)


def collector_identity(family, runner, root, timeout=8):
    """Match the exact on-disk device against a scoped, live simctl response."""
    path, disk = device(family, root)
    if type(disk.get('state')) is not int or disk['state'] not in (1, 3):
        raise ValueError('dedicated simulator is in a transitional/unknown state')
    text = require_ok(runner.run(['xcrun', 'simctl', 'list', 'devices', OWNED[family][0], '--json'], timeout))
    devices = json.loads(text).get('devices', {})
    candidates = [x for x in devices.get(RUNTIME, []) if x.get('udid') == OWNED[family][0]]
    if len(candidates) != 1:
        raise ValueError('live dedicated simulator identity missing/ambiguous')
    live = candidates[0]
    expected = {'udid': disk['UDID'], 'name': disk['name'], 'deviceTypeIdentifier': disk['deviceType'],
                'isAvailable': True, 'state': {1: 'Shutdown', 3: 'Booted'}[disk['state']]}
    if any(live.get(k) != v for k, v in expected.items()):
        raise ValueError('live/disk dedicated simulator identity mismatch')
    return path, dict(expected, runtime=RUNTIME, state_code=disk['state'], recorded_at=utc())


def native_timeout_reference(help_text):
    grammar = re.search(r'(?m)^.*--timeout <num>\[m\|h\|d\].*$', help_text)
    manual = Path('/usr/share/man/man1/log.1')
    data = manual.read_bytes()
    sentence = 'If minutes, hours, days not specified, seconds will be used.'
    if not grammar or sentence not in data.decode('utf-8'):
        raise ValueError('native timeout unit grammar unresolved; no stream attempted')
    return dict(help_line=grammar[0], manual=str(manual), sha256=digest(data), seconds_evidence=sentence)


def filtered_predicate(nonce):
    # A fixed grammar, never a caller-provided predicate or quoted fragment.
    if not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{32}', nonce):
        raise ValueError('filtered nonce must be 32 lowercase hex characters')
    return f'process == "SpringBoard" AND eventMessage CONTAINS "{FILTERED_UNIT}-{nonce}"'


def filtered_stream_complete(command, udid, nonce):
    expected = ['xcrun', 'simctl', 'spawn', udid, 'log', 'stream', '--style', 'ndjson',
                '--level', 'debug', '--timeout', '5', '--predicate', filtered_predicate(nonce)]
    if command['argv'] != expected or udid not in {v[0] for v in OWNED.values()}:
        raise ValueError('filtered stream command/predicate identity mismatch')
    if (command.get('timeout_seconds') != 12 or command.get('exit_code') != 0
            or command.get('timed_out') is not False
            or command.get('collector_complete') is not True
            or command.get('pipe_complete') is not True
            or command.get('eof_before_group_signal') is not True
            or command.get('output_truncated') is not False or command.get('primary_failure')):
        raise ValueError('filtered stream incomplete: ' + command.get('primary_failure', 'exit/EOF/cap unknown'))
    eof = command.get('pipe_eof', {})
    signals = command.get('signals', [])
    if set(eof) != {'stdout', 'stderr'} or not signals:
        raise ValueError('filtered stream EOF chronology unavailable')
    start = dt.datetime.fromisoformat(command['started_at'])
    end = dt.datetime.fromisoformat(command['ended_at'])
    signal_at = dt.datetime.fromisoformat(signals[0]['at'])
    if not 0 <= (end - start).total_seconds() < 12.5:
        raise ValueError('filtered stream exceeded supervision bound')
    for pipe in ('stdout', 'stderr'):
        count = command.get('observed_bytes', {}).get(pipe)
        full = command.get('raw_' + pipe + '_sha256')
        if (type(count) is not int or not 0 <= count < 8 * 1024 * 1024
                or not isinstance(full, str) or not re.fullmatch('[0-9a-f]{64}', full)
                or full != command.get('retained_' + pipe + '_sha256')
                or not start <= dt.datetime.fromisoformat(eof[pipe]) <= signal_at <= end):
            raise ValueError('filtered stream incomplete/hash/cap/EOF evidence')


def inspect_collector_predecessor():
    """Read-only, exact-byte checks; never relabel the historical capped streams."""
    root = COLLECTOR_PREDECESSOR
    head = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                   text=True, timeout=5).strip()
    if head != COLLECTOR_HEAD:
        raise ValueError('collector predecessor HEAD mismatch')
    hashes = {}
    for name, expected in COLLECTOR_PINS.items():
        actual = digest((root / name).read_bytes())
        if actual != expected:
            raise ValueError('collector predecessor hash mismatch: ' + name)
        hashes[name] = actual
    committed = subprocess.check_output(['git', '-C', str(root), 'show',
                                        head + ':tools/diagnose_ios_scene.py'], timeout=5)
    if digest(committed) != hashes['tools/diagnose_ios_scene.py']:
        raise ValueError('collector predecessor committed source mismatch')
    for area in ('live', 'closeout'):
        directory = root / '.local/ios-collector-006' / area
        obj = load(directory / 'receipt.json')
        for command in obj['commands']:
            name = command['output']
            if not re.fullmatch(r'command-[0-9]{3}\.json', name):
                raise ValueError('unsafe predecessor output path')
            actual = digest((directory / name).read_bytes())
            if actual != command['sha256']:
                raise ValueError('collector predecessor command output mismatch')
            hashes[area + '/' + name] = actual
    delivery = root.parent / 'IOS-SCENE-DELIVERY-005/.local/ios-scene-delivery/receipt.json'
    delivery_hash = digest(delivery.read_bytes())
    if delivery_hash != COLLECTOR_DELIVERY_SHA:
        raise ValueError('historical delivery receipt hash mismatch')
    return dict(head=head, hashes=hashes, delivery_sha256=delivery_hash,
                historical_outcome='native exit/EOF succeeded; output cap failed; blocked unchanged')


def capture_collector(family, runner, root, *, filtered_nonce=None):
    """One system-only stream; never invoke any app/install/build/attach command."""
    start = time.monotonic()
    rec = dict(family=family, udid=OWNED[family][0], started_at=utc(),
               status='blocked', cleanup='not_needed', launch_count=0, stream_count=0)
    changed = False
    stream = None
    initial = None

    def run(argv, timeout):
        # Leave at least 35 seconds for ordered stream finalization and shutdown.
        if time.monotonic() - start + timeout > 80:
            raise ValueError('family operation budget exhausted; cleanup reserved')
        return runner.run(argv, timeout)

    try:
        if filtered_nonce is not None:
            rec['predicate'] = filtered_predicate(filtered_nonce)
        _, initial = collector_identity(family, runner, root)
        rec['initial_identity'] = initial
        if initial['state_code'] != 1:
            raise ValueError('already Booted: service-side stream cleanup cannot preserve the existing session')
        changed = True  # A failed boot may nevertheless have changed state.
        require_ok(run(['xcrun', 'simctl', 'boot', rec['udid']], 20))
        spawn_help, output = run(['xcrun', 'simctl', 'help', 'spawn'], 8)
        rec['spawn_help_command'] = runner.commands.index(spawn_help)
        if spawn_help['timed_out'] or spawn_help['exit_code'] not in (0, 64) or spawn_help.get('collector_complete') is False:
            raise ValueError('simctl spawn help unavailable')
        command, output = run(['xcrun', 'simctl', 'spawn', rec['udid'], 'log', 'help', 'stream'], 8)
        rec['stream_help_command'] = runner.commands.index(command)
        help_text = output['stdout'] + output['stderr']
        if (command['timed_out'] or command['exit_code'] not in (0, 64)
                or command.get('collector_complete') is False
                or not all(x in help_text for x in ('--timeout', '--predicate', 'ndjson', '--level', 'debug'))):
            raise ValueError('native log stream capability unavailable')
        # This local help grammar has NO "s" suffix. The local man page states
        # explicitly that an unsuffixed number is seconds; record both sources.
        rec['native_timeout_reference'] = native_timeout_reference(help_text)
        argv = ['xcrun', 'simctl', 'spawn', rec['udid'], 'log', 'stream', '--style', 'ndjson',
                '--level', 'debug', '--timeout', '5', '--predicate', 'process == "SpringBoard"']
        if filtered_nonce is not None:
            argv[-1] = rec['predicate']
        rec['native_timeout_seconds'] = 5
        rec['stream_count'] = 1
        stream = runner.start_stream(argv, None, timeout=12)
        command, output = runner.finish_stream(stream)
        rec['trace_command'] = runner.commands.index(command)
        rec['native_exit_observed'] = not command['timed_out'] and command['exit_code'] == 0
        rec['stream_elapsed_seconds'] = (dt.datetime.fromisoformat(command['ended_at']) - dt.datetime.fromisoformat(command['started_at'])).total_seconds() if 'ended_at' in command else None
        if filtered_nonce is not None:
            filtered_stream_complete(command, rec['udid'], filtered_nonce)
        if (not rec['native_exit_observed'] or command.get('collector_complete') is not True
                or command.get('eof_before_group_signal') is not True):
            raise ValueError('native stream collector blocked: ' + command.get('primary_failure', 'exit/EOF failed'))
        rec['status'] = 'bounded_system_stream'
        rec['reason'] = 'Native system-process stream exited with complete pipes; no app observation.'
        if filtered_nonce is not None:
            rec['status'] = 'bounded_filtered_system_stream'
            rec['reason'] = 'Only bounded filtered collection established; empty logs prove no event absence, capability or scene acceptance.'
    except (ValueError, OSError, KeyError, TypeError) as exc:
        collector_failure(rec, str(exc))
    finally:
        # Stream supervisor completes (or fails boundedly) before device shutdown.
        if stream is not None and 'trace_command' not in rec:
            try:
                command, _ = runner.finish_stream(stream)
                rec['trace_command'] = runner.commands.index(command)
            except (ValueError, OSError, KeyError) as exc:
                collector_failure(rec, 'stream cleanup: ' + str(exc))
        if changed:
            try:
                command, _ = runner.run(['xcrun', 'simctl', 'shutdown', rec['udid']], 20)
                rec['shutdown_command'] = runner.commands.index(command)
                require_ok((command, _))
                rec['cleanup'] = 'shutdown_returned'
            except (ValueError, OSError, KeyError) as exc:
                rec['cleanup'] = 'failed'
                collector_failure(rec, 'shutdown: ' + str(exc))
        if initial is not None:
            try:
                _, final = collector_identity(family, runner, root)
                rec['final_identity'] = final
                if final['state_code'] != initial['state_code']:
                    raise ValueError('exact initial state not restored')
                if rec['cleanup'] != 'failed':
                    rec['cleanup'] = 'restored' if changed else 'unchanged_verified'
            except (ValueError, OSError, KeyError) as exc:
                rec['cleanup'] = 'failed'
                collector_failure(rec, 'final identity/state: ' + str(exc))
        rec['elapsed_seconds'] = time.monotonic() - start
        rec['ended_at'] = utc()
        if rec['elapsed_seconds'] > 120:
            collector_failure(rec, 'family exceeded 120s total bound')
        if rec.get('primary_failure'):
            rec['status'] = 'blocked'
            rec['reason'] = rec['primary_failure']
        rec['next_gate'] = 'Independent whole-head Astra/medium review; app scene startups remain blocked.'
        if filtered_nonce is not None and rec['status'] == 'blocked':
            rec['next_gate'] += ' Separate collector premise required for: ' + rec['reason'] + '; no live retry authorized.'
    return rec


def collect_collector(output):
    if output.exists() or output.parent.exists():
        raise ValueError('collector requires a fresh private receipt directory')
    if '.local' not in output.parts or output.name != 'receipt.json':
        raise ValueError('collector receipt must be a fresh .local directory/receipt.json')
    output.parent.mkdir(parents=True, mode=0o700)
    runner = Runner(output.parent)
    receipt = dict(schema=1, unit='IOS-COLLECTOR-006', started_at=utc(), commands=runner.commands,
                   runtime='26.5', minimum_target='26.0', launch_count=0, activation_claim=False,
                   source_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=5).strip(),
                   collector_sha256=digest(Path(__file__).read_bytes()), families=[])
    root = Path.home() / 'Library/Developer/CoreSimulator/Devices'
    for family in OWNED:
        receipt['families'].append(capture_collector(family, runner, root))
        write(output, receipt)
    receipt['ended_at'] = utc()
    write(output, receipt)
    return receipt


def collect_filtered_collector(output):
    if output.exists() or output.parent.exists():
        raise ValueError('filtered collector requires a fresh private receipt directory')
    if '.local' not in output.parts or output.name != 'receipt.json':
        raise ValueError('filtered collector receipt must be under .local as receipt.json')
    predecessor = inspect_collector_predecessor()  # Before boot or any simulator command.
    now = dt.datetime.now(dt.timezone.utc)
    if now >= dt.datetime(2026, 10, 18, 14, 30, tzinfo=dt.timezone.utc):
        raise ValueError('dispatch cutoff reached; no live attempt')
    output.parent.mkdir(parents=True, mode=0o700)
    source = Path(__file__).read_bytes()
    snapshot = output.parent / 'collector-source.py'
    snapshot.write_bytes(source)
    snapshot.chmod(0o600)
    runner = Runner(output.parent)
    nonce = secrets.token_hex(16)
    receipt = dict(schema=1, unit=FILTERED_UNIT, started_at=utc(), commands=runner.commands,
                   runtime='26.5', minimum_target='26.0', launch_count=0, activation_claim=False,
                   source_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True, timeout=5).strip(),
                   collector_sha256=digest(source), nonce=nonce, predicate=filtered_predicate(nonce),
                   predecessor=predecessor, families=[])
    write(output, receipt)
    root = Path.home() / 'Library/Developer/CoreSimulator/Devices'
    for family in OWNED:
        receipt['families'].append(capture_collector(family, runner, root, filtered_nonce=nonce))
        write(output, receipt)
    receipt['ended_at'] = utc()
    receipt['predecessor_after'] = inspect_collector_predecessor()
    write(output, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--collect-collector', type=Path)
    group.add_argument('--collect-filtered-collector', type=Path)
    group.add_argument('--collect', type=Path)
    group.add_argument('--collect-delivery', type=Path)
    group.add_argument('--verify-saved', type=Path)
    group.add_argument('--trace-retained', type=Path)
    group.add_argument('--retain-journals', type=Path)
    args = parser.parse_args()
    try:
        if args.retain_journals:
            obj = verify_saved(args.retain_journals)
            retain_journals(obj, args.retain_journals.parent)
            write(args.retain_journals, obj)
            print('Retained token-correlated owned journals; no device changes or launches.')
            return 0
        if args.verify_saved:
            obj = verify_saved(args.verify_saved)
            print('VALID OFFLINE RECEIPTS; activation not established; ' + '; '.join(
                f'{x["family"]}: {x["status"]}, request=unknown, ack=unknown, delegate={x["scene_delegate"]}' for x in obj['families']))
            return 0
        if args.collect_filtered_collector:
            obj = collect_filtered_collector(args.collect_filtered_collector)
        elif args.collect_collector:
            obj = collect_collector(args.collect_collector)
        elif args.collect_delivery:
            obj = collect_delivery(args.collect_delivery)
        elif args.trace_retained:
            obj = trace_retained(args.trace_retained)
        else:
            obj = collect(args.collect)
        print(json.dumps({x['family']: {'status': x['status'], 'reason': x['reason'], 'cleanup': x['cleanup']} for x in obj['families']}))
        return 2  # Trace prerequisite stays blocked until request/ack independently established.
    except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
        print('INVALID/BLOCKED: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
