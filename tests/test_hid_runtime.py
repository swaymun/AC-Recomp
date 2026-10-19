"""Compile the actual composed HID and loader with a deterministic host input.

Private pinned original source is required (HID_REFERENCE can override discovery).
No game bytes, provider calls, external packages, or network access are used by tests.
"""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime


class HidRuntimeTests(unittest.TestCase):
    def test_actual_hle_registry_and_private_composition(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        owner = common.parent
        reference = Path(os.environ.get('HID_REFERENCE', str(owner / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'provide clean pinned original source through HID_REFERENCE')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        output = ROOT / '.local/hid-045' / ('verify-' + uuid.uuid4().hex)
        output.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / name for name in ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-control-import.patch', 'astral-sqshl.patch', 'astral-notifications.patch', 'astral-apm.patch', 'astral-audio.patch', 'astral-ipc-buffer.patch', 'astral-hid.patch')]
        source = output / 'source'
        fingerprint = runtime.prepare_source(reference, source, patches)
        argv = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1',
                '-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'),
                str(ROOT / 'tests/test_hid_runtime.cpp'), '-o', str(output / 'hid-test')]
        build = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (output / 'compile.log').write_text(build.stdout + build.stderr)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        results = []
        for mode in ('capability',):
            result = subprocess.run([str(output / 'hid-test'), mode], cwd=output, capture_output=True, text=True, timeout=10)
            (output / (mode + '.log')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS actual HLE registry/call dispatch', result.stdout)
            print(result.stdout, end='')
            results.append({'mode': mode, 'exit_code': result.returncode, 'output': result.stdout})
        receipt = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'patches': {p.name: runtime.sha(p) for p in patches}, 'source_files': fingerprint,
                   'fixture_sha256': runtime.sha(ROOT / 'tests/test_hid_runtime.cpp'), 'compile': argv,
                   'binary_sha256': runtime.sha(output / 'hid-test'), 'results': results}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('private composition receipt:', output / 'receipt.json')


if __name__ == '__main__':
    unittest.main()
