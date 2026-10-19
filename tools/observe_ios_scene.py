#!/usr/bin/env python3
"""One-shot pinned-app observation. Evidence integrity is not scene acceptance."""
import argparse
import datetime as dt
import json
from pathlib import Path
import plistlib
import re
import secrets
import subprocess
import time

import diagnose_ios_scene as d

UNIT = 'IOS-SCENE-OBSERVER-008'
STORE = d.TRANSPORT.parent.parent.parent.parent
FILTERED = STORE / 'worktrees/IOS-COLLECTOR-FILTERED-007'
REVIEWED = 'c9e49b5beb856cabb11277c7fab4421e7ba94bf2'
LANDED = '52369d223a9dd08bc5d571dde8aee2117d990e74'
REVIEW = 'f243035d3e9e49c9931a0ef8324d8520'
FILTERED_SHA = '23ea40f1833182ccb7fd7a8062251d73041614b8d1e9beb692e18596b7cbe170'
HELPER_SHA = 'a6bd53f7ce07214a058d50ec08c1c6541b0e2c992c91ff16e6d34297c6500db7'
PREDICATE = ('process == "ACSHost" OR ((process == "SpringBoard" OR process == "runningboardd" '
             'OR process == "frontboardd") AND eventMessage CONTAINS "local.acs.ios-host-002")')
CAP = 8 * 1024 * 1024


def git(*args):
    return subprocess.check_output(['git', *args], timeout=5)


def patch_identity(base, head):
    diff = git('-c', 'core.fsmonitor=false', 'diff', '--binary', '--full-index', '--no-ext-diff',
               '--no-renames', '--unified=0', base, head).decode()
    return d.digest('\n'.join(s for s in diff.split('\n')
                              if not s.startswith('index ') and not s.startswith('@@ ')).encode())


def inspect_inputs():
    """Read predecessor bytes, review identity, ancestry and all output receipts."""
    review_path = STORE / 'reports' / (REVIEW + '.review.json')
    landing_path = STORE / 'reports/0df1846effd04765a7154bf50e2cf557.land-attempt.json'
    review, landing = d.load(review_path), d.load(landing_path)
    if (review['head'] != REVIEWED or review['verdict'] != 'pass'
            or review['model'] != 'gpt-6-astra' or review['effort'] != 'medium'
            or landing['reviewed_head'] != REVIEWED or landing['rebased_head'] != LANDED):
        raise ValueError('accepted collector review/landing identity mismatch')
    git('merge-base', '--is-ancestor', LANDED, 'HEAD')
    git('merge-base', '--is-ancestor', LANDED, 'main')
    actual_head = git('-C', str(FILTERED), 'rev-parse', 'HEAD').decode().strip()
    if actual_head not in (REVIEWED, LANDED):
        raise ValueError('filtered worktree head changed')
    patch = patch_identity('2b9b3dccbd19923d5846d8d08db9a9c1f3140e89', REVIEWED)
    if patch != review['patch'] or patch != landing['patch'] or patch != patch_identity(landing['base'], LANDED):
        raise ValueError('normalized reviewed/landed patch mismatch')
    directory = FILTERED / '.local/ios-collector-filtered-007/live'
    hashes = {str(review_path): d.digest(review_path.read_bytes()),
              str(landing_path): d.digest(landing_path.read_bytes())}
    for label, data in [('reviewed helper', git('show', REVIEWED + ':tools/diagnose_ios_scene.py')),
                        ('landed helper', git('show', LANDED + ':tools/diagnose_ios_scene.py')),
                        ('predecessor helper', (FILTERED / 'tools/diagnose_ios_scene.py').read_bytes()),
                        ('executed helper', (directory / 'collector-source.py').read_bytes())]:
        if d.digest(data) != HELPER_SHA:
            raise ValueError(label + ' hash mismatch')
        hashes[label] = d.digest(data)
    prior = directory / 'receipt.json'
    if d.digest(prior.read_bytes()) != FILTERED_SHA:
        raise ValueError('filtered receipt hash mismatch')
    obj = d.load(prior)
    for command in obj['commands']:
        name = command['output']
        if not re.fullmatch(r'command-[0-9]{3}\.json', name):
            raise ValueError('unsafe predecessor output path')
        data = (directory / name).read_bytes()
        if d.digest(data) != command['sha256']:
            raise ValueError('filtered command hash mismatch')
        hashes[name] = d.digest(data)
    for family in obj['families']:
        d.filtered_stream_complete(obj['commands'][family['trace_command']], family['udid'], obj['nonce'])
        if family['cleanup'] != 'restored' or family['final_identity']['state_code'] != 1:
            raise ValueError('predecessor restoration mismatch')
    older = d.inspect_collector_predecessor()
    reference = d.inspect_previous()
    for name, expected in d.SOURCE_SHA256.items():
        if d.digest(git('show', d.SOURCE_HEAD + ':' + name)) != expected:
            raise ValueError('preserved experiment source mismatch: ' + name)
    delivery = FILTERED.parent / 'IOS-SCENE-DELIVERY-005/.local/ios-scene-delivery/receipt.json'
    if d.digest(delivery.read_bytes()) != d.COLLECTOR_DELIVERY_SHA:
        raise ValueError('historical delivery changed')
    d.verify_saved(delivery)
    d.verify_saved(d.TRANSPORT / 'receipt.json')
    return dict(reviewed_head=REVIEWED, landed_head=LANDED, review=REVIEW, patch=patch,
                filtered_receipt_sha256=FILTERED_SHA, hashes=hashes, older=older,
                reference=reference, delivery_sha256=d.COLLECTOR_DELIVERY_SHA)


