"""Closed simulator composition; temporary Git and real subprocess application."""
import copy
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_runtime as r


class CumulativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.patches = self.root / 'runtime/patches'
        self.patches.mkdir(parents=True)
        host = self.root / 'ports/ios'
        host.mkdir(parents=True)
        (host / 'App.mm').write_text('synthetic host\n')
        self.ref = self.root / 'reference'
        self.ref.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.ref / 'state').write_text('stage0\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'synthetic base')
        self.pin = r.git(self.ref, 'rev-parse', 'HEAD')
        for name in r.IOS_PROFILES[r.IOS_CUMULATIVE]:
            shutil.copyfile(ROOT / 'runtime/patches' / name, self.patches / name)
        self.identity = {'profile': r.IOS_CUMULATIVE, 'pin': r.PIN,
            'patch_order': list(r.IOS_PROFILES[r.IOS_CUMULATIVE]),
            'patches': {p.name: r.sha(p) for p in r.ios_patches(r.IOS_CUMULATIVE, self.root)},
            'host': {'App.mm': r.sha(host / 'App.mm')}}

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.ref), *args], check=True, capture_output=True)

    def test_exact_order_and_hashes_reject_omitted_duplicate_extra_stale(self):
        r.validate_ios_identity(self.identity, self.root)
        for names in (self.identity['patch_order'][:-1], self.identity['patch_order'] + ['astral-apm.patch'],
                      list(reversed(self.identity['patch_order']))):
            bad = copy.deepcopy(self.identity)
            bad['patch_order'] = names
            with self.assertRaisesRegex(ValueError, 'order mismatch'):
                r.validate_ios_identity(bad, self.root)
        for mutate in ('omit', 'extra', 'stale'):
            bad = copy.deepcopy(self.identity)
            if mutate == 'omit': del bad['patches']['astral-audio.patch']
            if mutate == 'extra': bad['patches']['arbitrary.patch'] = '0' * 64
            if mutate == 'stale': bad['patches']['astral-notifications.patch'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'patch identity mismatch'):
                r.validate_ios_identity(bad, self.root)
        bad = dict(self.identity, profile='arbitrary')
        with self.assertRaisesRegex(ValueError, 'runtime identity'):
            r.validate_ios_identity(bad, self.root)

    def test_every_selected_file_tamper_missing_and_link_refused(self):
        for p in r.ios_patches(r.IOS_CUMULATIVE, self.root):
            original = p.read_bytes()
            p.write_bytes(original + b'# tampered\n')
            with self.assertRaisesRegex(ValueError, 'patch identity'):
                r.validate_ios_identity(self.identity, self.root)
            forged = copy.deepcopy(self.identity)
            forged['patches'][p.name] = r.sha(p)
            with self.assertRaisesRegex(ValueError, 'landed simulator patch identity'):
                r.validate_ios_identity(forged, self.root)
            p.unlink()
            with self.assertRaisesRegex(ValueError, 'missing simulator patch'):
                r.validate_ios_identity(self.identity, self.root)
            p.symlink_to(self.ref / 'state')
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                r.validate_ios_identity(self.identity, self.root)
            p.unlink()
            p.write_bytes(original)
        os.link(p, self.root / 'linked')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            r.validate_ios_identity(self.identity, self.root)

    def test_temporary_git_cumulative_equivalence_and_apply_prerequisites(self):
        patches = []
        for n, name in enumerate(r.IOS_PROFILES[r.IOS_CUMULATIVE]):
            path = self.root / name
            path.write_text(f'--- a/state\n+++ b/state\n@@ -1 +1 @@\n-stage{n}\n+stage{n+1}\n')
            patches.append(path)
        automatic = self.root / 'automatic'
        fingerprint = r.prepare_source(self.ref, automatic, patches, self.pin)
        manual = self.root / 'manual'
        subprocess.run(['git', 'clone', '-q', str(self.ref), str(manual)], check=True)
        for path in patches:
            subprocess.run(['git', '-C', str(manual), 'apply', str(path)], check=True)
        self.assertEqual(fingerprint, r.source_fingerprint(manual))
        self.assertEqual((automatic / 'state').read_text(), 'stage8\n')
        for label, sequence in [('omitted', patches[:3] + patches[4:]),
                                ('duplicate', patches[:3] + [patches[2]] + patches[3:]),
                                ('reordered', [patches[1], patches[0]] + patches[2:])]:
            with self.subTest(label=label), self.assertRaises(subprocess.CalledProcessError):
                r.prepare_source(self.ref, self.root / label, sequence, self.pin)

    def test_real_pinned_source_composition_equivalence(self):
        common = Path(r.git(ROOT, 'rev-parse', '--path-format=absolute', '--git-common-dir')).parent
        ref = common / '.local/orchestrate/2026-10-18/worktrees/PIN-004/.local/references/SuperMarioWonderRecomp'
        if not ref.is_dir():
            self.skipTest('local pinned reference absent')
        paths = r.ios_patches(r.IOS_CUMULATIVE)
        composed = self.root / 'composed'
        actual = r.prepare_source(ref, composed, paths)
        # Independently apply the default then service-only deltas. Their touched
        # paths are disjoint from iOS CMake/platform/NVN changes.
        alternate = self.root / 'alternate'
        r.prepare_source(ref, alternate, r.ios_patches(r.IOS_DEFAULT))
        for name in ('astral-control-import.patch', 'astral-audio.patch',
                     'astral-notifications.patch', 'astral-apm.patch'):
            subprocess.run(['git', '-C', str(alternate), 'apply', '--check', str(ROOT / 'runtime/patches' / name)], check=True)
            subprocess.run(['git', '-C', str(alternate), 'apply', str(ROOT / 'runtime/patches' / name)], check=True)
        self.assertEqual(actual, r.source_fingerprint(alternate))
        self.assertIn('runtime/src/svc_am.cpp', actual)
        self.assertIn('runtime/src/hle_audio.cpp', actual)

    def test_real_bounded_openstep_app_inventory_parser(self):
        if sys.platform != 'darwin':
            self.skipTest('macOS plist converter required')
        text = '{ "local.acs.example" = { CFBundleIdentifier = "local.acs.example"; }; }'
        apps = r.simulator_app_inventory(text, self.root / 'apps.plist')
        self.assertEqual(apps['local.acs.example']['CFBundleIdentifier'], 'local.acs.example')
        with self.assertRaises(subprocess.CalledProcessError):
            r.simulator_app_inventory('invalid plist', self.root / 'invalid.plist')
        with self.assertRaises(FileExistsError):
            r.simulator_app_inventory(text, self.root / 'apps.plist')

    def test_cli_refuses_unknown_profile_and_non_simulator_selection(self):
        tool = ROOT / 'tools/prepare_runtime.py'
        result = subprocess.run([sys.executable, str(tool), '--ios-profile', 'arbitrary'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid choice', result.stderr)
        args = [sys.executable, str(tool), '--ios-profile', r.IOS_CUMULATIVE]
        for name in ('repo', 'reference', 'inputs', 'gen', 'out'):
            args += ['--' + name, str(self.root / name)]
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires --ios-simulator', result.stderr)


class RunnerGateTests(unittest.TestCase):
    def cleanup_fixture(self, scenario):
        # Execute the real embedded ownership functions and cleanup AST in an
        # isolated subprocess. Only command transport is synthetic: no simctl,
        # installed application or real simulator is touched by this regression.
        harness = r'''
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

script, scenario, directory = sys.argv[1:]
tree = ast.parse(Path(script).read_text().split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0])
functions = [node for node in ast.walk(tree)
             if isinstance(node, ast.FunctionDef) and node.name in ('owned', 'sim')]
assert {node.name for node in functions} == {'owned', 'sim'}
blocks = [node.finalbody for node in ast.walk(tree) if isinstance(node, ast.Try)
          and any(isinstance(item, ast.If) and isinstance(item.test, ast.Name)
                  and item.test.id == 'booted' for item in node.finalbody)]
assert len(blocks) == 1
def require(condition, message):
    if not condition:
        raise ValueError(message)
runtime = SimpleNamespace(require=require, sha=lambda path: hashlib.sha256(path.read_bytes()).hexdigest())
family = 'iPhone'
simruntime = 'fixture-runtime'
types = {'iPhone': 'fixture-phone', 'iPad': 'fixture-tablet'}
registry = {name: {'name': 'ACS IOS-LAUNCH-RESCUE-026 ' + name,
                  'runtime': simruntime, 'type': kind, 'udid': name + '-owned'}
            for name, kind in types.items()}
devices = [{'name': entry['name'], 'udid': entry['udid'], 'deviceTypeIdentifier': entry['type'],
            'isAvailable': True, 'state': 'Booted'} for entry in registry.values()]
# A valid, unrelated booted device must never receive a mutation.
devices.append({'name': 'Unrelated personal phone', 'udid': 'unrelated',
                'deviceTypeIdentifier': types[family], 'isAvailable': True, 'state': 'Booted'})
if scenario == 'registry_mismatch':
    registry[family]['name'] = 'Unrelated personal phone'
if scenario == 'device_mismatch':
    devices[0]['name'] = 'Unrelated personal phone'
if scenario == 'redirected_udid':
    registry[family]['udid'] = 'unrelated'
run = Path(directory)
installed_app = run / 'installed.app'
installed_app.mkdir()
(installed_app / 'astral').write_bytes(b'owned binary')
report = {'executable_sha256': runtime.sha(installed_app / 'astral')}
if scenario == 'app_mismatch':
    (installed_app / 'astral').write_bytes(b'foreign binary')
result = {'installed': True}
bundle = 'fixture.bundle'
docs = None
booted = scenario != 'not_booted'
calls = []
def command(args, **kwargs):
    assert args[:2] == ['xcrun', 'simctl']
    calls.append(args[2:])
    if args[2:] == ['list', 'devices', '--json']:
        return json.dumps({'devices': {simruntime: devices}})
    action, udid, *tail = args[2:]
    assert udid == 'iPhone-owned', 'unrelated device mutation'
    if action == 'get_app_container':
        if scenario == 'lookup_failure':
            raise RuntimeError('synthetic app lookup failure')
        return str(installed_app)
    if action == 'uninstall' and scenario in ('uninstall_failure', 'two_failures'):
        raise RuntimeError('synthetic uninstall failure')
    if action == 'shutdown':
        assert kwargs['timeout'] == 60
        if scenario == 'two_failures':
            raise RuntimeError('synthetic shutdown failure')
        devices[0]['state'] = 'Shutdown'
    return ''
exec(compile(ast.Module(body=functions, type_ignores=[]), script, 'exec'))
exec(compile(ast.Module(body=blocks[0], type_ignores=[]), script, 'exec'))
print(json.dumps({'result': result, 'calls': calls, 'devices': devices}))
'''
        with tempfile.TemporaryDirectory() as temp:
            process = subprocess.run([sys.executable, '-c', harness,
                str(ROOT / 'scripts/check-ios-runtime'), scenario, temp],
                capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_cleanup_shutdown_survives_app_lookup_uninstall_and_identity_failures(self):
        for scenario, labels in (
            ('uninstall_failure', ['uninstall: synthetic uninstall failure']),
            ('lookup_failure', ['terminate: synthetic app lookup failure',
                                'uninstall: synthetic app lookup failure']),
            ('app_mismatch', ['terminate: cleanup app ownership mismatch',
                              'uninstall: cleanup app ownership mismatch']),
            ('two_failures', ['uninstall: synthetic uninstall failure',
                              'shutdown: synthetic shutdown failure'])):
            with self.subTest(scenario=scenario):
                observed = self.cleanup_fixture(scenario)
                calls = observed['calls']
                shutdown = next(i for i, call in enumerate(calls) if call[0] == 'shutdown')
                # A fresh device inventory check precedes shutdown even after
                # an earlier app ownership/transport failure.
                self.assertEqual(calls[shutdown - 1], ['list', 'devices', '--json'])
                self.assertEqual(calls[shutdown], ['shutdown', 'iPhone-owned'])
                self.assertEqual(observed['result']['cleanup_error'].split('; '), labels)
                self.assertEqual(observed['result']['app_cleanup'], 'app removal failed')
                self.assertNotIn('owned app removed', observed['result']['cleanup'])
                self.assertEqual(observed['devices'][1]['state'], 'Booted')
                self.assertEqual(observed['devices'][2]['state'], 'Booted')
                if scenario != 'two_failures':
                    self.assertEqual(observed['devices'][0]['state'], 'Shutdown')
                if scenario in ('lookup_failure', 'app_mismatch'):
                    self.assertFalse(any(call[0] in ('terminate', 'uninstall') for call in calls))

    def test_cleanup_refuses_changed_registry_device_or_redirected_udid(self):
        for scenario in ('registry_mismatch', 'device_mismatch', 'redirected_udid'):
            with self.subTest(scenario=scenario):
                observed = self.cleanup_fixture(scenario)
                self.assertFalse(any(call[0] in ('terminate', 'uninstall', 'shutdown')
                                     for call in observed['calls']))
                errors = observed['result']['cleanup_error']
                for label in ('terminate:', 'uninstall:', 'shutdown:'):
                    self.assertIn(label, errors)
                self.assertEqual(observed['result']['device_cleanup'], 'device shutdown failed')
                self.assertTrue(all(device['state'] == 'Booted' for device in observed['devices']))

    def test_cleanup_success_and_no_mutation_without_owned_boot(self):
        observed = self.cleanup_fixture('success')
        mutations = [call[0] for call in observed['calls'] if call[0] != 'list']
        self.assertEqual(mutations, ['get_app_container', 'terminate', 'get_app_container', 'uninstall', 'shutdown'])
        self.assertEqual(observed['result']['cleanup'], 'owned app removed; dedicated device shutdown')
        self.assertNotIn('cleanup_error', observed['result'])
        observed = self.cleanup_fixture('not_booted')
        self.assertEqual(observed['calls'], [])
        self.assertNotIn('cleanup', observed['result'])

    def test_subprocess_rejects_stale_source_and_omitted_overlay_before_device_use(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'scripts').mkdir()
            (root / 'tools').mkdir()
            shutil.copyfile(ROOT / 'scripts/check-ios-runtime', root / 'scripts/check-ios-runtime')
            for name in ('prepare_runtime.py', 'import_owned_dump.py', 'extract_control_metadata.py',
                         'nacp_metadata.py', 'cnmt_metadata.py'):
                shutil.copyfile(ROOT / 'tools' / name, root / 'tools' / name)
            shutil.copytree(ROOT / 'runtime/patches', root / 'runtime/patches')
            shutil.copytree(ROOT / 'ports/ios', root / 'ports/ios')
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            (root / '.gitignore').write_text('.local/\n')
            subprocess.run(['git','-C',str(root),'add','.'],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.email=fixture@example.invalid',
                            '-c','user.name=Fixture','commit','-qm','fixture'],check=True)
            out = root / '.local/prepared'
            (out / 'build/astral.app').mkdir(parents=True)
            (out / 'source').mkdir()
            subprocess.run(['git','init','-q',str(out/'source')],check=True)
            (out / 'build/astral.app/astral').write_bytes(b'synthetic executable')
            (out / 'build/compile_commands.json').write_text('[]')
            identity = {'pin':r.PIN,'profile':r.IOS_DEFAULT,
                'patches':{p.name:r.sha(p) for p in r.ios_patches(r.IOS_DEFAULT,root)},
                'host':{p.name:r.sha(p) for p in (root/'ports/ios').iterdir() if p.is_file()}}
            for failure in ('source', 'overlay'):
                bad = copy.deepcopy(identity)
                if failure == 'overlay': del bad['patches']['ios-runtime.patch']
                (out / 'prepared.json').write_text(json.dumps({'identity':bad,'source':{'missing':'0'*64}}))
                (out / 'built.json').write_text(json.dumps(r.simulator_build_identity(out)))
                result = subprocess.run(['bash',str(root/'scripts/check-ios-runtime'),
                    '--prepared',str(out),'--inputs',str(root/'.local/no-input'),
                    '--host-registry',str(root/'.local/no-registry')],capture_output=True,text=True,timeout=20)
                self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertIn('stale prepared source' if failure=='source' else 'patch identity mismatch',result.stdout)
                report_path = Path(next(x.split('=',1)[1] for x in result.stdout.splitlines()
                                        if x.startswith('private_evidence='))) / 'receipt.json'
                report = json.loads(report_path.read_text())
                self.assertEqual(report['families'],{})
                self.assertEqual(report['status'],'blocked')
                self.assertNotIn('xcrun',(report_path.parent/'commands.log').read_text())
