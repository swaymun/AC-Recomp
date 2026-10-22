"""Offline subprocess/Git fixtures; no SSH, cloud, credentials or private inputs."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
# The frozen supervisor predates prepare_runtime's removal of its inventory
# re-export. Supply that historical import boundary only while loading this
# offline fixture; do not mutate production modules for other test suites.
# This is not a repair of the legacy supervisor's standalone entrypoint.
import prepare_runtime as preparation
import import_owned_dump as inventory
supervisor = Path(__file__).resolve().parents[1] / 'tools/linux_runtime_startup.py'
spec = importlib.util.spec_from_file_location('_linux_startup_fixture', supervisor)
r = importlib.util.module_from_spec(spec)
with patch.object(preparation, 'inventory', inventory, create=True):
    spec.loader.exec_module(r)


class FixtureClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 18, 17, 0, tzinfo=timezone.utc)


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def write_controls(self, store):
        store.mkdir()
        auth = b'owner afternoon authorization'
        (store / 'AUTHORIZATION.md').write_bytes(auth)
        (store / 'RUN_OBJECTIVE.md').write_text('all platforms, bounded execution')
        cfg = {'task_id': 'acs-afternoon-20261018', 'mode': 'game',
               'targets': sorted(r.TARGETS), 'deadline': '2026-10-18T21:00:00Z',
               'dispatch_stop_at': '2026-10-18T20:30:00Z', 'morning_report_at': '2026-10-18T20:30:00Z'}
        cfg['owner_approval'] = {'approved': True, 'task_id': cfg['task_id'],
            'targets': cfg['targets'], 'deadline': cfg['deadline'],
            'authorization_sha256': hashlib.sha256(auth).hexdigest()}
        (store / 'lead-config.json').write_text(json.dumps(cfg))
        (store / 'config.json').write_text(json.dumps({'date': store.name, 'max_workers': 3, 'budget_usd': 20}))
        return cfg

    def test_current_controls_and_rejected_stale_malformed_extended(self):
        store = self.root / '2026-10-18-afternoon'
        cfg = self.write_controls(store)
        deadline, hashes = r.controls(store, FixtureClock.now())
        self.assertEqual(deadline.hour, 21)
        self.assertEqual(len(hashes), 4)
        with patch.dict(os.environ, ACS_BUDGET_CAP_USD='20'):
            r.controls(store, FixtureClock.now())
        with patch.dict(os.environ, ACS_BUDGET_CAP_USD='15'), self.assertRaisesRegex(ValueError, 'budget'):
            r.controls(store, FixtureClock.now())
        path = store / 'lead-config.json'
        for change in ({'deadline': '2026-10-18T15:00:00Z'},
                       {'dispatch_stop_at': '2026-10-18T20:31:00Z'},
                       {'deadline': '2026-10-19T21:00:00Z'},
                       {'targets': ['linux-x86_64']}, {'mode': 'proof'}):
            with self.subTest(change=change):
                path.write_text(json.dumps(dict(cfg, **change)))
                with self.assertRaises(ValueError):
                    r.controls(store, FixtureClock.now())
        path.write_text('{malformed')
        with self.assertRaises(ValueError):
            r.controls(store, FixtureClock.now())
        path.write_text(json.dumps(cfg))
        (store / 'AUTHORIZATION.md').write_text('drift')
        with self.assertRaisesRegex(ValueError, 'approval/control'):
            r.controls(store, FixtureClock.now())

    def run_child(self, code, seconds=3):
        return r.run_stage([sys.executable, '-c', code], self.root / 'child.log', seconds)

    def test_real_exit_signal_and_receipt_provenance(self):
        result = self.run_child('print("strict first gate"); raise SystemExit(17)')
        self.assertFalse(result['ok'])
        self.assertEqual(result['exit_code'], 17)
        self.assertEqual(result, json.loads((self.root / 'child.json').read_text()))
        self.assertEqual(result['log']['sha256'], hashlib.sha256((self.root / 'child.log').read_bytes()).hexdigest())
        self.assertIn('strict first gate', (self.root / 'child.log').read_text())
        self.assertIn('started_utc', result)
        result = self.run_child('import os,signal; os.kill(os.getpid(), signal.SIGTERM)')
        self.assertEqual(result['signal'], signal.SIGTERM)
        self.assertFalse(result['ok'])

    def test_real_timeout_is_failure(self):
        result = self.run_child('import time; time.sleep(30)', seconds=0.15)
        self.assertTrue(result['timeout'])
        self.assertFalse(result['ok'])
        self.assertIsNotNone(result['signal'])

    @unittest.skipUnless(Path('/proc').is_dir(), 'Linux owned-session cleanup fixture')
    def test_timeout_kills_actual_descendant(self):
        pidfile = self.root / 'descendant.pid'
        code = ('import subprocess,sys,time; '
                'p=subprocess.Popen([sys.executable,"-c","import os,time; os.setpgrp(); time.sleep(60)"]); '
                f'open({str(pidfile)!r},"w").write(str(p.pid)); time.sleep(60)')
        result = self.run_child(code, seconds=0.5)
        self.assertTrue(result['timeout'])
        self.assertLess(result['elapsed_seconds'], 4)
        pid = int(pidfile.read_text())
        # A zombie cannot execute; container PID 1 may reap it asynchronously.
        status = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True, text=True)
        self.assertTrue(not status.stdout.strip() or status.stdout.strip().startswith('Z'), status.stdout)

    def test_log_bound_and_missing_executable(self):
        with patch.object(r, 'LIMIT', 1024):
            result = self.run_child('import os; os.write(1,b"x"*100000); import time; time.sleep(60)')
        self.assertTrue(result['log_limit'])
        self.assertEqual((self.root / 'child.log').stat().st_size, 1024)
        result = r.run_stage(['/missing-fixture-executable'], self.root / 'missing.log', 1)
        self.assertFalse(result['ok'])
        self.assertIn('FileNotFoundError', result['error'])

    def fixture(self, build_exit=0, startup_exit=0, bootstrap_only=False, strict=True):
        """Fake preparation boundary and compiler, real Git/children/receipt chain."""
        repo = self.root / 'repo'
        repo.mkdir()
        (repo / 'tools').mkdir()
        (repo / '.gitignore').write_text('.local/\n')
        (repo / 'original').write_text('original fixture source\n')
        local = repo / '.local'
        (local / 'inputs').mkdir(parents=True)
        (local / 'gen/main').mkdir(parents=True)
        (local / 'gen/sdk').mkdir(parents=True)
        (local / 'inputs/manifest').write_text('fixture manifest')
        patches = repo / 'runtime/patches'
        patches.mkdir(parents=True)
        for name in r.PATCHES:
            (patches / name).write_text('synthetic overlay ' + name)
        helper = repo / 'tools/prepare_runtime.py'
        # Only synthetic metadata is substituted; the supervisor always spawns
        # the helper and build executable and hashes the resulting real files.
        helper.write_text('''import argparse,json,pathlib,subprocess,hashlib
p=argparse.ArgumentParser()
for name in ('repo','reference','inputs','gen','out','jobs','cmake','ninja','prefix','vulkan-include'):
 p.add_argument('--'+name)
p.add_argument('--configure',action='store_true')
p.add_argument('--prepare-composed',action='store_true')
p.add_argument('--generated-receipt'); p.add_argument('--control-metadata'); p.add_argument('--controls')
a=p.parse_args(); out=pathlib.Path(a.out); out.mkdir(); source=out/'source'
subprocess.run(['git','clone','-q',a.reference,str(source)],check=True)
build=out/'build'; build.mkdir()
commands=[{'file':str(pathlib.Path(a.gen)/m/'unit.cpp'),'directory':str(build),'command':'clang++ -DNX_ASTRAL_STRICT=1 -o '+m+'.o'} for m in ('main','sdk')]
(build/'compile_commands.json').write_text(json.dumps(commands))
h=lambda x:hashlib.sha256(x.read_bytes()).hexdigest()
paths=subprocess.check_output(['git','-C',str(source),'ls-files']).decode().splitlines()
names=PATCH_NAMES
inventory=[dict(name=n,sha256=h(pathlib.Path(a.repo)/'runtime/patches'/n),bytes=(pathlib.Path(a.repo)/'runtime/patches'/n).stat().st_size,state='applied',source_after={'fixture':'synthetic'}) for n in names]
pin=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD']).decode().strip()
(out/'prepared.json').write_text(json.dumps({'source':{x:h(source/x) for x in paths},'identity':{'pin':pin,'profile':'linux-hid-cumulative-v1','patch_order':names,'manifest_sha256':h(pathlib.Path(a.inputs)/'manifest'),'generated':{'synthetic':'fixture'},'patches':{n:h(pathlib.Path(a.repo)/'runtime/patches'/n) for n in names}},'composition':inventory}))
''')
        helper_text = helper.read_text().replace('PATCH_NAMES', repr(list(r.PATCHES[:2] if bootstrap_only else r.PATCHES)))
        if not strict:
            helper_text = helper_text.replace('-DNX_ASTRAL_STRICT=1', '-DNX_ASTRAL_STRICT=0')
        (repo / 'tools/linux_runtime_startup.py').write_text(helper_text)
        cmake = local / 'cmake'
        cmake.write_text(f'''#!{sys.executable}
from pathlib import Path
import sys
build=Path(sys.argv[sys.argv.index('--build')+1])
(build/'main.o').write_bytes(b'object')
if {build_exit}: raise SystemExit({build_exit})
(build/'sdk.o').write_bytes(b'object')
exe=build/'astral'
exe.write_text('#!{sys.executable}\\nprint("fixture guest gate")\\nraise SystemExit({startup_exit})\\n')
exe.chmod(0o700)
''')
        cmake.chmod(0o700)
        for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture']):
            subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
        head = r.prepare.git(repo, 'rev-parse', 'HEAD')
        store = local / '2026-10-18-afternoon'
        self.write_controls(store)
        a = argparse.Namespace(repo=repo, reference=repo, inputs=local / 'inputs', gen=local / 'gen',
                               out=local / 'result', cmake=cmake, ninja=cmake, prefix=local,
                               vulkan_include=local, jobs=3, seconds=10,
                               controls=store, generated_receipt=local / 'generated.json',
                               control_metadata=local / 'control.json')
        return repo, head, a

    def execute_fixture(self, build_exit=0, startup_exit=0, mutate=False, xvfb=False,
                        committed_drift=False, dirty_unrelated=False, wrong_ancestor=False,
                        descendant=False, bootstrap_only=False, strict=True):
        repo, head, a = self.fixture(build_exit, startup_exit, bootstrap_only, strict)
        if descendant:
            (repo / 'original').write_text('scoped supervisor descendant fixture\n')
            subprocess.run(['git', '-C', str(repo), 'add', 'original'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'descendant'], check=True)
        if mutate:
            (repo / 'tools/prepare_runtime.py').write_text('changed')
        if committed_drift:
            (repo / 'tools/prepare_runtime.py').write_text('committed unreviewed helper')
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'drift'], check=True)
        if dirty_unrelated:
            (repo / 'original').write_text('dirty tracked fixture')
        if wrong_ancestor:
            subprocess.run(['git', '-C', str(repo), 'checkout', '-q', '--orphan', 'unrelated'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'unrelated'], check=True)
        if xvfb:
            a.xvfb_run = repo / '.local/display-wrapper'
            a.xvfb_run.write_text(f'#!{sys.executable}\nimport os,sys\nos.execv(sys.argv[-1], [sys.argv[-1]])\n')
            a.xvfb_run.chmod(0o700)
        with patch.object(r, 'datetime', FixtureClock), patch.object(r, 'REVIEWED', head), patch.object(r, 'IDENTITY_PATHS', ('tools/prepare_runtime.py',)), patch.object(r.prepare, 'PIN', r.prepare.git(repo, 'rev-parse', 'HEAD')), \
             patch.object(r, 'parent_readiness', return_value={'synthetic': 'fixture'}), \
             patch.object(r.prepare, 'ROOT', repo), patch.object(r, 'validate_receipts', return_value={'synthetic': 'fixture'}), \
             patch.object(r.prepare, 'validate_inputs', return_value=({}, r.prepare.sha(a.inputs / 'manifest'))), \
             patch.object(r.prepare, 'generated_evidence', return_value={'synthetic': 'fixture'}):
            code = r.execute(a)
        return code, json.loads((a.out / 'receipt.json').read_text()), a

    def test_real_git_composition_order_already_applied_and_conflict(self):
        repo, head, a = self.fixture()
        patches = repo / 'runtime/patches'
        (patches / 'base.patch').write_text('diff --git a/original b/original\n--- a/original\n+++ b/original\n@@ -1 +1 @@\n-old fixture source\n+original fixture source\n')
        (patches / 'next.patch').write_text('diff --git a/original b/original\n--- a/original\n+++ b/original\n@@ -1 +1 @@\n-original fixture source\n+composed fixture source\n')
        subprocess.run(['git', '-C', str(repo), 'rm', '-qr', '--cached', 'runtime'], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'external patches'], check=True)
        head = r.prepare.git(repo, 'rev-parse', 'HEAD')
        with (repo / '.git/info/exclude').open('a') as ignore:
            ignore.write('runtime/\n')
        clone = r.prepare.prepare_source
        def fixture_clone(reference, source, selected):
            return clone(reference, source, selected, pin=head)
        def helper(args):
            args.out.mkdir()
            r.prepare.prepare_source(repo, args.out / 'source', [patches / 'base.patch', patches / 'next.patch'])
            (args.out / 'prepared.json').write_text(json.dumps({'identity': {}, 'source': r.prepare.source_fingerprint(args.out / 'source')}))
        # Test a real clone and git apply; only the higher preparation/input boundary is synthetic.
        # Keep reference pristine by storing synthetic patches outside its tracked tree.
        with patch.object(r, 'PATCHES', ('base.patch', 'next.patch')), \
             patch.object(r.prepare, 'prepare_source', fixture_clone), patch.object(r.prepare, 'execute', helper):
            r.prepare_composed(a)
            value = json.loads((a.out / 'prepared.json').read_text())
            self.assertEqual([x['state'] for x in value['composition']], ['already-applied', 'applied'])
            self.assertEqual(list(value['identity']['patches']), ['base.patch', 'next.patch'])
            self.assertEqual((a.out / 'source/original').read_text(), 'composed fixture source\n')
            self.assertEqual(value['source'], r.prepare.source_fingerprint(a.out / 'source'))
            (patches / 'next.patch').write_text('this is not a patch\n')
            a.out = a.out.with_name('conflict')
            with self.assertRaises(subprocess.CalledProcessError):
                r.prepare_composed(a)
            self.assertFalse((a.out / 'prepared.json').exists())

    def test_actual_pinned_source_closed_profile_and_corrupt_receipts(self):
        repo = Path(__file__).resolve().parents[1]
        common = Path(r.prepare.git(repo, 'rev-parse', '--git-common-dir'))
        if not common.is_absolute():
            common = (repo / common).resolve()
        reference = Path(os.environ.get('LINUX_REFERENCE', str(common.parent /
            '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp')))
        self.assertTrue(reference.is_dir(), 'provide clean pinned Wonder using LINUX_REFERENCE')
        a = argparse.Namespace(repo=repo, reference=reference, out=self.root / 'actual')
        def source_only(args):
            args.out.mkdir()
            r.prepare.prepare_source(args.reference, args.out / 'source',
                [repo / 'runtime/patches' / p for p in r.PATCHES[:2]])
            (args.out / 'prepared.json').write_text(json.dumps({'identity': {'pin': r.prepare.PIN},
                'source': r.prepare.source_fingerprint(args.out / 'source')}))
        with patch.object(r.prepare, 'execute', source_only):
            r.prepare_composed(a)
        value = json.loads((a.out / 'prepared.json').read_text())
        source = a.out / 'source'
        r.validate_composition(value, repo, source)
        self.assertEqual(len(value['composition']), 10)
        self.assertEqual(value['source']['runtime/src/hle_hid.cpp'],
                         '68af4e7cb56208c668c40bfac6c0cb19d1c73c8c0f6978cc420ba933cfe32509')
        self.assertIn('receive_size_table(8, 1, table)', (source / 'runtime/src/svc_am.cpp').read_text())
        subprocess.run(['git', '-C', str(source), 'diff', '--check'], check=True, capture_output=True)
        # Independent ordinary git apply must produce identical full source bytes.
        ordinary = self.root / 'ordinary'
        fingerprint = r.prepare.prepare_source(reference, ordinary,
            [repo / 'runtime/patches' / p for p in r.PATCHES])
        self.assertEqual(value['source'], fingerprint)
        for mutation in ('omitted', 'duplicate', 'stale', 'tampered', 'order', 'pin', 'old-six'):
            bad = copy.deepcopy(value)
            if mutation == 'omitted': bad['composition'].pop()
            elif mutation == 'duplicate': bad['composition'][-1] = bad['composition'][0]
            elif mutation == 'stale': bad['identity']['profile'] = 'default'
            elif mutation == 'tampered': bad['composition'][-1]['sha256'] = '0' * 64
            elif mutation == 'order': bad['identity']['patch_order'].reverse()
            elif mutation == 'pin': bad['identity']['pin'] = '0' * 40
            else: bad['identity']['patches'] = dict(list(bad['identity']['patches'].items())[:6])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                r.validate_composition(bad, repo, source)
        (source / 'runtime/src/hle_hid.cpp').write_text('tampered source')
        with self.assertRaisesRegex(ValueError, 'source drift'):
            r.validate_composition(value, repo, source)
        print('PASS actual pinned Linux composition: 10 overlays,', len(fingerprint), 'source files')

    def test_reviewed_patch_missing_tampered_and_committed_drift_rejected(self):
        repo, head, _ = self.fixture()
        with patch.object(r, 'REVIEWED', head), patch.object(r.prepare, 'ROOT', repo), \
             patch.object(r, 'IDENTITY_PATHS', ('tools/prepare_runtime.py',) + tuple('runtime/patches/' + p for p in r.PATCHES)):
            identities = r.reviewed_source(repo)
            self.assertIn('runtime/patches/astral-hid.patch', identities)
            target = repo / 'runtime/patches/astral-hid.patch'
            original = target.read_bytes()
            target.unlink()
            with self.assertRaisesRegex(ValueError, 'reviewed source drift'):
                r.reviewed_source(repo)
            target.write_bytes(original + b'tamper')
            with self.assertRaisesRegex(ValueError, 'reviewed source drift'):
                r.reviewed_source(repo)
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'unreviewed patch'], check=True)
            with self.assertRaisesRegex(ValueError, 'reviewed source drift'):
                r.reviewed_source(repo)

    def test_parent_readiness_rejects_old_profile_head_controls_and_time(self):
        repo, head, a = self.fixture()
        a.parent_readiness = repo / '.local/readiness.json'
        a.pod = 'fixture-pod-0001'
        hashes = r.controls(a.controls, FixtureClock.now())[1]
        value = {'schema': 1, 'unit': 'LINUX-HID-CUMULATIVE-049',
                 'pod': 'fixture-pod-0001', 'alias': 'acs-afternoon-linux', 'head': head,
                 'profile': r.PROFILE, 'wrapper': r.digest(Path(r.__file__)),
                 'afternoon_controls': hashes, 'live_stop_absent': True,
                 'at': '2026-10-18T17:00:00Z',
                 'review': {'head': head, 'verdict': 'pass', 'model': 'gpt-6-astra', 'effort': 'medium'}}
        a.parent_readiness.write_text(json.dumps(value))
        self.assertEqual(r.parent_readiness(a, hashes, FixtureClock.now()), r.digest(a.parent_readiness))
        for change in ({'unit': 'LINUX-SUPERVISOR-043'}, {'head': '0' * 40},
                       {'profile': 'default'}, {'pod': 'deleted-old-pod'},
                       {'live_stop_absent': False}, {'afternoon_controls': {}},
                       {'wrapper': {}}, {'at': '2026-10-18T16:49:59Z'},
                       {'at': '2026-10-18T17:00:01Z'}, {'review': dict(value['review'], verdict='fail')}):
            a.parent_readiness.write_text(json.dumps(dict(value, **change)))
            with self.subTest(change=change), self.assertRaises(ValueError):
                r.parent_readiness(a, hashes, FixtureClock.now())
        a.parent_readiness.unlink()
        with self.assertRaisesRegex(ValueError, 'unsafe parent readiness'):
            r.parent_readiness(a, hashes, FixtureClock.now())

    def test_pinned_private_receipts_reject_generated_and_receipt_drift(self):
        repo, _, a = self.fixture()
        mh = r.prepare.sha(a.inputs / 'manifest')
        generated = {'main': {'files': {'unit.cpp': 'fixture-sha'}}}
        a.generated_receipt.write_text(json.dumps({'identity': {'pin': r.prepare.PIN,
            'manifest_sha256': mh, 'generated': generated}}))
        a.control_metadata.write_text('synthetic control receipt')
        with patch.object(r, 'GENERATED_RECEIPT_SHA', r.prepare.sha(a.generated_receipt)), \
             patch.object(r, 'CONTROL_RECEIPT_SHA', r.prepare.sha(a.control_metadata)), \
             patch.object(r.prepare, 'validate_inputs', return_value=({}, mh)), \
             patch.object(r.prepare, 'generated_evidence', return_value=generated), \
             patch.object(r.prepare, 'validate_control', return_value=({'synthetic': True}, r.prepare.sha(a.control_metadata))):
            value = r.validate_receipts(repo, a.inputs, a.gen, a.generated_receipt, a.control_metadata)
            self.assertEqual(value['generated_receipt']['sha256'], r.prepare.sha(a.generated_receipt))
            with patch.object(r.prepare, 'generated_evidence', return_value={'main': 'stale'}):
                with self.assertRaisesRegex(ValueError, 'reviewed generated identity'):
                    r.validate_receipts(repo, a.inputs, a.gen, a.generated_receipt, a.control_metadata)
            a.control_metadata.write_text('receipt drift')
            with self.assertRaisesRegex(ValueError, 'reviewed private receipt'):
                r.validate_receipts(repo, a.inputs, a.gen, a.generated_receipt, a.control_metadata)

    def test_failed_build_stops_before_startup_and_retains_counts(self):
        code, receipt, a = self.execute_fixture(build_exit=19)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['stages']['build']['exit_code'], 19)
        self.assertNotIn('startup', receipt['stages'])
        self.assertEqual(receipt['counts']['objects_present'], 1)
        self.assertEqual(receipt['counts']['objects_absent'], 1)
        self.assertTrue((a.out / 'prepared/build/main.o').exists())
        self.assertEqual(receipt['counts']['object_identities'][str(a.out / 'prepared/build/main.o')]['sha256'],
                         r.prepare.sha(a.out / 'prepared/build/main.o'))

    def test_failed_startup_propagates_and_executable_is_bound(self):
        code, receipt, a = self.execute_fixture(startup_exit=23, xvfb=True)
        self.assertEqual(code, 1)
        self.assertTrue(receipt['stages']['build']['ok'])
        self.assertEqual(receipt['stages']['startup']['exit_code'], 23)
        self.assertEqual(receipt['stages']['startup']['environment']['SDL_VIDEODRIVER'], 'x11')
        self.assertEqual(receipt['stages']['startup']['argv'][0], str(a.xvfb_run))
        self.assertEqual(receipt['executable']['sha256'], r.prepare.sha(a.out / 'prepared/build/astral'))
        self.assertFalse(receipt['game_frame'])

    def test_successful_process_does_not_claim_frame(self):
        code, receipt, _ = self.execute_fixture()
        self.assertEqual(code, 0)
        self.assertFalse(receipt['game_frame'])
        self.assertEqual(receipt['game_metrics'], 'unknown')

    def test_compile_jobs_and_total_budget_are_bounded(self):
        _, _, a = self.fixture()
        for jobs, seconds in ((4, 10), (0, 10), (3, 1501), (3, 0)):
            a.jobs, a.seconds = jobs, seconds
            with self.subTest(jobs=jobs, seconds=seconds):
                with self.assertRaisesRegex(ValueError, 'jobs/budget out of range'):
                    r.execute(a)
                self.assertFalse(a.out.exists())

    def test_dispatch_cutoff_refuses_before_execution(self):
        _, _, a = self.fixture()
        class LateClock(FixtureClock):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 18, 20, 30, tzinfo=timezone.utc)
        with patch.object(r, 'datetime', LateClock):
            with self.assertRaisesRegex(ValueError, 'dispatch cutoff'):
                r.execute(a)
        self.assertFalse(a.out.exists())

    def test_explicit_reviewed_identity_accepts_clean_real_children(self):
        code, receipt, a = self.execute_fixture()
        self.assertEqual(code, 0)
        self.assertEqual(receipt['reviewed_head'], receipt['repository_head'])
        self.assertEqual(receipt['reviewed_files']['tools/prepare_runtime.py']['sha256'],
                         r.prepare.sha(a.repo / 'tools/prepare_runtime.py'))
        self.assertEqual(set(receipt['stages']), {'configure', 'build', 'startup'})
        self.assertTrue(receipt['compilers']['clang++']['sha256'])

    def test_reviewed_ancestor_accepts_clean_supervisor_descendant(self):
        code, receipt, _ = self.execute_fixture(descendant=True)
        self.assertEqual(code, 0)
        self.assertNotEqual(receipt['reviewed_head'], receipt['repository_head'])
        self.assertEqual(set(receipt['stages']), {'configure', 'build', 'startup'})

    def test_bootstrap_only_preparation_is_rejected_before_build(self):
        code, receipt, a = self.execute_fixture(bootstrap_only=True)
        self.assertEqual(code, 1)
        self.assertIn('incomplete overlay composition', receipt['blocker'])
        self.assertEqual(set(receipt['stages']), {'configure'})
        self.assertFalse((a.out / 'prepared/build/astral').exists())

    def test_non_strict_commands_are_rejected_before_build(self):
        code, receipt, _ = self.execute_fixture(strict=False)
        self.assertEqual(code, 1)
        self.assertIn('strict compiler flags missing', receipt['blocker'])
        self.assertEqual(set(receipt['stages']), {'configure'})

    def test_committed_unreviewed_helper_is_rejected(self):
        code, receipt, _ = self.execute_fixture(committed_drift=True)
        self.assertEqual(code, 1)
        self.assertIn('reviewed source drift', receipt['blocker'])
        self.assertFalse(receipt['stages'])

    def test_dirty_tracked_repo_is_rejected(self):
        code, receipt, _ = self.execute_fixture(dirty_unrelated=True)
        self.assertEqual(code, 1)
        self.assertEqual(receipt['blocker'], 'dirty tracked repo')
        self.assertFalse(receipt['stages'])

    def test_unrelated_reviewed_revision_is_rejected(self):
        code, receipt, _ = self.execute_fixture(wrong_ancestor=True)
        self.assertEqual(code, 1)
        self.assertFalse(receipt['stages'])
        self.assertIn('merge-base', receipt['blocker'])

    def test_reviewed_source_drift_is_rejected_before_children(self):
        code, receipt, _ = self.execute_fixture(mutate=True)
        self.assertEqual(code, 1)
        self.assertIn('reviewed source drift', receipt['blocker'])
        self.assertFalse(receipt['stages'])


if __name__ == '__main__':
    unittest.main()
