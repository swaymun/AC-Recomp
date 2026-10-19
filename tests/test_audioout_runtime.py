"""Compile the actual composed AudioOut and loader with a deterministic host sink.

Private pinned original source is required (AUDIOOUT_REFERENCE can override discovery).
No game bytes, provider calls, external packages, or network access are used by tests.
"""
import datetime
import hashlib
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


class AudioOutRuntimeTests(unittest.TestCase):
    def test_actual_hle_registry_and_private_composition(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        owner = common.parent
        reference = Path(os.environ.get('AUDIOOUT_REFERENCE', str(owner / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'provide clean pinned original source through AUDIOOUT_REFERENCE')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        output = ROOT / '.local/audioout-032' / ('verify-' + uuid.uuid4().hex)
        output.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / name for name in ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-audio.patch')]
        source = output / 'source'
        fingerprint = runtime.prepare_source(reference, source, patches)
        argv = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-DNX_APPLE_HIGH_MEMORY=1',
                '-I', str(source / 'runtime/include'), '-I', str(source / 'runtime/src'),
                str(ROOT / 'tests/test_audioout_runtime.cpp'), '-o', str(output / 'audio-test')]
        build = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (output / 'compile.log').write_text(build.stdout + build.stderr)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        results = []
        for mode in ('device', 'no-device', 'reject'):
            result = subprocess.run([str(output / 'audio-test'), mode], cwd=output, capture_output=True, text=True, timeout=10)
            (output / (mode + '.log')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS real HLE registry/call dispatch', result.stdout)
            print(result.stdout, end='')
            results.append({'mode': mode, 'exit_code': result.returncode, 'output': result.stdout})
        receipt = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'patches': {p.name: runtime.sha(p) for p in patches}, 'source_files': fingerprint,
                   'fixture_sha256': runtime.sha(ROOT / 'tests/test_audioout_runtime.cpp'), 'compile': argv,
                   'binary_sha256': runtime.sha(output / 'audio-test'), 'results': results}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('private composition receipt:', output / 'receipt.json')


if __name__ == '__main__':
    unittest.main()