def stream_args(udid):
    if udid not in {v[0] for v in d.OWNED.values()}:
        raise ValueError('foreign device')
    return ['xcrun', 'simctl', 'spawn', udid, 'log', 'stream', '--style', 'ndjson',
            '--level', 'debug', '--timeout', '25', '--predicate', PREDICATE]


def redact(text):
    text = re.sub(r'[\w.+-]+@[\w.-]+', '[redacted-email]', text)
    text = re.sub(r'\b(?:com|net|org|local)\.[A-Za-z0-9_.-]+',
                  lambda m: m[0] if m[0] == d.BUNDLE or m[0].startswith(d.BUNDLE + '-')
                  or m[0].startswith('com.apple.') else '[redacted-bundle]', text)
    # No unrelated filesystem paths survive in message bodies.
    return re.sub(r'/(?:Users|private|var|Applications|System|Library)/[^\s<>"\]]+', '[redacted-path]', text)


def filter_events(text, executable):
    events, rejected = [], 0
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            rejected += bool(line.strip())
            continue
        if not isinstance(item, dict) or not isinstance(item.get('eventMessage'), str):
            continue
        path, message = item.get('processImagePath', ''), item['eventMessage']
        if path != str(executable) and not (Path(path).name in ('SpringBoard', 'runningboardd', 'frontboardd')
                                           and d.BUNDLE in message):
            continue
        safe = {k: item[k] for k in ('timestamp', 'processID') if k in item}
        safe['processImagePath'] = path if path == str(executable) else Path(path).name
        for key in ('subsystem', 'category', 'eventMessage'):
            if isinstance(item.get(key), str):
                safe[key] = redact(item[key])
        events.append(safe)
    return json.dumps(dict(events=events, discarded_non_json_lines=rejected))


class Runner(d.Runner):
    def finish(self, handle, transform=None):
        rec, output = super().finish(handle, transform)
        if transform is not None:
            # Hashes inherited from the supervisor describe original observed bytes
            # and original retained prefixes, not this redacted representation.
            output['stderr'] = '\n'.join(line if line == 'getpwuid_r did not find a match for uid 501'
                                         else '[redacted diagnostic]' for line in output['stderr'].splitlines())
            for pipe in ('stdout', 'stderr'):
                if len(output[pipe].encode()) >= CAP:
                    self.failure(rec, 'filtered representation exceeds output cap')
                    output[pipe] = ''
            d.write(self.directory / rec['output'], output)
            rec['sha256'] = d.digest((self.directory / rec['output']).read_bytes())
            rec['representation'] = 'scoped redacted events; raw/prefix hashes precede redaction'
        return rec, output


