"""Tests for tools/acr_setup_cmd.py, the setup app's helper: command assembly, PATH, prerequisite rows and the kit
copy. Everything runs against fake prefixes and fake runners; nothing is installed or built."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import acr_setup_cmd as sc  # noqa: E402
import acr_build  # noqa: E402


def fake_runner(versions=None, sdks='', clt=True):
    versions = {os.path.normpath(str(k)): v for k, v in (versions or {}).items()}

    def run(cmd, **kw):
        exe = cmd[0]
        if exe.endswith('xcode-select'):
            return types.SimpleNamespace(returncode=0 if clt else 2, stdout='', stderr='')
        if exe.endswith('dotnet'):
            return types.SimpleNamespace(returncode=0, stdout=sdks, stderr='')
        if os.path.normpath(exe) in versions:
            return types.SimpleNamespace(returncode=0, stdout=versions[os.path.normpath(exe)] + '\n', stderr='')
        return types.SimpleNamespace(returncode=1, stdout='', stderr='')
    return run


class CommandTest(unittest.TestCase):
    def test_minimal_command(self):
        argv = sc.build_argv('/py', '/kit', '/g/Astral Chain.nsp', '/k/prod.keys', '/o')
        self.assertEqual(argv, ['/py', '-u', os.path.join('/kit', 'tools', 'acr_build.py'), '--nsp', '/g/Astral Chain.nsp',
                                '--keys', '/k/prod.keys', '--out', '/o'])

    def test_all_options(self):
        argv = sc.build_argv('/py', '/kit', '/a.nsp', '/p.keys', '/o', title_keys='/t.keys', fonts='/f',
                             fps='60', render_res='2560x1440')
        self.assertEqual(argv[3:], ['--nsp', '/a.nsp', '--keys', '/p.keys', '--title-keys', '/t.keys',
                                    '--fonts', '/f', '--out', '/o', '--fps', '60', '--render-res', '2560x1440'])

    def test_command_is_accepted_by_acr_build(self):
        argv = sc.build_argv('/py', '/kit', '/a.nsp', '/p.keys', '/tmp/acr-setup-test-out', title_keys='/t.keys',
                             fonts='/f', fps='60', render_res='2560x1440')
        a = acr_build.parse(argv[3:] + ['--dry-run'])
        self.assertEqual((a.nsp.as_posix(), a.keys.as_posix(), a.title_keys.as_posix(), a.fonts.as_posix(), a.fps, a.render_res),
                         ('/a.nsp', '/p.keys', '/t.keys', '/f', '60', '2560x1440'))

    def test_rejects_bad_values(self):
        with self.assertRaises(ValueError):
            sc.build_argv('/py', '/kit', '', '/p.keys', '/o')
        with self.assertRaises(ValueError):
            sc.build_argv('/py', '/kit', '/a.nsp', '/p.keys', '/o', fps='120')
        with self.assertRaises(ValueError):
            sc.build_argv('/py', '/kit', '/a.nsp', '/p.keys', '/o', render_res='4k; rm -rf ~')

    def test_offered_resolutions_are_valid(self):
        import astral_render_res as rr
        swift = (ROOT / 'ports/macos-setup/SetupApp.swift').read_text()
        offered = set(__import__('re').findall(r'"(\d{4}x\d{3,4})"', swift))
        self.assertTrue(offered)
        for res in offered:
            rr.plan(*rr.parse_res(res))

    def test_env_puts_homebrew_first_without_duplicates(self):
        brew_bin = os.path.join('/opt/homebrew', 'bin')
        env = sc.build_env({'PATH': '/usr/bin:' + brew_bin + ':/bin', 'HOME': '/h'}, prefixes=('/opt/homebrew',))
        self.assertEqual(env['PATH'].split(':')[:3], [brew_bin, os.path.join('/opt/homebrew', 'sbin'),
                                                      '/usr/local/share/dotnet'])
        self.assertEqual(env['PATH'].count(brew_bin), 1)
        self.assertEqual(env['PYTHONUNBUFFERED'], '1')
        self.assertEqual(env['HOME'], '/h')

    def test_command_subcommand_prints_json(self):
        p = subprocess.run([sys.executable, str(ROOT / 'tools/acr_setup_cmd.py'), 'command', '--nsp', '/a.nsp',
                            '--keys', '/p.keys', '--out', '/o', '--python', '/py', '--fps', '60'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        argv = json.loads(p.stdout)['argv']
        self.assertEqual(argv[:2], ['/py', '-u'])
        self.assertEqual(argv[-2:], ['--fps', '60'])

    def test_helper_runs_on_python39_syntax(self):
        # The command-line tools ship Python 3.9; the helper must parse with its grammar.
        import ast
        ast.parse((ROOT / 'tools/acr_setup_cmd.py').read_text(), feature_version=(3, 9))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.brew = self.tmp / 'brew'

    def install_brew(self, formulae=()):
        (self.brew / 'bin').mkdir(parents=True)
        (self.brew / 'bin/brew').write_text('')
        for f in formulae:
            (self.brew / 'opt' / f).mkdir(parents=True)

    def rows(self, **kw):
        return {r['id']: r for r in sc.check(prefixes=(str(self.brew),), runner=fake_runner(**kw))}

    def test_nothing_installed(self):
        rows = self.rows(clt=False)
        self.assertEqual(list(rows), ['clt', 'brew', 'python', 'formulae', 'dotnet'])
        self.assertFalse(any(r['ok'] for r in rows.values()))
        self.assertEqual(rows['clt']['fix'], 'xcode-select --install')
        self.assertIn('install.sh', rows['brew']['fix'])
        self.assertEqual(rows['formulae']['fix'], 'brew install ' + ' '.join(sc.FORMULAE))

    def test_everything_installed(self):
        self.install_brew(sc.FORMULAE)
        py = str(self.brew / 'bin/python3')
        Path(py).write_text('')
        (self.brew / 'bin/dotnet').write_text('')
        rows = self.rows(versions={py: '3.13'}, sdks='10.0.100 [/x]\n')
        self.assertTrue(all(r['ok'] for r in rows.values()), rows)
        self.assertIn('3.13', rows['python']['detail'])

    def test_old_python_and_missing_formulae(self):
        self.install_brew(('sdl3', 'opus', 'cmake'))
        py = str(self.brew / 'bin/python3')
        Path(py).write_text('')
        rows = self.rows(versions={py: '3.10'}, sdks='8.0.100 [/x]\n')
        self.assertFalse(rows['python']['ok'])
        self.assertTrue(rows['python']['fix'].endswith('brew install python'))
        self.assertFalse(rows['formulae']['ok'])
        self.assertNotIn('sdl3', rows['formulae']['fix'])
        self.assertIn('molten-vk', rows['formulae']['fix'])
        self.assertFalse(rows['dotnet']['ok'])
        self.assertEqual(rows['dotnet']['fix'], sc.DOTNET_INSTALL)
        self.assertIn('--install-dir ~/.dotnet', rows['dotnet']['fix'])
        self.assertNotIn('sudo', rows['dotnet']['fix'])

    def test_optional_formulae_do_not_block(self):
        self.install_brew([f for f in sc.FORMULAE if f not in sc.OPTIONAL_FORMULAE])
        rows = self.rows()
        self.assertTrue(rows['formulae']['ok'])
        self.assertIn('missing: cmake', rows['formulae']['detail'])

    def test_preflight_list_matches_acr_build(self):
        hint = set(acr_build.BREW_HINT.split()[2:])
        self.assertEqual(hint, set(sc.FORMULAE))


class OutFolderTest(unittest.TestCase):
    def test_overlapping_folders(self):
        self.assertTrue(sc.nested('/a/kit', '/a/kit/'))
        self.assertTrue(sc.nested('/a/kit/build', '/a/kit'))
        self.assertTrue(sc.nested('/a', '/a/kit'))
        self.assertTrue(sc.nested('/a/kit/x/../build', '/a/kit'))
        self.assertFalse(sc.nested('/a/build', '/a/kit'))
        self.assertFalse(sc.nested('/a/kit2', '/a/kit'))
        sc.check_out('/a/build', ('/a/kit', None))
        with self.assertRaises(ValueError):
            sc.check_out('/a/kit/build', ('/b/bundled', '/a/kit'))

    def test_run_refuses_an_out_inside_the_kit_before_touching_anything(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        kit = tmp / 'kit'
        (kit / 'build').mkdir(parents=True)
        (kit / 'build/acr-state.json').write_text('{}')
        for out in (kit, kit / 'build', tmp):
            p = subprocess.run([sys.executable, str(ROOT / 'tools/acr_setup_cmd.py'), 'run', '--nsp', '/a.nsp',
                                '--keys', '/p.keys', '--out', str(out), '--kit', str(kit), '--python', '/py'],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn('overlaps the build kit', p.stderr)
        self.assertTrue((kit / 'build/acr-state.json').is_file())
        p = subprocess.run([sys.executable, str(ROOT / 'tools/acr_setup_cmd.py'), 'command', '--nsp', '/a.nsp',
                            '--keys', '/p.keys', '--out', str(ROOT / 'tools/out'), '--python', '/py'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 2)


class KitCopyTest(unittest.TestCase):
    def test_copy_is_skipped_when_current_and_refreshed_when_not(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src = tmp / 'src'
        (src / 'tools').mkdir(parents=True)
        (src / 'tools/acr_build.py').write_text('a')
        (src / 'KIT_VERSION').write_text('v1+aaa\n')
        dest = tmp / 'support/kit'
        dest.parent.mkdir()
        sc.copy_kit(src, dest)
        self.assertEqual((dest / 'tools/acr_build.py').read_text(), 'a')
        (dest / 'marker').write_text('kept')
        sc.copy_kit(src, dest)
        self.assertTrue((dest / 'marker').exists())
        (src / 'KIT_VERSION').write_text('v1+bbb\n')
        (src / 'tools/acr_build.py').write_text('b')
        sc.copy_kit(src, dest)
        self.assertFalse((dest / 'marker').exists())
        self.assertEqual((dest / 'tools/acr_build.py').read_text(), 'b')
        self.assertFalse(Path(str(dest) + '.tmp').exists())


class WindowsSetupTest(unittest.TestCase):
    def test_windows_build_env_overrides_legacy_encoding_without_mutating_parent(self):
        base = {'PATH': 'unchanged', 'PYTHONUTF8': '0', 'PYTHONIOENCODING': 'cp1252'}
        env = sc.windows_build_env(base)
        self.assertEqual(env['PATH'], base['PATH'])
        self.assertEqual(env['PYTHONUTF8'], '1')
        self.assertEqual(env['PYTHONIOENCODING'], 'utf-8')
        self.assertEqual(base['PYTHONIOENCODING'], 'cp1252')

    def test_windows_setup_python_processes_handle_unicode_without_preset_encoding(self):
        # Start with no inherited UTF-8 settings. Force only the already-running
        # helper's streams to cp1252 to reproduce the review failure on any host.
        # The child also reads a UTF-8 text file without an encoding argument,
        # checking PYTHONUTF8 in addition to PYTHONIOENCODING.
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            kit = temp / 'kit'
            (kit / 'tools').mkdir(parents=True)
            unicode_text = 'build \u96ea \u2603'
            output = temp / unicode_text
            (kit / 'tools/acr_build.py').write_text(
                'import json, os, sys\nfrom pathlib import Path\n'
                'out = Path(sys.argv[sys.argv.index("--out") + 1])\n'
                'out.mkdir(parents=True)\n'
                'p = out / "utf8.txt"\n'
                'p.write_bytes("\\u96ea \\u2603".encode("utf-8"))\n'
                'assert p.read_text() == "\\u96ea \\u2603"\n'
                'assert os.environ["PYTHONUTF8"] == "1"\n'
                'assert os.environ["PYTHONIOENCODING"] == "utf-8"\n'
                'print(out, flush=True)\n'
                'print(out, file=sys.stderr, flush=True)\n'
                'sys.exit(0 if "--to-stage" in sys.argv else 17)\n', encoding='utf-8')
            bootstrap = (
                'import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                'import acr_setup_cmd as sc; sc.KIT=Path(sys.argv[2]); '
                'sys.stdout.reconfigure(encoding="cp1252"); '
                'sys.stderr.reconfigure(encoding="cp1252"); '
                'raise SystemExit(sc.main(sys.argv[3:]))')
            env = {k: v for k, v in os.environ.items() if k not in ('PYTHONUTF8', 'PYTHONIOENCODING')}
            for control_only, expected in ((True, 0), (False, 17)):
                out = output / str(control_only)
                args = ['run', '--windows', '--nsp', 'unused.nsp', '--keys', 'unused.keys',
                        '--out', str(out)]
                if control_only:
                    args += ['--to-stage', 'control']
                result = subprocess.run([sys.executable, '-X', 'utf8=0', '-c', bootstrap,
                                         str(ROOT / 'tools'), str(kit), *args], env=env,
                                        capture_output=True, encoding='utf-8')
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertIn(unicode_text, str(out))
                self.assertEqual(result.stdout.strip(), str(out))
                self.assertEqual(result.stderr.strip(), str(out))
                self.assertEqual((out / 'utf8.txt').read_text(encoding='utf-8'), '\u96ea \u2603')
            # The helper itself can report Unicode paths before a child starts.
            overlap = kit / unicode_text
            result = subprocess.run([sys.executable, '-X', 'utf8=0', '-c', bootstrap,
                                     str(ROOT / 'tools'), str(kit), 'run', '--windows',
                                     '--out', str(overlap)], env=env,
                                    capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(str(overlap), result.stderr)
            self.assertIn('overlaps the build kit', result.stderr)

    @unittest.skipUnless(os.name == 'nt', 'requires Windows PowerShell 5 native process handling')
    def test_powershell_uses_exit_code_even_when_native_build_writes_stderr(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            native = temp / 'native build.py'
            native.write_text('import os,sys\nassert os.environ["PYTHONUTF8"] == "1"\n'
                              'assert os.environ["PYTHONIOENCODING"] == "utf-8"\n'
                              'print("progress \\u96ea", file=sys.stderr)\n'
                              'print("build output \\u2603")\nsys.exit(int(sys.argv[1]))\n')
            probe = temp / 'probe.ps1'
            probe.write_text(r'''
$ErrorActionPreference = 'Stop'
$tokens = $null; $errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw "Setup parse errors: $errors" }
Remove-Item Env:PYTHONUTF8,Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
foreach ($name in @('Set-PythonUtf8','Invoke-SetupBuild')) {
    $function = $ast.Find({param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    if (-not $function) { throw "Function missing: $name" }
    . ([scriptblock]::Create($function.Extent.Text))
}
foreach ($expected in @(0,17)) {
    $result = Invoke-SetupBuild -Python $args[1] -Arguments @($args[2], "$expected")
    if ($result -ne $expected) { throw "Expected exit $expected, got $result" }
    if ($ErrorActionPreference -ne 'Stop') { throw 'Error preference was not restored' }
}
$missingRejected = $false
try { Invoke-SetupBuild -Python (Join-Path $PSScriptRoot 'missing-interpreter.exe') -Arguments @() }
catch { $missingRejected = $_.Exception.Message -eq 'Build interpreter is missing. Rerun setup.' }
if (-not $missingRejected) { throw 'Missing interpreter was not rejected' }
''')
            result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                                     str(probe), str(ROOT / 'ports/windows/Setup.ps1'), sys.executable, str(native)],
                                    capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('progress \u96ea', result.stdout)
            self.assertIn('build output \u2603', result.stdout)

    def test_import_command_roundtrips_through_actual_build_parser(self):
        argv = sc.build_argv('/py', '/kit', None, None, '/install with spaces',
                             import_dir='/private input', control_receipt='/receipt.json',
                             spirv_dir='/shaders', jobs=2)
        a = acr_build.parse(argv[3:])
        self.assertEqual(a.import_dir.as_posix(), '/private input')
        self.assertEqual(a.out.as_posix(), '/install with spaces')
        self.assertEqual(a.control_receipt.as_posix(), '/receipt.json')
        self.assertEqual(a.jobs, 2)
        self.assertNotIn('--keys', argv)

    def test_import_rejects_missing_receipt_or_key_mixing(self):
        for kw in ({'import_dir': '/input'},
                   {'import_dir': '/input', 'control_receipt': '/receipt', 'keys': '/keys'},
                   {'control_receipt': '/receipt'}):
            args = dict(python='/py', kit='/kit', nsp=None, keys=None, out='/out')
            args.update(kw)
            with self.assertRaises(ValueError):
                sc.build_argv(**args)

    def test_windows_command_cli_preserves_paths_without_opening_inputs(self):
        p = subprocess.run([sys.executable, str(ROOT / 'tools/acr_setup_cmd.py'), 'command',
                            '--windows', '--import-dir', '/input not present', '--control-receipt',
                            '/no receipt', '--out', '/output not present', '--python', sys.executable,
                            '--spirv-dir', '/private shaders', '--jobs', '3'], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)
        self.assertIn('/input not present', data['argv'])
        self.assertEqual(data['env']['PATH'], os.environ['PATH'])
        p = subprocess.run([sys.executable, str(ROOT / 'tools/acr_setup_cmd.py'), 'command',
                            '--windows', '--nsp', '/dump', '--keys', '/keys', '--out', '/out'],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn('--nsp', json.loads(p.stdout)['argv'])
        self.assertNotIn('--import-dir', json.loads(p.stdout)['argv'])

    def test_local_dump_can_reuse_translated_shaders(self):
        argv = sc.build_argv('/py', '/kit', '/dump.nsp', '/prod.keys', '/out', spirv_dir='/shaders')
        self.assertIn('--spirv-dir', argv)
        self.assertNotIn('--import-dir', argv)

    def test_control_only_setup_never_finishes_an_install(self):
        args = ['run', '--windows', '--nsp', '/dump.nsp', '--keys', '/prod.keys',
                '--out', '/out', '--to-stage', 'control']
        with patch.object(sc.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as run, \
                patch.object(sc, 'windows_install') as finish:
            self.assertEqual(sc.main(args), 0)
            self.assertEqual(run.call_args.args[0][-2:], ['--to-stage', 'control'])
            finish.assert_not_called()

    def test_failed_real_build_process_never_runs_finish_or_creates_shortcuts(self):
        calls = []
        def runner(argv, **kw):
            calls.append(argv)
            # Meaningful subprocess exit propagation without running installers.
            return subprocess.run([sys.executable, '-c', 'raise SystemExit(17)'], **kw)
        self.assertEqual(sc.windows_install(['build'], '/kit', '/out', runner=runner), 17)
        self.assertEqual(calls, [['build']])

    def test_finish_runs_only_after_success_and_propagates_its_failure(self):
        calls = []
        def runner(argv, **kw):
            calls.append(argv)
            return types.SimpleNamespace(returncode=0 if len(calls) == 1 else 9)
        self.assertEqual(sc.windows_install(['build'], '/kit', '/output with spaces', False, runner), 9)
        self.assertEqual(calls[1][-3:], ['-InstallDir', '/output with spaces', '-NoDesktopShortcut'])
        self.assertIn(str(Path('/kit') / 'ports/windows/FinishInstall.ps1'), calls[1])

    def test_dry_run_never_finishes_windows_install(self):
        args = ['run', '--windows', '--import-dir', '/input', '--control-receipt', '/receipt',
                '--out', '/out', '--dry-run']
        with patch.object(sc.subprocess, 'run', return_value=types.SimpleNamespace(returncode=0)) as run, \
                patch.object(sc, 'windows_install') as finish, patch.object(sc.os, 'makedirs') as mkdir:
            self.assertEqual(sc.main(args), 0)
            self.assertIn('--dry-run', run.call_args.args[0])
            finish.assert_not_called()
            mkdir.assert_not_called()

    def test_invalid_inputs_cannot_refresh_a_kit_or_overlap_the_import(self):
        with patch.object(sc, 'copy_kit') as copy:
            self.assertEqual(sc.main(['run', '--windows', '--out', '/out', '--kit', '/kit']), 2)
            copy.assert_not_called()
        with patch.object(sc, 'windows_install') as install:
            self.assertEqual(sc.main(['run', '--windows', '--out', '/input/install',
                                      '--import-dir', '/input', '--control-receipt', '/receipt']), 2)
            install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
