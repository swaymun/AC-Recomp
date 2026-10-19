"""Compile actual shipped IPC/kernel/AM sources plus the isolated notification overlay."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as runtime


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AppletNotificationTests(unittest.TestCase):
    def test_actual_serialized_handlers_and_regressions(self):
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler, 'C++ compiler required')
        patches = [ROOT / 'runtime/patches' / name for name in
                   ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-notifications.patch')]
        receipt = {'utc': datetime.now(timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'patches': {p.name: sha(p) for p in patches}, 'runs': []}
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            src = d / 'runtime/src'
            src.mkdir(parents=True)
            (d / 'nx').mkdir()
            names = ('kernel.cpp', 'kernel.h', 'ipc.cpp', 'ipc.h', 'svc_am.cpp',
                     'svc_misc.cpp', 'hle_audio.cpp', 'hle_vi.cpp')
            prepared = os.environ.get('APPLET_NOTIFICATION_SOURCE')
            for name in names:
                if prepared:
                    shutil.copyfile(Path(prepared) / 'runtime/src' / name, src / name)
                else:
                    (src / name).write_text(runtime.patched_source(patches[1], 'runtime/src/' + name))
            if not prepared:
                # Apply the actual overlay with Git, never emulate it with string substitutions.
                for args in (['--check'], []):
                    applied = subprocess.run(['git', 'apply', *args, str(patches[2])], cwd=d,
                                             capture_output=True, text=True, timeout=15)
                    self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            receipt['compiled_sources'] = {name: sha(src / name) for name in names}
            receipt['prepared_source'] = prepared
            for name in ('nx/runtime.h', 'nx/game.h', 'kernel_state.h', 'platform.h', 'language.h'):
                (d / name).write_text('// Unrelated host declarations supplied by fixture.\n')
            (d / 'astral_control_context.h').write_text(
                '#pragma once\n#define NX_CONTROL_CONTEXT {1,1,0,{0},"' + 'a' * 64 + '"}\n')
            host = (ROOT / 'tests/test_kernel_events.cpp').read_text().split('int main() {', 1)[0]
            (d / 'kernel-host.h').write_text(host)
            # Reuse every existing 13/16/91 assertion. Only retire the precise
            # obsolete assertions that these now-implemented selectors are fatal.
            regressions = (ROOT / 'tests/test_self_controller.cpp').read_text()
            regressions = regressions.replace(
                'for(uint32_t cmd:{11u,12u,14u,15u,17u,90u,0xffffffffu})',
                'for(uint32_t cmd:{15u,17u,90u,0xffffffffu})').replace(
                'for(uint32_t cmd:{14u,15u,17u,18u,90u,0xffffffffu})',
                'for(uint32_t cmd:{15u,17u,18u,90u,0xffffffffu})')
            (d / 'regressions.cpp').write_text(regressions)
            shutil.copyfile(ROOT / 'tests/test_applet_notifications.cpp', d / 'notifications.cpp')
            for fixture in ('notifications', 'regressions'):
                command = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1',
                           '-I', str(d), '-I', str(src), str(d / (fixture + '.cpp')),
                           '-o', str(d / fixture)]
                build = subprocess.run(command, capture_output=True, text=True, timeout=90)
                self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
                result = subprocess.run([str(d / fixture)], capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('PASS ', result.stdout)
                receipt['runs'].append({'fixture': fixture, 'source_sha256': sha(d / (fixture + '.cpp')),
                                        'binary_sha256': sha(d / fixture), 'command': command,
                                        'exit_code': result.returncode, 'output': result.stdout})
                print(result.stdout, end='')
        out = ROOT / '.local/applet-notify-033'
        out.mkdir(parents=True, exist_ok=True)
        target = out / ('prepared-tests.json' if prepared else 'tests.json')
        target.write_text(json.dumps(receipt, indent=2) + '\n')
        print('retained receipt:', target.relative_to(ROOT), sha(target))


if __name__ == '__main__':
    unittest.main()