def complete(command, udid):
    if command['argv'] != stream_args(udid) or command['timeout_seconds'] != 30:
        raise ValueError('observer stream command mismatch')
    if (command.get('exit_code') != 0 or command.get('timed_out') is not False
            or command.get('collector_complete') is not True or command.get('pipe_complete') is not True
            or command.get('eof_before_group_signal') is not True
            or command.get('output_truncated') is not False or command.get('primary_failure')):
        raise ValueError('observer stream incomplete: ' + command.get('primary_failure', 'exit/EOF uncertainty'))
    start, end = (dt.datetime.fromisoformat(command[k]) for k in ('started_at', 'ended_at'))
    if not 0 <= (end-start).total_seconds() <= 30:
        raise ValueError('observer stream exceeded 30s')
    signal_at = dt.datetime.fromisoformat(command['signals'][0]['at'])
    for pipe in ('stdout', 'stderr'):
        count = command.get('observed_bytes', {}).get(pipe)
        full = command.get('raw_' + pipe + '_sha256')
        if (type(count) is not int or not 0 <= count < CAP or not isinstance(full, str)
                or not re.fullmatch('[0-9a-f]{64}', full)
                or full != command.get('retained_' + pipe + '_sha256')
                or not start <= dt.datetime.fromisoformat(command['pipe_eof'][pipe]) <= signal_at <= end):
            raise ValueError('observer stream cap/hash/EOF mismatch')


def journals(container, token):
    marker = container / 'Documents/startup.jsonl'
    if marker.is_symlink() or (marker.exists() and marker.stat().st_size >= CAP):
        raise ValueError('journal size/path unavailable')
    return [item for line in marker.read_text().splitlines() if (item := json.loads(line)).get('evidence_run') == token] if marker.exists() else []


