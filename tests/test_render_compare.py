"""Synthetic pixel oracles and real CLI invocations; no game files or GPU."""
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from render_compare import Frame, compare, load_ppm


class RenderCompareTests(unittest.TestCase):
    def test_identical_strict_json(self):
        frame = Frame(2, 1, bytes([10, 20, 30, 40, 50, 60]))
        result = compare(frame, frame)
        self.assertEqual(result['mae'], 0)
        self.assertEqual(result['changed_pixels'], 0)
        self.assertIsNone(result['psnr_db'])
        json.dumps(result, allow_nan=False)

    def test_hand_calculated_rgb_errors_and_threshold_boundary(self):
        a = Frame(2, 1, bytes(6))
        b = Frame(2, 1, bytes([3, 0, 0, 0, 4, 0]))
        result = compare(a, b, tolerance=3)
        self.assertAlmostEqual(result['mae'], 7 / 6)
        self.assertAlmostEqual(result['rmse'], math.sqrt(25 / 6))
        self.assertEqual(result['max_channel_error'], 4)
        self.assertEqual(result['changed_fraction'], 0.5)
        self.assertAlmostEqual(result['psnr_db'], 10 * math.log10(255**2 / (25 / 6)))

    def test_roi_uses_source_stride_and_all_channels(self):
        a = Frame(2, 2, bytes(12))
        b = Frame(2, 2, bytes([100] * 9 + [3, 6, 9]))
        result = compare(a, b, roi=(1, 1, 1, 1))
        self.assertEqual(result['mae'], 6)
        self.assertEqual(result['pixels'], 1)
        self.assertEqual(result['max_channel_error'], 9)

    def test_invalid_geometry_and_tolerance(self):
        with self.assertRaises(ValueError):
            Frame(1, 1, b'')
        frame = Frame(2, 1, bytes(6))
        with self.assertRaises(ValueError):
            compare(frame, Frame(1, 2, bytes(6)))
        for roi in [(-1, 0, 1, 1), (0, 0, 0, 1), (1, 0, 2, 1), (0, 0, 1, 2)]:
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                compare(frame, frame, roi=roi)
        for tolerance in [-1, 256, 0.5]:
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                compare(frame, frame, tolerance=tolerance)

    def test_ppm_comments_crlf_and_whitespace_first_pixel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'frame.ppm'
            path.write_bytes(b'P6\n# comment\n2 1\n255\r\n' + b'\n #\x00\xff\x80')
            self.assertEqual(load_ppm(path), Frame(2, 1, b'\n #\x00\xff\x80'))
            for content in [b'P3 1 1 255\n000', b'P6 1 1 65535\n000',
                            b'P6 1 1 255\n00', b'P6 1 1 255\n0000', b'P6\n# unfinished']:
                path.write_bytes(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    load_ppm(path)

    def test_cli_exit_codes_and_output(self):
        with tempfile.TemporaryDirectory(prefix='render compare ') as directory:
            root = Path(directory)
            a, b, output = (root / name for name in ['a.ppm', 'b.ppm', 'metrics.json'])
            a.write_bytes(b'P6\n1 1\n255\n' + bytes(3))
            b.write_bytes(b'P6\n1 1\n255\n' + bytes([3, 6, 9]))
            command = [sys.executable, str(ROOT / 'tools/render_compare.py'), str(a), str(b),
                       '--output', str(output), '--max-mae']
            for limit, expected in [('6', 0), ('5.99', 1)]:
                run = subprocess.run(command + [limit], capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, expected, run.stderr)
                report = json.loads(output.read_text())
                self.assertEqual(report, json.loads(run.stdout))
                self.assertEqual(report['metrics']['mae'], 6)
                self.assertEqual(report['passed'], expected == 0)
            # A metric without an acceptance limit is an observation, not a gate.
            run = subprocess.run(command[:-1], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIsNone(json.loads(run.stdout)['passed'])
            run = subprocess.run(command + ['nan'], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 2)


if __name__ == '__main__':
    unittest.main()
