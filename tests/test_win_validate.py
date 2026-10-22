"""Offline validation of SSH orchestration and real capture metrics; no VM needed."""
import base64
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('win_validate', ROOT / 'tools/win_validate.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class DriverTest(unittest.TestCase):
    def test_linked_worktree_uses_common_private_store(self):
        with tempfile.TemporaryDirectory() as d:
            repo, linked = Path(d)/'repo', Path(d)/'linked'
            env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull}
            subprocess.run(['git','init','-q',str(repo)],check=True,capture_output=True,env=env)
            subprocess.run(['git','-C',str(repo),'-c','user.name=Fixture','-c','user.email=fixture@local',
                            'commit','-q','--allow-empty','-m','fixture'],check=True,capture_output=True,env=env)
            subprocess.run(['git','-C',str(repo),'worktree','add','-q','--detach',str(linked)],
                           check=True,capture_output=True,env=env)
            expected=repo.resolve()/'.local/units'/w.UNIT
            self.assertEqual(w.default_private(repo),expected)
            self.assertEqual(w.default_private(linked),expected)

    def test_powershell_round_trip_with_quotes_and_unicode(self):
        script = "$x=" + w.ps("C:\\A B\\o'hare-雪")
        with patch.object(w.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'ok', '')) as run:
            self.assertEqual(w.VM().run(script), 'ok')
        argv = run.call_args.args[0]
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(argv[:6], ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'acr-win'])
        self.assertEqual(base64.b64decode(argv[-1]).decode('utf-16le'), '$ErrorActionPreference="Stop"\n' + script)

    def test_nonzero_ssh_fails(self):
        with patch.object(w.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7, '', 'broken')):
            with self.assertRaisesRegex(RuntimeError, 'exit 7'):
                w.VM().run('exit 7')

    def test_real_subprocess_fake_ssh(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / 'ssh'
            fake.write_text('#!' + sys.executable + '\nimport sys,base64\ns=base64.b64decode(sys.argv[-1]).decode("utf-16le")\nprint("encoded-ok" if "雪" in s else "bad")\n')
            fake.chmod(0o755)
            self.assertEqual(w.VM(ssh=str(fake)).run("Write-Output '雪'"), 'encoded-ok')

    def test_large_unicode_write_fits_windows_commands_and_preserves_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            fake, output = Path(d)/'ssh', Path(d)/'transferred.bin'
            fake.write_text('#!' + sys.executable + '\n' +
                'import sys,base64,re,pathlib\n' +
                'assert len(" ".join(sys.argv)) < 30000\n' +
                's=base64.b64decode(sys.argv[-1]).decode("utf-16le")\n' +
                'b=base64.b64decode(re.search("FromBase64String\\\\(\'([^\']*)\'",s).group(1))\n' +
                'p=pathlib.Path(' + repr(str(output)) + ')\n' +
                'with p.open("wb" if "WriteAllBytes" in s else "ab") as f: f.write(b)\n')
            fake.chmod(0o755)
            vm=w.VM(ssh=str(fake))
            payload=('controller 雪\n'*5000)
            vm.write(w.REMOTE+'\\large.jsonl', payload)
            self.assertEqual(output.read_bytes(),payload.encode('utf-8'))
            vm.write(w.REMOTE+'\\large.jsonl','')
            self.assertEqual(output.read_bytes(),b'')

    def test_ownership_guards(self):
        for bad in [r'C:\acr\data\x', w.REMOTE + r'\..\OTHER\x', w.REMOTE + '-other\\x']:
            with self.assertRaises(ValueError):
                w.owned_remote(bad)
        self.assertEqual(w.owned_remote(w.REMOTE + '\\build\\astral.exe'), w.REMOTE + '\\build\\astral.exe')
        with self.assertRaises(ValueError):
            w.VM('-oProxyCommand=bad')
        with self.assertRaises(ValueError):
            w.VM().launch(w.REMOTE+'\\a.exe', w.REMOTE, w.REMOTE, {'NX_SECRET': 'no'})

    def test_pad_releases_normalisation_and_range_checks(self):
        states = [json.loads(l) for l in w.pad_script([{'left_trigger': 255, 'right_trigger': 255, 'ms': 500}], True).splitlines()]
        self.assertEqual(len(states), 8)
        self.assertEqual(states[:2], [{'buttons': ['A'], 'ms': 140}, {'ms': 300}])
        self.assertEqual(states[-1], {'ms': 250})
        warmed = [json.loads(l) for l in w.pad_script([], True, 15000).splitlines()]
        self.assertEqual(warmed[0], {'ms':15000})
        self.assertEqual(warmed[1]['buttons'], ['A'])
        for state in [{'buttons':['not-a-button']}, {'ms': 60001}, {'left_trigger': -1}, {'lx': 40000}, {'ms': True}, {'other': 3}]:
            with self.assertRaises(ValueError):
                w.pad_script([state])

    def test_interactive_tasks_restore_only_owned_game_focus(self):
        vm = w.VM()
        with patch.object(vm, 'write') as write, patch.object(vm, 'run', return_value='{"SessionId":2}'):
            vm.task('Write-Output "capture"', 'focus-test')
        code = write.call_args.args[1]
        self.assertIn('SetForegroundWindow', code)
        self.assertIn(w.REMOTE, code)
        self.assertIn('No owned visible desktop game', code)
        self.assertLess(code.index('No owned visible'), code.index('SetCursorPos(0,0)'))
        self.assertLess(code.index('SetForegroundWindow'), code.index('Write-Output'))

    def test_pid_publication_race_recovers_exact_job_without_relaunch(self):
        vm = w.VM()
        directory = w.REMOTE + '\\jobs\\' + 'a'*32
        with patch.object(vm, 'run', side_effect=RuntimeError(directory + '\\pid.txt used by another process')) as run, patch.object(vm, 'recover', return_value={'PID':17}) as recover:
            self.assertEqual(vm.interactive('start once', w.REMOTE+'\\jobs'), {'PID':17})
            self.assertEqual(run.call_count, 1)
            recover.assert_called_once_with(directory)
        with patch.object(vm, 'run', side_effect=RuntimeError('unrelated launch failure')), patch.object(vm, 'recover') as recover:
            with self.assertRaises(RuntimeError):
                vm.interactive('start once', w.REMOTE+'\\jobs')
            recover.assert_not_called()

    def test_wait_retains_failures_and_times_out_without_stopping(self):
        vm = w.VM()
        with patch.object(vm, 'status', side_effect=[{'Running':True,'ExitCode':None},{'Running':False,'ExitCode':'0'}]), patch.object(w.time,'sleep'):
            self.assertEqual(vm.wait({},1)['ExitCode'],'0')
        with patch.object(vm, 'status', return_value={'Running':False,'ExitCode':'7'}):
            with self.assertRaisesRegex(RuntimeError,'failed'):
                vm.wait({},1)
        with patch.object(vm, 'status', return_value={'Running':True,'ExitCode':None}):
            with self.assertRaises(TimeoutError):
                vm.wait({},0)

    def test_status_does_not_turn_exit_7_into_success(self):
        job = {'PID': 11, 'Stdout': w.REMOTE+'\\stdout', 'Stderr': w.REMOTE+'\\stderr', 'ExitCodeFile': w.REMOTE+'\\exit'}
        with patch.object(w.VM, 'run', return_value='{"Running":false,"ExitCode":"7"}'):
            self.assertEqual(w.VM().status(job)['ExitCode'], '7')

    def test_launch_persists_original_identity_in_serialized_receipt(self):
        job, parent, _ = self.stop_fixture()
        del job['Created']
        job['ExitCodeFile'] = w.REMOTE+'\\jobs\\exit-code.txt'
        vm = w.VM()
        # Both the usual helper response and publication-race recovery flow
        # through launch() before the CLI serializes the receipt.
        for recovered in (False, True):
            with self.subTest(recovered=recovered):
                directory = w.REMOTE+'\\jobs\\'+'a'*32
                first = (RuntimeError(directory+'\\pid.txt used by another process')
                         if recovered else json.dumps(job))
                with patch.object(vm, 'run', side_effect=[first, '100']) as run, \
                        patch.object(vm, 'recover', return_value=dict(job)) as recover:
                    saved = json.loads(json.dumps(vm.launch(
                        parent['Executable'], w.REMOTE, w.REMOTE+'\\jobs')))
                for key in ('PID', 'SessionId', 'Executable', 'Created'):
                    self.assertEqual(saved[key], parent[key])
                code = run.call_args.args[0]
                self.assertIn('CreationDate.ToUniversalTime().Ticks.ToString()', code)
                self.assertIn('Test-Path', code)
                self.assertIn(job['ExitCodeFile'], code)
                self.assertIn('$p.HasExited', code)
                self.assertIn('$c.SessionId -ne 2', code)
                self.assertLess(code.index('$p.Handle'), code.index('Get-CimInstance'))
                self.assertEqual(recover.call_count, int(recovered))

    def test_stop_checks_identity_and_only_own_task(self):
        job = {'PID': 11, 'SessionId': 2, 'Created': '100', 'Executable': w.REMOTE+'\\astral.exe', 'TaskName': 'ACR-interactive-'+'a'*32}
        parent = dict(job, ParentPID=10, Created='100')
        with patch.object(w.VM, 'game_processes', side_effect=[[parent], [], []]), patch.object(w.VM, 'run', return_value='') as run:
            w.VM().stop(job)
            kill, cleanup = [c.args[0] for c in run.call_args_list]
            self.assertIn('PID identity changed', kill)
            self.assertIn('$p.SessionId -ne 2', kill)
            self.assertIn('$c.ParentProcessId -ne 10', kill)
            self.assertIn('Ticks -ne 100', kill)
            self.assertLess(kill.index('$p.Handle'), kill.index('Get-CimInstance'))
            self.assertLess(kill.index('PID identity changed'), kill.index('$p.Kill()'))
            self.assertIn('WaitForExit(15000)', kill)
            self.assertIn(job['TaskName'], cleanup)
        with self.assertRaises(ValueError):
            w.VM().stop(dict(job, Executable=r'C:\other.exe'))

    def stop_fixture(self):
        parent = dict(PID=11, ParentPID=10, SessionId=2,
                      Executable=w.REMOTE+'\\player\\astral.exe', Created='100')
        child = dict(PID=12, ParentPID=11, SessionId=2,
                     Executable=w.REMOTE+'\\player\\astral-60fps.exe', Created='200')
        job = dict(parent, TaskName='ACR-interactive-'+'a'*32)
        return job, parent, child

    def test_stop_fps_child_through_real_subprocess_ssh_transport(self):
        job, parent, child = self.stop_fixture()
        # The peer is a separate launch of the identical executable in this unit.
        # Also preserve another unit even if its parent PID happens to match.
        peer = dict(child, PID=13, ParentPID=99)
        other = dict(child, PID=14, Executable=r'C:\acr\units\PEER\astral-60fps.exe')
        with tempfile.TemporaryDirectory() as d:
            fake, trace, state = (Path(d)/name for name in ('ssh', 'trace.json', 'state.json'))
            state.write_text(json.dumps([parent, child, peer, other]))
            trace.write_text('[]')
            fake.write_text('#!' + sys.executable + '\n' + '''
import base64,json,pathlib,re,sys
state=pathlib.Path(@STATE@); trace=pathlib.Path(@TRACE@)
rows=json.loads(state.read_text()); calls=json.loads(trace.read_text())
code=base64.b64decode(sys.argv[-1]).decode('utf-16le')
if 'OR ParentProcessId=' in code:
    print(json.dumps(rows))
elif '$p.Kill()' in code:
    pid=int(re.search(r'Get-Process -Id (\\d+)',code)[1])
    calls.append(pid)
    rows=[r for r in rows if r['PID'] != pid]
elif 'Unregister-ScheduledTask' in code:
    assert {r['PID'] for r in rows} == {13,14}
    calls.append('cleanup')
    print('Stopped owned game task')
else:
    raise AssertionError(code)
state.write_text(json.dumps(rows)); trace.write_text(json.dumps(calls))
'''.replace('@STATE@', repr(str(state))).replace('@TRACE@', repr(str(trace))))
            fake.chmod(0o755)
            self.assertEqual(w.VM(ssh=str(fake)).stop(job), 'Stopped owned game task')
            self.assertEqual(json.loads(trace.read_text()), [11, 12, 'cleanup'])

    def test_child_ownership_requires_parent_sibling_session_and_creation(self):
        job, parent, child = self.stop_fixture()
        peers = [
            dict(child, PID=13, ParentPID=99),
            dict(child, PID=14, SessionId=3),
            dict(child, PID=15, Created='99'),
            dict(child, PID=16, Executable=r'C:\acr\units\PEER\astral-60fps.exe'),
            dict(child, PID=17, Executable=w.REMOTE+'\\other-player\\astral-60fps.exe'),
            dict(child, PID=18, Executable=w.REMOTE+'\\player\\helper.exe'),
            dict(child, PID=19, Executable=None),
        ]
        self.assertEqual(w.game_children(parent, [parent, child, *peers]), [child])
        self.assertEqual(w.game_children(parent, [dict(child, Executable=child['Executable'].upper())]),
                         [dict(child, Executable=child['Executable'].upper())])

    def test_stop_catches_variant_spawn_between_inventory_and_parent_exit(self):
        job, parent, child = self.stop_fixture()
        vm = w.VM()
        with patch.object(vm, 'game_processes', side_effect=[[parent], [child], []]), \
                patch.object(vm, 'stop_process') as stop, patch.object(vm, 'run') as run:
            vm.stop(job)
            self.assertEqual([c.args[0]['PID'] for c in stop.call_args_list], [11, 12])
            self.assertIn('Unregister-ScheduledTask', run.call_args.args[0])

    def test_stop_rejects_changed_parent_without_touching_children_or_task(self):
        job, parent, child = self.stop_fixture()
        for changed in [dict(parent, SessionId=3),
                        dict(parent, Executable=r'C:\acr\units\PEER\astral.exe')]:
            vm = w.VM()
            with patch.object(vm, 'game_processes', return_value=[changed, child]), \
                    patch.object(vm, 'stop_process') as stop, patch.object(vm, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'PID identity changed'):
                    vm.stop(job)
                stop.assert_not_called()
                run.assert_not_called()

    def test_stop_rejects_child_pid_reuse_and_retains_task(self):
        job, parent, child = self.stop_fixture()
        vm = w.VM()
        with patch.object(vm, 'game_processes', side_effect=[
                [parent, child], [dict(child, Created='300')]]), \
                patch.object(vm, 'stop_process') as stop, patch.object(vm, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Child PID identity changed'):
                vm.stop(job)
            self.assertEqual([c.args[0]['PID'] for c in stop.call_args_list], [11])
            run.assert_not_called()

    def test_stop_rejects_same_path_session_launcher_pid_reuse(self):
        job, parent, child = self.stop_fixture()
        replacement = dict(parent, Created='300')
        replacement_child = dict(child, Created='400')
        vm = w.VM()
        with patch.object(vm, 'game_processes', return_value=[replacement, replacement_child]), \
                patch.object(vm, 'stop_process') as stop, patch.object(vm, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'PID identity changed'):
                vm.stop(json.loads(json.dumps(job)))
            stop.assert_not_called()
            run.assert_not_called()

    def test_stop_refuses_legacy_or_invalid_receipt_without_rebinding(self):
        job, _, _ = self.stop_fixture()
        del job['Created']
        vm = w.VM()
        for receipt in [job, *(dict(job, Created=value) for value in ('', None, '0', '-1', 'bad'))]:
            with self.subTest(receipt=receipt), \
                    patch.object(vm, 'game_processes') as snapshot, \
                    patch.object(vm, 'stop_process') as stop, patch.object(vm, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'original creation time'):
                    vm.stop(receipt)
                snapshot.assert_not_called()
                stop.assert_not_called()
                run.assert_not_called()

    def test_stop_failures_never_unregister_or_report_success(self):
        job, parent, child = self.stop_fixture()
        vm = w.VM()
        for snapshots, message in [
                ([[child]], 'cannot verify ancestry'),
                ([[parent, child], [parent, child]], 'Launcher PID still present'),
                ([[parent, child], [child], [child]], 'Owned game remains')]:
            with patch.object(vm, 'game_processes', side_effect=snapshots), \
                    patch.object(vm, 'stop_process'), patch.object(vm, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, message):
                    vm.stop(job)
                run.assert_not_called()
        with patch.object(vm, 'game_processes', side_effect=[[parent, child], [child]]), \
                patch.object(vm, 'stop_process', side_effect=[None, RuntimeError('denied')]), \
                patch.object(vm, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'denied'):
                vm.stop(job)
            run.assert_not_called()

    def test_stop_already_exited_game_is_idempotent(self):
        job, _, _ = self.stop_fixture()
        vm = w.VM()
        with patch.object(vm, 'game_processes', return_value=[]), \
                patch.object(vm, 'stop_process') as stop, patch.object(vm, 'run') as run:
            vm.stop(job)
            stop.assert_not_called()
            self.assertIn('Unregister-ScheduledTask', run.call_args.args[0])

    def test_memory_measurement_spans_observations_not_initial_ssh_delay(self):
        with tempfile.TemporaryDirectory() as d, patch.object(w.time,'monotonic',side_effect=[100,112,124]), patch.object(w.time,'sleep'):
            vm=w.VM()
            with patch.object(vm,'status',return_value={'Running':True,'WorkingSet':100}):
                result=w.sample_memory(vm,{},24,10,Path(d))
            rows=json.loads((Path(d)/'memory-samples.json').read_text())
            self.assertEqual(rows[0]['elapsed_s'],0)
            self.assertEqual(result['duration_s'],24)
            self.assertEqual(len(rows),3)

    def test_interrupted_soak_retains_samples_without_stale_success_summary(self):
        with tempfile.TemporaryDirectory() as d, patch.object(w.time,'monotonic',return_value=100), patch.object(w.time,'sleep'):
            directory=Path(d)
            (directory/'memory-summary.json').write_text('{"duration_s":600}')
            vm=w.VM()
            with patch.object(vm,'status',side_effect=[{'Running':True,'WorkingSet':100},{'Running':False}]):
                with self.assertRaisesRegex(RuntimeError,'exited'):
                    w.sample_memory(vm,{},600,10,directory)
            self.assertFalse((directory/'memory-summary.json').exists())
            self.assertEqual(json.loads((directory/'memory-samples.json').read_text()),
                             [{'elapsed_s':0,'working_set':100}])

    def test_memory_linear_regression_and_insufficient_evidence(self):
        rows = [{'elapsed_s': i*10, 'working_set': (100+i)*(1<<20)} for i in range(61)]
        result = w.memory_metrics(rows)
        self.assertEqual(result['duration_s'], 600)
        self.assertAlmostEqual(result['slope_mib_per_min'], 6)
        self.assertIn('does not establish', result['interpretation'])
        for bad in [[], rows[:1], rows[:1]*2, [{'elapsed_s':0,'working_set':-1}, rows[1]]]:
            with self.assertRaises(ValueError):
                w.memory_metrics(bad)

    def test_logs_keep_device_surface_and_per_window_stats_separate(self):
        result = w.log_metrics('vkCreateSwapchainKHR 1280x720 format 44, 3 images, present mode 2 -> 0\n'
            'vk: frame 300 presented (0), 59.9 fps (last 5.0 s), 59.0 average; worst 40.0 ms\n'
            'audio: device output (48 kHz stereo s16)\nCRASH: exception fake\n'
            'memory: 8.00 GB is over the 8.0 GB limit (NX_MEM_LIMIT_GB): stopping\n')
        self.assertEqual(result['frame_windows'][0]['fps'], 59.9)
        self.assertEqual(len(result['swapchains']), 1)
        self.assertEqual(len(result['audio_device_lines']), 1)
        self.assertEqual(len(result['fatal_or_crash_lines']), 1)
        self.assertEqual(len(result['memory_guard_lines']), 1)
        self.assertEqual(w.log_metrics('nvn: present #1024')['frame_windows'], [])
        nvn=w.log_metrics('nvn/vk: swapchain 1600x900, 3 images, transform 1, blitted\n'
                          'nvn/vk: per frame over 60: 60.0 fps, 1.0 submits, replay 7.50 ms\n')
        self.assertEqual(nvn['nvn_replay_windows'][0]['fps'],60)
        self.assertEqual(len(nvn['swapchains']),1)


class AudioTest(unittest.TestCase):
    def test_pcm_channels_clipping_and_silence_across_chunks(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'pcm.wav'
            with wave.open(str(path), 'wb') as f:
                f.setparams((2, 2, 1000, 0, 'NONE', 'not compressed'))
                f.writeframes(struct.pack('<hhhh', 32767, -32768, 16384, 0) + b'\0'*4*20000)
            m = w.wav_metrics(path)
            self.assertEqual(m['clipped_samples'], 2)
            self.assertEqual(m['frames'], 20002)
            self.assertEqual(m['longest_silence_s'], 20)
            self.assertAlmostEqual(m['rms'], math.sqrt(((32767/32768)**2+1+.25)/(20002*2)))

    def test_wasapi_float_extensible_with_metadata(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'wasapi.wav'
            fmt = struct.pack('<HHIIHHHHI', 0xfffe, 2, 48000, 384000, 8, 32, 22, 32, 3)
            fmt += struct.pack('<IHH8s', 3, 0, 0x10, b'\x80\0\0\xaa\0\x38\x9b\x71')
            pcm = struct.pack('<6f', .5, -.5, 0, 0, 1, -1)
            body = b'WAVEfmt ' + struct.pack('<I',len(fmt)) + fmt + b'JUNK\x01\0\0\0x\0data' + struct.pack('<I', len(pcm)) + pcm
            path.write_bytes(b'RIFF'+struct.pack('<I',len(body))+body)
            m = w.wav_metrics(path)
            self.assertEqual(m['frames'], 3)
            self.assertEqual(m['clipped_samples'], 2)
            self.assertAlmostEqual(m['rms'], math.sqrt(2.5/6))
            self.assertAlmostEqual(m['longest_silence_s'], 1/48000)
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, 'truncated'):
                w.wav_metrics(path)

    def test_empty_and_unsupported_files(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'empty.wav'
            with wave.open(str(path),'wb') as f:
                f.setparams((1,2,48000,0,'NONE',''))
            self.assertIsNone(w.wav_metrics(path)['rms_dbfs'])
            path.write_bytes(b'not RIFF')
            with self.assertRaises(ValueError):
                w.wav_metrics(path)


if __name__ == '__main__':
    unittest.main()