def capture(family, runner, reference, root, sleep=time.sleep, clock=time.monotonic):
    started = clock()
    rec = dict(family=family, udid=d.OWNED[family][0], bundle=d.BUNDLE, started_at=d.utc(),
               status='blocked', cleanup='not_needed', stream_count=0, launch_count=0,
               processes=[], markers=[], system_request='unknown', system_registration='unknown',
               app_delivery='unknown', app_acknowledgement='unknown', scene_delegate='unknown')
    initial, stream, container = None, None, None
    changed = False
    finalized = False

    def run(argv, timeout):
        if clock() - started + timeout > 80:
            raise ValueError('family budget exhausted; cleanup reserved')
        return runner.run(argv, timeout)

    def check_stream():
        if stream is not None:
            command = stream['rec']
            if command.get('primary_failure'):
                raise ValueError('stream failed during observation: ' + command['primary_failure'])
            if 'ended_at' in command:
                raise ValueError('stream ended before app observation completed')

    def pause(seconds):
        end = clock() + seconds
        while clock() < end:
            check_stream()
            sleep(min(0.05, end-clock()))

    try:
        path, initial = d.collector_identity(family, runner, root)
        rec['initial_identity'] = initial
        if initial['state_code'] != 1:
            raise ValueError('already Booted; family blocked without changes')
        apps = [p.parent for p in (path / 'data/Containers/Bundle/Application').glob('*/ACSHost.app/Info.plist')
                if plistlib.loads(p.read_bytes()).get('CFBundleIdentifier') == d.BUNDLE]
        if len(apps) != 1:
            raise ValueError('exactly one pinned installed app required')
        app = apps[0]
        rec.update(app=str(app), app_files=d.app_identity(app))
        if rec['app_files'] != reference['app_files']:
            raise ValueError('installed full app hashes differ from preserved experiment')
        d.require_ok(run(['codesign', '--verify', '--strict', '--verbose=2', str(app)], 8))
        changed = True
        d.require_ok(run(['xcrun', 'simctl', 'boot', rec['udid']], 20))
        command, output = run(['xcrun', 'simctl', 'spawn', rec['udid'], 'log', 'help', 'stream'], 8)
        rec['stream_help_command'] = runner.commands.index(command)
        help_text = output['stdout'] + output['stderr']
        if (command['exit_code'] not in (0, 64) or command['timed_out']
                or command.get('collector_complete') is False
                or not all(x in help_text for x in ('--predicate', '--level', 'debug', '--timeout', 'ndjson'))):
            raise ValueError('native stream help/capability unavailable')
        rec['native_timeout_reference'] = d.native_timeout_reference(help_text)
        container = Path(d.require_ok(run(['xcrun', 'simctl', 'get_app_container', rec['udid'], d.BUNDLE, 'data'], 8))).resolve()
        if not container.is_relative_to((path / 'data/Containers/Data/Application').resolve()):
            raise ValueError('owned data container escaped device')
        if plistlib.loads((container / '.com.apple.mobile_container_manager.metadata.plist').read_bytes()).get('MCMMetadataIdentifier') != d.BUNDLE:
            raise ValueError('data container bundle mismatch')
        rec['token'] = UNIT + '-' + family + '-' + secrets.token_hex(16)
        rec['stream_count'] = 1
        stream = runner.start_stream(stream_args(rec['udid']), lambda text: filter_events(text, app / 'ACSHost'), timeout=30)
        pause(0.25)  # No listener-readiness guarantee is claimed.
        rec['launch_count'] = 1
        launch, _ = run(['xcrun', 'simctl', 'launch', rec['udid'], d.BUNDLE, '--evidence-run', rec['token']], 8)
        rec['launch_command'] = runner.commands.index(launch)
        d.require_ok((launch, _))  # A timed-out RPC is a live failure: no further observation.
        deadline = clock() + 2
        while True:
            check_stream()
            rec['markers'] = journals(container, rec['token'])
            if rec['markers'] or clock() >= deadline:
                break
            pause(0.05)
        pids = {m['pid'] for m in rec['markers']}
        if len(pids) != 1 or type(next(iter(pids))) is not int or next(iter(pids)) <= 1:
            raise ValueError('unique token-correlated live journal PID unavailable')
        pid = pids.pop()

        def identity():
            check_stream()
            command, output = run(['/bin/ps', '-ww', '-p', str(pid), '-o', 'pid=,args='], 5)
            d.verify_process_text(d.require_ok((command, output)), pid, str(app / 'ACSHost'), rec['token'])
            rec['processes'].append(dict(pid=pid, executable=str(app / 'ACSHost'), token=rec['token'],
                                         command=runner.commands.index(command)))
            check_stream()

        identity()
        rec['observation'] = dict(started_at=d.utc(), seconds=8)
        window = clock()
        pause(8)
        rec['observation'].update(ended_at=d.utc(), elapsed_seconds=clock()-window)
        identity()
        rec['observation_state'] = 'complete'
    except (ValueError, OSError, KeyError, TypeError) as exc:
        d.collector_failure(rec, str(exc))
    finally:
        if stream is not None:
            try:
                command, output = runner.finish_stream(stream)
                finalized = True
                rec['trace_command'] = runner.commands.index(command)
                complete(command, rec['udid'])
                rec['stream_complete'] = True
                events = json.loads(output['stdout'])['events']
                rec['trace_events'] = len(events)
                rec['system_candidates'] = d.trace_observations(events)
                for key, candidate in [('system_request', 'open_request_received'), ('system_registration', 'server_scene_registration')]:
                    if rec['system_candidates'][candidate]:
                        rec[key] = 'observed'
                rec['app_event_count'] = sum(e.get('processImagePath') == rec['app'] + '/ACSHost'
                                             and e.get('processID') in {p['pid'] for p in rec['processes']} for e in events)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                d.collector_failure(rec, 'stream finalization: ' + str(exc))
        rec['stream_finalization_returned'] = finalized
        if rec['launch_count'] and container is not None:
            try:
                # Post-stream read also retains delay10 files without extending the
                # measured app interval or treating journals as live identity.
                d.retain_journals({'families': [rec], 'commands': runner.commands}, runner.directory)
                rec['journal_after_observation'] = d.utc()
                if any(m.get('stage') == 'scene-connect' for m in rec['markers']):
                    rec['scene_delegate'] = 'observed token-correlated scene-connect journal'
            except (ValueError, OSError, KeyError, TypeError) as exc:
                d.collector_failure(rec, 'journal retention: ' + str(exc))
        if changed:
            try:
                command, output = runner.run(['xcrun', 'simctl', 'shutdown', rec['udid']], 20)
                rec['shutdown_command'] = runner.commands.index(command)
                d.require_ok((command, output))
                rec['cleanup'] = 'shutdown_returned'
            except (ValueError, OSError, KeyError) as exc:
                rec['cleanup'] = 'failed'
                d.collector_failure(rec, 'shutdown: ' + str(exc))
        if initial is not None:
            try:
                _, final = d.collector_identity(family, runner, root)
                rec['final_identity'] = final
                if final['state_code'] != initial['state_code']:
                    raise ValueError('initial state not restored')
                if rec['cleanup'] != 'failed':
                    rec['cleanup'] = 'restored' if changed else 'unchanged_verified'
            except (ValueError, OSError, KeyError) as exc:
                rec['cleanup'] = 'failed'
                d.collector_failure(rec, 'final identity: ' + str(exc))
        if 'app' in rec:
            try:
                rec['final_app_files'] = d.app_identity(Path(rec['app']))
                if rec['final_app_files'] != reference['app_files']:
                    raise ValueError('installed app changed')
            except (ValueError, OSError) as exc:
                d.collector_failure(rec, 'final app hashes: ' + str(exc))
        rec['elapsed_seconds'] = clock()-started
        rec['ended_at'] = d.utc()
        if rec['elapsed_seconds'] > 120:
            d.collector_failure(rec, 'family exceeded 120 seconds')
        rec['observation_state'] = rec.get('observation_state', 'unavailable')
        rec['reason'] = rec.get('primary_failure', 'Bounded app stream and measured identity interval; scene transaction delivery/ack visibility missing.')
        rec['next_blocker'] = ('No retry authorized. ' + rec['reason'] if rec.get('primary_failure') else
                               'Pinned app has no transaction receive/ack observer. Separately scope observer permission/symbol prerequisites; no lifecycle defect established.')
        rec['descendant_uncertainty'] = 'Host escaped descendants unknown; exact simulator shutdown is separate evidence.'
    return rec


