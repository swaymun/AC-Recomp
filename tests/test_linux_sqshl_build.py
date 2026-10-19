import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import linux_sqshl_build as b


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_stage_real_success_and_failure(self):
        end = time.monotonic() + 5
        r = b.stage(self.root, 'ok', [sys.executable, '-c', "print('compiled fixture')"], end)
        self.assertEqual(r['exit_code'], 0)
        self.assertIn('compiled fixture', (self.root / 'ok.log').read_text())
        with self.assertRaisesRegex(ValueError, 'failed'):
            b.stage(self.root, 'bad', [sys.executable, '-c', 'raise SystemExit(7)'], end)
        self.assertEqual(b.read(self.root / 'bad.json')['exit_code'], 7)

    def test_timeout_cleanup_retained(self):
        with self.assertRaisesRegex(ValueError, 'failed'):
            b.stage(self.root, 'timeout', [sys.executable, '-c',
                'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); time.sleep(30)'],
                time.monotonic() + .2)
        rec = b.read(self.root / 'timeout.json')
        self.assertTrue(rec['timeout'])
        self.assertIsNotNone(rec['exit_code'])
        self.assertIn(rec['pid'], rec['cleanup_groups'])

    def test_fake_ssh_only_allowed_host(self):
        fake = self.root / 'ssh'
        fake.write_text('#!/usr/bin/env python3\nimport sys\nassert sys.argv[2]=="-oConnectTimeout=10"\nassert sys.argv[3]=="acs-recovery-linux"\nprint("fixture-pod-0001")\n')
        fake.chmod(0o700)
        with patch.dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ['PATH']), \
                patch.object(b, 'POD', 'fixture-pod-0001'):
            b.stage(self.root, 'ssh', b.ssh(['python3', '-c', b.host_probe()]), time.monotonic() + 5)
        self.assertEqual((self.root / 'ssh.log').read_text().strip(), 'fixture-pod-0001')

    def test_extract_hash_and_links_refused(self):
        tar = self.root / 'a.tar.gz'
        data = b'fixture'
        with tarfile.open(tar, 'w:gz') as t:
            m = tarfile.TarInfo('safe/x');m.size=len(data);t.addfile(m,io.BytesIO(data))
        h = {'safe/x': hashlib.sha256(data).hexdigest()}
        with self.assertRaisesRegex(ValueError, 'hash'):
            b.safe_unpack(tar, self.root / 'wrong', {'safe/x': '0'*64})
        self.assertFalse((self.root / 'wrong').exists())
        b.safe_unpack(tar, self.root / 'good', h)
        with self.assertRaisesRegex(ValueError, 'existing'):
            b.safe_unpack(tar, self.root / 'good', h)
        with tarfile.open(tar, 'w:gz') as t:
            m=tarfile.TarInfo('link');m.type=tarfile.SYMTYPE;m.linkname='/etc/passwd';t.addfile(m)
        with self.assertRaisesRegex(ValueError,'unsafe'):
            b.safe_unpack(tar, self.root / 'linked', {'link': '0'*64})

    def test_compile_contract(self):
        c = {'directory': str(self.root), 'file': 'main.cpp', 'arguments':
             ['clang++','-DNX_ASTRAL_STRICT=1','-ffp-contract=off','-march=x86-64-v3','-o','a.o']}
        self.assertEqual(b.compile_objects([c],self.root,1),[self.root/'a.o'])
        with self.assertRaisesRegex(ValueError,'count'):
            b.compile_objects([c],self.root)
        with self.assertRaisesRegex(ValueError,'flags'):
            b.compile_objects([{**c,'arguments':['clang++','-o','a.o']}],self.root,1)
        with self.assertRaisesRegex(ValueError,'outside'):
            b.compile_objects([{**c,'arguments':c['arguments'][:-1]+['../outside.o']}],self.root,1)

    def test_temp_git_wrong_provenance(self):
        repo=self.root/'repo';repo.mkdir()
        subprocess.run(['git','init',repo],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        (repo/'f').write_text('fixture')
        subprocess.run(['git','-C',repo,'add','f'],check=True)
        subprocess.run(['git','-C',repo,'-c','user.name=Fixture','-c','user.email=f@invalid','commit','-qm','fixture'],check=True)
        store=self.root/'store';store.mkdir()
        (store/'units.tsv').write_text('id\tstate\thead\trun_id\tpatch\nCPU-REGEN-020\tcompleted\twrong\twrong\twrong\n')
        with self.assertRaisesRegex(ValueError,'not exactly landed'):
            b.acceptance(repo,store)
        h=subprocess.check_output(['git','-C',repo,'rev-parse','HEAD'],text=True).strip()
        self.assertEqual(b.identity(repo,h,h),hashlib.sha256(b'').hexdigest())

    def accepted_fixture(self):
        repo = self.root / 'accepted'
        repo.mkdir()
        subprocess.run(['git', 'init', '-b', 'main', repo], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (repo / 'base').write_text('base')
        def commit():
            subprocess.run(['git', '-C', repo, 'add', '.'], check=True)
            subprocess.run(['git', '-C', repo, '-c', 'user.name=Fixture',
                '-c', 'user.email=f@invalid', 'commit', '-qm', 'fixture'], check=True)
            return subprocess.check_output(['git', '-C', repo, 'rev-parse', 'HEAD'], text=True).strip()
        base = commit()
        for name in b.HELPERS:
            f = repo / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text('reviewed fixture ' + name)
        head = commit()
        patch_id = b.identity(repo, base, head)
        store = self.root / 'accepted-store'
        (store / 'reports').mkdir(parents=True)
        (store / 'units.tsv').write_text('id\tstate\thead\trun_id\tpatch\tworktree\n' +
            '\t'.join(['CPU-REGEN-020', 'landed', head, b.PRODUCER, patch_id, str(repo)]) + '\n')
        producer = dict(head=head, patch=patch_id, run_id=b.PRODUCER,
                        state='completed', report={'head': head}, artifacts=[])
        review = dict(head=head, patch=patch_id, producer_run=b.PRODUCER, run_id=b.REVIEW,
                      model='gpt-6-astra', effort='medium', verdict='pass',
                      report=dict(head=head, patch=patch_id, verdict='pass'))
        land = dict(unit='CPU-REGEN-020', head=head, reviewed_head=head, patch=patch_id)
        for name, data in [(b.PRODUCER+'.json', producer), (b.REVIEW+'.review.json', review),
                           (b.PRODUCER+'.land.json', land)]:
            (store / 'reports' / name).write_text(json.dumps(data))
        return repo, store, head, base, patch_id

    def test_independent_review_exact_head_and_dirty_git(self):
        repo, store, head, base, pid = self.accepted_fixture()
        with patch.multiple(b, HEAD=head, BASE=base, PATCH=pid):
            self.assertEqual(b.acceptance(repo, store)[0], repo)
            review = store / 'reports' / (b.REVIEW + '.review.json')
            data = json.loads(review.read_text())
            data['model'] = 'gpt-6.1-sol'
            review.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'independent review'):
                b.acceptance(repo, store)
            data['model'] = 'gpt-6-astra'
            review.write_text(json.dumps(data))
            (repo / b.HELPERS[0]).write_text('unreviewed')
            with self.assertRaisesRegex(ValueError, 'dirty tracked'):
                b.acceptance(repo, store)

    def test_landing_head_and_patch_must_match(self):
        repo, store, head, base, pid = self.accepted_fixture()
        with patch.multiple(b, HEAD=head, BASE=base, PATCH=pid):
            land = store / 'reports' / (b.PRODUCER + '.land.json')
            data = json.loads(land.read_text())
            data['reviewed_head'] = 'f'*40
            land.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'landing identity'):
                b.acceptance(repo, store)

    def test_build_only_pipeline_with_fake_tools(self):
        out = self.root / 'native'
        repo = out / 'repo'
        (repo / 'tools').mkdir(parents=True)
        gen = repo / '.local/gen'
        gen.mkdir(parents=True)
        (gen / 'fixture').write_text('synthetic generated data')
        gpu = self.root / 'gpu'
        (gpu / 'venv/bin').mkdir(parents=True)
        prefix = gpu / 'repo/.local/sdl3'
        prefix.mkdir(parents=True)
        (prefix / 'library').write_text('synthetic SDL')
        header = self.root / 'header.h'
        header.write_text('synthetic header')
        helper = repo / 'tools/prepare_runtime.py'
        helper.write_text("""import sys,json,pathlib
p=pathlib.Path(sys.argv[sys.argv.index('--out')+1]);p.mkdir(parents=True)
b=p/'build';b.mkdir();(p/'source').mkdir()
(p/'prepared.json').write_text(json.dumps({'source':{'source':'fixture'}}))
g=sys.argv[sys.argv.index('--gen')+1]
c=[{'directory':str(b),'file':g+('/main/' if i<200 else '/sdk/')+str(i)+'.cpp',
 'arguments':['clang++','-DNX_ASTRAL_STRICT=1','-ffp-contract=off','-march=x86-64-v3','-o',str(i)+'.o']} for i in range(395)]
(b/'compile_commands.json').write_text(json.dumps(c))
""")
        cmake = gpu / 'venv/bin/cmake'
        cmake.write_text('#!' + sys.executable + """
import sys,pathlib,json
if '--build' in sys.argv:
 b=pathlib.Path(sys.argv[sys.argv.index('--build')+1])
 for c in json.loads((b/'compile_commands.json').read_text()):
  (b/c['arguments'][-1]).write_text('synthetic object')
 (b/'astral').write_text('synthetic executable, never launched')
print('fake cmake 3.31.6')
""")
        cmake.chmod(0o700)
        ninja = self.root / 'fake-ninja'
        ninja.write_text('#!' + sys.executable + '\nimport sys\n' +
            "print('    '+" + repr(str(header)) + ") if 'deps' in sys.argv else print('fake ninja')\n")
        ninja.chmod(0o700)
        plan = out / 'plan.json'
        b.save(plan, dict(landed_head=b.HEAD, sites=8, sdk_files=110,
            helpers={'tools/prepare_runtime.py': b.sha(helper)}, generated=b.regen.tree(gen),
            manifest_sha256='fixture', source={'source':'fixture'}))
        with patch.object(b, 'GPU', gpu), \
             patch.object(b.prep, 'validate_inputs', return_value=({}, 'fixture')), \
             patch.object(b.prep, 'git', return_value='wrong-pin'):
            with self.assertRaisesRegex(ValueError, 'dependency pin/dirty'):
                b.native(plan, out, time.monotonic()+5)
        real_stage = b.stage
        def fake_ninja_stage(out, name, argv, end, **kwargs):
            if str(argv[0]) == '/usr/bin/ninja':
                argv = [str(ninja), *argv[1:]]
            return real_stage(out, name, argv, end, **kwargs)
        def git_pin(path, *args):
            if args[0] == 'status':
                return ''
            return {'wonder': b.regen.PIN, 'SDL':'a8589a84226a6202831a3d49ff4edda4acab9acd',
                    'Vulkan-Headers':'e3b1eec08173d6b825cd3ac88c885a63b621504a'}[path.name]
        # Ninja binary hashing uses the installed system path; map only this
        # fixture's hash lookup while all child processes and files remain real.
        original_sha = b.sha
        def fixture_sha(path):
            return original_sha(ninja if str(path) == '/usr/bin/ninja' else path)
        with patch.object(b, 'GPU', gpu), patch.object(b, 'stage', side_effect=fake_ninja_stage), \
             patch.object(b.prep, 'git', side_effect=git_pin), \
             patch.object(b.prep, 'validate_inputs', return_value=({}, 'fixture')), \
             patch.object(b.prep, 'source_fingerprint', return_value={'source':'fixture'}), \
             patch.object(b, 'sha', side_effect=fixture_sha):
            b.native(plan, out, time.monotonic()+20)
        rec = b.read(out/'receipt.json')
        self.assertEqual(rec['state'], 'compiled')
        self.assertEqual(rec['object_count'], 395)
        self.assertFalse(rec['title_launched'])
        self.assertTrue(all(Path(x['argv'][0]).name != 'astral' for x in rec['stages'].values()))
        self.assertEqual(rec['dependencies'][str(header)], original_sha(header))

    def test_host_controls_refused(self):
        for name in ('registry','ready','transfer'):
            (self.root/name).write_text('{}')
        (self.root/'registry').write_text(json.dumps({'task_id':'wrong','resources':[]}))
        with self.assertRaisesRegex(ValueError,'task registry'):
            b.controls(*(self.root/n for n in ('registry','ready','transfer')))

    def test_expired_no_process(self):
        with self.assertRaisesRegex(ValueError,'failed'):
            b.stage(self.root,'expired',[sys.executable,'-c','raise Exception()'],time.monotonic()-1)
        self.assertNotIn('pid',b.read(self.root/'expired.json'))

    def test_dispatch_refuses_existing_and_unowned_output_before_ssh(self):
        repo = self.output_repo()
        out = repo / '.local/linux-sqshl-021/existing'
        out.mkdir(parents=True)
        with patch.object(b, 'stage', side_effect=AssertionError('network must not be called')):
            with self.assertRaisesRegex(ValueError, 'existing local'):
                b.dispatch(repo, self.root, out, time.monotonic()+10)
            with self.assertRaisesRegex(ValueError, 'ownership'):
                b.dispatch(repo, self.root, repo/'.local/unowned', time.monotonic()+10)

    def output_repo(self):
        repo = self.root / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', repo], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (repo / '.gitignore').write_text('.local/\n')
        return repo

    def assert_output_refused_without_mutation(self, repo, out, message):
        with patch.object(Path, 'mkdir') as mkdir, \
             patch.object(Path, 'write_text') as write_text, \
             patch.object(Path, 'write_bytes') as write_bytes, \
             patch.object(b.tarfile, 'open') as archive, \
             patch.object(b, 'provenance') as provenance, \
             patch.object(b, 'stage') as stage, \
             patch.object(b, 'ssh') as ssh, \
             patch.object(b, 'save') as save:
            with self.assertRaisesRegex(ValueError, message):
                b.dispatch(repo, self.root, out, time.monotonic()+10)
            for operation in (mkdir, write_text, write_bytes, archive,
                              provenance, stage, ssh, save):
                operation.assert_not_called()

    def test_exact_parent_escape_refused_before_any_output_or_staging(self):
        repo = self.output_repo()
        root = repo / '.local/linux-sqshl-021'
        outside = repo / '.local/outside-unit-probe'
        out = root / '../outside-unit-probe'
        self.assertTrue(out.is_relative_to(root))  # Original lexical-check hole.
        self.assertFalse(os.path.lexists(outside))
        self.assert_output_refused_without_mutation(repo, out, 'ownership')
        self.assertFalse(os.path.lexists(outside))
        self.assertFalse(root.exists())

    def test_root_aliases_existing_and_overlapping_outputs_refused(self):
        repo = self.output_repo()
        root = repo / '.local/linux-sqshl-021'
        # Even a missing root must not be accepted as a fresh output via '..'.
        for out in (root, root / 'unused/..'):
            self.assert_output_refused_without_mutation(repo, out, 'ownership')
        retained = root / 'retained'
        retained.mkdir(parents=True)
        marker = retained / 'historical.json'
        marker.write_text('retained fixture')
        for out, reason in ((retained, 'existing local'),
                            (retained / 'new', 'overlapping local'),
                            (root / 'retained/..', 'ownership')):
            self.assert_output_refused_without_mutation(repo, out, reason)
        self.assertEqual(marker.read_text(), 'retained fixture')
        self.assertEqual(list(retained.iterdir()), [marker])

    def test_output_symlinks_including_erased_components_refused(self):
        repo = self.output_repo()
        root = repo / '.local/linux-sqshl-021'
        root.mkdir(parents=True)
        outside = self.root / 'absent-outside'
        link = root / 'link'
        link.symlink_to(outside, target_is_directory=True)
        for out in (link, link / 'new', link / '../fresh'):
            self.assert_output_refused_without_mutation(repo, out, 'symlink')
        self.assertFalse(os.path.lexists(outside))
        link.unlink()
        root.rmdir()
        root.symlink_to(outside, target_is_directory=True)
        self.assert_output_refused_without_mutation(repo, root / 'new', 'symlink')
        self.assertFalse(os.path.lexists(outside))
        root.unlink()
        (repo / '.local').rmdir()
        (repo / '.local').symlink_to(outside, target_is_directory=True)
        self.assert_output_refused_without_mutation(repo, root / 'new', 'symlink')
        self.assertFalse(os.path.lexists(outside))

    def test_valid_dispatch_uses_normalized_path_for_creation_and_receipt(self):
        repo = self.output_repo()
        root = repo / '.local/linux-sqshl-021'
        # Normalization must be retained, even when no component exists yet.
        for requested, out in ((root / 'plain', root / 'plain'),
                               (root / 'unused/../fresh', root / 'fresh')):
            with patch.object(b, 'provenance', side_effect=ValueError('offline fixture stop')), \
                 patch.object(b, 'stage') as stage, patch.object(b, 'ssh') as ssh:
                with self.assertRaisesRegex(ValueError, 'offline fixture stop'):
                    b.dispatch(repo, self.root, requested, time.monotonic()+10)
                stage.assert_not_called()
                ssh.assert_not_called()
            self.assertTrue(out.is_dir())
            self.assertFalse((root / 'unused').exists())
            self.assertIn('offline fixture stop', b.read(out / 'refusal.json')['error'])
            self.assertEqual(list(out.iterdir()), [out / 'refusal.json'])

    def test_linked_receipt_refused(self):
        f=self.root/'x';f.write_text('{}');os.link(f,self.root/'y')
        with self.assertRaisesRegex(ValueError,'linked'):
            b.read(f)


if __name__ == '__main__':
    unittest.main()
