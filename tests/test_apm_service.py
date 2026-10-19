"""Compile actual composed service/kernel/IPC sources with synthetic requests only.

Requires a clean local pinned Wonder reference; APM_REFERENCE overrides discovery.
All compiled sources, binaries, logs and receipts remain in ignored .local storage.
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


class ApmServiceTests(unittest.TestCase):
    def test_actual_patched_handlers_and_composition(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('APM_REFERENCE', str(common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'clean pinned reference required via APM_REFERENCE')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        output = ROOT / '.local/apm-030' / ('verify-' + uuid.uuid4().hex)
        output.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / p for p in ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-apm.patch')]
        overlay = patches[-1].read_text()
        self.assertEqual([s for s in overlay.splitlines() if s.startswith('diff --git ')],
                         ['diff --git a/runtime/src/svc_misc.cpp b/runtime/src/svc_misc.cpp'])
        source = output / 'source'
        fingerprint = runtime.prepare_source(reference, source, patches)
        # Independently undo the overlay on the composed private source, compare
        # every tracked/untracked fingerprint, then reapply exactly that overlay.
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patches[-1])], check=True)
        base = runtime.source_fingerprint(source)
        subprocess.run(['git', '-C', str(source), 'apply', str(patches[-1])], check=True)
        self.assertEqual(runtime.source_fingerprint(source), fingerprint)
        self.assertEqual([p for p in fingerprint if base[p] != fingerprint[p]], ['runtime/src/svc_misc.cpp'])
        fixture = output / 'fixture'
        fixture.mkdir()
        (fixture / 'nx').mkdir()
        for name in ('kernel.cpp', 'kernel.h', 'ipc.cpp', 'ipc.h', 'svc_am.cpp', 'svc_misc.cpp', 'hle_audio.cpp', 'hle_vi.cpp'):
            shutil.copyfile(source / 'runtime/src' / name, fixture / name)
        for name in ('nx/runtime.h', 'nx/game.h', 'kernel_state.h', 'platform.h', 'language.h'):
            (fixture / name).write_text('// Unrelated host boundary declarations are in kernel-host.h.\n')
        host = (ROOT / 'tests/test_kernel_events.cpp').read_text().split('int main() {', 1)[0]
        self.assertIn('#include "ipc.cpp"', host)
        (fixture / 'kernel-host.h').write_text(host)
        (fixture / 'astral_control_context.h').write_text('#pragma once\n')
        argv = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-I', str(fixture),
                str(ROOT / 'tests/test_apm_service.cpp'), '-o', str(output / 'apm-test')]
        build = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        (output / 'compile.log').write_text(build.stdout + build.stderr)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        result = subprocess.run([str(output / 'apm-test')], capture_output=True, text=True, timeout=10)
        (output / 'test.log').write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('PASS '), 4)
        receipt = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'patches': {p.name: runtime.sha(p) for p in patches}, 'source_files': fingerprint,
                   'base_svc_misc_sha256': base['runtime/src/svc_misc.cpp'],
                   'overlay_changed_paths': ['runtime/src/svc_misc.cpp'],
                   'fixture_sha256': runtime.sha(ROOT / 'tests/test_apm_service.cpp'),
                   'host_scaffold_sha256': runtime.sha(ROOT / 'tests/test_kernel_events.cpp'),
                   'compile': argv, 'binary_sha256': runtime.sha(output / 'apm-test'),
                   'exit_code': result.returncode, 'output': result.stdout}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(result.stdout, end='')
        print('private composition/test receipt:', output / 'receipt.json')


if __name__ == '__main__':
    unittest.main()