def collect(output):
    output = output.resolve()
    expected = Path.cwd() / '.local/ios-scene-observer-008/live/receipt.json'
    if output != expected or output.parent.exists():
        raise ValueError('requires fresh in-worktree .local/ios-scene-observer-008/live/receipt.json')
    output.parent.mkdir(parents=True, mode=0o700)
    receipt = dict(schema=1, unit=UNIT, started_at=d.utc(), families=[], commands=[],
                   activation_claim=False, runtime='26.5', minimum_target='26.0')
    d.write(output, receipt)
    try:
        receipt['inputs_before'] = inspect_inputs()
        if dt.datetime.now(dt.timezone.utc) >= dt.datetime(2026, 10, 18, 14, 30, tzinfo=dt.timezone.utc):
            raise ValueError('dispatch cutoff reached')
        runner = Runner(output.parent)
        receipt['commands'] = runner.commands
        receipt['source_head'] = git('rev-parse', 'HEAD').decode().strip()
        for name, source in [('observer-source.py', Path(__file__)), ('helper-source.py', Path(d.__file__))]:
            data = source.read_bytes()
            (output.parent / name).write_bytes(data)
            (output.parent / name).chmod(0o600)
            receipt[name + '_sha256'] = d.digest(data)
        reference = receipt['inputs_before']['reference']
        d.require_ok(runner.run(['codesign', '--verify', '--strict', '--verbose=2', reference['app']], 8))
        for family in d.OWNED:
            receipt['families'].append(capture(family, runner, reference, Path.home() / 'Library/Developer/CoreSimulator/Devices'))
            d.write(output, receipt)
        receipt['inputs_after'] = inspect_inputs()
        if receipt['inputs_after'] != receipt['inputs_before']:
            raise ValueError('predecessor changed during observation')
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        receipt['primary_failure'] = str(exc)
    receipt['ended_at'] = d.utc()
    d.write(output, receipt)
    return receipt


