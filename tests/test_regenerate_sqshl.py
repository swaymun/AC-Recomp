"""Temporary Git/subprocess integration; no game inputs or external services."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import regenerate_sqshl as regen


class RegenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.ref = self.root / 'reference'
        self.ref.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.ref / 'recomp').mkdir()
        (self.ref / 'recomp/emit_neon.py').write_text('OLD = True\n')
        (self.ref / 'recomp/__init__.py').write_text('')
        self.base = self.root / 'baseline'
        for mod in ('main', 'sdk'):
            (self.base / mod).mkdir(parents=True)
        self.sites = []
        old = []
        new = []
        for i in range(8):
            emission = '{ synthetic_%d(); }' % i
            operands = 'synthetic%d' % i
            site = dict(file='code_000.cpp', offset=i * 4, operands=operands,
                        emission=emission, emission_sha256=hashlib.sha256(emission.encode()).hexdigest())
            self.sites.append(site)
            old.append(f'nx::unimpl(c, NXB + {i*4:#x}ull, "sqshl {operands}"); // no handler // sqshl {operands}\n')
            new.append(emission + ' // sqshl ' + operands + '\n')
        report = 'functions 27763, handled 2569143, unhandled 8\njump tables 1, unresolved br (indirect tail calls) 2\n\n       8 sqshl\n'
        self.newreport = report.replace('handled 2569143, unhandled 8', 'handled 2569151, unhandled 0').removesuffix('       8 sqshl\n')
        (self.base / 'main/code_000.cpp').write_text(''.join(old))
        (self.base / 'main/report.txt').write_text(report)
        (self.base / 'main/funcs.h').write_text('unchanged\n')
        (self.base / 'sdk/code.cpp').write_text('sdk unchanged\n')
        fake = ('from pathlib import Path\nimport sys\nfrom .emit_neon import OLD\n'
                'assert not OLD\nassert sys.argv[3:] == ["--name", "main", "--base", "0x4000000000"]\n'
                'out=Path(sys.argv[2]);out.mkdir()\n'
                f'(out/"code_000.cpp").write_text({"".join(new)!r})\n'
                f'(out/"report.txt").write_text({self.newreport!r})\n'
                '(out/"funcs.h").write_text("unchanged\\n")\n')
        (self.ref / 'recomp/__main__.py').write_text(fake)
        self.git('add', '.')
        self.git('commit', '-qm', 'synthetic emitter')
        self.pin = self.git('rev-parse', 'HEAD').strip()
        (self.ref / 'recomp/emit_neon.py').write_text('OLD = False\n')
        self.patch = self.root / 'patch'
        self.patch.write_text(self.git('diff'))
        self.git('checkout', '--', 'recomp/emit_neon.py')
        self.nso = self.root / 'fake.nso'
        self.nso.write_bytes(b'synthetic')
        self.out = self.root / 'out'
        self.out.mkdir()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.ref), *args], text=True, stderr=subprocess.PIPE)

    def run_generation(self, pin=None):
        runner = regen.Runner(self.out, 20)
        return regen.regenerate(self.ref, sys.executable, self.nso, self.base, self.out,
                                self.patch, self.sites, runner, pin=pin or self.pin)

    def test_actual_subprocess_generation_and_exact_audit(self):
        before = regen.tree(self.base)
        result = self.run_generation()
        self.assertEqual(result['semantic_sites'], 8)
        self.assertEqual(regen.tree(self.base), before)
        self.assertEqual((self.out / 'gen/sdk/code.cpp').read_bytes(), b'sdk unchanged\n')
        records = json.loads((self.out / 'commands.json').read_text())
        self.assertTrue(all(x['exit_code'] == 0 and x['reaped'] for x in records))
        self.assertIn('-m', records[-1]['argv'])

    def test_wrong_pin_refused_before_clone(self):
        with self.assertRaisesRegex(ValueError, 'wrong reference pin'):
            self.run_generation('0' * 40)
        self.assertFalse((self.out / 'source').exists())

    def test_dirty_reference_refused(self):
        (self.ref / 'untracked').write_text('dirty')
        with self.assertRaisesRegex(ValueError, 'dirty reference'):
            self.run_generation()

    def test_patch_scope_refused_before_generation(self):
        path = self.ref / 'recomp/__init__.py'
        path.write_text('unexpected = True\n')
        extra = self.git('diff')
        self.git('checkout', '--', 'recomp/__init__.py')
        self.patch.write_text(self.patch.read_text() + extra)
        with self.assertRaisesRegex(ValueError, 'unexpected source'):
            self.run_generation()
        self.assertFalse((self.out / 'gen').exists())

    def test_emitter_source_mutation_refused(self):
        path = self.ref / 'recomp/__main__.py'
        path.write_text(path.read_text() +
            'Path(__file__).with_name("emit_neon.py").write_text("mutated = True\\n")\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'source mutation fixture')
        self.pin = self.git('rev-parse', 'HEAD').strip()
        with self.assertRaisesRegex(ValueError, 'emitter source drift'):
            self.run_generation()

    def test_unexplained_semantic_change_refused(self):
        self.run_generation()
        (self.out / 'gen/main/funcs.h').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'unexplained generated change'):
            regen.audit(self.base, self.out / 'gen', self.sites)

    def test_report_change_refused(self):
        self.run_generation()
        (self.out / 'gen/main/report.txt').write_text(self.newreport + 'extra\n')
        with self.assertRaisesRegex(ValueError, 'unexplained generated change'):
            regen.audit(self.base, self.out / 'gen', self.sites)

    def test_missing_site_refused(self):
        self.run_generation()
        with self.assertRaisesRegex(ValueError, 'wrong site count'):
            regen.audit(self.base, self.out / 'gen', self.sites[:-1])

    def test_extra_output_refused(self):
        self.run_generation()
        (self.out / 'gen/main/extra').write_text('extra')
        with self.assertRaisesRegex(ValueError, 'inventory changed'):
            regen.audit(self.base, self.out / 'gen', self.sites)

    def test_linked_and_symlinked_files_refused(self):
        import os
        p = self.base / 'sdk/code.cpp'
        os.link(p, self.root / 'hardlink')
        with self.assertRaisesRegex(ValueError, 'linked file'):
            regen.tree(self.base)
        (self.root / 'hardlink').unlink()
        (self.base / 'link').symlink_to(p)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            regen.tree(self.base)

    def test_provenance_hash_refused(self):
        with self.assertRaisesRegex(ValueError, 'provenance hash mismatch'):
            regen.read_checked(self.nso, '0' * 64)

    def preflight_args(self, output):
        return SimpleNamespace(reference=self.ref, python=Path(sys.executable),
            inputs=self.base, baseline=self.base, receipt=self.nso,
            inventory=self.nso, sites=self.nso, out=output, timeout=10)

    def ignore_private(self):
        (self.ref / '.gitignore').write_text('.local/\n')
        self.git('add', '.gitignore')
        self.git('commit', '-qm', 'ignore private fixtures')

    def test_existing_output_and_outside_ownership_refused(self):
        self.ignore_private()
        owned = self.ref / '.local/cpu-regen-020/existing'
        owned.mkdir(parents=True)
        with mock.patch.object(regen, 'ROOT', self.ref):
            with self.assertRaisesRegex(ValueError, 'existing output'):
                regen.execute(self.preflight_args(owned))
            with self.assertRaisesRegex(ValueError, 'outside unit ownership'):
                regen.execute(self.preflight_args(self.ref / '.local/other/fresh'))

    def test_output_overlap_refused(self):
        self.ignore_private()
        owned = self.ref / '.local/cpu-regen-020/fresh'
        args = self.preflight_args(owned)
        args.inputs = owned.parent
        with mock.patch.object(regen, 'ROOT', self.ref):
            with self.assertRaisesRegex(ValueError, 'output overlap'):
                regen.execute(args)
        self.assertFalse(owned.exists())

    def test_symlink_argument_refused_before_mutation(self):
        self.ignore_private()
        link = self.root / 'linked-baseline'
        link.symlink_to(self.base, target_is_directory=True)
        args = self.preflight_args(self.ref / '.local/cpu-regen-020/fresh')
        args.baseline = link
        with mock.patch.object(regen, 'ROOT', self.ref):
            with self.assertRaisesRegex(ValueError, 'symlink argument'):
                regen.execute(args)
        self.assertFalse(args.out.exists())

    def test_timeout_kills_and_reaps_group(self):
        runner = regen.Runner(self.out, 0.1)
        with self.assertRaises(subprocess.TimeoutExpired):
            runner.run([sys.executable, '-c', 'import time; time.sleep(60)'])
        rec = json.loads((self.out / 'commands.json').read_text())[0]
        self.assertTrue(rec['reaped'])
        self.assertTrue(rec['terminated'])
        self.assertNotEqual(rec['exit_code'], 0)

    def test_timeout_terminates_descendant(self):
        pidfile = self.root / 'descendant-pid'
        child = ("import subprocess,sys,signal,time; from pathlib import Path; "
                 "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                 "Path(sys.argv[1]).write_text(str(p.pid)); "
                 "signal.signal(signal.SIGTERM,lambda *a:(p.wait(),sys.exit(0))); time.sleep(60)")
        runner = regen.Runner(self.out, 1)
        with self.assertRaises(subprocess.TimeoutExpired):
            runner.run([sys.executable, '-c', child, pidfile])
        self.assertTrue(pidfile.exists())
        check = subprocess.run(['ps', '-p', pidfile.read_text(), '-o', 'stat='],
                               text=True, capture_output=True)
        self.assertTrue(check.returncode != 0 or check.stdout.strip().startswith('Z'), check.stdout)
        self.assertTrue(runner.records[0]['reaped'])

    def test_failed_emitter_retains_exit_and_log(self):
        runner = regen.Runner(self.out, 5)
        with self.assertRaisesRegex(ValueError, 'child failed'):
            runner.run([sys.executable, '-c', 'raise SystemExit(7)'])
        self.assertEqual(json.loads((self.out / 'commands.json').read_text())[0]['exit_code'], 7)


if __name__ == '__main__':
    unittest.main()
