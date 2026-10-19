"""Offline subprocess-only diagnostic contracts; no simulator/cloud operations."""
import copy
import importlib.util
import json
from pathlib import Path
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('diagnose_ios_scene', Path(__file__).resolve().parents[1] / 'tools/diagnose_ios_scene.py')
d = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(d)


class FakeChild:
    pid = 123456
    returncode = 0

    def __init__(self, timeout=False):
        self.timeout = timeout
        self.calls = []

    def communicate(self, timeout):
        self.calls.append(timeout)
        if self.timeout and len(self.calls) == 1:
            raise subprocess.TimeoutExpired(['fake'], timeout)
        if self.timeout:
            self.returncode = -9
        return b'owned output', b''


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self):
        runner = d.Runner(self.root, popen=lambda *a, **kw: FakeChild())
        runner.run(['xcrun', 'simctl', 'help', 'launch'], 10)
        obj = {'schema': 1, 'unit': 'IOS-TRANSPORT-004', 'bundle': d.BUNDLE,
               'activation_claim': False, 'reference': {'build_sha256': d.BUILD_SHA,
                   'source_head': d.SOURCE_HEAD, 'source_sha256': dict(d.SOURCE_SHA256),
                   'inspected': dict(d.INSPECTED_SHA256), 'app': str(d.PREVIOUS / d.REFERENCE / 'ACSHost.app'), 'app_files': dict(d.APP_FILES)},
               'commands': runner.commands, 'families': []}
        for family, (udid, _) in d.OWNED.items():
            obj['families'].append({'family': family, 'udid': udid, 'bundle': d.BUNDLE,
                'request_sent': 'unknown', 'acknowledged': 'unknown', 'scene_delegate': 'unknown',
                'status': 'blocked', 'reason': 'tool denied', 'next_prerequisite': 'usable scoped trace',
                'launch_count': 0, 'trace_command': None, 'cleanup': 'not_needed',
                'initial_state': 1, 'final_state': 1,
                'processes': [], 'markers': [], 'token': 'token'})
        return obj

    def verify(self, obj):
        path = self.root / 'receipt.json'
        d.write(path, obj)
        return d.verify_saved(path)

    def add_cycle(self, obj, family):
        """Synthetic ordered subprocess receipts; never invoke simctl."""
        template = obj['commands'][0]
        boot = copy.deepcopy(template)
        boot['argv'] = ['xcrun', 'simctl', 'boot', family['udid']]
        boot['started_at'] = boot['ended_at'] = '2026-01-01T00:00:00+00:00'
        shutdown = copy.deepcopy(template)
        shutdown['argv'] = ['xcrun', 'simctl', 'shutdown', family['udid']]
        shutdown['started_at'] = shutdown['ended_at'] = '2026-12-01T00:00:00+00:00'
        obj['commands'].insert(0, boot)
        obj['commands'].append(shutdown)
        family['cleanup'] = 'restored'
        return boot, shutdown

    def test_reference_maps_require_complete_expected_identities(self):
        for key in ('source_sha256', 'inspected'):
            for replacement in (None, {}, [], '', {'extra': 'a' * 64}):
                with self.subTest(key=key, replacement=replacement):
                    obj = self.fixture()
                    obj['reference'][key] = replacement
                    with self.assertRaisesRegex(ValueError, 'reference ' + key):
                        self.verify(obj)
            obj = self.fixture()
            del obj['reference'][key]
            with self.assertRaisesRegex(ValueError, 'reference ' + key):
                self.verify(obj)
            for value in ('', None, 123, 'abc', 'g' * 64, 'A' * 64, '0' * 64):
                with self.subTest(key=key, value=value):
                    obj = self.fixture()
                    name = next(iter(obj['reference'][key]))
                    obj['reference'][key][name] = value
                    with self.assertRaisesRegex(ValueError, 'reference ' + key):
                        self.verify(obj)
            obj = self.fixture()
            del obj['reference'][key][next(iter(obj['reference'][key]))]
            with self.assertRaisesRegex(ValueError, 'reference ' + key):
                self.verify(obj)

    def test_restored_requires_states_and_successful_shutdown(self):
        obj = self.fixture()
        f = obj['families'][0]
        self.add_cycle(obj, f)
        self.verify(obj)
        for initial, final in ((1, 3), (3, 3), (None, 1), (1, None), (True, 1), (1, True)):
            with self.subTest(initial=initial, final=final):
                candidate = copy.deepcopy(obj)
                candidate['families'][0].update(initial_state=initial, final_state=final)
                with self.assertRaises(ValueError):
                    self.verify(candidate)
        for exit_code, timed_out in ((1, False), (0, True), (1, True), (None, False)):
            with self.subTest(exit_code=exit_code, timed_out=timed_out):
                candidate = copy.deepcopy(obj)
                candidate['commands'][-1].update(exit_code=exit_code, timed_out=timed_out)
                with self.assertRaisesRegex(ValueError, 'successful bounded shutdown'):
                    self.verify(candidate)
        # Exact review counterexample: inconsistent state AND all shutdowns fail.
        candidate = copy.deepcopy(obj)
        candidate['families'][0]['final_state'] = 3
        candidate['commands'][-1].update(exit_code=1, timed_out=True)
        with self.assertRaises(ValueError):
            self.verify(candidate)

    def test_each_boot_requires_shutdown_including_failed_boot(self):
        obj = self.fixture()
        boot, shutdown = self.add_cycle(obj, obj['families'][0])
        boot.update(exit_code=-9, timed_out=True)
        self.verify(obj)  # A failed boot followed by successful shutdown is valid.
        obj['commands'].remove(shutdown)
        with self.assertRaisesRegex(ValueError, 'successful bounded shutdown'):
            self.verify(obj)
        obj['commands'].append(shutdown)
        later_boot = copy.deepcopy(boot)
        later_boot['started_at'] = later_boot['ended_at'] = '2026-12-02T00:00:00+00:00'
        obj['commands'].append(later_boot)
        with self.assertRaisesRegex(ValueError, 'successful bounded shutdown'):
            self.verify(obj)
        obj['commands'].insert(1, obj['commands'].pop())
        with self.assertRaisesRegex(ValueError, 'earlier boot'):
            self.verify(obj)

    def test_cleanup_label_cannot_replace_missing_or_foreign_commands(self):
        obj = self.fixture()
        f = obj['families'][0]
        f['cleanup'] = 'restored'
        with self.assertRaisesRegex(ValueError, 'restoration unsupported'):
            self.verify(obj)
        self.add_cycle(obj, f)
        obj['commands'][-1]['argv'][3] = obj['families'][1]['udid']
        with self.assertRaisesRegex(ValueError, 'successful bounded shutdown'):
            self.verify(obj)
        obj['commands'][-1]['argv'][3] = f['udid']
        f['cleanup'] = 'not_needed'
        with self.assertRaisesRegex(ValueError, 'cannot claim cleanup not_needed'):
            self.verify(obj)

    def test_later_trace_boot_needs_its_own_successful_shutdown(self):
        obj = self.fixture()
        family = obj['families'][0]
        boot, shutdown = self.add_cycle(obj, family)
        later_boot, later_shutdown = copy.deepcopy(boot), copy.deepcopy(shutdown)
        later_boot['started_at'] = later_boot['ended_at'] = '2026-12-02T00:00:00+00:00'
        later_shutdown['started_at'] = later_shutdown['ended_at'] = '2026-12-03T00:00:00+00:00'
        obj['commands'].extend([later_boot, later_shutdown])
        self.verify(obj)
        # The first successful shutdown cannot justify a later failed cleanup.
        later_shutdown.update(exit_code=1, timed_out=True)
        with self.assertRaisesRegex(ValueError, 'successful bounded shutdown'):
            self.verify(obj)

    def test_unchanged_device_states_and_restoration_order(self):
        obj = self.fixture()
        f = obj['families'][0]
        f.update(initial_state=3, final_state=3)
        self.verify(obj)  # Refusal to disturb an already booted device.
        f['final_state'] = 1
        with self.assertRaises(ValueError):
            self.verify(obj)
        f.update(initial_state=1, final_state=1)
        boot, shutdown = self.add_cycle(obj, f)
        obj['commands'] = [shutdown, boot, obj['commands'][1]]
        with self.assertRaisesRegex(ValueError, 'shutdown lacks an owned boot'):
            self.verify(obj)
        obj['commands'] = [boot, shutdown]
        shutdown['started_at'] = shutdown['ended_at'] = '2025-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError, 'chronology inconsistent'):
            self.verify(obj)

    def test_timeout_kills_only_created_group_and_records_exit(self):
        child = FakeChild(True)
        calls = []
        def popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return child
        with patch.object(d.os, 'killpg') as kill:
            runner = d.Runner(self.root, popen=popen)
            rec, output = runner.run(['fake', 'argument with spaces'], 7)
        kill.assert_called_once_with(child.pid, d.signal.SIGKILL)
        self.assertTrue(rec['timed_out'])
        self.assertEqual(rec['exit_code'], -9)
        self.assertGreater(child.calls[0], 6.9)
        self.assertLessEqual(child.calls[0], 7)
        self.assertEqual(child.calls[1], 2)
        self.assertTrue(calls[0][1]['start_new_session'])
        self.assertNotIn('shell', calls[0][1])
        self.assertEqual(output['stdout'], 'owned output')

    def test_invalid_timeout_and_shell_string_rejected_before_spawn(self):
        for timeout in (0, -1, 31):
            with self.assertRaises(ValueError):
                d.Runner(self.root, popen=lambda *a, **k: self.fail('spawned')).run(['fake'], timeout)
        with self.assertRaises(ValueError):
            d.Runner(self.root).run('shell command')

    def test_tool_not_found_preserves_failure(self):
        def missing(*a, **kw):
            raise FileNotFoundError('tool unavailable')
        runner = d.Runner(self.root, popen=missing)
        rec, output = runner.run(['fake'])
        self.assertIsNone(rec['exit_code'])
        self.assertIn('tool unavailable', output['stderr'])
        with self.assertRaises(ValueError):
            d.require_ok((rec, output))

    def test_unknown_receipts_verify_without_activation(self):
        obj = self.verify(self.fixture())
        self.assertFalse(obj['activation_claim'])
        self.assertEqual(obj['families'][0]['acknowledged'], 'unknown')

    def test_malformed_receipt_fails(self):
        obj = self.fixture()
        for mutation in (lambda x: x.update(schema=2), lambda x: x.update(activation_claim=True),
                         lambda x: x.update(families=[]), lambda x: x['reference'].update(build_sha256='bad')):
            candidate = copy.deepcopy(obj)
            mutation(candidate)
            with self.assertRaises(ValueError):
                self.verify(candidate)

    def test_unknown_states_and_invented_ack_rejected(self):
        for key, value in [('request_sent', 'sent'), ('acknowledged', 'yes'),
                           ('scene_delegate', 'no'), ('status', 'success')]:
            obj = self.fixture()
            obj['families'][0][key] = value
            with self.assertRaises(ValueError):
                self.verify(obj)

    def test_unowned_simulator_and_bundle_rejected(self):
        for argv in (['xcrun', 'simctl', 'boot', 'booted'],
                     ['xcrun', 'simctl', 'launch', d.OWNED['iPhone'][0], 'unrelated.app'],
                     ['xcrun', 'simctl', 'erase', d.OWNED['iPhone'][0]],
                     ['xcrun', 'simctl', 'spawn', d.OWNED['iPhone'][0], 'sh', '-c', 'anything']):
            obj = self.fixture()
            obj['commands'][0]['argv'] = argv
            with self.assertRaises(ValueError):
                self.verify(obj)

    def test_retained_output_tampering_rejected(self):
        obj = self.fixture()
        (self.root / obj['commands'][0]['output']).write_text('{}')
        with self.assertRaises(ValueError):
            self.verify(obj)

    def test_output_escape_rejected(self):
        obj = self.fixture()
        obj['commands'][0]['output'] = '../outside'
        with self.assertRaises(ValueError):
            self.verify(obj)

    def test_failed_diagnostic_cannot_be_collected(self):
        obj = self.fixture()
        family = obj['families'][0]
        family['status'] = 'collected_unknown'
        with self.assertRaises(ValueError):
            self.verify(obj)
        command = obj['commands'][0]
        family['app'] = str(d.SIMULATOR_DEVICES) + '/' + family['udid'] + '/data/Containers/Bundle/Application/00000000-0000-0000-0000-000000000000/ACSHost.app'
        command['argv'] = ['xcrun', 'simctl', 'spawn', family['udid'], 'log', 'show', '--start', '@0', '--style', 'ndjson', '--info', '--debug', '--predicate', d.predicate(Path(family['app']) / 'ACSHost')]
        command['exit_code'] = 1
        d.write(self.root / command['output'], {'stdout': json.dumps({'events': [{'eventMessage': d.BUNDLE + ' event', 'processImagePath': '/runtime/SpringBoard'}], 'non_json_lines': 0}), 'stderr': 'denied'})
        command['sha256'] = d.digest((self.root / command['output']).read_bytes())
        family['trace_command'] = 0
        family['trace_events'] = 1
        with self.assertRaisesRegex(ValueError, 'failed diagnostics relabeled collected'):
            self.verify(obj)

    def test_successful_rpc_is_not_scene_evidence(self):
        obj = self.fixture()
        f = obj['families'][0]
        obj['commands'][0]['argv'] = ['xcrun', 'simctl', 'launch', f['udid'], d.BUNDLE, '--evidence-run', 'token']
        f['launch_count'] = 1
        self.add_cycle(obj, f)
        self.assertEqual(self.verify(obj)['families'][0]['request_sent'], 'unknown')

    def test_second_launch_rejected(self):
        obj = self.fixture()
        f = obj['families'][0]
        obj['commands'][0]['argv'] = ['xcrun', 'simctl', 'launch', f['udid'], d.BUNDLE, '--evidence-run', 'token']
        obj['commands'].append(copy.deepcopy(obj['commands'][0]))
        f['launch_count'] = 2
        with self.assertRaises(ValueError):
            self.verify(obj)

    def test_unowned_family_and_cleanup_failure_rejected(self):
        obj = self.fixture()
        obj['families'][0]['udid'] = 'unowned'
        with self.assertRaises(ValueError):
            self.verify(obj)
        obj = self.fixture()
        obj['families'][0]['cleanup'] = 'failed'
        with self.assertRaises(ValueError):
            self.verify(obj)

    def test_trace_filters_unrelated_and_redacts_message(self):
        exe = '/owned/ACSHost'
        lines = [json.dumps({'processImagePath': '/unrelated', 'eventMessage': 'other app'}),
                 json.dumps({'processImagePath': exe, 'processID': 1, 'eventMessage': 'com.other.app a@b.example'}),
                 json.dumps({'eventMessage': d.BUNDLE + ' request com.some.app'}), 'bad-json']
        data = json.loads(d.filter_trace('\n'.join(lines), exe))
        self.assertEqual(len(data['events']), 2)
        self.assertEqual(data['non_json_lines'], 1)
        self.assertNotIn('com.other.app', str(data))
        self.assertNotIn('a@b.example', str(data))

    def test_arbitrary_executable_and_unowned_process_query_rejected(self):
        for argv in (['sh', '-c', 'anything'], ['/bin/ps', '-p', '42', '-o', 'pid=,comm=,args='],
                     ['codesign', '--force', '--sign', '-', '/owned/app']):
            obj = self.fixture()
            obj['commands'][0]['argv'] = argv
            with self.assertRaises(ValueError):
                self.verify(obj)

    def test_offline_verifier_never_spawns(self):
        obj = self.fixture()
        with patch.object(d.subprocess, 'Popen', side_effect=AssertionError('offline must not spawn')):
            self.verify(obj)

    def test_bad_command_utc_and_deadline_rejected(self):
        for key, value in [('started_at', '2026-01-01T00:00:00'), ('timeout_seconds', 90), ('exit_code', '0')]:
            obj = self.fixture()
            obj['commands'][0][key] = value
            with self.assertRaises(ValueError):
                self.verify(obj)

    def test_owned_scene_suffix_is_preserved_during_redaction(self):
        message = d.BUNDLE + '-default other=com.other.app'
        trace = d.filter_trace(json.dumps({'eventMessage': message}), '/owned/ACSHost')
        self.assertIn(d.BUNDLE + '-default', trace)
        self.assertNotIn('com.other.app', trace)

    def test_malformed_json_rejected_offline(self):
        path = self.root / 'receipt.json'
        path.write_text('{')
        with self.assertRaises(ValueError):
            d.verify_saved(path)

    def test_failed_owned_pid_query_remains_honest_unknown(self):
        obj = self.fixture()
        family = obj['families'][0]
        family['markers'] = [{'evidence_run': 'token', 'pid': 42, 'stage': 'main'}]
        obj['commands'][0]['argv'] = ['/bin/ps', '-p', '42', '-o', 'pid=,comm=,args=']
        obj['commands'][0]['exit_code'] = 1
        self.assertEqual(self.verify(obj)['families'][0]['scene_delegate'], 'unknown')

    def test_unowned_installed_path_rejected(self):
        obj = self.fixture()
        obj['families'][0]['app'] = '/unrelated/ACSHost.app'
        with self.assertRaises(ValueError):
            self.verify(obj)

    def test_device_identity_requires_exact_udid_type_runtime_name(self):
        family = 'iPhone'
        udid, kind = d.OWNED[family]
        p = self.root / udid
        p.mkdir()
        identity = {'UDID': udid, 'name': 'ACS IOS-HOST-002 iPhone', 'runtime': d.RUNTIME, 'deviceType': kind, 'state': 1}
        (p / 'device.plist').write_bytes(plistlib.dumps(identity))
        self.assertEqual(d.device(family, self.root)[1]['state'], 1)
        for key in ('UDID', 'name', 'runtime', 'deviceType'):
            wrong = dict(identity, **{key: 'other'})
            (p / 'device.plist').write_bytes(plistlib.dumps(wrong))
            with self.assertRaises(ValueError):
                d.device(family, self.root)

    def test_booted_device_is_not_changed_or_launched(self):
        runner = d.Runner(self.root, popen=lambda *a, **kw: self.fail('must not execute'))
        with patch.object(d, 'device', return_value=(self.root, {'state': 3})):
            result = d.capture_family('iPhone', runner, {}, self.root)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['launch_count'], 0)
        self.assertEqual(runner.commands, [])

    def test_boot_failure_restores_only_exact_device(self):
        udid = d.OWNED['iPhone'][0]
        app = self.root / 'data/Containers/Bundle/Application/one/ACSHost.app'
        app.mkdir(parents=True)
        (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': d.BUNDLE}))
        class FakeRunner:
            def __init__(self): self.commands = []
            def run(self, argv, timeout):
                self.commands.append(argv)
                return ({'exit_code': 1 if 'boot' in argv else 0, 'timed_out': False, 'argv': argv}, {'stdout': '', 'stderr': ''})
        runner = FakeRunner()
        # codesign should pass; boot fails and finally must restore same owned simulator.
        with patch.object(d, 'device', return_value=(self.root, {'state': 1})), patch.object(d, 'app_identity', return_value=dict(d.APP_FILES)):
            result = d.capture_family('iPhone', runner, {'app_files': dict(d.APP_FILES)}, self.root)
        self.assertEqual(result['cleanup'], 'restored')
        self.assertEqual(result['launch_count'], 0)
        self.assertEqual(runner.commands[-1], ['xcrun', 'simctl', 'shutdown', udid])

    def delivery_fixture(self):
        """Entire portable receipt tree, with real hashing and no simulator access."""
        prior = self.fixture()
        directory = self.root / 'predecessor'
        directory.mkdir(exist_ok=True)
        for c in prior['commands']:
            (directory / c['output']).write_bytes((self.root / c['output']).read_bytes())
        d.write(directory / 'receipt.json', prior)
        pin = d.digest((directory / 'receipt.json').read_bytes())
        patcher = patch.object(d, 'TRANSPORT_SHA', pin)
        patcher.start()
        self.addCleanup(patcher.stop)
        obj = copy.deepcopy(prior)
        obj.update(unit='IOS-SCENE-DELIVERY-005', runtime='26.5', minimum_target='26.0', predecessor={'path': 'predecessor/receipt.json', 'sha256': pin}, commands=[])
        def command(argv, start, end, stdout='', exit_code=0):
            name = f'delivery-{len(obj["commands"]):03}.json'
            d.write(self.root / name, {'stdout': stdout, 'stderr': ''})
            c = dict(argv=argv, started_at=f'2026-01-01T00:00:{start:02}+00:00',
                     ended_at=f'2026-01-01T00:00:{end:02}+00:00', exit_code=exit_code,
                     timed_out=False, timeout_seconds=30, output=name,
                     sha256=d.digest((self.root / name).read_bytes()))
            obj['commands'].append(c)
            return len(obj['commands'])-1
        for n, f in enumerate(obj['families']):
            f.update(app=str(d.SIMULATOR_DEVICES) + '/' + f['udid'] + '/data/Containers/Bundle/Application/00000000-0000-0000-0000-000000000000/ACSHost.app',
                     app_files=dict(d.APP_FILES), launch_count=1, cleanup='restored', token='fixture-token-'+str(n), observation_state='complete',
                     observation=dict(seconds=12, elapsed_seconds=12, started_at='2026-01-01T00:00:05+00:00', ended_at='2026-01-01T00:00:17+00:00'))
            pid = 42+n
            f['markers'] = [dict(pid=pid, stage='main', evidence_run=f['token'])]
            command(['xcrun','simctl','boot',f['udid']],0,0)
            f['stream_help_command'] = command(['xcrun','simctl','spawn',f['udid'],'log','help','stream'],1,1,'--predicate --level debug --timeout ndjson',64)
            events = [{'processID':pid, 'processImagePath':f['app']+'/ACSHost', 'eventMessage':'Handshake succeeded; fixture-session'}]
            f['trace_command'] = command(d.stream_args(f['udid'], Path(f['app'])),2,28,json.dumps({'events': events, 'non_json_lines':0}))
            f['trace_events'] = 1
            f['observations'] = d.trace_observations(events)
            f['launch_command'] = command(['xcrun','simctl','launch',f['udid'],d.BUNDLE,'--evidence-run',f['token']],3,3)
            for second in (4,18):
                idx = command(['/bin/ps','-ww','-p',str(pid),'-o','pid=,args='],second,second,f"{pid} {f['app']}/ACSHost --evidence-run {f['token']}\n")
                f['processes'].append(dict(pid=pid, executable=f['app']+'/ACSHost', token=f['token'], command=idx))
            journal = dict(family=f['family'],udid=f['udid'],bundle=d.BUNDLE,token=f['token'],markers=f['markers'],
                           activation=[{'value':{'pid':pid,'evidence_run':f['token'],'sessions':[{'identifier':'fixture-session'}]}}],read_at='2026-01-01T00:00:20+00:00')
            name = f['family']+'-fixture.json'
            d.write(self.root/name,journal)
            f['journal'] = dict(path=name,sha256=d.digest((self.root/name).read_bytes()))
            f['delivery_observations'] = d.delivery_observations(f,events,journal)
            command(['xcrun','simctl','shutdown',f['udid']],29,29)
        return obj

    def test_delivery_entire_receipt_verifies_offline_and_handshake_is_not_ack(self):
        obj = self.delivery_fixture()
        with patch.object(d.subprocess, 'Popen', side_effect=AssertionError('offline must not spawn')):
            self.verify(obj)
        f = obj['families'][0]
        self.assertEqual(f['delivery_observations']['app_session_candidate_indices'], [0])
        self.assertEqual(f['delivery_observations']['app_acknowledgement'], 'unknown')
        self.assertEqual(f['scene_delegate'], 'unknown')

    def test_delivery_mutations_reject_interval_identity_help_and_correlation(self):
        obj = self.delivery_fixture()
        mutations = [
            lambda f: f['observation'].update(seconds=1),
            lambda f: f['observation'].update(elapsed_seconds=0),
            lambda f: f['observation'].update(ended_at='2026-01-01T00:00:06+00:00'),
            lambda f: f.update(processes=f['processes'][:1]),
            lambda f: f.update(observation_state='unavailable'),
            lambda f: f['delivery_observations'].update(app_delivery='delivered'),
            lambda f: f['delivery_observations'].update(app_acknowledgement='acknowledged'),
            lambda f: f['delivery_observations'].update(persistent_sessions=['invented']),
            lambda f: f.update(scene_delegate='reached'),
            lambda f: f.update(stream_help_command=f['launch_command']),
            lambda f: f.update(launch_command=f['trace_command']),
        ]
        for mutate in mutations:
            candidate = copy.deepcopy(obj)
            mutate(candidate['families'][0])
            with self.subTest(mutation=mutate), self.assertRaises((ValueError, KeyError)):
                self.verify(candidate)

    def test_delivery_unavailable_interval_is_explicit_failure_not_completion(self):
        obj = self.delivery_fixture()
        f = obj['families'][0]
        # Remove the unused PID commands, preserving indices for the other family.
        for p in f['processes']:
            obj['commands'][p['command']]['argv'] = ['/usr/bin/log','help','stream']
        f.update(processes=[], observation_state='unavailable', observation_unavailable_reason='No successful pre-interval live PID/path/token query was recorded.')
        del f['observation']
        journal = d.load(self.root / f['journal']['path'])
        events = json.loads(d.load(self.root / obj['commands'][f['trace_command']]['output'])['stdout'])['events']
        f['delivery_observations'] = d.delivery_observations(f,events,journal)
        self.assertEqual(self.verify(obj)['families'][0]['status'], 'blocked')
        f['observation_state'] = 'complete'
        with self.assertRaises((ValueError,KeyError)):
            self.verify(obj)

    def test_delivery_predecessor_and_stream_output_mutations_rejected(self):
        obj = self.delivery_fixture()
        candidate = copy.deepcopy(obj)
        candidate['predecessor']['sha256'] = '0'*64
        with self.assertRaises(ValueError): self.verify(candidate)
        obj['commands'][obj['families'][0]['trace_command']]['argv'][-1] = 'TRUEPREDICATE'
        with self.assertRaises(ValueError): self.verify(obj)

    def test_exact_live_pid_path_token_parser(self):
        d.verify_process_text('42 /owned/ACSHost --evidence-run token',42,'/owned/ACSHost','token')
        for text in ('142 /owned/ACSHost --evidence-run token', '42 /owned/ACSHost-copy --evidence-run token',
                     '42 /owned/ACSHost --evidence-run token-extra', '42 /owned/ACSHost --evidence-run token --extra'):
            with self.assertRaises(ValueError): d.verify_process_text(text,42,'/owned/ACSHost','token')

    def test_live_stream_drains_before_finish_and_uses_original_deadline(self):
        import threading
        drained = threading.Event()
        class Child(FakeChild):
            def communicate(self, timeout):
                drained.set()
                return b'{}', b''
        runner = d.Runner(self.root,popen=lambda *a,**kw: Child())
        handle = runner.start_stream(['fake'],lambda text: text)
        self.assertTrue(drained.wait(1), 'pipe must drain while launch/observation proceeds')
        result = runner.finish_stream(handle)
        self.assertEqual(result[0]['timeout_seconds'],30)
        self.assertEqual(result[0]['exit_code'],0)

    def test_delivery_missing_installation_refuses_boot(self):
        # A failed installation prerequisite must cause zero subprocess side effects.
        class FakeRunner:
            directory = self.root
            commands = []
            def run(self, argv, timeout):
                self.commands.append(dict(argv=argv,exit_code=0,timed_out=False))
                return self.commands[-1], {'stdout':'','stderr':''}
        runner = FakeRunner()
        with patch.object(d,'device',return_value=(self.root,{'state':1})), patch.object(d,'app_identity',return_value=dict(d.APP_FILES)):
            # Missing installed app fails before boot and must not touch a simulator.
            result = d.capture_delivery('iPhone',runner,{'app_files':dict(d.APP_FILES)},self.root,sleep=lambda _:None)
        self.assertEqual(result['launch_count'],0)
        self.assertEqual(runner.commands,[])

    def test_stream_real_subprocess_drains_large_output_without_backpressure(self):
        import sys
        import time
        marker = self.root / 'drained'
        script = "import sys,pathlib; sys.stdout.write('x'*1048576); sys.stdout.flush(); pathlib.Path(sys.argv[1]).write_text('done')"
        runner = d.Runner(self.root)
        handle = runner.start_stream([sys.executable,'-c',script,str(marker)],lambda text:str(len(text)))
        deadline = time.monotonic()+3
        while not marker.exists() and time.monotonic()<deadline:
            time.sleep(0.01)
        drained_before_join = marker.exists()
        result = runner.finish_stream(handle)
        self.assertTrue(drained_before_join, 'child must finish writing before stream join')
        self.assertEqual(result[1]['stdout'],'1048576')
        self.assertEqual(result[0]['exit_code'],0)

    def test_delivery_stream_finalize_exception_still_restores_owned_device(self):
        app = self.root/'data/Containers/Bundle/Application/one/ACSHost.app'
        app.mkdir(parents=True)
        (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':d.BUNDLE}))
        container = self.root/'data/Containers/Data/Application/one'
        container.mkdir(parents=True)
        (container/'.com.apple.mobile_container_manager.metadata.plist').write_bytes(plistlib.dumps({'MCMMetadataIdentifier':d.BUNDLE}))
        class FakeRunner:
            directory = self.root
            def __init__(self): self.commands=[]
            def run(self,argv,timeout):
                c=dict(argv=argv,exit_code=0,timed_out=False)
                self.commands.append(c)
                text='--predicate --level debug --timeout ndjson' if argv[-2:]==['help','stream'] else str(container)
                return c, {'stdout':text,'stderr':''}
            def start_stream(self,*args): return object()
            def finish_stream(self,*args): raise ValueError('synthetic finalizer failure')
        runner=FakeRunner()
        with patch.object(d,'device',return_value=(self.root,{'state':1})), patch.object(d,'app_identity',return_value=dict(d.APP_FILES)):
            result = d.capture_delivery('iPhone',runner,{'app_files':dict(d.APP_FILES)},self.root,sleep=lambda _:None)
        self.assertIn('unique token-correlated live app PID unavailable', result['primary_failure'])
        self.assertTrue(result['reason'].startswith(result['primary_failure']))
        self.assertIn('synthetic finalizer failure', result['reason'])
        self.assertEqual(result['cleanup'], 'restored')
        self.assertEqual(runner.commands[-1]['argv'],['xcrun','simctl','shutdown',d.OWNED['iPhone'][0]])

    def test_actual_receipt_review_counterexamples_and_missing_intervals(self):
        base = Path(__file__).resolve().parents[1] / '.local'
        receipt = base / 'ios-scene-delivery-failed-200d88c/receipt.json'
        if not receipt.exists():
            receipt = base / 'ios-scene-delivery/receipt.json'
        if not receipt.exists():
            receipt = d.COLLECTOR_PREDECESSOR.parent / 'IOS-SCENE-DELIVERY-005/.local/ios-scene-delivery/receipt.json'
        if not receipt.exists():
            self.skipTest('private actual receipt not distributed in Git')
        import shutil
        actual = self.root / 'actual'
        shutil.copytree(receipt.parent, actual)
        obj = d.load(actual / 'receipt.json')
        d.verify_saved(actual / 'receipt.json')
        for family_index in (0, 1):
            for mutation in ('missing_help', 'wrong_help', 'negative_help', 'late_stream',
                             'missing_interval', 'missing_state', 'wrong_capability'):
                with self.subTest(family=family_index, mutation=mutation):
                    candidate = copy.deepcopy(obj)
                    f = candidate['families'][family_index]
                    if mutation == 'missing_help': del f['stream_help_command']
                    elif mutation == 'wrong_help': f['stream_help_command'] = f['launch_command']
                    elif mutation == 'negative_help': f['stream_help_command'] = -1
                    elif mutation == 'late_stream':
                        c = candidate['commands'][f['trace_command']]
                        c.update(started_at='2026-10-18T12:00:00+00:00', ended_at='2026-10-18T12:00:28+00:00')
                    elif mutation == 'missing_interval':
                        f.pop('observation', None)
                        f['observation_state'] = 'complete'
                    elif mutation == 'missing_state': f.pop('observation_state', None)
                    elif mutation == 'wrong_capability':
                        # Rehash a genuine output with capability flags removed.
                        c = candidate['commands'][f['stream_help_command']]
                        file = actual / c['output']
                        original = file.read_bytes()
                        d.write(file, {'stdout':'usage: log stream', 'stderr':''})
                        c['sha256'] = d.digest(file.read_bytes())
                    d.write(actual / 'receipt.json', candidate)
                    try:
                        with self.assertRaises((ValueError, KeyError)):
                            d.verify_saved(actual / 'receipt.json')
                    finally:
                        if mutation == 'wrong_capability': file.write_bytes(original)

    def test_real_stream_backpressure_and_timeout_are_bounded(self):
        import sys
        import time
        script = "import sys,time; sys.stdout.write('x'*1048576); sys.stdout.flush(); sys.stderr.write('y'*1048576); sys.stderr.flush(); time.sleep(10)"
        runner = d.Runner(self.root)
        started = time.monotonic()
        handle = runner.start_stream([sys.executable, '-c', script], lambda text: str(len(text)), timeout=0.3)
        result = runner.finish_stream(handle)
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(result[0]['timed_out'])
        self.assertEqual(result[0]['exit_code'], -9)
        self.assertEqual(result[1]['stdout'], '1048576')
        self.assertEqual(len(result[1]['stderr']), 1048576)

    def test_unavailable_and_preflight_branches_require_capability_chronology(self):
        obj = self.delivery_fixture()
        f = obj['families'][0]
        # A missing interval cannot be relabeled unavailable after successful PID checks.
        f.pop('observation')
        f.update(observation_state='unavailable', observation_unavailable_reason='No successful pre-interval live PID/path/token query was recorded.')
        with self.assertRaises(ValueError): self.verify(obj)
        obj = self.delivery_fixture()
        f = obj['families'][0]
        obj['commands'][f['stream_help_command']]['started_at'] = '2026-01-01T00:00:30+00:00'
        obj['commands'][f['stream_help_command']]['ended_at'] = '2026-01-01T00:00:30+00:00'
        with self.assertRaises(ValueError): self.verify(obj)

    def test_collector_delayed_journal_full_window_and_primary_identity_failure(self):
        app = self.root / 'data/Containers/Bundle/Application/one/ACSHost.app'
        app.mkdir(parents=True)
        (app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': d.BUNDLE}))
        container = self.root / 'data/Containers/Data/Application/one'
        (container / 'Documents').mkdir(parents=True)
        (container / '.com.apple.mobile_container_manager.metadata.plist').write_bytes(
            plistlib.dumps({'MCMMetadataIdentifier': d.BUNDLE}))
        marker = container / 'Documents/startup.jsonl'
        for fail_identity in (False, True):
            with self.subTest(fail_identity=fail_identity):
                marker.unlink(missing_ok=True)
                intervals = []
                class FakeRunner:
                    directory = self.root
                    def __init__(self): self.commands = []; self.token = None
                    def run(self, argv, timeout):
                        c = dict(argv=argv, exit_code=0, timed_out=False)
                        self.commands.append(c)
                        text = ''
                        if argv[-2:] == ['help', 'stream']:
                            text = '--predicate --level debug --timeout ndjson'
                        elif 'get_app_container' in argv: text = str(container)
                        elif 'launch' in argv: self.token = argv[-1]
                        elif argv[0] == '/bin/ps':
                            text = f"42 {app}/ACSHost --evidence-run {self.token}"
                            if fail_identity: text += ' --unexpected'
                        return c, {'stdout': text, 'stderr': ''}
                    def start_stream(self, argv, transform):
                        c = dict(argv=argv, exit_code=-9, timed_out=True)
                        self.commands.append(c)
                        return c
                    def finish_stream(self, handle):
                        return handle, {'stdout': '{"events":[]}', 'stderr':''}
                runner = FakeRunner()
                def sleep(seconds):
                    intervals.append(seconds)
                    if seconds == 0.05 and runner.token:
                        marker.write_text(json.dumps(dict(pid=42, evidence_run=runner.token, stage='main'))+'\n')
                def retain(receipt, directory):
                    f = receipt['families'][0]
                    name = 'fake-journal.json'
                    d.write(directory / name, dict(activation=[], markers=f['markers']))
                    f['journal'] = dict(path=name, sha256=d.digest((directory/name).read_bytes()))
                with patch.object(d, 'device', return_value=(self.root, {'state':1})), patch.object(d, 'app_identity', return_value=dict(d.APP_FILES)), patch.object(d, 'retain_journals', side_effect=retain):
                    result = d.capture_delivery('iPhone', runner, {'app_files':dict(d.APP_FILES)}, self.root, sleep=sleep)
                self.assertIn(0.05, intervals, 'collector must wait for delayed token journal')
                self.assertEqual(result['launch_count'], 1)
                self.assertEqual(result['cleanup'], 'restored')
                self.assertEqual(runner.commands[-1]['argv'], ['xcrun','simctl','shutdown',d.OWNED['iPhone'][0]])
                if fail_identity:
                    self.assertNotIn(12, intervals)
                    self.assertEqual(result['primary_failure'], 'owned process PID/path/token mismatch')
                    self.assertTrue(result['reason'].startswith(result['primary_failure']))
                    self.assertIn('collector live stream failed', result['reason'])
                    self.assertEqual(result['observation_state'], 'unavailable')
                else:
                    self.assertIn(12, intervals)
                    self.assertEqual(len(result['processes']), 2)
                    self.assertIn('collector live stream failed', result['primary_failure'])
                self.assertIn('Collector blocked:', result['next_prerequisite'])


    def real_descendant(self, escaped=False, close_pipes=False):
        import sys
        marker = self.root / 'descendant-ready'
        done = self.root / 'descendant-done'
        child = ("import pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text('ready');"
                 "time.sleep(1.6);pathlib.Path(sys.argv[2]).write_text('finished')")
        script = ("import subprocess,sys,pathlib,time; "
                  "p=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]],"
                  "start_new_session=" + str(escaped) +
                  (",stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL" if close_pipes else '') + ");"
                  "deadline=time.monotonic()+1;"
                  "\nwhile not pathlib.Path(sys.argv[2]).exists() and time.monotonic()<deadline: time.sleep(.005)"
                  "\nprint(p.pid,flush=True)")
        return [sys.executable, '-c', script, child, str(marker), str(done)], done

    def test_real_parent_exit_descendant_retains_both_pipes(self):
        import time
        argv, done = self.real_descendant()
        runner = d.Runner(self.root)
        started = time.monotonic()
        rec, output = runner.run(argv, 2)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(rec['exit_code'], 0)
        self.assertTrue(rec['pipe_complete'])
        self.assertEqual(set(rec['pipe_eof']), {'stdout', 'stderr'})
        self.assertTrue(rec['collector_complete'])
        self.assertIn('WNOWAIT', rec['ownership'])
        self.assertEqual(rec['signals'][0]['outcome'], 'sent to reserved owned group')
        self.assertFalse(done.exists())
        self.assertIn('escaped descendants unknown', rec['descendant_outcome'])

    def test_real_closed_pipes_do_not_skip_owned_descendant_cleanup(self):
        import time
        argv, done = self.real_descendant(close_pipes=True)
        rec, _ = d.Runner(self.root).run(argv, 2)
        self.assertTrue(rec['collector_complete'])
        self.assertTrue(rec['signals'])
        time.sleep(1.7)
        self.assertFalse(done.exists(), 'descendant that closed both pipes must still be killed')

    def test_real_escaped_pipe_holder_is_bounded_and_never_claims_eof(self):
        import time
        argv, done = self.real_descendant(escaped=True)
        started = time.monotonic()
        rec, output = d.Runner(self.root).run(argv, .4)
        self.assertLess(time.monotonic() - started, 1.4)
        self.assertEqual(rec['exit_code'], 0)
        self.assertTrue(rec['timed_out'])
        self.assertFalse(rec['pipe_complete'])
        self.assertFalse(rec['collector_complete'])
        self.assertEqual(rec['primary_failure'], 'execution/pipe deadline exceeded')
        self.assertIn('unknown', rec['descendant_outcome'])
        with self.assertRaises(ValueError): d.require_ok((rec, output))
        # Escaped fixture owns its own short lifetime. Never signal a guessed PID.
        deadline = time.monotonic()+3
        while not done.exists() and time.monotonic()<deadline: time.sleep(.02)
        self.assertTrue(done.exists())

    def test_real_output_cap_rejects_partial_success(self):
        import sys
        rec, output = d.Runner(self.root).run([sys.executable, '-c',
            "import sys;sys.stdout.write('x'*(9*1024*1024));sys.stdout.flush()"], 3)
        self.assertEqual(len(output['stdout']), 8*1024*1024)
        self.assertTrue(rec['pipe_complete'])
        self.assertTrue(rec['output_truncated'])
        self.assertFalse(rec['collector_complete'])
        self.assertEqual(rec['primary_failure'], 'output byte cap exceeded')
        self.assertEqual(rec['observed_bytes']['stdout'], 9*1024*1024)
        self.assertEqual(rec['raw_stdout_sha256'], d.digest(b'x'*(9*1024*1024)))
        self.assertNotEqual(rec['raw_stdout_sha256'], rec['retained_stdout_sha256'])
        with self.assertRaises(ValueError): d.require_ok((rec, output))

    def test_cap_error_survives_later_timeout(self):
        import sys
        rec, _ = d.Runner(self.root).run([sys.executable, '-c',
            "import sys,time;sys.stdout.write('x'*(9*1024*1024));sys.stdout.flush();time.sleep(5)"], .5)
        self.assertTrue(rec['timed_out'])
        self.assertEqual(rec['primary_failure'], 'output byte cap exceeded')
        self.assertIn('execution/pipe deadline exceeded', rec['errors'])
        self.assertTrue(rec['pipe_complete'])

    def test_short_lived_child_is_still_reserved_before_reaping(self):
        import sys,time
        runner = d.Runner(self.root)
        handle = runner.start([sys.executable, '-c', 'pass'], 1)
        time.sleep(.15)
        rec, _ = runner.finish(handle)
        self.assertEqual(rec['exit_code'], 0)
        self.assertTrue(rec['collector_complete'])

    def test_native_timeout_reference_requires_exact_local_grammar(self):
        sentence = b'If minutes, hours, days not specified, seconds will be used.'
        with patch.object(d.Path, 'read_bytes', return_value=sentence):
            ref = d.native_timeout_reference('--timeout <num>[m|h|d] timeout')
            self.assertEqual(ref['sha256'],d.digest(sentence))
            with self.assertRaises(ValueError): d.native_timeout_reference('--timeout <seconds>s')
        with patch.object(d.Path, 'read_bytes', return_value=b'unknown units'):
            with self.assertRaises(ValueError): d.native_timeout_reference('--timeout <num>[m|h|d]')

    def test_collector_booted_session_is_left_unchanged(self):
        runner = self.collector_fake()
        with patch.object(d, 'collector_identity', return_value=(self.root,dict(state_code=3))):
            rec = d.capture_collector('iPad',runner,self.root)
        self.assertEqual(runner.commands,[])
        self.assertEqual(rec['stream_count'],0)
        self.assertEqual(rec['cleanup'],'unchanged_verified')
        self.assertEqual(rec['status'],'blocked')

    def test_real_unsafe_group_identity_refuses_signal(self):
        import sys
        runner = d.Runner(self.root)
        handle = runner.start([sys.executable, '-c', 'import time;time.sleep(.1)'], .5)
        try:
            with patch.object(d.os, 'getsid', return_value=1), patch.object(d.os, 'killpg') as kill:
                rec, _ = runner.finish(handle)
                kill.assert_not_called()
            self.assertIn('unsafe process-group identity', rec['primary_failure'])
            self.assertFalse(rec['collector_complete'])
        finally:
            handle['proc'].wait(timeout=2)

    def test_nonfinite_and_boolean_deadlines_rejected(self):
        for timeout in (True, float('nan'), float('inf'), '3'):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                d.Runner(self.root).start(['unused'], timeout)

    def collector_fake(self, fail=None):
        outer = self
        class FakeRunner:
            directory = outer.root
            def __init__(self): self.commands = []
            def run(self, argv, timeout):
                c = dict(argv=argv, exit_code=0, timed_out=False, collector_complete=True, eof_before_group_signal=True)
                self.commands.append(c)
                text = '--predicate --level debug ndjson\n --timeout <num>[m|h|d]  timeout'
                if 'boot' in argv and fail == 'boot': c.update(exit_code=-9,timed_out=True)
                if 'shutdown' in argv and fail == 'shutdown': c['exit_code'] = 1
                return c, dict(stdout=text,stderr='')
            def start_stream(self, argv, transform, timeout):
                return self.run(argv, timeout)
            def finish_stream(self, stream):
                if fail == 'stream': raise ValueError('synthetic pipe EOF unknown')
                return stream
        return FakeRunner()

    def test_collector_no_app_commands_and_ordered_cleanup_on_failures(self):
        for failure in (None, 'boot', 'stream', 'shutdown'):
            with self.subTest(failure=failure):
                runner = self.collector_fake(failure)
                initial = dict(state_code=1)
                with patch.object(d, 'collector_identity', return_value=(self.root, initial)), patch.object(d, 'native_timeout_reference', return_value={'help_line':'fixture'}):
                    result = d.capture_collector('iPhone', runner, self.root)
                self.assertEqual(result['launch_count'], 0)
                self.assertLessEqual(result['stream_count'], 1)
                self.assertTrue(all(c['argv'][2] not in ('launch','install','terminate') for c in runner.commands))
                self.assertEqual(runner.commands[-1]['argv'], ['xcrun','simctl','shutdown',d.OWNED['iPhone'][0]])
                self.assertEqual(result['cleanup'], 'failed' if failure == 'shutdown' else 'restored')
                if failure: self.assertEqual(result['status'], 'blocked')
                if failure == 'stream': self.assertIn('synthetic pipe EOF unknown', result['primary_failure'])

    def test_collector_identity_failure_has_no_boot_or_stream(self):
        runner = self.collector_fake()
        with patch.object(d, 'collector_identity', side_effect=ValueError('wrong live identity')):
            result = d.capture_collector('iPhone', runner, self.root)
        self.assertEqual(runner.commands, [])
        self.assertEqual(result['stream_count'], 0)
        self.assertEqual(result['primary_failure'], 'wrong live identity')

    def test_collector_live_identity_matches_exact_scoped_runtime(self):
        family = 'iPhone'
        udid, kind = d.OWNED[family]
        disk = dict(UDID=udid, name='ACS IOS-HOST-002 iPhone', runtime=d.RUNTIME, deviceType=kind, state=1)
        live = dict(udid=udid, name=disk['name'], deviceTypeIdentifier=kind, isAvailable=True, state='Shutdown')
        runner = self.collector_fake()
        def run(argv, timeout):
            self.assertEqual(argv, ['xcrun','simctl','list','devices',udid,'--json'])
            return dict(exit_code=0,timed_out=False,argv=argv), dict(stdout=json.dumps({'devices':{d.RUNTIME:[live]}}))
        runner.run = run
        with patch.object(d, 'device', return_value=(self.root,disk)):
            self.assertEqual(d.collector_identity(family,runner,self.root)[1]['state_code'],1)
            live['udid'] = 'another-device'
            with self.assertRaises(ValueError): d.collector_identity(family,runner,self.root)

    def filtered_command(self):
        nonce = 'a' * 32
        stamp = '2026-10-18T11:00:00+00:00'
        command = dict(argv=['xcrun', 'simctl', 'spawn', d.OWNED['iPhone'][0], 'log', 'stream',
                            '--style', 'ndjson', '--level', 'debug', '--timeout', '5',
                            '--predicate', d.filtered_predicate(nonce)],
                       started_at=stamp, ended_at='2026-10-18T11:00:05+00:00',
                       timeout_seconds=12, exit_code=0, timed_out=False, collector_complete=True,
                       pipe_complete=True, eof_before_group_signal=True, output_truncated=False,
                       pipe_eof=dict(stdout=stamp, stderr=stamp), signals=[dict(at=stamp)],
                       observed_bytes=dict(stdout=0, stderr=0))
        for pipe in ('stdout', 'stderr'):
            command['raw_' + pipe + '_sha256'] = d.digest(b'')
            command['retained_' + pipe + '_sha256'] = d.digest(b'')
        return command, nonce

    def test_filtered_fixed_predicate_and_injection_rejection(self):
        command, nonce = self.filtered_command()
        self.assertEqual(d.filtered_predicate(nonce),
            'process == "SpringBoard" AND eventMessage CONTAINS "IOS-COLLECTOR-FILTERED-007-' + nonce + '"')
        for bad in ('', 'a'*31, 'a'*33, 'A'*32, '" OR TRUEPREDICATE', 'a'*32+'\n', None, 12):
            with self.subTest(bad=bad), self.assertRaises(ValueError): d.filtered_predicate(bad)
        command['argv'][-1] = 'TRUEPREDICATE'
        with self.assertRaisesRegex(ValueError, 'identity'):
            d.filtered_stream_complete(command, d.OWNED['iPhone'][0], nonce)

    def test_filtered_incomplete_truncated_unknown_and_at_cap_never_accept(self):
        command, nonce = self.filtered_command()
        d.filtered_stream_complete(command, d.OWNED['iPhone'][0], nonce)
        for key, value in [('output_truncated', True), ('collector_complete', False),
                           ('eof_before_group_signal', False), ('pipe_complete', False),
                           ('pipe_eof', {}), ('timed_out', True), ('exit_code', -9),
                           ('timeout_seconds', 30), ('observed_bytes', {'stdout':8*1024*1024, 'stderr':0}),
                           ('observed_bytes', {}), ('raw_stdout_sha256', 'f'*64),
                           ('primary_failure', 'first error'),
                           ('pipe_eof', dict(stdout='2026-10-18T11:00:06+00:00', stderr=command['started_at']))]:
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(command)
                changed[key] = value
                with self.assertRaises(ValueError):
                    d.filtered_stream_complete(changed, d.OWNED['iPhone'][0], nonce)

    def test_filtered_capture_one_stream_cleanup_and_first_error(self):
        for failure in (None, 'cap', 'shutdown', 'booted'):
            runner = self.collector_fake('shutdown' if failure == 'shutdown' else None)
            command, nonce = self.filtered_command()
            def start(argv, transform, timeout):
                self.assertIsNone(transform)
                self.assertEqual(timeout, 12)
                command['argv'] = argv
                if failure == 'cap':
                    command.update(output_truncated=True, primary_failure='output byte cap exceeded')
                runner.commands.append(command)
                return command, dict(stdout='', stderr='')
            runner.start_stream = start
            with patch.object(d, 'collector_identity', return_value=(self.root, dict(state_code=3 if failure == 'booted' else 1))), patch.object(d, 'native_timeout_reference', return_value={}):
                result = d.capture_collector('iPhone', runner, self.root, filtered_nonce=nonce)
            self.assertEqual(result['stream_count'], 0 if failure == 'booted' else 1)
            self.assertEqual(result['launch_count'], 0)
            self.assertEqual(result['status'], 'bounded_filtered_system_stream' if failure is None else 'blocked')
            self.assertFalse(any(x['argv'][2] in ('launch', 'install', 'terminate') for x in runner.commands))
            if failure == 'cap': self.assertIn('output byte cap exceeded', result['primary_failure'])
            if failure == 'booted': self.assertEqual(runner.commands, [])
            else: self.assertEqual(runner.commands[-1]['argv'][2], 'shutdown')

    def test_filtered_predecessor_exact_private_identities_read_only(self):
        if not d.COLLECTOR_PREDECESSOR.exists():
            self.skipTest('private predecessor not distributed')
        before = {p: d.digest((d.COLLECTOR_PREDECESSOR / p).read_bytes()) for p in d.COLLECTOR_PINS}
        result = d.inspect_collector_predecessor()
        self.assertEqual(result['head'], d.COLLECTOR_HEAD)
        self.assertIn('blocked unchanged', result['historical_outcome'])
        self.assertEqual(before, {p: d.digest((d.COLLECTOR_PREDECESSOR / p).read_bytes()) for p in before})
        # Reject a changed pin without ever touching the predecessor itself.
        changed = dict(d.COLLECTOR_PINS)
        changed[next(iter(changed))] = '0' * 64
        with patch.object(d, 'COLLECTOR_PINS', changed), self.assertRaisesRegex(ValueError, 'hash mismatch'):
            d.inspect_collector_predecessor()

    def test_filtered_preflight_blocks_before_any_simulator_command(self):
        output = self.root / '.local/fresh/receipt.json'
        with patch.object(d, 'inspect_collector_predecessor', side_effect=ValueError('predecessor changed')), patch.object(d, 'Runner') as runner:
            with self.assertRaisesRegex(ValueError, 'predecessor changed'):
                d.collect_filtered_collector(output)
            runner.assert_not_called()
        self.assertFalse(output.parent.exists())

    def test_filtered_predecessor_temporary_git_and_output_mutation(self):
        root = self.root / 'collector'
        (root / 'tools').mkdir(parents=True)
        (root / 'tools/diagnose_ios_scene.py').write_text('original fixture source\n')
        def git(*args):
            return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()
        git('init', '--quiet')
        git('add', 'tools/diagnose_ios_scene.py')
        git('-c', 'user.name=Offline Fixture', '-c', 'user.email=fixture@invalid',
            '-c', 'commit.gpgsign=false', 'commit', '--quiet', '-m', 'original fixture')
        head = git('rev-parse', 'HEAD')
        pins = {'tools/diagnose_ios_scene.py': d.digest((root / 'tools/diagnose_ios_scene.py').read_bytes())}
        for area in ('live', 'closeout'):
            directory = root / '.local/ios-collector-006' / area
            directory.mkdir(parents=True)
            d.write(directory / 'command-001.json', dict(stdout='', stderr=''))
            d.write(directory / 'receipt.json', dict(commands=[dict(output='command-001.json',
                sha256=d.digest((directory / 'command-001.json').read_bytes()))]))
            name = str((directory / 'receipt.json').relative_to(root))
            pins[name] = d.digest((root / name).read_bytes())
        delivery = root.parent / 'IOS-SCENE-DELIVERY-005/.local/ios-scene-delivery/receipt.json'
        delivery.parent.mkdir(parents=True)
        delivery.write_text('{"synthetic":true}\n')
        with patch.object(d, 'COLLECTOR_PREDECESSOR', root), patch.object(d, 'COLLECTOR_HEAD', head), patch.object(d, 'COLLECTOR_PINS', pins), patch.object(d, 'COLLECTOR_DELIVERY_SHA', d.digest(delivery.read_bytes())):
            self.assertEqual(d.inspect_collector_predecessor()['head'], head)
            (root / '.local/ios-collector-006/live/command-001.json').write_text('tampered output')
            with self.assertRaisesRegex(ValueError, 'command output mismatch'):
                d.inspect_collector_predecessor()
            (root / 'tools/diagnose_ios_scene.py').write_text('dirty source')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                d.inspect_collector_predecessor()



if __name__ == '__main__':
    unittest.main()
