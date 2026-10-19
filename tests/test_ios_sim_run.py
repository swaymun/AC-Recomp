"""tools/ios_sim_run.py against a mock `xcrun simctl` and `codesign` (no simulator, CPU only)."""
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/ios_sim_run.py'

FAKE_XCRUN = textwrap.dedent(r'''
    #!/usr/bin/env python3
    import json, os, sys
    from pathlib import Path
    state = Path(os.environ['FAKE_STATE'])
    args = sys.argv[1:]
    with (state / 'calls.jsonl').open('a') as f:
        f.write(json.dumps({'args': args, 'env': {k: v for k, v in os.environ.items() if k.startswith('SIMCTL_CHILD_')}}) + '\n')
    mode = os.environ.get('FAKE_MODE', 'ok')
    assert args[0] == 'simctl'
    cmd = args[1]
    container = state / 'container'
    if cmd == 'list':
        print(json.dumps({
            'runtimes': [{'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-26-5', 'version': '26.5', 'buildversion': '23F77', 'isAvailable': True, 'platform': 'iOS'},
                         {'identifier': 'com.apple.CoreSimulator.SimRuntime.iOS-27-1', 'version': '27.1', 'buildversion': '24A', 'isAvailable': True, 'platform': 'iOS'}],
            'devicetypes': [{'name': 'iPhone 17 Pro', 'identifier': 'com.apple.CoreSimulator.SimDeviceType.iPhone-17-Pro'},
                            {'name': 'iPad Pro 13-inch (M5)', 'identifier': 'com.apple.CoreSimulator.SimDeviceType.iPad-Pro-13'}],
            'devices': {'x': [{'udid': 'OFF-1', 'state': 'Shutdown', 'name': 'off'}]
                        + ([{'udid': 'BOOTED-1', 'state': 'Booted', 'name': 'other'}] if mode == 'other-booted' else [])}}))
    elif cmd == 'create':
        print('NEW-UDID')
    elif cmd == 'boot' and mode == 'boot-fails':
        print('boom', file=sys.stderr); sys.exit(3)
    elif cmd == 'get_app_container':
        (container / 'Documents').mkdir(parents=True, exist_ok=True)
        print(container)
    elif cmd == 'launch':
        docs = container / 'Documents'
        log = 'astral strict boot\nnvn/vk: per frame over 60: 30.0 fps, 1.0 submits\n'
        if mode == 'fatal':
            log += 'FATAL: strict IPC missing command: service=X command=1\n'
        (docs / 'guest.log').write_text(log)
        (docs / 'startup.jsonl').write_text('{"stage":"main"}\n')
        root = os.environ.get('SIMCTL_CHILD_NX_DATA_ROOT')
        if root:
            (Path(root) / 'frames').mkdir(exist_ok=True)
            (Path(root) / 'frames' / '00300.ppm').write_bytes(b'P6 1 1 255 abc')
        print(f'local.acs.astral-sim: {os.getppid() if mode != "dead" else 999999}')
    elif cmd == 'io':
        Path(args[-1]).write_bytes(b'\x89PNG fake')
    ''').lstrip()

FAKE_CODESIGN = '#!/bin/sh\necho "$@" >> "$FAKE_STATE/codesign.txt"\n'
FAKE_PS = ('#!/bin/sh\necho "  1 /sbin/launchd"\n'
           'if [ "$FAKE_MODE" = game-running ]; then echo " 4242 /private/var/x/Sim/Bundle/astral.app/astral --evidence-run y"; fi\n')


class IosSimRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.state = self.d / 'state'
        self.state.mkdir()
        self.xcrun = self.d / 'xcrun'
        self.xcrun.write_text(FAKE_XCRUN.replace('/usr/bin/env python3', sys.executable))
        self.codesign = self.d / 'codesign'
        self.codesign.write_text(FAKE_CODESIGN)
        self.ps = self.d / 'ps'
        self.ps.write_text(FAKE_PS)
        for p in (self.xcrun, self.codesign, self.ps):
            p.chmod(0o755)
        self.app = self.d / 'astral.app'
        self.app.mkdir()
        (self.app / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable': 'ACSRescue', 'CFBundleIdentifier': 'old'}))
        exe = self.app / 'astral'
        exe.write_text('binary')
        exe.chmod(0o755)
        self.data = self.d / 'data'
        self.data.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *extra, mode='ok', inherited=None):
        env = dict(os.environ, FAKE_STATE=str(self.state), FAKE_MODE=mode, ACS_PS=str(self.ps), **(inherited or {}))
        out = self.d / 'out'
        proc = subprocess.run([sys.executable, str(TOOL), '--app', str(self.app), '--device-type', 'iPhone 17 Pro',
                               '--seconds', '2', '--screenshot-every', '1', '--data-root', str(self.data),
                               '--xcrun', str(self.xcrun), '--codesign', str(self.codesign), '--out', str(out),
                               '--env', 'NX_PERF_HUD=1', *extra], capture_output=True, text=True, env=env, timeout=60)
        calls = [json.loads(l) for l in (self.state / 'calls.jsonl').read_text().splitlines()]
        summary = json.loads((out / 'summary.json').read_text())
        return proc, calls, summary, out

    def commands(self, calls):
        return [c['args'][1] for c in calls]

    def test_completed_run_collects_and_always_cleans_up(self):
        proc, calls, summary, out = self.run_tool()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(summary['status'], 'completed')
        self.assertEqual(summary['runtime']['version'], '27.1')  # newest by default
        cmds = self.commands(calls)
        self.assertEqual(cmds[:2], ['list', 'create'])
        self.assertLess(cmds.index('get_app_container'), cmds.index('launch'))
        self.assertEqual(cmds[-3:], ['terminate', 'shutdown', 'delete'])
        launch = next(c for c in calls if c['args'][1] == 'launch')
        self.assertEqual(launch['env']['SIMCTL_CHILD_NX_PERF_HUD'], '1')
        self.assertEqual(launch['env']['SIMCTL_CHILD_NX_DATA_ROOT'], str(self.data.resolve()))
        self.assertIn('--terminate-running-process', launch['args'])
        self.assertTrue(summary['screenshots'])
        self.assertEqual(summary['collected']['frames'], 1)
        self.assertTrue((out / 'frames/00300.ppm').is_file())
        self.assertFalse((self.data / 'frames/00300.ppm').exists())
        self.assertTrue((out / 'guest.log').is_file())
        self.assertEqual(summary['last_fps_in_log'], '30.0')
        staged = plistlib.loads((out / 'astral.app/Info.plist').read_bytes())
        self.assertEqual(staged['CFBundleExecutable'], 'astral')
        self.assertEqual(staged['CFBundleIdentifier'], 'local.acs.astral-sim')
        self.assertIn('--sign -', (self.state / 'codesign.txt').read_text())

    def test_fatal_stops_early_and_cleans_up(self):
        proc, calls, summary, _ = self.run_tool('--seconds', '30', mode='fatal')
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary['status'], 'fatal')
        self.assertIn('strict IPC missing command', summary['fatal'])
        self.assertLess(summary['elapsed'], 20)
        self.assertEqual(self.commands(calls)[-3:], ['terminate', 'shutdown', 'delete'])

    def test_exited_process_is_detected(self):
        proc, calls, summary, _ = self.run_tool('--seconds', '30', mode='dead')
        self.assertEqual(summary['status'], 'exited')
        self.assertEqual(self.commands(calls)[-3:], ['terminate', 'shutdown', 'delete'])

    def test_boot_failure_still_shuts_down_and_deletes_created_device(self):
        proc, calls, summary, _ = self.run_tool(mode='boot-fails')
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(summary['status'], 'error')
        cmds = self.commands(calls)
        self.assertNotIn('launch', cmds)
        self.assertEqual(cmds[-2:], ['shutdown', 'delete'])

    def test_existing_device_must_be_shutdown_and_is_never_deleted(self):
        proc, calls, summary, _ = self.run_tool('--udid', 'BOOTED-1', mode='other-booted')
        self.assertEqual(summary['status'], 'error')
        self.assertNotIn('boot', self.commands(calls))
        proc, calls, summary, _ = self.run_tool('--udid', 'OFF-1', '--runtime', '26.5')
        self.assertEqual(summary['status'], 'completed')
        cmds = self.commands(calls)
        self.assertNotIn('create', cmds)
        self.assertNotIn('delete', cmds)
        self.assertEqual(cmds[-1], 'shutdown')
        self.assertEqual(summary['runtime']['version'], '26.5')

    def test_bad_env_and_unknown_device_type_fail_without_simulator_mutation(self):
        (self.state / 'calls.jsonl').write_text('')
        proc, calls, summary, _ = self.run_tool('--env', 'not a pair')
        self.assertEqual(summary['status'], 'error')
        self.assertEqual(self.commands(calls), [])
        proc = subprocess.run([sys.executable, str(TOOL), '--app', str(self.app), '--device-type', 'Toaster',
                               '--xcrun', str(self.xcrun), '--codesign', str(self.codesign), '--out', str(self.d / 'o2')],
                              capture_output=True, text=True, env=dict(os.environ, FAKE_STATE=str(self.state)), timeout=60)
        self.assertEqual(proc.returncode, 1)
        self.assertIn('unknown simulator device type', json.loads((self.d / 'o2/summary.json').read_text())['error'])
        self.assertNotIn('create', self.commands([json.loads(l) for l in (self.state / 'calls.jsonl').read_text().splitlines()]))

    def test_one_game_simulator_at_a_time(self):
        for mode, needle in (('other-booted', 'other simulators are booted'),
                             ('game-running', 'a game instance is already running')):
            (self.state / 'calls.jsonl').write_text('')
            proc, calls, summary, _ = self.run_tool(mode=mode)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(summary['status'], 'error')
            self.assertIn(needle, summary['error'])
            self.assertEqual(self.commands(calls), ['list'])  # nothing created, booted or launched

    def test_gpu_timeout_above_the_clamp_is_refused(self):
        for value in ('6', '120', '0', 'abc'):
            (self.state / 'calls.jsonl').write_text('')
            proc, calls, summary, _ = self.run_tool('--env', f'NX_GPU_TIMEOUT_S={value}')
            self.assertEqual(summary['status'], 'error', value)
            self.assertIn('NX_GPU_TIMEOUT_S', summary['error'])
            self.assertEqual(self.commands(calls), [])
        proc, calls, summary, _ = self.run_tool('--env', 'NX_GPU_TIMEOUT_S=5')
        self.assertEqual(summary['status'], 'completed')

    def test_gpu_heavy_settings_are_refused(self):
        for pair in ('NX_PIPELINED=3', 'NX_ASYNC_GPU=4', 'NX_PIPELINED=x', 'NX_DUMP_TEXTURES=1',
                     'NX_DUMP_ON_TARGET=7104690ed8', 'NX_DUMP_ON_FS=abc'):
            (self.state / 'calls.jsonl').write_text('')
            proc, calls, summary, _ = self.run_tool('--env', pair)
            self.assertEqual(summary['status'], 'error', pair)
            self.assertIn(pair.split('=')[0], summary['error'])
            self.assertEqual(self.commands(calls), [], pair)
        proc, calls, summary, _ = self.run_tool('--env', 'NX_PIPELINED=2', '--env', 'NX_ASYNC_GPU=1')
        self.assertEqual(summary['status'], 'completed')

    def test_inherited_simctl_child_variables_do_not_reach_the_app(self):
        proc, calls, summary, _ = self.run_tool(inherited={'SIMCTL_CHILD_NX_GPU_TIMEOUT_S': '120',
                                                           'SIMCTL_CHILD_NX_DUMP_TEXTURES': '1'})
        self.assertEqual(summary['status'], 'completed')
        launch = next(c for c in calls if c['args'][1] == 'launch')
        self.assertEqual(sorted(launch['env']), ['SIMCTL_CHILD_NX_DATA_ROOT', 'SIMCTL_CHILD_NX_PERF_HUD'])

    def test_failed_boot_of_an_existing_device_still_shuts_it_down(self):
        proc, calls, summary, _ = self.run_tool('--udid', 'OFF-1', mode='boot-fails')
        self.assertEqual(summary['status'], 'error')
        cmds = self.commands(calls)
        self.assertEqual(cmds[-1], 'shutdown')
        self.assertNotIn('delete', cmds)


if __name__ == '__main__':
    unittest.main()
