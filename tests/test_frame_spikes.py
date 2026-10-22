import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('frame_spikes', ROOT / 'tools/frame_spikes.py')
spikes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spikes)


def frame(index, ts, ms):
    return f'[log] shader-cache frame index={index} ts_ns={ts} interval_ms={ms}\n'


def event(kind, start, end, phase='runtime'):
    return f'shader-cache compile kind={kind} start_ns={start} end_ns={end} phase={phase}\n'


class FrameSpikesTest(unittest.TestCase):
    def test_thresholds_and_first_sample(self):
        text = frame(0, 1, 0) + frame(1, 20_000_001, 20) + frame(2, 120_000_001, 100)
        text += frame(3, 220_100_001, 100.1)
        result = spikes.summarize(text, 10)
        self.assertEqual((result['intervals'], result['above_2x'], result['above_100ms']), (3, 2, 1))
        self.assertEqual(result['longest_ms'], 100.1)
        self.assertEqual(result['p50_ms'], 100)

    def test_overlap_not_line_adjacency_and_boot_cost(self):
        text = event('graphics', 1, 10_000_001, 'prewarm')
        text += frame(0, 20_000_000, 0) + frame(1, 120_000_000, 100)
        text += frame(2, 140_000_000, 20)
        # Buffered event can appear after later frame log lines.
        text += event('module', 15_000_000, 30_000_000) + event('graphics', 120_000_000, 130_000_000)
        result = spikes.summarize(text, 30)
        self.assertEqual(result['spikes_with_compilation'], 1)
        self.assertEqual(len(result['spikes'][0]['compilation']), 1)
        self.assertEqual(result['spikes'][0]['compilation'][0]['overlap_ms'], 10)
        self.assertEqual(result['total_compile_ms'], 35)
        self.assertEqual(result['selected_interval_compile_ms'], 20)
        self.assertEqual(result['compile_ms_by_phase']['prewarm'], 10)

    def test_range(self):
        text = frame(0, 1, 0) + frame(1, 200_000_001, 200) + frame(2, 220_000_001, 20)
        r = spikes.summarize(text, 30, 2, 2)
        self.assertEqual((r['intervals'], r['above_2x'], r['longest_ms']), (1, 0, 20))

    def test_invalid_and_histograms_fail(self):
        for text in ('present intervals over 600: more 2', frame(0, 1, -1),
                     frame(1, 10, 2) + frame(1, 20, 3), frame(1, 10, 2) + frame(2, 9, 3),
                     'shader-cache frame incomplete', frame(1, 10, '1e999'),
                     frame(1, 10, 2) + event('graphics', 9, 8)):
            with self.subTest(text=text), self.assertRaises(ValueError):
                spikes.summarize(text)
        for budget in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError): spikes.summarize(frame(1, 10, 2), budget)

    def test_cli_json_and_error(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'run.log'
            p.write_text(frame(0, 1, 0) + frame(1, 33_000_001, 33))
            command = [sys.executable, str(ROOT / 'tools/frame_spikes.py'), str(p), '--fps', '60']
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)['intervals'], 1)
            run = subprocess.run(command + ['--end-frame', '0'], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('no measured intervals', run.stderr)


if __name__ == '__main__': unittest.main()
