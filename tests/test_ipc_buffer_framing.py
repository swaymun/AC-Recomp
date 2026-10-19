"""Apply the overlay to pinned private source and execute real serialized IPC."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class IpcBufferFramingTests(unittest.TestCase):
    def test_serialized_framing_and_existing_ipc(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip()).resolve()
        reference = common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        self.assertTrue(reference.is_dir(), 'clean pinned Wonder reference required')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        out = ROOT / '.local/ipc-buffer-039' / ('verify-' + uuid.uuid4().hex)
        out.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / n for n in
                   ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-ipc-buffer.patch')]
        source = out / 'source'
        fingerprint = runtime.prepare_source(reference, source, patches)
        subprocess.run(['git', 'apply', '-R', str(patches[-1])], cwd=source, check=True)
        base = runtime.source_fingerprint(source)
        subprocess.run(['git', 'apply', str(patches[-1])], cwd=source, check=True)
        self.assertEqual(runtime.source_fingerprint(source), fingerprint)
        self.assertEqual(sorted(p for p in fingerprint if base[p] != fingerprint[p]),
                         ['runtime/src/ipc.cpp', 'runtime/src/ipc.h'])
        changed = subprocess.check_output(['git', 'diff', '--name-only'], cwd=source, text=True).splitlines()
        # Validate the standalone overlay scope independently of the bootstrap.
        overlay_paths = [line.split(' b/')[1] for line in patches[-1].read_text().splitlines() if line.startswith('diff --git ')]
        self.assertEqual(set(overlay_paths), {'runtime/src/ipc.h', 'runtime/src/ipc.cpp'})
        fixture = out / 'fixture'
        fixture.mkdir()
        (fixture / 'nx').mkdir()
        names = ('kernel.cpp', 'kernel.h', 'ipc.cpp', 'ipc.h', 'svc_am.cpp', 'svc_misc.cpp', 'hle_audio.cpp', 'hle_vi.cpp')
        for name in names:
            shutil.copyfile(source / 'runtime/src' / name, fixture / name)
        for name in ('nx/runtime.h', 'nx/game.h', 'kernel_state.h', 'platform.h', 'language.h'):
            (fixture / name).write_text('// unrelated host declarations supplied by fixture\n')
        (fixture / 'astral_control_context.h').write_text('#pragma once\n#define NX_CONTROL_CONTEXT {1,1,0,{0},"' + 'a' * 64 + '"}\n')
        host = (ROOT / 'tests/test_kernel_events.cpp').read_text().split('int main() {', 1)[0]
        (fixture / 'kernel-host.h').write_text(host)
        receipt = {'utc': datetime.now(timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'patches': {p.name: sha(p) for p in patches}, 'prepared_changed_paths': changed,
                   'overlay_changed_paths': ['runtime/src/ipc.cpp', 'runtime/src/ipc.h'],
                   'compiled_sources': {n: sha(fixture / n) for n in names}, 'runs': []}
        for test in ('test_ipc_buffer_framing', 'test_ipc_caller'):
            binary = fixture / test
            command = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1',
                       '-I', str(fixture), str(ROOT / 'tests' / (test + '.cpp')), '-o', str(binary)]
            build = subprocess.run(command, capture_output=True, text=True, timeout=90)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn('PASS ', run.stdout)
            print(run.stdout, end='')
            receipt['runs'].append({'command': command, 'exit_code': run.returncode, 'output': run.stdout,
                                    'test_sha256': sha(ROOT / 'tests' / (test + '.cpp')), 'binary_sha256': sha(binary)})
        target = out / 'receipt.json'
        target.write_text(json.dumps(receipt, indent=2) + '\n')
        print('retained receipt:', target.relative_to(ROOT), sha(target))


if __name__ == '__main__':
    unittest.main()
