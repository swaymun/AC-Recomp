import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('probe', ROOT / 'tools/run_mac_prepo_native.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def retain_failure_evidence(test, root, **captured):
    """Copy a failed fixture's private evidence before temporary cleanup.

    Opt-in via ACS_TEST_EVIDENCE_DIR; the destination must be fresh. Assertions
    are unchanged: callers re-raise after retention.
    """
    base = os.environ.get('ACS_TEST_EVIDENCE_DIR')
    if not base:
        return None
    destination = probe.fresh_path(Path(base) / f'{test.id()}-{time.time_ns()}')
    shutil.copytree(root, destination / 'fixture', symlinks=True)
    (destination / 'captured.json').write_text(json.dumps(captured, indent=2, default=str) + '\n')
    return destination


@unittest.skipUnless(os.name == 'posix', 'POSIX owned groups required')
class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def run_fake(self, source, **kwargs):
        script = self.root / 'fake.py'
        script.write_text(source)
        return probe.supervise([sys.executable, str(script)], self.root / 'evidence',
                               guest_seconds=1, total_seconds=15,
                               term_grace=0.3, kill_grace=0.8, **kwargs)

    def test_exit_and_private_evidence(self):
        r = self.run_fake("import sys; print('fixture output'); sys.exit(7)")
        self.assertTrue(r['control_passed'])
        self.assertEqual(r['returncode'], 7)
        self.assertFalse(r['timed_out'])
        self.assertEqual(r['pid'], r['pgid'])
        self.assertNotEqual(r['pgid'], os.getpgrp())
        saved = json.loads((self.root / 'evidence/receipt.json').read_text())
        self.assertTrue(saved['cleanup_verified'])
        self.assertEqual((self.root / 'evidence/stdout.log').read_text(), 'fixture output\n')

    def test_term_then_kill_and_unrelated_sentinel(self):
        sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'],
                                    start_new_session=True)
        self.addCleanup(lambda: sentinel.poll() is None and sentinel.kill())
        try:
            r = self.run_fake('import signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(10)')
            self.assertTrue(r['timed_out'])
            self.assertEqual(r['signals'], ['SIGTERM', 'SIGKILL'])
            self.assertEqual(r['signal'], signal.SIGKILL)
            self.assertTrue(r['cleanup_verified'], r)
            self.assertLess(r['elapsed_seconds'], 5)
            self.assertIsNone(sentinel.poll())
        finally:
            sentinel.kill()
            sentinel.wait(timeout=2)

    def test_leftover_descendant_after_leader_exit(self):
        r = self.run_fake('import os,time\npid=os.fork()\nif pid == 0: time.sleep(10)\nelse: print(pid, flush=True)')
        self.assertTrue(r['control_passed'], r)
        child = int((self.root / 'evidence/stdout.log').read_text())
        self.assertNotIn(child, probe.process_table())
        self.assertIn('SIGTERM', r['signals'])

    def test_observed_escape_rejected_without_signalling_other_group(self):
        # A real fork/setsid child remains briefly visible under its parent.
        # It exits by itself; the supervisor may only signal the original group.
        r = self.run_fake('import os,time\npid=os.fork()\nif pid == 0:\n os.setsid(); time.sleep(5); os._exit(0)\nelse: time.sleep(10)')
        self.assertFalse(r['control_passed'])
        self.assertFalse(r['cleanup_verified'])
        self.assertEqual(len(r['escaped_descendants']), 1)
        self.assertEqual(r['remaining_group_members'], [])

    def test_retired_group_escape_requires_observed_pid_absence(self):
        r = self.run_fake('import os,time\npid=os.fork()\nif pid == 0:\n os.setsid(); time.sleep(0.1); os._exit(0)\nelse: time.sleep(0.22); os.waitpid(pid,0)')
        self.assertTrue(r['control_passed'], r)
        self.assertTrue(r['cleanup_verified'], r)
        self.assertEqual(len(r['escaped_descendants']), 1)
        self.assertEqual(r['remaining_observed_descendants'], [])
        self.assertEqual(r['remaining_group_members'], [])

    def test_fail_closed_if_inventory_unavailable(self):
        with patch.object(probe, 'process_table', side_effect=RuntimeError('fixture')):
            r = self.run_fake('raise AssertionError("must not launch")')
        self.assertIsNone(r['pid'])
        self.assertFalse(r['control_passed'])
        self.assertFalse(r['cleanup_verified'])

    def test_post_launch_inventory_failure_never_certifies(self):
        original = probe.process_table
        calls = 0
        def inventory():
            nonlocal calls
            calls += 1
            if calls > 1:
                raise RuntimeError('fixture inspection failure')
            return original()
        with patch.object(probe, 'process_table', side_effect=inventory):
            r = self.run_fake('import time; time.sleep(10)')
        self.assertFalse(r['control_passed'])
        self.assertFalse(r['cleanup_verified'])
        self.assertIsNotNone(r['returncode'])
        self.assertLess(r['elapsed_seconds'], 5)

    def test_reject_invalid_budgets_and_existing_evidence(self):
        for value in [41, float('inf'), float('nan'), -1]:
            with self.assertRaises(ValueError):
                probe.supervise(['false'], self.root / 'bad', guest_seconds=value)
        existing = self.root / 'existing'
        existing.mkdir()
        with self.assertRaises(FileExistsError):
            probe.supervise(['false'], existing)

    def test_owned_build_bound_with_fake_compiler(self):
        r = probe.supervise([sys.executable, '-c', 'print("synthetic compiler")'],
                            self.root/'build', cwd=self.root, mode='build',
                            guest_seconds=1, total_seconds=12,
                            term_grace=.1, kill_grace=.2)
        self.assertTrue(r['control_passed'], r)
        self.assertEqual(r['returncode'], 0)
        self.assertEqual(r['mode'], 'build')
        for kwargs in ({'mode':'build','total_seconds':901},
                       {'mode':'build','guest_seconds':891},
                       {'mode':'session','guest_seconds':601,'total_seconds':630},
                       {'mode':'session','guest_seconds':600,'total_seconds':631},
                       {'mode':'guest','guest_seconds':41},
                       {'mode':'other'}):
            with self.assertRaises(ValueError):
                probe.supervise(['false'],self.root/'bad',**kwargs)

    def test_guest_exit_before_session_check(self):
        # Reproduces the 089 failure: a fast guest exits before the session
        # check, where macOS getpgid/getsid raise ESRCH for the zombie.
        real = subprocess.Popen
        class ExitedBeforeReturn(real):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                if not kwargs.get('start_new_session'):
                    return  # the supervisor's own inventory commands
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if probe.process_table().get(self.pid, (0, 0, ''))[2].startswith('Z'):
                        break
                    time.sleep(0.02)
                else:
                    raise AssertionError('fixture guest did not exit')
        with patch.object(probe.subprocess, 'Popen', ExitedBeforeReturn):
            r = self.run_fake('print("fast")')
        self.assertTrue(r['control_passed'], r)
        self.assertEqual(r['errors'], [])
        self.assertEqual(r['returncode'], 0)
        self.assertEqual(r['signals'], [])
        self.assertTrue(r['cleanup_verified'], r)
        self.assertIn('session_checked_via', r)

    def test_slow_inventory_retried_within_bounds(self):
        original = probe.process_table
        calls = []
        def inventory():
            calls.append(1)
            if len(calls) in (3, 4):  # two consecutive slow inventories while the guest runs
                raise subprocess.TimeoutExpired(['ps'], 1)
            return original()
        with patch.object(probe, 'process_table', side_effect=inventory):
            r = self.run_fake('import time; time.sleep(0.3)')
        self.assertTrue(r['control_passed'], r)
        self.assertEqual(r['inventory_timeouts'], 2)
        self.assertEqual(r['errors'], [])

    def test_persistently_slow_inventory_never_certifies(self):
        original = probe.process_table
        calls = []
        def inventory():
            calls.append(1)
            if len(calls) > 2:
                raise subprocess.TimeoutExpired(['ps'], 1)
            return original()
        with patch.object(probe, 'process_table', side_effect=inventory):
            r = self.run_fake('import time; time.sleep(10)')
        self.assertFalse(r['control_passed'])
        self.assertFalse(r['cleanup_verified'])
        self.assertIn('process inventory unavailable: TimeoutExpired', r['errors'])
        self.assertIn('SIGTERM', r['signals'])
        self.assertLess(r['elapsed_seconds'], 15)
        deadline = time.monotonic() + 5
        while r['pid'] in original() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertNotIn(r['pid'], original())

    def test_exited_guest_without_owned_group_row_fails_closed(self):
        # The session check (second inventory) sees no row for the guest; later
        # inventories are real so the live guest is still cleaned up.
        original = probe.process_table
        calls = []
        def inventory():
            rows = original()
            calls.append(set(rows))
            if len(calls) == 2:
                return {pid: row for pid, row in rows.items() if pid in calls[0]}
            return rows
        with patch.object(probe.os, 'getpgid', side_effect=ProcessLookupError), \
                patch.object(probe, 'process_table', side_effect=inventory):
            r = self.run_fake('import time; time.sleep(10)')
        self.assertFalse(r['control_passed'])
        self.assertIn('launch or supervision failed', r['errors'])
        self.assertNotIn('session_checked_via', r)
        self.assertTrue(r['cleanup_verified'], r)
        self.assertNotIn(r['pid'], probe.process_table())

    def test_leader_exit_during_timeout_signal_is_not_a_failure(self):
        # The guest exits between the supervisor's reap and inventory, so the
        # group holds only its unreaped zombie and macOS refuses killpg (EPERM).
        real = os.killpg
        calls = []
        def killpg(pgid, sig):
            calls.append(sig)
            if len(calls) == 1:
                real(pgid, signal.SIGKILL)
                deadline = time.monotonic() + 5
                while not probe.process_table().get(pgid, (0, 0, 'Z'))[2].startswith('Z'):
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.02)
                return real(pgid, sig)
            return real(pgid, sig)
        with patch.object(probe.os, 'killpg', side_effect=killpg):
            r = self.run_fake('import time; time.sleep(10)')
        self.assertTrue(r['timed_out'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(r['errors'], [])
        self.assertTrue(r['control_passed'], r)
        self.assertEqual(r['signal'], signal.SIGKILL)

    def test_cli_from_temporary_git_repository_no_shell(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        run = probe.copy_inputs({}, self.root / 'isolation')
        command = [sys.executable, str(ROOT / 'tools/run_mac_prepo_native.py'),
                   '--run-root', str(run), '--loader', '/fixture/loader',
                   '--profile', '/fixture/profile',
                   '--evidence', str(run / 'cli'), '--guest-seconds', '0.2',
                   '--', sys.executable, '-c', 'print("$(touch forbidden)")']
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=8)
        try:
            self.assertEqual(result.returncode, 0, (result.stderr, result.stdout))
            self.assertTrue(json.loads(result.stdout)['control_passed'])
            self.assertFalse((self.root / 'forbidden').exists())
            status = subprocess.run(['git', 'status', '--porcelain'], cwd=self.root,
                                    capture_output=True, text=True, check=True)
            self.assertIn('?? isolation/', status.stdout)
        except AssertionError:
            retain_failure_evidence(self, self.root, returncode=result.returncode,
                                    stdout=result.stdout, stderr=result.stderr,
                                    process_table=probe.process_table())
            raise

    def test_session_mode_bounds_and_cleanup(self):
        r = probe.supervise([sys.executable, '-c', 'import time; time.sleep(30)'], self.root/'session',
                            cwd=self.root, mode='session', guest_seconds=1, total_seconds=13,
                            term_grace=.3, kill_grace=.8)
        self.assertTrue(r['control_passed'], r)
        self.assertEqual(r['mode'], 'session')
        self.assertTrue(r['timed_out'])
        self.assertNotIn(r['pid'], probe.process_table())
        r = probe.supervise([sys.executable, '-c', 'pass'], self.root/'session-max', cwd=self.root,
                            mode='session', guest_seconds=600, total_seconds=630)
        self.assertTrue(r['control_passed'], r)

    def test_cli_rejects_traversal_outside_run_root(self):
        run = probe.copy_inputs({}, self.root/'isolation')
        command = [sys.executable, str(ROOT/'tools/run_mac_prepo_native.py'),
                   '--run-root', str(run), '--loader', '/fixture/loader',
                   '--profile', '/fixture/profile', '--evidence', str(run/'../outside'),
                   '--', sys.executable, '-c', 'raise AssertionError("must not run")']
        r = subprocess.run(command, capture_output=True, text=True, timeout=8)
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.root/'outside').exists())


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.inputs = {}
        for name in ('analysis', 'extract', 'spirv'):
            p = self.base / 'canonical' / name
            p.mkdir(parents=True)
            (p / 'input.bin').write_bytes(b'canonical immutable fixture')
            self.inputs[name] = p

    def prepare(self, name='run'):
        return probe.copy_inputs(self.inputs, self.base / name)

    def test_fresh_copy_and_hostile_environment_actual_subprocess(self):
        canonical = self.base / 'canonical'
        old = canonical / 'frames'
        old.mkdir()
        (old / 'prior.ppm').write_text('prior evidence')
        root = self.prepare()
        profile = root / 'astral.profile'
        profile.write_text('synthetic')
        hostile = {'PATH': os.environ['PATH'], 'NX_DATA_ROOT': str(canonical),
                   'NX_LOG': str(canonical / 'old.log'),
                   'NX_DUMP_TEXTURES': 'deadbeef', 'NX_DUMP_RAW': '0',
                   'NX_DUMP_ON_FS': 'any', 'NX_AUDIO_DUMP': str(canonical / 'audio'),
                   'NX_TRACE_PASSES': str(canonical / 'trace'),
                   'DYLD_INSERT_LIBRARIES': '/hostile', 'VK_ICD_FILENAMES': '/hostile',
                   'SDL_VULKAN_LIBRARY': '/hostile', 'NX_UNKNOWN_FUTURE_DEBUG': '1'}
        env = probe.frozen_environment(root, '/synthetic/loader', profile, hostile)
        self.assertEqual(set(k for k in env if k.startswith('NX_')),
                         {'NX_DATA_ROOT', 'NX_LOG', 'NX_TRACE', 'NX_NVN_REAL',
                          'NX_DUMP_FRAMES', 'NX_DUMP_SHADER_MISSES',
                          'NX_TRACE_PROGRAMS', 'NX_TRACE_PIPELINES', 'NX_NVN_FORMAT_PROFILE'})
        self.assertNotIn('DYLD_INSERT_LIBRARIES', env)
        self.assertNotIn('VK_ICD_FILENAMES', env)
        script = """import os,pathlib
r=pathlib.Path(os.environ['NX_DATA_ROOT'])
(r/'frames/00001.ppm').write_text('synthetic, never game evidence')
(r/'user/prepo').mkdir()
(r/'user/prepo/report.bin').write_bytes(b'fixture')
pathlib.Path(os.environ['NX_LOG']).write_text('trace')
pathlib.Path('relative-output').write_text('cwd')
(r/'extract/input.bin').write_text('changed private copy')
"""
        result = probe.supervise([sys.executable, '-c', script], root / 'receipt',
                                 cwd=root / 'cwd', env=env, guest_seconds=1,
                                 total_seconds=12, term_grace=.1, kill_grace=.2)
        self.assertTrue(result['control_passed'], result)
        self.assertEqual(result['returncode'], 0)
        self.assertEqual((old/'prior.ppm').read_text(), 'prior evidence')
        self.assertEqual((self.inputs['extract']/'input.bin').read_bytes(), b'canonical immutable fixture')
        self.assertFalse((canonical/'old.log').exists())
        self.assertTrue((root/'cwd/relative-output').exists())
        self.assertFalse((root/'data/frames/prior.ppm').exists())
        for name, source in self.inputs.items():
            self.assertNotEqual((source/'input.bin').stat().st_ino,
                                (root/'data'/name/'input.bin').stat().st_ino)
        probe.assert_isolated(root)
        second = self.prepare('second')
        self.assertEqual(list((second/'data/frames').iterdir()), [])

    def test_frame_dump_interval(self):
        root = self.prepare()
        self.assertEqual(probe.frozen_environment(root, '/l', '/p')['NX_DUMP_FRAMES'], '1')
        self.assertEqual(probe.frozen_environment(root, '/l', '/p', dump_every=10)['NX_DUMP_FRAMES'], '10')
        for bad in (0, -1, 601, 2.5, True, '10'):
            with self.assertRaises(ValueError):
                probe.frozen_environment(root, '/l', '/p', dump_every=bad)

    def test_existing_output_link_or_directory_rejected(self):
        target = self.base / 'canonical'
        old = self.base / 'old'
        old.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            probe.copy_inputs(self.inputs, old)
        with self.assertRaises(ValueError):
            probe.copy_inputs(self.inputs, old/'new')
        root = self.prepare()
        with self.assertRaises(FileExistsError):
            self.prepare()
        (root/'data/frames').rmdir()
        (root/'data/frames').symlink_to(target)
        with self.assertRaises(ValueError):
            probe.frozen_environment(root, '/loader', '/profile')
        self.assertFalse((target/'guest.log').exists())

    def test_internal_input_links_and_hardlinked_outputs_rejected(self):
        bad = self.inputs['analysis']/'bad'
        bad.symlink_to(self.inputs['extract'])
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse((self.base/'run').exists())
        bad.unlink()
        root = self.prepare()
        os.link(self.inputs['analysis']/'input.bin', root/'trace/escape')
        with self.assertRaises(ValueError):
            probe.assert_isolated(root)

    def test_destination_inside_canonical_input_rejected_before_write(self):
        target = self.inputs['extract']/'new-output'
        with self.assertRaises(ValueError):
            probe.copy_inputs(self.inputs, target)
        self.assertFalse(target.exists())

    def test_unknown_input_tree_rejected(self):
        with self.assertRaises(ValueError):
            probe.copy_inputs({'frames': self.inputs['analysis']}, self.base/'run')


if __name__ == '__main__':
    unittest.main()
