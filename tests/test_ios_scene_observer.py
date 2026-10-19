"""Offline tests only: fake commands and local subprocesses, never simulators."""
import copy
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import observe_ios_scene as o
d = o.d


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def stream_record(udid):
    return dict(argv=o.stream_args(udid), timeout_seconds=30, exit_code=0,
                timed_out=False, collector_complete=True, pipe_complete=True,
                eof_before_group_signal=True, output_truncated=False,
                started_at='2026-10-18T11:00:00+00:00', ended_at='2026-10-18T11:00:25+00:00',
                signals=[dict(at='2026-10-18T11:00:25+00:00')],
                pipe_eof={p: '2026-10-18T11:00:25+00:00' for p in ('stdout', 'stderr')},
                observed_bytes={'stdout': 0, 'stderr': 0},
                **{prefix + p + '_sha256': d.digest(b'') for p in ('stdout', 'stderr')
                   for prefix in ('raw_', 'retained_')})


class FakeRunner:
    """Stateful command transport; every launch and cleanup is inspectable."""
    def __init__(self, directory, container, executable, fault=None):
        self.directory, self.container, self.executable = directory, container, executable
        self.commands = []
        self.fault = fault
        self.token = None

    def command(self, argv, timeout, stdout='', code=0):
        rec = dict(argv=argv, timeout_seconds=timeout, exit_code=code, timed_out=False,
                   started_at=d.utc(), ended_at=d.utc(), collector_complete=True,
                   output=f'command-{len(self.commands)+1:03}.json')
        self.commands.append(rec)
        output = {'stdout': stdout, 'stderr': ''}
        d.write(self.directory / rec['output'], output)
        rec['sha256'] = d.digest((self.directory / rec['output']).read_bytes())
        return rec, output

    def run(self, argv, timeout):
        if argv[0] == 'codesign' or argv[2] in ('boot', 'shutdown'):
            result = self.command(argv, timeout)
            if self.fault == 'boot' and argv[2] == 'boot':
                result[0]['exit_code'] = 1
            if self.fault == 'shutdown' and argv[2] == 'shutdown':
                result[0]['exit_code'] = 1
            return result
        if argv[0] == '/bin/ps':
            text = f'123 {self.executable} --evidence-run {self.token}'
            if self.fault == 'identity':
                text += ' --unowned'
            return self.command(argv, timeout, text)
        if argv[2] == 'get_app_container':
            return self.command(argv, timeout, str(self.container))
        if argv[2] == 'spawn':
            return self.command(argv, timeout, '--timeout <num>[m|h|d] --predicate --level debug ndjson',
                                1 if self.fault == 'help' else 64)
        if argv[2] == 'launch':
            self.token = argv[-1]
            documents = self.container / 'Documents'
            documents.mkdir(exist_ok=True)
            if self.fault != 'journal':
                (documents / 'startup.jsonl').write_text(json.dumps(dict(evidence_run=self.token, pid=123, stage='main')) + '\n')
            result = self.command(argv, timeout)
            if self.fault == 'launch':
                result[0].update(timed_out=True, exit_code=-9)
            return result
        raise AssertionError(argv)

    def start_stream(self, argv, transform, timeout):
        rec, output = self.command(argv, timeout)
        rec.pop('ended_at')
        self.transform = transform
        return {'rec': rec}

    def finish_stream(self, stream):
        if self.fault == 'finalize':
            raise ValueError('fake finalizer failure')
        command = stream['rec']
        command.update(stream_record(command['argv'][3]))
        if self.fault == 'stream':
            command.update(exit_code=-9, timed_out=True, primary_failure='first stream error')
        output = {'stdout': self.transform(''), 'stderr': ''}
        d.write(self.directory / command['output'], output)
        command['sha256'] = d.digest((self.directory / command['output']).read_bytes())
        return command, output


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.root = self.directory / 'Devices'
        self.family = 'iPhone'
        self.udid = d.OWNED[self.family][0]
        self.path = self.root / self.udid
        self.app = self.path / 'data/Containers/Bundle/Application/TEST/ACSHost.app'
        self.app.mkdir(parents=True)
        (self.app / 'Info.plist').write_bytes(plistlib.dumps(dict(CFBundleIdentifier=d.BUNDLE, CFBundleExecutable='ACSHost')))
        (self.app / 'ACSHost').write_bytes(b'original test fixture')
        self.container = self.path / 'data/Containers/Data/Application/TEST'
        self.container.mkdir(parents=True)
        (self.container / '.com.apple.mobile_container_manager.metadata.plist').write_bytes(plistlib.dumps(dict(MCMMetadataIdentifier=d.BUNDLE)))
        self.ref = {'app_files': d.app_identity(self.app)}

    def capture(self, fault=None, state=1):
        runner = FakeRunner(self.directory, self.container, self.app / 'ACSHost', fault)
        clock = Clock()
        identity = dict(state_code=state, runtime=d.RUNTIME)

        def retain(receipt, directory):
            f = receipt['families'][0]
            f['markers'] = o.journals(self.container, f['token'])
            f['journal'] = {'path': 'fixture-journal.json'}
            d.write(directory / 'fixture-journal.json', {'markers': f['markers']})

        with patch.object(d, 'collector_identity', return_value=(self.path, identity)), \
             patch.object(d, 'native_timeout_reference', return_value={'fixture': True}), \
             patch.object(d, 'retain_journals', side_effect=retain):
            rec = o.capture(self.family, runner, self.ref, self.root, sleep=clock.sleep, clock=clock)
        return rec, runner

    def test_fixed_predicate_and_no_arbitrary_device(self):
        self.assertEqual(o.PREDICATE, 'process == "ACSHost" OR ((process == "SpringBoard" OR process == "runningboardd" OR process == "frontboardd") AND eventMessage CONTAINS "local.acs.ios-host-002")')
        self.assertEqual(o.stream_args(self.udid)[-3:], ['25', '--predicate', o.PREDICATE])
        with self.assertRaises(ValueError):
            o.stream_args('unrelated')

    def test_filter_rejects_unrelated_app_and_system_messages(self):
        app = str(self.app / 'ACSHost')
        home = '/' + 'Users' + '/other'  # a macOS home path, assembled so the literal stays out of exports
        values = [dict(processImagePath=app, eventMessage='owned user@example.com local.other.app ' + home + '/private'),
                  dict(processImagePath='/System/Library/SpringBoard', eventMessage=d.BUNDLE + ' com.third.party'),
                  dict(processImagePath='/bad/ACSHost', eventMessage='unrelated'),
                  dict(processImagePath='/bad/Other', eventMessage=d.BUNDLE),
                  dict(processImagePath='/System/Library/SpringBoard', eventMessage='unrelated')]
        result = json.loads(o.filter_events('\n'.join(map(json.dumps, values)) + '\nnot json', app))
        self.assertEqual(len(result['events']), 2)
        self.assertNotIn('user@example.com', str(result))
        self.assertNotIn('local.other.app', str(result))
        self.assertNotIn(home, str(result))
        self.assertEqual(result['events'][1]['processImagePath'], 'SpringBoard')

    def test_complete_rejects_each_incomplete_state(self):
        command = stream_record(self.udid)
        o.complete(command, self.udid)
        for key, value in [('exit_code', -9), ('timed_out', True), ('pipe_complete', False),
                           ('output_truncated', True), ('collector_complete', False),
                           ('eof_before_group_signal', False), ('timeout_seconds', 29)]:
            candidate = copy.deepcopy(command)
            candidate[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                o.complete(candidate, self.udid)
        for pipe in ('stdout', 'stderr'):
            for key in ('observed_bytes', 'retained_' + pipe + '_sha256', 'pipe_eof'):
                candidate = copy.deepcopy(command)
                if key == 'observed_bytes':
                    candidate[key][pipe] = o.CAP
                elif key == 'pipe_eof':
                    candidate[key][pipe] = '2026-10-18T12:00:00+00:00'
                else:
                    candidate[key] = 'a'*64
                with self.subTest(pipe=pipe, key=key), self.assertRaises(ValueError):
                    o.complete(candidate, self.udid)

    def test_full_flow_one_stream_launch_measured_window_two_exact_ps(self):
        rec, runner = self.capture()
        self.assertNotIn('primary_failure', rec)
        self.assertEqual(rec['stream_count'], 1)
        self.assertEqual(rec['launch_count'], 1)
        self.assertGreaterEqual(rec['observation']['elapsed_seconds'], 8)
        self.assertEqual(rec['observation_state'], 'complete')
        self.assertEqual(len(rec['processes']), 2)
        self.assertEqual(rec['cleanup'], 'restored')
        self.assertLess(rec['trace_command'], rec['shutdown_command'])
        self.assertEqual(rec['app_delivery'], 'unknown')
        self.assertEqual(rec['app_acknowledgement'], 'unknown')
        self.assertEqual(rec['scene_delegate'], 'unknown')
        self.assertTrue(all(c['timeout_seconds'] <= 30 for c in runner.commands))

    def test_already_booted_no_changes(self):
        rec, runner = self.capture(state=3)
        self.assertIn('already Booted', rec['primary_failure'])
        self.assertEqual(runner.commands, [])
        self.assertEqual(rec['cleanup'], 'unchanged_verified')

    def test_failed_boot_and_help_restore_without_launch(self):
        for fault in ('boot', 'help'):
            with self.subTest(fault=fault):
                rec, runner = self.capture(fault)
                self.assertEqual(rec['launch_count'], 0)
                self.assertEqual(rec['stream_count'], 0)
                self.assertEqual(rec['cleanup'], 'restored')
                self.assertTrue(rec['primary_failure'])

    def test_launch_timeout_stops_observation_retains_journal_no_ps(self):
        rec, runner = self.capture('launch')
        self.assertEqual(rec['launch_count'], 1)
        self.assertEqual(rec['stream_count'], 1)
        self.assertEqual(rec['processes'], [])
        self.assertEqual(rec['observation_state'], 'unavailable')
        self.assertIn('timeout=True', rec['primary_failure'])
        self.assertIn('journal', rec)
        self.assertEqual(rec['cleanup'], 'restored')

    def test_missing_journal_and_wrong_live_identity_never_supply_window(self):
        for fault in ('journal', 'identity'):
            with self.subTest(fault=fault):
                rec, _ = self.capture(fault)
                self.assertEqual(rec['observation_state'], 'unavailable')
                self.assertNotIn('observation', rec)
                self.assertEqual(rec['cleanup'], 'restored')
                self.assertEqual(rec['launch_count'], 1)

    def test_stream_and_finalizer_failure_preserve_primary_and_shutdown(self):
        for fault in ('stream', 'finalize'):
            rec, _ = self.capture(fault)
            self.assertTrue(rec['primary_failure'])
            self.assertEqual(rec['cleanup'], 'restored')
            self.assertEqual(rec['stream_count'], 1)
            self.assertEqual(rec['launch_count'], 1)
            self.assertEqual(rec['app_delivery'], 'unknown')

    def test_secondary_shutdown_failure_preserves_primary(self):
        runner = FakeRunner(self.directory, self.container, self.app / 'ACSHost', 'launch')
        original = runner.run

        def run(argv, timeout):
            result = original(argv, timeout)
            if argv[2] == 'shutdown':
                result[0]['exit_code'] = 1
            return result

        runner.run = run
        clock = Clock()
        with patch.object(d, 'collector_identity', return_value=(self.path, {'state_code': 1})), \
             patch.object(d, 'native_timeout_reference', return_value={}), \
             patch.object(d, 'retain_journals'):
            rec = o.capture(self.family, runner, self.ref, self.root, sleep=clock.sleep, clock=clock)
        self.assertIn('timeout=True', rec['primary_failure'])
        self.assertTrue(any(x.startswith('shutdown:') for x in rec['errors']))
        self.assertEqual(rec['cleanup'], 'failed')

    def test_fresh_path_required_prevents_recollection(self):
        with self.assertRaisesRegex(ValueError, 'requires fresh'):
            o.collect(self.directory / 'receipt.json')

    def require_private_store(self):
        if not (o.STORE / 'reports').is_dir():
            self.skipTest('private predecessor store not distributed (set ACS_ROOT)')

    def test_retained_predecessors_checked_without_simulator_commands(self):
        self.require_private_store()
        inputs = o.inspect_inputs()
        self.assertEqual(inputs['filtered_receipt_sha256'], o.FILTERED_SHA)
        self.assertEqual(inputs['reference']['app_files'], d.APP_FILES)

    def test_predecessor_helper_mutation_rejected_read_only(self):
        self.require_private_store()
        with patch.object(o, 'HELPER_SHA', '0'*64), self.assertRaisesRegex(ValueError, 'hash mismatch'):
            o.inspect_inputs()

    def retained(self):
        source = Path(__file__).resolve().parents[1] / '.local/ios-scene-observer-008/live'
        if not source.exists():
            self.skipTest('post-live receipt mutation checks; fake subprocess tests still run before live')
        target = self.directory / 'retained-copy'
        shutil.copytree(source, target)
        return target / 'receipt.json'

    def test_saved_receipt_verifies_offline_without_subprocess(self):
        path = self.retained()
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('offline verification must not execute')):
            obj = o.verify_saved(path)
        self.assertEqual(len(obj['families']), 2)
        self.assertTrue(all(f['observation_state'] == 'unavailable' for f in obj['families']))

    def test_saved_mutations_cannot_promote_blocked_observation(self):
        path = self.retained()
        original = d.load(path)
        mutations = [lambda v: v['families'][0].update(app_delivery='observed'),
                     lambda v: v['families'][0].update(observation_state='complete'),
                     lambda v: v['families'][0].update(trace_command=-1),
                     lambda v: v['families'][0]['final_identity'].update(state_code=3),
                     lambda v: v['families'][0].update(stream_count=2),
                     lambda v: v['commands'][v['families'][0]['trace_command']].update(timed_out=True),
                     lambda v: v['commands'][v['families'][0]['shutdown_command']].update(exit_code=1),
                     lambda v: v['commands'][v['families'][0]['stream_help_command']].update(started_at='2026-10-18T12:00:00+00:00'),
                     lambda v: v['families'][0].update(scene_delegate='observed'),
                     lambda v: v['inputs_after'].update(review='wrong')]
        for index, mutate in enumerate(mutations):
            obj = copy.deepcopy(original)
            mutate(obj)
            d.write(path, obj)
            with self.subTest(index=index), self.assertRaises(ValueError):
                o.verify_saved(path)

    def test_saved_rehashed_incomplete_help_is_rejected(self):
        path = self.retained()
        obj = d.load(path)
        command = obj['commands'][obj['families'][0]['stream_help_command']]
        output = path.parent / command['output']
        d.write(output, {'stdout': '--timeout --predicate ndjson', 'stderr': ''})
        command['sha256'] = d.digest(output.read_bytes())
        d.write(path, obj)
        with self.assertRaisesRegex(ValueError, 'help capabilities'):
            o.verify_saved(path)

    def test_saved_output_and_source_mutation_are_rejected(self):
        path = self.retained()
        output = path.parent / 'command-001.json'
        output.write_bytes(output.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'output hash'):
            o.verify_saved(path)
        obj = d.load(path)
        obj['commands'][0]['sha256'] = d.digest(output.read_bytes())
        d.write(path, obj)
        (path.parent / 'observer-source.py').write_text('changed source')
        with self.assertRaisesRegex(ValueError, 'source snapshot'):
            o.verify_saved(path)

    def test_real_fake_subprocess_drains_both_pipes_and_hashes_before_redaction(self):
        script = ('import os,time;'
                  'os.write(1,b"x"*1048576);os.write(2,b"y"*1048576);time.sleep(.1)')
        runner = o.Runner(self.directory)
        handle = runner.start_stream([sys.executable, '-c', script], lambda text: o.filter_events(text, self.app / 'ACSHost'), timeout=3)
        command, output = runner.finish_stream(handle)
        self.assertEqual(command['exit_code'], 0)
        self.assertTrue(command['pipe_complete'])
        self.assertEqual(command['observed_bytes'], {'stdout': 1048576, 'stderr': 1048576})
        self.assertEqual(command['raw_stdout_sha256'], d.digest(b'x'*1048576))
        self.assertEqual(command['retained_stdout_sha256'], command['raw_stdout_sha256'])
        self.assertEqual(json.loads(output['stdout'])['events'], [])
        self.assertNotIn('yyyyy', output['stderr'])

    def test_real_fake_subprocess_first_cap_error_survives_timeout(self):
        script = 'import os,time;os.write(1,b"x"*(9*1024*1024));time.sleep(5)'
        runner = o.Runner(self.directory)
        command, _ = runner.run([sys.executable, '-c', script], timeout=.3, transform=lambda text: '{}')
        self.assertEqual(command['primary_failure'], 'output byte cap exceeded')
        self.assertTrue(command['timed_out'])
        self.assertTrue(command['output_truncated'])
        self.assertNotEqual(command['raw_stdout_sha256'], command['retained_stdout_sha256'])
        self.assertEqual(command['observed_bytes']['stdout'], 9*1024*1024)

    def test_real_descendant_pipe_holder_is_bounded(self):
        script = 'import os,time;pid=os.fork();time.sleep(4) if pid==0 else os._exit(0)'
        runner = o.Runner(self.directory)
        start = time.monotonic()
        command, _ = runner.run([sys.executable, '-c', script], timeout=.3)
        self.assertLess(time.monotonic()-start, 1.5)
        self.assertIn('unknown', command['descendant_outcome'])
        self.assertTrue(command['signals'])


if __name__ == '__main__':
    unittest.main()
