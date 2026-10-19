"""Compile actual notification+creator overlay handlers in a fresh pinned tree.

No network, credentials or game input. Compiled evidence stays in ignored .local.
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


class AppletServiceTests(unittest.TestCase):
    def test_actual_handlers_and_composition(self):
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT / common).resolve()
        reference = Path(os.environ.get('APPLET_REFERENCE', str(common.parent / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'clean pinned Wonder reference required via APPLET_REFERENCE')
        compiler = shutil.which('c++')
        self.assertIsNotNone(compiler)
        output = ROOT / '.local/applet-044' / ('verify-' + uuid.uuid4().hex)
        output.mkdir(parents=True)
        patches = [ROOT / 'runtime/patches' / p for p in
                   ('apple-memory.patch', 'astral-bootstrap.patch', 'astral-notifications.patch', 'astral-ipc-buffer.patch', 'astral-applet.patch')]
        self.assertEqual([s for s in patches[-1].read_text().splitlines() if s.startswith('diff --git ')],
                         ['diff --git a/runtime/src/svc_am.cpp b/runtime/src/svc_am.cpp'])
        source = output / 'source'
        fingerprint = runtime.prepare_source(reference, source, patches)
        subprocess.run(['git', '-C', str(source), 'apply', '-R', str(patches[-1])], check=True)
        base = runtime.source_fingerprint(source)
        subprocess.run(['git', '-C', str(source), 'apply', str(patches[-1])], check=True)
        self.assertEqual(runtime.source_fingerprint(source), fingerprint)
        self.assertEqual([p for p in fingerprint if base[p] != fingerprint[p]], ['runtime/src/svc_am.cpp'])
        fixture = output / 'fixture'
        fixture.mkdir()
        (fixture / 'nx').mkdir()
        for name in ('kernel.cpp', 'kernel.h', 'ipc.cpp', 'ipc.h', 'svc_am.cpp', 'svc_misc.cpp', 'hle_audio.cpp', 'hle_vi.cpp'):
            shutil.copyfile(source / 'runtime/src' / name, fixture / name)
        for name in ('nx/runtime.h', 'nx/game.h', 'kernel_state.h', 'platform.h', 'language.h'):
            (fixture / name).write_text('// Unrelated host declarations supplied by kernel-host.h.\n')
        host = (ROOT / 'tests/test_kernel_events.cpp').read_text().split('int main() {', 1)[0]
        old = 'VmInfo vm_query(uint64_t) { unexpected(); }'
        self.assertIn(old, host)
        host = host.replace(old, 'std::vector<VmInfo> fixture_regions;\n'
                            'VmInfo vm_query(uint64_t at) {\n'
                            ' for (auto v : fixture_regions) if (at >= v.addr && at-v.addr < v.size) return v;\n'
                            ' return {at,4096,0,0};\n}\n')
        (fixture / 'kernel-host.h').write_text(host)
        (fixture / 'astral_control_context.h').write_text('#pragma once\n')
        runs = []
        # Notification predecessor regression is compiled from the same composed source.
        for name in ('test_applet_service', 'test_applet_notifications'):
            binary = output / name
            argv = [compiler, '-std=c++20', '-pthread', '-DNX_ASTRAL_STRICT=1', '-I', str(fixture),
                    str(ROOT / 'tests' / (name + '.cpp')), '-o', str(binary)]
            build = subprocess.run(argv, capture_output=True, text=True, timeout=90)
            (output / (name + '-compile.log')).write_text(build.stdout + build.stderr)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
            (output / (name + '.log')).write_text(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS ', result.stdout)
            print(result.stdout, end='')
            runs.append({'build_command': argv, 'build_exit_code': build.returncode,
                         'command': [str(binary)], 'binary_sha256': runtime.sha(binary),
                         'compile_log_sha256': runtime.sha(output / (name + '-compile.log')),
                         'run_log_sha256': runtime.sha(output / (name + '.log')),
                         'compiled_sources': {n: runtime.sha(fixture / n) for n in ('kernel.cpp', 'kernel.h', 'ipc.cpp', 'ipc.h', 'svc_am.cpp')},
                         'fixture_sha256': runtime.sha(ROOT / 'tests' / (name + '.cpp')),
                         'exit_code': result.returncode, 'output': result.stdout})
        receipt = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'pin': runtime.PIN,
                   'patches': {p.name: runtime.sha(p) for p in patches}, 'source_files': fingerprint,
                   'base_svc_am_sha256': base['runtime/src/svc_am.cpp'],
                   'overlay_changed_paths': ['runtime/src/svc_am.cpp'], 'runs': runs,
                   'main': subprocess.check_output(['git', 'rev-parse', 'main'], cwd=ROOT, text=True).strip(),
                   'auto_select_acceptance': True, 'native_guest_run': False}
        (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print('private composition/test receipt:', (output / 'receipt.json').relative_to(ROOT), runtime.sha(output / 'receipt.json'))


if __name__ == '__main__':
    unittest.main()
