"""Synthetic package/path and real subprocess checks; no VM or credentials."""
import importlib.util
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import struct
import shutil
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('windows_native', ROOT / 'tools/windows_native.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def frozen_overlay(name):
    """The archived profile predates the comment-only public-export rewrite.

    Use its exact historical patch bytes; never re-bless changed live overlays by
    replacing CUMULATIVE_HASHES. Integration runs require the private Git history.
    """
    path = ROOT / 'runtime/patches' / name
    if w.sha(path) == w.CUMULATIVE_HASHES[name]:
        return path.read_bytes()
    raw = subprocess.check_output(['git', 'show',
        '47d82ea285e43d2ae260f28e703cd5aa2cf96420^:runtime/patches/' + name], cwd=ROOT)
    import hashlib
    if hashlib.sha256(raw).hexdigest() != w.CUMULATIVE_HASHES[name]:
        raise AssertionError('archived patch identity mismatch: ' + name)
    return raw


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='windows native ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def package(self):
        names = ['source/CMakeLists.txt', 'source/games/astral/game.cpp', 'source/runtime/src/main.cpp',
                 'gen/main/table.cpp', 'gen/sdk/table.cpp', 'data/analysis/main.bin',
                 'data/analysis/sdk.bin', 'driver/windows_native.py']
        for n in names:
            p = self.root / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'synthetic bytes\n')
        return {'schema': 1, 'unit': w.UNIT, 'pin': w.PIN, 'revision': 'a' * 40, 'files': w.tree(self.root)}

    def test_package_tamper_and_extra_file_rejected(self):
        manifest = self.package()
        w.validate_package(self.root, manifest)
        f = self.root / 'gen/main/table.cpp'
        f.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            w.validate_package(self.root, manifest)
        f.write_bytes(b'synthetic bytes\n')
        (self.root / 'extra').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            w.validate_package(self.root, manifest)

    def test_manifest_may_not_smuggle_auth_or_dump(self):
        for name in ('.git/config', 'source/.codex/auth.json', 'data/prod.keys', 'data/game.nsp'):
            with self.subTest(name=name):
                p = self.root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                manifest = self.package()
                p.write_text('synthetic')
                manifest['files'] = w.tree(self.root)
                with self.assertRaisesRegex(ValueError, 'forbidden'):
                    w.validate_package(self.root, manifest)
                p.unlink()

    def test_pe_identity_rejects_x86_dll_and_truncated_artifact(self):
        data = bytearray(256)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, 128)
        data[128:132] = b'PE\0\0'
        struct.pack_into('<HH', data, 132, 0x8664, 5)
        struct.pack_into('<H', data, 150, 2)
        struct.pack_into('<H', data, 152, 0x20b)
        exe = self.root / 'fixture.exe'
        exe.write_bytes(data)
        self.assertEqual(w.pe_identity(exe)['machine'], 'AMD64')
        for offset, value in ((132, 0x14c), (150, 0x2002), (152, 0x10b)):
            wrong = bytearray(data)
            struct.pack_into('<H', wrong, offset, value)
            exe.write_bytes(wrong)
            with self.assertRaisesRegex(ValueError, 'not a Windows x64'):
                w.pe_identity(exe)
        exe.write_bytes(b'MZ')
        with self.assertRaisesRegex(ValueError, 'DOS header'):
            w.pe_identity(exe)

    def test_path_traversal_and_windows_drives_rejected(self):
        for n in ('../a', '/abs', 'C:/acs', 'a/../../b', 'a\\b', 'a//b', './a', 'a/../b'):
            with self.subTest(name=n), self.assertRaises(ValueError):
                w.safe_member(n)
        self.assertEqual(w.safe_member('gen/main/table.cpp').as_posix(), 'gen/main/table.cpp')

    @unittest.skipIf(os.name == 'nt', 'symlink privilege differs on Windows')
    def test_symbolic_package_member_rejected(self):
        manifest = self.package()
        (self.root / 'gen/main/alias.cpp').symlink_to(self.root / 'gen/main/table.cpp')
        with self.assertRaisesRegex(ValueError, 'symbolic'):
            w.validate_package(self.root, manifest)

    def test_real_command_space_paths_and_nonzero_exit(self):
        script = self.root / 'script with spaces.py'
        script.write_text('import sys; print(sys.argv[1]); sys.exit(7)')
        result = w.run_stage([sys.executable, script, 'literal $() & value'], self.root / 'out.log', 3)
        self.assertEqual(result['exit_code'], 7)
        self.assertFalse(result['ok'])
        self.assertEqual((self.root / 'out.log').read_text().strip(), 'literal $() & value')
        self.assertEqual(result['log_sha256'], w.sha(self.root / 'out.log'))

    def test_real_timeout(self):
        result = w.run_stage([sys.executable, '-c', 'import time; time.sleep(20)'], self.root / 'timeout.log', .2)
        self.assertTrue(result['timed_out'])
        self.assertFalse(result['ok'])
        self.assertLess(result['elapsed_seconds'], 5)

    def test_log_limit(self):
        result = w.run_stage([sys.executable, '-u', '-c',
            'import time; print("x"*10000); time.sleep(20)'], self.root / 'limit.log', 3, max_bytes=1024)
        self.assertTrue(result['log_limit'])
        self.assertFalse(result['ok'])

    @unittest.skipIf(os.name == 'nt', 'POSIX process-group cleanup case')
    def test_normal_exit_cleans_owned_background_child(self):
        pidfile = self.root / 'child.pid'
        script = self.root / 'spawn.py'
        script.write_text('import subprocess,sys,pathlib\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(20)"])\npathlib.Path(sys.argv[1]).write_text(str(p.pid))\n')
        result = w.run_stage([sys.executable, script, pidfile], self.root / 'child.log', 3)
        self.assertTrue(result['ok'])
        pid = int(pidfile.read_text())
        end = time.monotonic() + 2
        while time.monotonic() < end:
            p = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
            if p.returncode or p.stdout.strip().startswith('Z'):
                break
            time.sleep(.02)
        else:
            self.fail('owned background child still running')

    def commands(self):
        build = self.root / 'output build'
        package = self.root / 'package'
        commands = []
        for n in ('gen/main/table.cpp', 'gen/sdk/table.cpp', 'source/runtime/src/main.cpp'):
            commands.append({'directory': str(build), 'file': str(package / n),
                'command': 'clang-cl /DNX_ASTRAL_STRICT=1 /clang:-ffp-contract=off /Fo"' + str(build / (str(len(commands)) + '.obj')) + '"'})
        return commands, build, package

    def test_compile_graph_must_include_actual_modules_and_strict_flags(self):
        commands, build, package = self.commands()
        self.assertEqual(len(w.compile_objects(commands, build, package)), 3)
        with self.assertRaisesRegex(ValueError, 'incomplete actual'):
            w.compile_objects(commands[:2], build, package)
        commands[0]['command'] = commands[0]['command'].replace('/DNX_ASTRAL_STRICT=1', '')
        with self.assertRaisesRegex(ValueError, 'strict'):
            w.compile_objects(commands, build, package)

    def test_compile_output_must_be_owned(self):
        commands, build, package = self.commands()
        commands[0]['command'] = 'clang-cl /DNX_ASTRAL_STRICT=1 /clang:-ffp-contract=off /Fo"' + str(self.root / 'escape.obj') + '"'
        with self.assertRaisesRegex(ValueError, 'outside'):
            w.compile_objects(commands, build, package)

    @unittest.skipIf(os.name == 'nt', 'POSIX fake compiler executable uses a shebang')
    def test_full_driver_with_real_synthetic_tool_subprocesses(self):
        self.full_driver(False)

    @unittest.skipIf(os.name == 'nt', 'POSIX fake compiler executable uses a shebang')
    def test_cumulative_driver_with_real_synthetic_tool_subprocesses(self):
        self.full_driver(True)

    def full_driver(self, cumulative):
        package = self.root / 'package'
        package.mkdir()
        original = self.root
        self.root = package
        manifest = self.cumulative_package() if cumulative else self.package()
        w.save(package / 'manifest.json', manifest)
        self.root = original
        tool = self.root / 'fake cmake'
        tool.write_text('#!' + sys.executable + '\n' + r'''import json,pathlib,sys
args=sys.argv[1:]
if args == ['--version']:
    print('synthetic tool 1.0'); sys.exit(0)
if '-S' in args:
    src=pathlib.Path(args[args.index('-S')+1]); package=src.parent
    build=pathlib.Path(args[args.index('-B')+1]); build.mkdir()
    commands=[]
    for i,n in enumerate(('gen/main/table.cpp','gen/sdk/table.cpp','source/runtime/src/main.cpp')):
        commands.append({'directory':str(build),'file':str(package/n),
            'command':'clang-cl /DNX_ASTRAL_STRICT=1 /clang:-ffp-contract=off /Fo"'+str(build/(str(i)+'.obj'))+'"'})
    (build/'compile_commands.json').write_text(json.dumps(commands))
elif '--build' in args:
    build=pathlib.Path(args[args.index('--build')+1])
    for i in range(3): (build/(str(i)+'.obj')).write_bytes(b'synthetic object')
    exe=build/'astral.exe'
    exe.write_text('#!'+sys.executable+'\nprint("entering nn::init::Start at synthetic fixture")\nprint("FATAL: synthetic boundary")\nraise SystemExit(1)\n')
    exe.chmod(0o700)
else: sys.exit(12)
''')
        tool.chmod(0o700)
        fake = {'clang-cl': str(tool), 'cmake': str(tool), 'ninja': str(tool), 'vulkan_sdk': 'synthetic SDK'}
        deadline = (w.datetime.now(w.timezone.utc) + timedelta(seconds=60)).isoformat()
        args = SimpleNamespace(package=package, out=self.root/'run', jobs=3, launch_seconds=2,
                               seconds=20, deadline=deadline)
        # Emulate only the platform gate; all configure/build/launch subprocesses
        # are real synthetic tools. No actual Windows acceptance is inferred.
        with mock.patch.object(w, 'os', SimpleNamespace(name='nt', environ=os.environ)), \
             mock.patch.object(w, 'discover', return_value=fake), \
             mock.patch.object(w, 'pe_identity', return_value={'synthetic_fixture': True}):
            w.native(args)
        rec = json.loads((args.out/'receipt.json').read_text())
        self.assertEqual(rec['object_count'], 3)
        self.assertTrue(rec['guest_executed'])
        self.assertEqual(rec['guest_exit_code'], 1)
        self.assertEqual(rec['startup_boundary'], 'FATAL: synthetic boundary')
        self.assertFalse(rec['gameplay_verified'])
        self.assertTrue(rec['inputs_unchanged'])
        self.assertEqual(rec['launch_environment']['NX_LOG'], str(args.out.resolve()/'guest-trace.log'))

    @unittest.skipIf(os.name == 'nt', 'Mac-only preparation validator imports fcntl')
    def test_stage_refuses_missing_control_before_source_preparation(self):
        sys.path.insert(0, str(ROOT/'tools'))
        self.addCleanup(lambda: sys.path.remove(str(ROOT/'tools')))
        import prepare_runtime as prep
        subprocess.run(['git', 'init', '-q', self.root], check=True)
        (self.root/'.gitignore').write_text('.local/\n')
        canonical = self.root.resolve()
        for name in ('inputs', 'gen', 'reference'):
            (canonical/name).mkdir()
        (canonical/'inputs/.wrapper').mkdir()
        (canonical/'inputs/.wrapper/manifest.json').write_text('{}')
        a = SimpleNamespace(repo=canonical, inputs=canonical/'inputs', gen=canonical/'gen', reference=canonical/'reference',
                            out=canonical/'.local/stage', control_metadata=None)
        with mock.patch.object(prep, 'validate_inputs', return_value=({}, 'a'*64)), \
             mock.patch.object(prep, 'validate_control', create=True), \
             mock.patch.object(w, 'profile_patches', return_value=[]), \
             mock.patch.object(prep, 'prepare_source') as prepare:
            with self.assertRaisesRegex(ValueError, 'requires validated control'):
                w.stage(a)
            prepare.assert_not_called()

    def cumulative_package(self):
        manifest = self.package()
        manifest.update(unit=w.CUMULATIVE_UNIT, profile=w.CUMULATIVE_PROFILE, patch_order=list(w.PROFILES[w.CUMULATIVE_PROFILE]),
                        patches=dict(w.CUMULATIVE_HASHES), input_manifest_sha256='a'*64)
        (self.root/'overlays').mkdir()
        for name in w.PROFILES[w.CUMULATIVE_PROFILE]:
            (self.root/'overlays'/name).write_bytes(frozen_overlay(name))
        generated = {mod: {'files': {'table.cpp': w.sha(self.root/'gen'/mod/'table.cpp')}}
                     for mod in ('main', 'sdk')}
        receipt = {'schema': 1, 'state': 'accepted', 'pin': w.PIN,
                   'manifest_sha256': 'a'*64, 'patch_sha256': w.CUMULATIVE_HASHES['astral-sqshl.patch'],
                   'files': {mod+'/table.cpp': {'after': rec['files']['table.cpp']}
                             for mod, rec in generated.items()}}
        (self.root/'receipts').mkdir()
        w.save(self.root/'receipts/regeneration.json', receipt)
        manifest.update(generated=generated, generated_receipt_sha256=w.sha(self.root/'receipts/regeneration.json'),
                        files=w.tree(self.root))
        manifest['prepared_sources'] = {n[7:]: v['sha256'] for n,v in manifest['files'].items()
                                        if n.startswith('source/')}
        return manifest

    def test_cumulative_package_rejects_profile_order_and_identity_drift(self):
        manifest = self.cumulative_package()
        w.validate_package(self.root, manifest)
        for field, bad in (('profile', '../other'), ('patch_order', list(reversed(manifest['patch_order']))),
                           ('patches', {}), ('prepared_sources', {}), ('generated', {}),
                           ('generated_receipt_sha256', '0'*64)):
            with self.subTest(field=field):
                changed = dict(manifest, **{field: bad})
                with self.assertRaises(ValueError):
                    w.validate_package(self.root, changed)
        receipt = json.loads((self.root/'receipts/regeneration.json').read_text())
        receipt['files']['main/table.cpp']['after'] = '0'*64
        w.save(self.root/'receipts/regeneration.json', receipt)
        manifest['files'] = w.tree(self.root)
        manifest['generated_receipt_sha256'] = w.sha(self.root/'receipts/regeneration.json')
        with self.assertRaisesRegex(ValueError, 'regeneration hash mismatch'):
            w.validate_package(self.root, manifest)

    def test_cumulative_native_bounds_rejected_before_tool_or_process(self):
        manifest = self.cumulative_package()
        w.save(self.root/'manifest.json', manifest)
        for seconds, launch in ((1201, 30), (1200, 31)):
            args = SimpleNamespace(package=self.root, out=self.root.parent/'must-not-exist',
                jobs=3, launch_seconds=launch, seconds=seconds, deadline='2099-01-01T00:00:00Z')
            with mock.patch.object(w, 'os', SimpleNamespace(name='nt', environ=os.environ)), \
                 mock.patch.object(w, 'discover') as discover, \
                 mock.patch.object(w, 'run_stage') as run:
                with self.assertRaisesRegex(ValueError, 'bounds exceeded'):
                    w.native(args)
                discover.assert_not_called()
                run.assert_not_called()

    def test_closed_profile_rejects_unknown_missing_tampered_and_linked_overlays(self):
        with self.assertRaisesRegex(ValueError, 'unknown Windows profile'):
            w.profile_patches('../../custom.patch', ROOT)
        patchroot = self.root/'runtime/patches'
        patchroot.mkdir(parents=True)
        for name in w.PROFILES[w.CUMULATIVE_PROFILE]:
            (patchroot/name).write_bytes(frozen_overlay(name))
        self.assertEqual(len(w.profile_patches(w.DEFAULT_PROFILE, self.root)), 3)
        self.assertEqual(len(w.profile_patches(w.CUMULATIVE_PROFILE, self.root)), 11)
        patch = patchroot/'astral-hid.patch'
        original = patch.read_bytes()
        patch.write_bytes(original+b'changed')
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            w.profile_patches(w.CUMULATIVE_PROFILE, self.root)
        patch.unlink()
        with self.assertRaisesRegex(ValueError, 'missing or linked'):
            w.profile_patches(w.CUMULATIVE_PROFILE, self.root)
        patch.write_bytes(original)
        os.link(patch, self.root/'hardlink')
        with self.assertRaisesRegex(ValueError, 'missing or linked'):
            w.profile_patches(w.CUMULATIVE_PROFILE, self.root)
        (self.root/'hardlink').unlink()
        patch.unlink()
        patch.symlink_to(ROOT/'runtime/patches/astral-hid.patch')
        with self.assertRaisesRegex(ValueError, 'symbolic'):
            w.profile_patches(w.CUMULATIVE_PROFILE, self.root)

    def test_hardlinked_and_parent_symlink_inputs_refused(self):
        f = self.root/'input'
        f.write_text('synthetic')
        os.link(f, self.root/'alias')
        with self.assertRaisesRegex(ValueError, 'linked'):
            w.tree(self.root)
        (self.root/'alias').unlink()
        directory = self.root/'real'
        directory.mkdir()
        (directory/'file').write_text('synthetic')
        (self.root/'link').symlink_to(directory, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symbolic'):
            w.regular(self.root/'link/file')

    @unittest.skipIf(os.name == 'nt', 'Mac-only pinned source composition')
    def test_actual_clean_pinned_reference_composes_closed_cumulative_profile(self):
        sys.path.insert(0, str(ROOT/'tools'))
        self.addCleanup(lambda: sys.path.remove(str(ROOT/'tools')))
        import prepare_runtime as prep
        common = Path(subprocess.check_output(['git', 'rev-parse', '--git-common-dir'], cwd=ROOT, text=True).strip())
        if not common.is_absolute():
            common = (ROOT/common).resolve()
        reference = Path(os.environ.get('WINDOWS_REFERENCE', str(common.parent/
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'provide clean pinned Wonder using WINDOWS_REFERENCE')
        source = self.root/'prepared'
        patchroot = self.root / 'runtime/patches'
        patchroot.mkdir(parents=True)
        for name in w.PROFILES[w.CUMULATIVE_PROFILE]:
            (patchroot / name).write_bytes(frozen_overlay(name))
        patches = w.profile_patches(w.CUMULATIVE_PROFILE, self.root)
        fingerprint = prep.prepare_source(reference, source, patches)
        self.assertEqual(prep.git(source, 'rev-parse', 'HEAD'), w.PIN)
        self.assertEqual(fingerprint, prep.source_fingerprint(source))
        self.assertIn('add_compile_options(/bigobj /clang:-ffp-contract=off)', (source/'CMakeLists.txt').read_text())
        self.assertIn('receive_size_table(8, 1, table)', (source/'runtime/src/svc_am.cpp').read_text())
        self.assertEqual(fingerprint['runtime/src/hle_hid.cpp'],
                         '68af4e7cb56208c668c40bfac6c0cb19d1c73c8c0f6978cc420ba933cfe32509')
        subprocess.run(['git', '-C', source, 'diff', '--check'], check=True, capture_output=True)
        print('PASS clean pinned cumulative composition:', len(patches), 'overlays,', len(fingerprint), 'sources')

    def test_windows_patch_git_integration_and_reverse(self):
        subprocess.run(['git', 'init', '-q', self.root], check=True)
        cmake = self.root / 'CMakeLists.txt'
        baseline = ('cmake_minimum_required(VERSION 3.25)\n'
            'project(SwitchGamesRecomp C CXX)\n\n'
            'set(CMAKE_CXX_STANDARD 20)\nset(CMAKE_CXX_STANDARD_REQUIRED ON)\n\n'
            '# The game this build is for: games/<NX_GAME>/ holds what only that game needs (game.cpp: nx/game.h), the shared\n'
            '# runtime is the rest. One build directory per game.\n'
            'set(NX_GAME "hades" CACHE STRING "Game to build (a folder under games/)")\n'
            '# Astral native memory profile is shared by runtime AND every generated TU.\n'
            'if(NX_GAME STREQUAL "astral")\n    add_compile_definitions(NX_ASTRAL_STRICT=1)\nendif()\n')
        cmake.write_text(baseline)
        patch = ROOT / 'runtime/patches/windows-native.patch'
        for args in (['apply', '--check', patch], ['apply', patch], ['diff', '--check']):
            subprocess.run(['git', '-C', self.root, *args], check=True, capture_output=True)
        self.assertIn('add_compile_options(/bigobj /clang:-ffp-contract=off)', cmake.read_text())
        subprocess.run(['git', '-C', self.root, 'apply', '--reverse', patch], check=True, capture_output=True)
        self.assertEqual(cmake.read_text(), baseline)

    def test_cli_refuses_native_execution_off_windows(self):
        if os.name == 'nt': self.skipTest('non-Windows gate')
        p = subprocess.run([sys.executable, ROOT / 'tools/windows_native.py', 'run', '--package', self.root,
            '--out', self.root / 'out', '--deadline', '2000-01-01T00:00:00Z'], capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn('must execute on Windows', p.stderr)
        self.assertFalse((self.root / 'out').exists())


class PlayerHelpersTests(unittest.TestCase):
    def test_native_archive_reader_refuses_links_and_binds_open_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            file = root / 'archive.pkz'
            file.write_bytes(b'synthetic archive')
            with w.windows_regular_open(file) as stream:
                self.assertEqual(stream.read(), b'synthetic archive')
            os.link(file, root / 'hardlink')
            with self.assertRaisesRegex(ValueError, 'single-link regular'):
                w.windows_regular_open(file)
            (root / 'hardlink').unlink()
            if os.name != 'nt':
                (root / 'symbolic').symlink_to(file)
                with self.assertRaisesRegex(ValueError, 'symbolic archive path'):
                    w.windows_regular_open(root / 'symbolic')
            replacement = root / 'replacement'
            replacement.write_bytes(b'other archive')
            original_open = os.open
            def swap_then_open(path, flags):
                os.replace(replacement, file)
                return original_open(path, flags)
            with mock.patch.object(w.os, 'open', side_effect=swap_then_open):
                with self.assertRaisesRegex(ValueError, 'changed while opening'):
                    w.windows_regular_open(file)

    def test_archive_reader_is_installed_in_real_spawned_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            file = root / 'fixture.pkz'
            file.write_bytes(b'fixture archive bytes')
            script = root / 'spawn_reader.py'
            script.write_text('''import concurrent.futures,multiprocessing,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import windows_native as w
def read(path):
 import inventory_astral_pkz as pkz
 with pkz.regular_open(Path(path)) as stream: return stream.read()
if __name__ == '__main__':
 with concurrent.futures.ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn'),initializer=w.install_windows_archive_reader) as pool:
  assert pool.submit(read,sys.argv[2]).result(timeout=20)==b'fixture archive bytes'
 print('PASS spawned native reader')
''')
            result = subprocess.run([sys.executable, str(script), str(ROOT / 'tools'), str(file)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PASS spawned native reader', result.stdout)

    def test_cmd_environment_keeps_equals_and_skips_pseudo_variables(self):
        self.assertEqual(w.parse_environment('banner\r\n=C:=C:\\src\r\nPath=A;B\r\nLIB=x=y\r\n'),
                         {'PATH': 'A;B', 'LIB': 'x=y'})

    def test_developer_environment_uses_vswhere_and_x64_prompt(self):
        with mock.patch.object(Path, 'is_file', return_value=True), \
             mock.patch.object(w.subprocess, 'check_output', side_effect=[
                 'C:/VS Build Tools\n', 'Path=old\nINCLUDE=inc\nLIB=lib\n']), \
             mock.patch.object(w.shutil, 'which', return_value='clang-cl.exe'):
            env = w.developer_environment()
            calls = w.subprocess.check_output.call_args_list
        self.assertIn('Microsoft.VisualStudio.Component.VC.Tools.x86.x64', calls[0].args[0])
        self.assertIn('"C:/VS Build Tools/Common7/Tools/VsDevCmd.bat"', calls[1].args[0])
        self.assertIn('-arch=x64 -host_arch=x64', calls[1].args[0])
        self.assertIn('Llvm/x64/bin', env['PATH'])
        self.assertEqual(env['INCLUDE'], 'inc')

    def test_incomplete_developer_environment_fails_closed(self):
        with mock.patch.object(Path, 'is_file', return_value=True), \
             mock.patch.object(w.subprocess, 'check_output', side_effect=['C:/VS', 'PATH=x\n']):
            with self.assertRaisesRegex(ValueError, 'INCLUDE/LIB/PATH'):
                w.developer_environment()

    def test_junction_detection_uses_mount_point_tag(self):
        path = mock.Mock()
        with mock.patch.object(w.stat, 'IO_REPARSE_TAG_MOUNT_POINT', 0xa0000003, create=True):
            path.lstat.return_value = SimpleNamespace(st_reparse_tag=0xa0000003)
            self.assertTrue(w.is_junction(path))
            path.lstat.return_value = SimpleNamespace(st_reparse_tag=0xa000000c)
            self.assertFalse(w.is_junction(path))
            path.lstat.side_effect = FileNotFoundError()
            self.assertFalse(w.is_junction(path))

    def test_termination_targets_only_invocation_pid(self):
        process = mock.Mock(pid=4321)
        with mock.patch.object(w.subprocess, 'run') as run:
            w.terminate_tree(process)
        self.assertEqual(run.call_args.args[0], ['taskkill.exe', '/PID', '4321', '/T', '/F'])
        process.wait.assert_called_once_with(timeout=30)

    def test_archived_profile_still_rejects_evolved_live_patches(self):
        drift = [name for name, digest in w.CUMULATIVE_HASHES.items()
                 if w.sha(ROOT / 'runtime/patches' / name) != digest]
        if drift:
            with self.assertRaisesRegex(ValueError, 'landed Windows patch identity mismatch'):
                w.profile_patches(w.CUMULATIVE_PROFILE, ROOT)
        self.assertEqual(w.CUMULATIVE_HASHES['astral-bootstrap.patch'],
                         '05f84f0025cc7074f157232e066288fae8f8b5c9ada535820cf2c5a2adff2f7c')


if __name__ == '__main__':
    unittest.main()
