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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import acr_setup_cmd as sc  # noqa: E402
import acr_build  # noqa: E402


def fake_runner(versions=None, sdks='', clt=True):
    versions = versions or {}

    def run(cmd, **kw):
        exe = cmd[0]
        if exe.endswith('xcode-select'):
            return types.SimpleNamespace(returncode=0 if clt else 2, stdout='', stderr='')
        if exe.endswith('dotnet'):
            return types.SimpleNamespace(returncode=0, stdout=sdks, stderr='')
        if exe in versions:
            return types.SimpleNamespace(returncode=0, stdout=versions[exe] + '\n', stderr='')
        return types.SimpleNamespace(returncode=1, stdout='', stderr='')
    return run


class CommandTest(unittest.TestCase):
    def test_minimal_command(self):
        argv = sc.build_argv('/py', '/kit', '/g/Astral Chain.nsp', '/k/prod.keys', '/o')
        self.assertEqual(argv, ['/py', '-u', '/kit/tools/acr_build.py', '--nsp', '/g/Astral Chain.nsp',
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
        self.assertEqual((str(a.nsp), str(a.keys), str(a.title_keys), str(a.fonts), a.fps, a.render_res),
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
        env = sc.build_env({'PATH': '/usr/bin:/opt/homebrew/bin:/bin', 'HOME': '/h'}, prefixes=('/opt/homebrew',))
        self.assertEqual(env['PATH'].split(':')[:3], ['/opt/homebrew/bin', '/opt/homebrew/sbin',
                                                      '/usr/local/share/dotnet'])
        self.assertEqual(env['PATH'].count('/opt/homebrew/bin'), 1)
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


if __name__ == '__main__':
    unittest.main()