def verify_saved(path):
    """Offline integrity/chronology check of a completed two-family observation.

    This deliberately verifies blocked observations; it never accepts startup.
    No subprocess or simulator filesystem is used here.
    """
    obj = d.load(path)
    if (obj.get('schema') != 1 or obj.get('unit') != UNIT or obj.get('activation_claim') is not False
            or obj.get('primary_failure') or obj.get('inputs_before') != obj.get('inputs_after')):
        raise ValueError('observer receipt identity/predecessor mismatch')
    inputs = obj['inputs_before']
    if (inputs['reviewed_head'] != REVIEWED or inputs['landed_head'] != LANDED
            or inputs['review'] != REVIEW or inputs['filtered_receipt_sha256'] != FILTERED_SHA
            or inputs['delivery_sha256'] != d.COLLECTOR_DELIVERY_SHA
            or inputs['patch'] != '10beb5f0d42258e1c3cdc664165b8fff033fea667fb52679481b5a70a7a11c62'):
        raise ValueError('saved predecessor identities mismatch')
    reference = inputs['reference']
    if reference['app_files'] != d.APP_FILES or reference['source_head'] != d.SOURCE_HEAD:
        raise ValueError('saved preserved app mismatch')
    d.validate_hash_map(reference['source_sha256'], d.SOURCE_SHA256, 'source_sha256')
    d.validate_hash_map(reference['inspected'], d.INSPECTED_SHA256, 'inspected')
    for name in ('observer-source.py', 'helper-source.py'):
        if d.digest((path.parent / name).read_bytes()) != obj[name + '_sha256']:
            raise ValueError('executed source snapshot mismatch')
    if obj['helper-source.py_sha256'] != HELPER_SHA:
        raise ValueError('saved helper mismatch')
    commands = obj['commands']
    for index, command in enumerate(commands):
        if command['output'] != f'command-{index+1:03}.json':
            raise ValueError('saved command output path mismatch')
        if d.digest((path.parent / command['output']).read_bytes()) != command['sha256']:
            raise ValueError('saved command output hash mismatch')
        if not 0 < command['timeout_seconds'] <= 30:
            raise ValueError('saved command deadline mismatch')
        start, end = (dt.datetime.fromisoformat(command[k]) for k in ('started_at', 'ended_at'))
        if not 0 <= (end-start).total_seconds() <= 30:
            raise ValueError('saved command elapsed bound mismatch')
    families = obj['families']
    if [f['family'] for f in families] != list(d.OWNED):
        raise ValueError('saved family set mismatch')
    allowed = {('codesign', '--verify', '--strict', '--verbose=2', reference['app'])}
    for family in families:
        name = family['family']
        udid, kind = d.OWNED[name]
        if family['udid'] != udid or family['bundle'] != d.BUNDLE:
            raise ValueError('saved family identity mismatch')
        if family['status'] != 'blocked' or family['app_delivery'] != 'unknown' or family['app_acknowledgement'] != 'unknown':
            raise ValueError('unsupported app transaction claim')
        expected = dict(udid=udid, name=f'ACS IOS-HOST-002 {name}', deviceTypeIdentifier=kind,
                        runtime=d.RUNTIME, isAvailable=True, state='Shutdown', state_code=1)
        for key in ('initial_identity', 'final_identity'):
            if any(family[key].get(k) != v for k, v in expected.items()):
                raise ValueError('saved exact Shutdown identity mismatch')
        if family['app_files'] != d.APP_FILES or family['final_app_files'] != d.APP_FILES:
            raise ValueError('saved installed app mismatch')
        if family['cleanup'] != 'restored' or not 0 <= family['elapsed_seconds'] <= 120:
            raise ValueError('saved family cleanup/bound mismatch')
        token = family['token']
        if not re.fullmatch(UNIT + '-' + name + '-[0-9a-f]{32}', token):
            raise ValueError('saved token mismatch')
        launch_argv = ['xcrun', 'simctl', 'launch', udid, d.BUNDLE, '--evidence-run', token]
        for key in ('trace_command', 'launch_command', 'stream_help_command', 'shutdown_command'):
            if type(family[key]) is not int or not 0 <= family[key] < len(commands):
                raise ValueError('saved command reference mismatch')
        stream = commands[family['trace_command']]
        launch = commands[family['launch_command']]
        help_command = commands[family['stream_help_command']]
        shutdown = commands[family['shutdown_command']]
        boot = [c for c in commands if c['argv'] == ['xcrun', 'simctl', 'boot', udid]]
        signature = [c for c in commands if c['argv'] == ['codesign', '--verify', '--strict', '--verbose=2', family['app']]]
        if (len(boot) != 1 or len(signature) != 1
                or any(c['exit_code'] != 0 or c['timed_out'] for c in boot + signature)
                or not family['initial_identity']['recorded_at'] <= signature[0]['started_at']
                <= signature[0]['ended_at'] <= boot[0]['started_at'] <= boot[0]['ended_at'] <= help_command['started_at']):
            raise ValueError('saved installed signature/boot prerequisite mismatch')
        complete(stream, udid)
        if (family['stream_count'] != 1 or family['launch_count'] != 1 or launch['argv'] != launch_argv
                or launch['timeout_seconds'] != 8
                or help_command['argv'] != ['xcrun', 'simctl', 'spawn', udid, 'log', 'help', 'stream']
                or help_command['exit_code'] not in (0, 64) or help_command['timed_out']
                or shutdown['argv'] != ['xcrun', 'simctl', 'shutdown', udid]
                or shutdown['exit_code'] != 0 or shutdown['timed_out']):
            raise ValueError('saved help/launch/shutdown command mismatch')
        help_output = d.load(path.parent / help_command['output'])
        if not all(x in help_output['stdout'] + help_output['stderr']
                   for x in ('--timeout', '--predicate', 'ndjson', '--level', 'debug')):
            raise ValueError('saved native help capabilities missing')
        if not (help_command['ended_at'] <= stream['started_at'] <= launch['started_at']
                <= launch['ended_at'] <= stream['ended_at'] <= shutdown['started_at']
                <= shutdown['ended_at'] <= family['final_identity']['recorded_at']):
            raise ValueError('saved stream/launch/shutdown chronology mismatch')
        if launch['exit_code'] != 0 or launch['timed_out']:
            if family['observation_state'] != 'unavailable' or family['processes'] or family.get('observation') or not family.get('primary_failure'):
                raise ValueError('failed launch cannot establish app observation')
        else:
            window = family['observation']
            if (family['observation_state'] != 'complete' or len(family['processes']) != 2
                    or window['seconds'] != 8 or window['elapsed_seconds'] < 8
                    or (dt.datetime.fromisoformat(window['ended_at']) - dt.datetime.fromisoformat(window['started_at'])).total_seconds() < 8
                    or not launch['ended_at'] <= window['started_at'] <= window['ended_at'] <= stream['ended_at']):
                raise ValueError('saved app window unavailable')
            if family['processes'][0]['pid'] != family['processes'][1]['pid']:
                raise ValueError('saved app PID changed')
            for process in family['processes']:
                command = commands[process['command']]
                argv = ['/bin/ps', '-ww', '-p', str(process['pid']), '-o', 'pid=,args=']
                if command['argv'] != argv or command['exit_code'] != 0 or command['timed_out']:
                    raise ValueError('saved live app identity command mismatch')
                d.verify_process_text(d.load(path.parent / command['output'])['stdout'].strip(), process['pid'], family['app'] + '/ACSHost', token)
                allowed.add(tuple(argv))
            if not (commands[family['processes'][0]['command']]['ended_at'] <= window['started_at']
                    and window['ended_at'] <= commands[family['processes'][1]['command']]['started_at']):
                raise ValueError('saved app identity does not enclose window')
        journal_path = family['journal']['path']
        if journal_path != name + '-journal.json' or d.digest((path.parent / journal_path).read_bytes()) != family['journal']['sha256']:
            raise ValueError('saved journal path/hash mismatch')
        journal = d.load(path.parent / journal_path)
        if journal['token'] != token or journal['udid'] != udid or journal['markers'] != family['markers']:
            raise ValueError('saved journal correlation mismatch')
        if journal['read_at'] < stream['ended_at'] or journal['read_at'] > shutdown['started_at']:
            raise ValueError('saved journal chronology mismatch')
        for marker in journal['markers']:
            if marker['evidence_run'] != token:
                raise ValueError('foreign journal token')
        if any(a['value'].get('evidence_run') != token for a in journal['activation']):
            raise ValueError('foreign activation token')
        delegate = any(m.get('stage') == 'scene-connect' for m in journal['markers'])
        if family['scene_delegate'] != ('observed token-correlated scene-connect journal' if delegate else 'unknown'):
            raise ValueError('unsupported delegate claim')
        events = json.loads(d.load(path.parent / stream['output'])['stdout'])['events']
        refiltered = json.loads(filter_events('\n'.join(json.dumps(e) for e in events), Path(family['app']) / 'ACSHost'))['events']
        if refiltered != events:
            raise ValueError('saved unscoped/unredacted event')
        if family['system_candidates'] != d.trace_observations(events):
            raise ValueError('saved system candidates mismatch')
        for key, candidate in [('system_request', 'open_request_received'), ('system_registration', 'server_scene_registration')]:
            if family[key] != ('observed' if family['system_candidates'][candidate] else 'unknown'):
                raise ValueError('unsupported system observation claim')
        for argv in (stream_args(udid), launch_argv,
                     ['codesign', '--verify', '--strict', '--verbose=2', family['app']],
                     ['xcrun', 'simctl', 'list', 'devices', udid, '--json'],
                     ['xcrun', 'simctl', 'boot', udid],
                     ['xcrun', 'simctl', 'shutdown', udid],
                     ['xcrun', 'simctl', 'get_app_container', udid, d.BUNDLE, 'data'],
                     ['xcrun', 'simctl', 'spawn', udid, 'log', 'help', 'stream']):
            allowed.add(tuple(argv))
        if sum(c['argv'] == stream_args(udid) for c in commands) != 1 or sum(c['argv'] == launch_argv for c in commands) != 1:
            raise ValueError('saved repeated stream/launch')
    if any(tuple(c['argv']) not in allowed for c in commands):
        raise ValueError('saved unrelated command')
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--collect', type=Path)
    mode.add_argument('--verify-saved', type=Path)
    args = parser.parse_args()
    if args.verify_saved:
        verify_saved(args.verify_saved)
        print('Verified retained observer evidence; startup remains unaccepted.')
        return 0
    receipt = collect(args.collect)
    print(json.dumps(dict(unit=UNIT, families=[dict(family=f['family'], reason=f['reason'], cleanup=f['cleanup'])
                                              for f in receipt['families']], primary_failure=receipt.get('primary_failure'))))
    return 2  # Diagnostic completion never establishes startup acceptance.


if __name__ == '__main__':
    raise SystemExit(main())
