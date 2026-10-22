import importlib.util
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1]/'tools/playthrough_survey.py'
spec = importlib.util.spec_from_file_location('survey', TOOL)
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)


class SurveyTests(unittest.TestCase):
    def test_file_contacts_combine_runs_without_claiming_reach(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); records = []; expected = []
            for index, file in enumerate(['01', '02', '01']):
                run = root/f'run-{index}'; frames = run/'data/frames'; frames.mkdir(parents=True)
                frame = frames/'00120.ppm'
                frame.write_bytes(b'P6\n1 1\n255\n'+bytes([30+index, 60, 90]))
                records.append(dict(file=file, run=str(run)))
                if file == '01': expected.append(str(frame.resolve()))
            manifest = root/'manifest.json'; manifest.write_text(json.dumps(records))
            report = survey.analyze(manifest, root/'out')
            contacts = {r['file']:r for r in report['file_contacts']}
            self.assertEqual(contacts['01']['frames'], 2)
            sidecar = Path(contacts['01']['contact_sheet']).with_suffix('.json')
            self.assertEqual(json.loads(sidecar.read_text()), expected)
            self.assertEqual(contacts['02']['frames'], 1)
            self.assertIsNone(contacts['epilogue']['contact_sheet'])
            self.assertFalse(any(r['reached'] for r in report['coverage']))

    def test_synthetic_logs_and_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run = root/'run'; frames = run/'data/frames'; frames.mkdir(parents=True)
            (run/'nx.log').write_text('astral strict boot: unsupported guest instructions remain fatal\n'
                                       '[1.2] FATAL guest fault\n[1.3] missing shader 0x123\n'
                                       '[1.4] unimplemented call\n[1.5] audio underrun\n')
            (frames/'00001.ppm').write_bytes(b'P6\n2 1\n255\n'+bytes([255,0,255])*2)
            (run/'receipt.json').write_text(json.dumps(dict(termination='exited', returncode=1)))
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps([dict(file='01', run=str(run), platform='synthetic', phase='bootstrap')]))
            result = subprocess.run([sys.executable, str(TOOL), 'analyze', str(manifest), '--out', str(root/'out')],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root/'out/summary.json').read_text())
            r = report['results'][0]
            self.assertEqual(r['status'], 'crashed')
            self.assertEqual(report['issues'][0]['phase'], 'bootstrap')
            self.assertEqual(r['hit_counts'], dict(fatal=1, gpu_hang=0, render_error=0,
                             resource_limit=0, stub=1, missing_shader=1, audio=1))
            self.assertEqual(r['frame_metrics'][0]['flags'], ['magenta_candidate'])
            self.assertTrue(Path(r['contact_sheet']).exists())
            self.assertEqual(len(report['coverage']), 13)
            self.assertFalse(any(c['reached'] for c in report['coverage']))

    def test_time_limit_is_not_hang_and_boot_is_not_reach(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'receipt.json').write_text(json.dumps(dict(termination='time_limit', returncode=-15)))
            r = survey.analyze_record(dict(run=str(root), file='01', reached=True), root, 0)
            self.assertEqual(r['status'], 'not_verified')
            r = survey.analyze_record(dict(run=str(root), file='01', reached=True,
                                           reach_evidence='manual frame 00150'), root, 0)
            self.assertEqual(r['status'], 'reached')

    def test_ppm_whitespace_pixel_and_truncation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'a.ppm'
            path.write_bytes(b'P6\n1 1\n255\n\x0a\x20\x09')
            self.assertEqual(survey.read_ppm(path)[2], b'\x0a\x20\x09')
            path.write_bytes(b'P6\n2 2\n255\n123')
            with self.assertRaises(ValueError): survey.read_ppm(path)

    def test_runner_real_subprocess(self):
        # Exercise a real short child, isolated writes, and a nonzero exit receipt.
        if sys.platform == 'win32': self.skipTest('POSIX fixture executable')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data').mkdir()
            binary = root/'fixture'; binary.write_text('#!/bin/sh\necho "FATAL synthetic"\necho "trace_fs=$NX_TRACE_FS"\necho "record_path=$NX_INPUT_RECORD"\nexit 7\n'); binary.chmod(0o700)
            from argparse import Namespace
            from unittest.mock import patch
            args = Namespace(run=str(root), binary=str(binary), seconds=10, every=150,
                             profile='Test', input='', locked=False, trace_fs=True, record_input=True)
            with patch.object(survey.sys, 'platform', 'linux'):
                self.assertEqual(survey.run(args), 0)
            receipt = json.loads((root/'receipt.json').read_text())
            self.assertEqual(receipt['returncode'], 7)
            self.assertEqual(receipt['termination'], 'exited')
            self.assertTrue(receipt['started_utc'])
            self.assertEqual(receipt['save_profile'], 'Test')
            self.assertEqual(receipt['input_script'], '')
            self.assertIn('trace_fs=1', (root/'console.log').read_text())
            self.assertIn('record_path='+str((root/'physical-input.txt').resolve()), (root/'console.log').read_text())
            with self.assertRaises(ValueError): survey.run(args)

    def test_mix_metrics_flag_silence_and_clipping_without_device_claim(self):
        import wave
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'audio.wav'
            for value, flag in [(0, 'silent_mix_candidate'), (32767, 'clipping_mix_candidate')]:
                with wave.open(str(path), 'wb') as w:
                    w.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                    w.writeframes(struct.pack('<h', value)*64000)
                info = survey.audio_info(path)
                self.assertEqual(info['flags'], [flag])
                self.assertEqual(info['sampled_values'], 64000)
                self.assertAlmostEqual(info['rms'], value/32768)
                self.assertIn('no device-timing proof', info['signal_note'])

    def test_segment_copies_only_selected_interval(self):
        import os
        import wave
        from argparse import Namespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp); root = base/'run'; frames = root/'data/frames'
            frames.mkdir(parents=True); output = base/'segment'
            (root/'process.json').write_text('{}')
            (root/'nx.log').write_text('pre-load noise\n')
            for index, timestamp in [(120, 990), (240, 999), (360, 1001), (480, 1003)]:
                frame = frames/f'{index:05d}.ppm'; frame.write_bytes(b'P6\n1 1\n255\nabc')
                os.utime(frame, (timestamp, timestamp))
            (root/'frames.jsonl').write_text(''.join(json.dumps(dict(name=f'{n:05d}.ppm',
                observed_seconds=n/60))+'\n' for n in [120, 240, 360, 480]))
            def audio(count):
                with wave.open(str(root/'audio.wav'), 'wb') as w:
                    w.setparams((1, 2, 100, 0, 'NONE', 'not compressed'))
                    w.writeframes(b'\0\0'*count)
            audio(200)
            with patch.object(survey.time, 'time', return_value=1000):
                survey.begin_segment(Namespace(run=str(root), out=str(output), file='02',
                    chapter=1, selection_frame=120))
            (root/'nx.log').write_text('pre-load noise\nFATAL current segment\n')
            audio(500)
            with patch.object(survey.time, 'time', return_value=1002):
                survey.end_segment(Namespace(segment=str(output), end_frame=480,
                    reach_evidence='Synthetic verified scene at frame00360'))
            self.assertEqual(sorted(p.name for p in (output/'data/frames').glob('*.ppm')),
                             ['00120.ppm', '00360.ppm'])
            self.assertEqual((output/'nx.log').read_text(), 'FATAL current segment\n')
            self.assertEqual(survey.audio_info(output/'audio.wav')['seconds'], 3)
            marker = json.loads((output/'segment.json').read_text())
            self.assertTrue(marker['reached'])
            self.assertEqual(marker['frames'], 2)
            self.assertEqual(len((output/'frames.jsonl').read_text().splitlines()), 2)
            self.assertEqual(len(list(frames.glob('*.ppm'))), 4)  # Source is untouched.
            with self.assertRaisesRegex(ValueError, 'already ended'):
                survey.end_segment(Namespace(segment=str(output)))

    def test_requested_stop_preserves_real_child_receipt(self):
        if sys.platform == 'win32': self.skipTest('POSIX fixture executable')
        import time
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data').mkdir()
            binary = root/'fixture'
            binary.write_text('#!/bin/sh\nexec sleep 30\n'); binary.chmod(0o700)
            child = subprocess.Popen([sys.executable, str(TOOL), 'run', '--run', str(root),
                '--binary', str(binary), '--seconds', '20', '--locked'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic()+5
                while not (root/'process.json').exists() and time.monotonic()<deadline:
                    time.sleep(.02)
                stop = subprocess.run([sys.executable, str(TOOL), 'stop', '--run', str(root),
                    '--reason', 'synthetic sample finished'], capture_output=True, text=True)
                self.assertEqual(stop.returncode, 0, stop.stderr)
                stdout, stderr = child.communicate(timeout=5)
                self.assertEqual(child.returncode, 0, stderr)
                receipt = json.loads((root/'receipt.json').read_text())
                self.assertEqual(receipt['termination'], 'requested_stop')
                repeated = subprocess.run([sys.executable, str(TOOL), 'stop', '--run', str(root),
                    '--reason', 'duplicate request'], capture_output=True, text=True)
                self.assertEqual(repeated.returncode, 0, repeated.stderr)
                self.assertLess(receipt['elapsed'], 10)
                result = survey.analyze_record(dict(run=str(root), file='01'), root, 0)
                self.assertEqual(result['status'], 'not_verified')
                self.assertEqual(json.loads((root/'stop-request.json').read_text())['reason'],
                                 'synthetic sample finished')
            finally:
                if child.poll() is None: child.kill(); child.communicate()

    def test_writable_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data').mkdir(); (root/'outside').mkdir()
            (root/'data/user').symlink_to(root/'outside')
            from argparse import Namespace
            with self.assertRaises(ValueError):
                survey.run(Namespace(run=str(root), seconds=1, every=1))

    def test_nested_save_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data/user/save').mkdir(parents=True)
            (root/'outside').write_text('owner data')
            (root/'data/user/save/GameData.dat').symlink_to(root/'outside')
            from argparse import Namespace
            with self.assertRaisesRegex(ValueError, 'nested'):
                survey.run(Namespace(run=str(root), seconds=1, every=1))

    def test_blank_reach_evidence_and_capture_timeline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); frames = root/'data/frames'; frames.mkdir(parents=True)
            (frames/'00150.ppm').write_bytes(b'P6\n1 1\n255\n\x80\x80\x80')
            event = dict(name='00150.ppm', observed_seconds=5.25, modified_unix=100)
            (root/'frames.jsonl').write_text(json.dumps(event)+'\n')
            r = survey.analyze_record(dict(run=str(root), file='12', reached=True,
                                           reach_evidence='  '), root, 0)
            self.assertFalse(r['reached'])
            self.assertEqual(r['frame_metrics'][0]['capture'], event)

    def test_timeout_records_real_child_frames(self):
        if sys.platform == 'win32': self.skipTest('POSIX fixture executable')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'data').mkdir()
            binary = root/'fixture'
            binary.write_text('#!/bin/sh\nmkdir -p data/frames\nprintf "P6\\n1 1\\n255\\nabc" > data/frames/00150.ppm\nexec sleep 30\n')
            binary.chmod(0o700)
            from argparse import Namespace
            from unittest.mock import patch
            with patch.object(survey.sys, 'platform', 'linux'):
                survey.run(Namespace(run=str(root), binary=str(binary), seconds=5,
                    every=150, profile='Test', input='1:A:0.2', locked=False))
            receipt = json.loads((root/'receipt.json').read_text())
            self.assertEqual(receipt['termination'], 'time_limit')
            events = [json.loads(l) for l in (root/'frames.jsonl').read_text().splitlines()]
            self.assertEqual(len(events), 1)
            self.assertGreater(events[0]['observed_seconds'], 0)

    def test_prepare_and_parallel_batch_isolate_saves(self):
        if sys.platform == 'win32': self.skipTest('POSIX fixture executable')
        from argparse import Namespace
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); assets = root/'assets'; save = root/'save'; save.mkdir()
            for n in ['analysis', 'exefs', 'extract', 'spirv', 'shared-fonts']:
                (assets/n).mkdir(parents=True)
            (assets/'astral.profile').write_text('synthetic profile')
            (save/'GameData.dat').write_text('original synthetic save')
            binary = root/'fixture'
            binary.write_text('#!/bin/sh\necho changed > data/user/save/GameData.dat\nexit 0\n')
            binary.chmod(0o700)
            plans = []
            for file in ['01', '02']:
                run = root/file
                survey.prepare(Namespace(run=str(run), assets=str(assets), save=str(save)))
                plans.append(dict(file=file, run=str(run), binary=str(binary), seconds=10))
            plan = root/'plan.json'; plan.write_text(json.dumps(plans))
            real_run = subprocess.run
            def fixture_run(command, **kwargs):
                # These synthetic children are not games. Avoid acquiring a live
                # Mac game lock in tests, while executing the actual CLI runner.
                return real_run(command+['--locked'], **kwargs)
            with patch.object(survey.sys, 'platform', 'linux'), patch.object(survey.subprocess, 'run', fixture_run):
                self.assertEqual(survey.batch(Namespace(plan=str(plan), out=str(root/'out'), jobs=2)), 0)
            report = json.loads((root/'out/summary.json').read_text())
            self.assertEqual(len(report['results']), 2)
            self.assertTrue(all(not r['reached'] for r in report['results']))
            self.assertEqual((save/'GameData.dat').read_text(), 'original synthetic save')
            for run in [root/'01', root/'02']:
                self.assertEqual((run/'data/user/save/GameData.dat').read_text(), 'changed\n')
            with self.assertRaises(ValueError):
                survey.prepare(Namespace(run=str(root/'01'), assets=str(assets), save=str(save)))

    def test_launch_failure_is_not_a_game_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            r = survey.analyze_record(dict(run=str(root), file='01', launch_returncode=2), root, 0)
            self.assertEqual(r['status'], 'launch_failed')

    def test_runtime_missing_spirv_messages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'nx.log').write_text('nvn: shader '+('a'*64)+' (code 0x100 bytes, control 123): no C:/spirv/abc.spv\n'
                'nvn: no C:/spirv/results.tsv: storage buffers of translated shaders cannot be bound\n'
                'nvn: shader abc vertex: 2 bindings, 1 inputs, 1 outputs\n')
            r = survey.analyze_record(dict(run=str(root), file='01'), root, 0)
            self.assertEqual(r['hit_counts']['missing_shader'], 2)

    def test_memory_guard_exit_is_distinct_from_guest_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'nx.log').write_text('memory: 8.02 GB is over the 8.0 GB limit (NX_MEM_LIMIT_GB): stopping\n')
            (root/'receipt.json').write_text(json.dumps(dict(termination='exited', returncode=3)))
            r = survey.analyze_record(dict(run=str(root), file='12', phase='save_load'), root, 0)
            self.assertEqual(r['status'], 'resource_limit')

    def test_reviewed_visual_issue_keeps_frame_and_time(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); run = root/'run'; (run/'data/frames').mkdir(parents=True)
            (run/'data/frames/00120.ppm').write_bytes(b'P6\n1 1\n255\nabc')
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps([dict(file='12', run=str(run), phase='chapter_scene',
                visual_issues=[dict(frame='data/frames/00120.ppm', observed_seconds=10.5,
                                    description='Synthetic reviewed artifact')])]))
            report = survey.analyze(manifest, root/'out')
            issue = report['issues'][0]
            self.assertEqual(issue['kind'], 'reviewed_visual_issue')
            self.assertEqual(issue['repro']['observed_seconds'], 10.5)
            self.assertEqual(issue['repro']['frame'], str((run/'data/frames/00120.ppm').resolve()))

    def test_driver_gpu_hang_and_upload_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'nx.log').write_text('nvn/vk: upload buffer full (710643880 bytes in this submit)\n'
                                       'nvn/vk: GPU hang (vkWaitForFences): stopping\n')
            (root/'receipt.json').write_text(json.dumps(dict(termination='exited', returncode=4)))
            r = survey.analyze_record(dict(run=str(root), file='12', phase='save_load'), root, 0)
            self.assertEqual(r['status'], 'hang')
            self.assertEqual(r['hit_counts']['gpu_hang'], 1)
            self.assertEqual(r['hit_counts']['render_error'], 1)

    def test_windows_exception_is_a_ranked_crash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'nx.log').write_text('CRASH: exception e06d7363 at KERNELBASE.dll+c7d9a\n')
            (root/'receipt.json').write_text(json.dumps(dict(termination='exited', returncode=3765269347)))
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps([dict(run=str(root), file='12', phase='save_load')]))
            report = survey.analyze(manifest, root/'out')
            self.assertEqual(report['results'][0]['status'], 'crashed')
            self.assertEqual(report['issues'][0]['kind'], 'fatal')

    def test_isolated_controller_report_and_release(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'process.json').write_text(json.dumps(dict(pid=123, controlled_pad=True)))
            (root/'controller.bin.ack').write_bytes(struct.pack('<4sI', b'PAD1', 123))
            (root/'controller.bin').write_bytes(survey.pad_report([], 0, 0))
            args = Namespace(run=str(root), hold=.01, buttons=['A', 'ZL'], lx=123, ly=0,
                             rx=0, ry=0, note='synthetic controlled input')
            self.assertEqual(survey.pad(args), 0)
            final = struct.unpack(survey.PAD_FORMAT, (root/'controller.bin').read_bytes())
            self.assertEqual(final[1], 3)
            self.assertEqual(final[3:], (0, 0, 0, 0, 0, 0, 0))
            packed = struct.unpack(survey.PAD_FORMAT, survey.pad_report(['A', 'ZL'], 2, 100, (123, 0, 0, 0)))
            self.assertEqual(packed[3:6], (0x2000, 255, 0))  # Xbox B is Nintendo A in this runtime.
            self.assertEqual(packed[6], 123)
            self.assertEqual(len((root/'controls.jsonl').read_text().splitlines()), 1)

    def test_concurrent_input_writer_is_rejected_and_lock_recovers(self):
        # Independent CLI writer must not replace another writer's held report.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'process.json').write_text(json.dumps(dict(pid=123, controlled_pad=True)))
            (root/'controller.bin.ack').write_bytes(struct.pack('<4sI', b'PAD1', 123))
            (root/'controller.bin').write_bytes(survey.pad_report([], 0, 0))
            command = [sys.executable, str(TOOL), 'pad', '--run', str(root), '--hold', '.01',
                       '--buttons', 'A']
            with survey.controller_lock(root/'controller.lock'):
                blocked = subprocess.run(command, capture_output=True, text=True)
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn('another controller writer is active', blocked.stderr)
                self.assertEqual(struct.unpack(survey.PAD_FORMAT,
                    (root/'controller.bin').read_bytes())[1], 0)
            recovered = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(recovered.returncode, 0, recovered.stderr)
            self.assertEqual(len((root/'controls.jsonl').read_text().splitlines()), 1)

    def test_controller_rejects_wrong_process_and_ended_run(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'process.json').write_text(json.dumps(dict(pid=123, controlled_pad=True)))
            (root/'controller.bin.ack').write_bytes(struct.pack('<4sI', b'PAD1', 999))
            with self.assertRaisesRegex(ValueError, 'exact process'):
                survey.pad(Namespace(run=str(root)))
            self.assertFalse((root/'controller.bin').exists())
            (root/'receipt.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'already ended'):
                survey.pad(Namespace(run=str(root)))

if __name__ == '__main__': unittest.main()
