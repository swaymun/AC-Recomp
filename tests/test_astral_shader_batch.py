"""Synthetic parser/CLI and subprocess translator tests; no network or paid tools."""
import copy
import csv
import dataclasses
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import build_astral_shader_batch as batch
from test_astral_pkz import dat_fixture, graphics_fixture, pkz_fixture

SCRIPT = Path(batch.__file__).resolve()


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve() / 'repo'
        self.repo.mkdir()
        self.git('init', '-q')
        (self.repo / '.gitignore').write_text('.local/\n')
        self.inputs = Path(self.temp.name).resolve() / 'inputs'
        self.inputs.mkdir()
        self.selection = {'schema': 1, 'representatives': []}
        self.wrappers = {}
        for stage in ('vertex', 'fragment'):
            wrapper = graphics_fixture('vertex' if stage == 'vertex' else 'pixel')
            self.wrappers[stage] = wrapper
            code, _, _ = batch.inventory.graphics_pair(wrapper)
            self.selection['representatives'].append({
                'archive': stage + '.pkz', 'member': 'original.dat', 'index': 0,
                'stage': stage, 'wrapper_sha256': batch.inventory.sha256(wrapper),
                'code_sha1_16': hashlib.sha1(code).hexdigest()[:16]})
            self.write_archive(stage, wrapper)
        self.local = self.repo / '.local'
        self.local.mkdir()
        self.selectfile = self.local / 'selection.json'
        self.selectfile.write_text(json.dumps(self.selection))

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write_archive(self, stage, wrapper):
        (self.inputs / (stage + '.pkz')).write_bytes(pkz_fixture(payload=dat_fixture(
            name=b'original.vso' if stage == 'vertex' else b'original.pso', payload=wrapper)))

    def extract(self, name='batch', selection=None, **kwargs):
        if not batch.inventory.ctypes.util.find_library('zstd'):
            self.skipTest('installed optional libzstd absent')
        return batch.extract(self.repo, self.inputs, self.local / name,
                             selection or self.selection, **kwargs)

    def cli(self, action, input_root, output, *args):
        return subprocess.run([sys.executable, str(SCRIPT), action, '--repo', str(self.repo),
                               '--input', str(input_root), '--output', str(output), *args],
                              capture_output=True, text=True, timeout=30)

    def test_real_parsers_aggregate_manifest_provenance_and_permissions(self):
        originals = {p.name: p.read_bytes() for p in self.inputs.iterdir()}
        report = self.extract()
        self.assertEqual(report['status'], 'extracted-translation-blocked')
        self.assertEqual(report['stages'], {'vertex': 1, 'fragment': 1})
        root = self.local / 'batch/handoff'
        index = batch.validate_handoff(self.repo, root)
        self.assertEqual(len(index['by_code_sha1_16']), 2)
        self.assertEqual(batch.translator.validate_manifest(self.repo, root), 2)
        for record in index['by_code_sha1_16'].values():
            source = record['source']
            self.assertEqual(source['archive_sha256'], batch.inventory.sha256(originals[source['archive']]))
            self.assertIn('compressed_sha256', source['compressed_member'])
            self.assertIn('decoded_sha256', source['compressed_member'])
            self.assertEqual(source['dat_member']['offset'], 77)
        self.assertEqual({p.name: p.read_bytes() for p in self.inputs.iterdir()}, originals)
        self.assertEqual(self.git('status', '--porcelain'), '?? .gitignore')
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir()))
        self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    def test_cli_extraction_and_fresh_output_failure(self):
        if not batch.inventory.ctypes.util.find_library('zstd'):
            self.skipTest('installed optional libzstd absent')
        output = self.local / 'cli'
        result = self.cli('extract', self.inputs, output, '--selectors', str(self.selectfile))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'extracted-translation-blocked')
        self.assertEqual(self.cli('extract', self.inputs, output, '--selectors',
                                  str(self.selectfile)).returncode, 1)

    def test_selector_bounds_duplicate_conflicts_unknown_and_required_stages(self):
        cases = []
        for key, value in [('stage', 'compute'), ('stage', 'unknown'), ('index', -1),
                           ('index', True), ('archive', '../bad'), ('member', 'a::b'),
                           ('wrapper_sha256', 'bad'), ('code_sha1_16', 'A' * 16)]:
            bad = copy.deepcopy(self.selection)
            bad['representatives'][0][key] = value
            cases.append(bad)
        cases.extend([{'schema': 1, 'representatives': self.selection['representatives'][:1]},
                      {'schema': 1, 'representatives': self.selection['representatives'] * 3}])
        duplicate = copy.deepcopy(self.selection)
        duplicate['representatives'].append(duplicate['representatives'][0].copy())
        cases.append(duplicate)
        conflict = copy.deepcopy(self.selection)
        conflict['representatives'][1]['code_sha1_16'] = conflict['representatives'][0]['code_sha1_16']
        cases.append(conflict)
        no_fragment = copy.deepcopy(self.selection)
        no_fragment['representatives'][1]['stage'] = 'vertex'
        cases.append(no_fragment)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                batch.selectors(case)

    def test_wrapper_compute_unknown_stage_header_and_hash_rejection(self):
        good = self.wrappers['vertex']
        variants = []
        for magic in (b'CSO\0', b'BAD\0'):
            variants.append(magic + good[4:])
        for offset, value in [(12, 0), (24, 0), (24 + 0x708, 0),
                              (24 + 0x758 + 0x30, 5 << 10)]:
            bad = bytearray(good)
            struct.pack_into('<I', bad, offset, value)
            variants.append(bytes(bad))
        for n, wrapper in enumerate(variants):
            self.write_archive('vertex', wrapper)
            with self.subTest(n=n), self.assertRaises(ValueError):
                self.extract('invalid-' + str(n))
        self.write_archive('vertex', good)
        for key in ('wrapper_sha256', 'code_sha1_16'):
            bad = copy.deepcopy(self.selection)
            bad['representatives'][0][key] = '0' * len(bad['representatives'][0][key])
            with self.assertRaises(ValueError):
                self.extract('hash-' + key, bad)
        bad = copy.deepcopy(self.selection)
        bad['representatives'][0]['stage'], bad['representatives'][1]['stage'] = 'fragment', 'vertex'
        with self.assertRaises(ValueError):
            self.extract('wrong-stage', bad)

    def test_oversized_missing_and_malformed_original_inputs(self):
        for n, limits in enumerate((dataclasses.replace(batch.inventory.Limits(), input_bytes=1),
                                    dataclasses.replace(batch.inventory.Limits(), decoded_bytes=1))):
            with self.assertRaises(ValueError):
                self.extract('oversize-' + str(n), limits=limits)
        bad = copy.deepcopy(self.selection)
        bad['representatives'][0]['member'] = 'absent.dat'
        with self.assertRaises(ValueError):
            self.extract('missing', bad)
        data = (self.inputs / 'vertex.pkz').read_bytes()
        (self.inputs / 'vertex.pkz').write_bytes(data[:-1])
        with self.assertRaises(ValueError):
            self.extract('truncated')

    def test_unsafe_tracked_symlink_and_hardlink_outputs_inputs(self):
        with self.assertRaises(ValueError):
            batch.extract(self.repo, self.inputs, self.repo / 'public', self.selection)
        (self.local / 'tracked').mkdir()
        (self.local / 'tracked/existing').write_text('original')
        self.git('add', '-f', '.local/tracked/existing')
        with self.assertRaisesRegex(ValueError, 'tracked'):
            batch.extract(self.repo, self.inputs, self.local / 'tracked', self.selection)
        (self.local / 'link').symlink_to(self.inputs, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.extract('link/escape')
        os.link(self.inputs / 'vertex.pkz', self.inputs / 'hard.pkz')
        with self.assertRaises(ValueError):
            self.extract('hardlink')

    def test_tampered_handoff_manifest_code_control_header_and_index(self):
        self.extract()
        root = self.local / 'batch/handoff'
        index = batch.load(root / 'index.json')
        h = self.selection['representatives'][0]['code_sha1_16']
        for name in ('manifest.tsv', h + '.code.bin', h + '.ctrl.bin', 'index.json'):
            p = root / name
            before = p.read_bytes()
            p.write_bytes(before + b'X')
            with self.subTest(name=name), self.assertRaises(ValueError):
                batch.validate_handoff(self.repo, root)
            p.write_bytes(before)
        index['by_code_sha1_16'][h]['wrapper_header_hex'] = '00' * 24
        (root / 'index.json').write_text(json.dumps(index))
        with self.assertRaises(ValueError):
            batch.validate_handoff(self.repo, root)

    def test_cli_translation_missing_toolchain_fails_preserving_blocker(self):
        self.extract()
        result = self.cli('translate', self.local / 'batch/handoff', self.local / 'missing-tools',
                          '--toolchain-prefix', str(self.local / 'absent'))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        receipt = batch.load(self.local / 'missing-tools/translation.json')
        self.assertEqual(receipt['status'], 'translation-rejected')
        self.assertIn('blocker', receipt)

    def fake_toolchain(self):
        prefix = self.local / 'tools'
        prefix.mkdir()
        dotnet = prefix / 'dotnet'
        dotnet.write_text('''#!/usr/bin/env python3
import csv,json,os,struct,sys
from pathlib import Path
args=sys.argv
root=Path(args[args.index('--batch')+1]);out=Path(args[args.index('--out')+1])
mode=os.environ.get('SHADER_FIXTURE_MODE','ok')
rows=list(csv.DictReader((root/'manifest.tsv').open(),delimiter='\\t'))
if mode=='exit':raise SystemExit(7)
with (out/'results.tsv').open('w') as f:
 f.write('hash\\tstatus\\n')
 for n,row in enumerate(rows):
  h=row['code_sha1_16'];status='invalid' if mode=='failed' else 'ok'
  f.write(h+'\\t'+status+'\\n')
  if mode=='duplicate':f.write(h+'\\tok\\n')
  if mode=='missing' and n==0:continue
  model=0 if row['stage']=='vertex' else 4
  if mode=='stage':model=5
  data=struct.pack('<10I',0x07230203,0x10000,0,2,0,(5<<16)|15,model,1,0x6e69616d,0)
  if mode=='header':data=b'BAD!'+data[4:]
  path=out/(('0'*16 if mode=='name' and n==0 else h)+'.spv')
  path.write_bytes(data)
  if mode=='symlink' and n==0:
   other=out.parent/'other';other.write_bytes(data);path.unlink();path.symlink_to(other)
''')
        dotnet.chmod(0o755)
        dll = prefix / 'harness.dll'
        dll.write_text('synthetic harness identity')
        validator = prefix / 'spirv-val'
        validator.write_text('''#!/usr/bin/env python3
import os,sys
from pathlib import Path
with Path(__file__).with_name('calls').open('a') as f:f.write('validate\\n')
raise SystemExit(1 if os.environ.get('SHADER_FIXTURE_MODE')=='validator' else 0)
''')
        validator.chmod(0o755)
        lock = self.repo / 'dependencies.lock'
        lock.write_text('synthetic test lock')
        receipt = {'schema': 1, 'wonder': batch.translator.WONDER, 'ryubing': batch.translator.RYUBING,
                   'dependency_lock_sha256': batch.translator.digest(lock),
                   'dotnet': str(dotnet), 'dotnet_sha256': batch.translator.digest(dotnet),
                   'dll': str(dll), 'dll_sha256': batch.translator.digest(dll),
                   'runtime_files': {str(dll): batch.translator.digest(dll)},
                   'restore_locks': {}, 'packages': {},
                   'validator': {'path': str(validator), 'sha256': batch.translator.digest(validator)}}
        (prefix / 'toolchain.json').write_text(json.dumps(receipt))
        return prefix

    def test_strict_upstream_api_fake_subprocess_translation_and_failure_paths(self):
        self.extract()
        prefix = self.fake_toolchain()
        # Only unavailable upstream dependency provenance is mocked. Real batch,
        # manifest, result/hash checks, translator and validators execute locally.
        with mock.patch.object(batch.translator, 'verify_lock'), \
             mock.patch.object(batch.translator, 'verify_pin'), \
             mock.patch.object(batch.translator, 'package_receipts', return_value={}):
            result = batch.translate(self.repo, self.local / 'batch/handoff', self.local / 'ok', prefix)
            self.assertEqual(result['status'], 'translated-validated')
            self.assertEqual(len(result['products']), 2)
            self.assertEqual((prefix / 'calls').read_text().count('validate'), 4)
            for mode in ('exit', 'failed', 'duplicate', 'missing', 'name', 'header', 'stage',
                         'validator', 'symlink'):
                with self.subTest(mode=mode), mock.patch.dict(os.environ, {'SHADER_FIXTURE_MODE': mode}):
                    with self.assertRaises(ValueError):
                        batch.translate(self.repo, self.local / 'batch/handoff', self.local / mode, prefix)
                    self.assertEqual(batch.load(self.local / mode / 'translation.json')['status'],
                                     'translation-rejected')
            # Fresh receipt hash checks in the unmodified API remain active.
            (prefix / 'harness.dll').write_text('changed')
            with self.assertRaises(ValueError):
                batch.translate(self.repo, self.local / 'batch/handoff', self.local / 'changed-tools', prefix)

    def bulk_fixture(self, count=6, duplicate=False):
        probes, hashes = [], []
        for n in range(count):
            wrapper = bytearray(graphics_fixture('vertex' if n % 2 == 0 else 'pixel'))
            # Alter an instruction word, preserving the checked SPH and padding.
            wrapper[24 + 0x758 + 0x38] = n if not duplicate else n % 2
            wrapper = bytes(wrapper)
            data = dat_fixture(name=b'original.vso' if n % 2 == 0 else b'original.pso', payload=wrapper)
            archive = pkz_fixture(payload=data)
            name = 'bulk%d.pkz' % n
            (self.inputs / name).write_bytes(archive)
            code, _, _ = batch.inventory.graphics_pair(wrapper)
            hashes.append(hashlib.sha1(code).hexdigest()[:16])
            probes.append(dict(archive=name, member='original.dat',
                archive_sha256=batch.inventory.sha256(archive), decoded_sha256=batch.inventory.sha256(data)))
        log = self.local / 'runtime.log'
        log.write_text(''.join('nvn: shader '+h+' (code 0x200 bytes, control abc): no /private/'+h+'.spv\n'
                               for h in hashes + ['f'*16]))
        plan = dict(schema=2, mode='runtime-graphics', probes=probes,
                    log_sha256=batch.inventory.sha256(log.read_bytes()))
        return plan, log

    def test_bulk_cli_over_four_and_strict_translation(self):
        plan, log = self.bulk_fixture()
        self.selectfile.write_text(json.dumps(plan))
        result = self.cli('bulk-extract', self.inputs, self.local/'bulk', '--selectors', str(self.selectfile),
                          '--runtime-log', str(log))
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        report = batch.load(self.local/'bulk/batch.json')
        self.assertEqual((report['observed_requests'], report['matched_graphics'], report['extracted'],
                          report['unmatched'], report['remaining_untranslated']), (7, 6, 6, 1, 7))
        with self.assertRaisesRegex(ValueError, 'anchor'):
            batch.translate(self.repo, self.local/'bulk/handoff', self.local/'unanchored', self.local/'absent')
        prefix = self.fake_toolchain()
        anchor = batch.inventory.sha256((self.local/'bulk/handoff/index.json').read_bytes())
        with mock.patch.object(batch.translator, 'verify_lock'), \
             mock.patch.object(batch.translator, 'verify_pin'), \
             mock.patch.object(batch.translator, 'package_receipts', return_value={}):
            translated = batch.translate(self.repo, self.local/'bulk/handoff', self.local/'bulk-trans', prefix, anchor)
            self.assertEqual(translated['schema'], 2)
            self.assertEqual(len(translated['products']), 6)
            with mock.patch.dict(os.environ, SHADER_FIXTURE_MODE='missing'):
                with self.assertRaises(ValueError):
                    batch.translate(self.repo, self.local/'bulk/handoff', self.local/'bulk-failed', prefix, anchor)
            self.assertNotIn('products', batch.load(self.local/'bulk-failed/translation.json'))

    def test_bulk_resume_deterministic_anchors_and_changed_identity(self):
        plan, log = self.bulk_fixture()
        a = batch.bulk_extract(self.repo, self.inputs, self.local/'first', plan, log, 2)
        first = self.local/'first/handoff'
        index = batch.load(first/'index.json')
        self.assertEqual(sorted(index['by_code_sha1_16']), index['runtime']['matched'][:2])
        again = batch.bulk_extract(self.repo, self.inputs, self.local/'repeat', plan, log, 2)
        self.assertEqual(a['handoff_index']['sha256'], again['handoff_index']['sha256'])
        digest = batch.inventory.sha256((first/'index.json').read_bytes())
        second = batch.bulk_extract(self.repo, self.inputs, self.local/'second', plan, log, 2, first, digest)
        self.assertEqual(second['remaining_matched'], 2)
        with self.assertRaises(ValueError):
            batch.bulk_extract(self.repo, self.inputs, self.local/'bad-anchor', plan, log, 2, first, '0'*64)
        changed = copy.deepcopy(plan)
        changed['probes'][0]['archive_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            batch.bulk_extract(self.repo, self.inputs, self.local/'bad-source', changed, log)
        # A changed, still valid unselected archive also invalidates resumable source identity.
        self.write_archive('vertex', self.wrappers['fragment'])
        with self.assertRaises(ValueError):
            batch.bulk_extract(self.repo, self.inputs, self.local/'changed-resume', plan, log, 2, first, digest)

    def test_bulk_dedup_and_conflicting_control_rejected(self):
        plan, log = self.bulk_fixture(6, duplicate=True)
        report = batch.bulk_extract(self.repo, self.inputs, self.local/'dedup', plan, log)
        self.assertEqual(report['extracted'], 2)
        index = batch.load(self.local/'dedup/handoff/index.json')
        self.assertTrue(all(len(r['sources']) == 3 for r in index['by_code_sha1_16'].values()))
        # Same code identifier with changed opaque control data must fail, not select adjacency.
        wrapper = bytearray(graphics_fixture('vertex'))
        wrapper[24+20] ^= 1
        data = dat_fixture(payload=bytes(wrapper))
        archive = pkz_fixture(payload=data)
        (self.inputs/'bulk0.pkz').write_bytes(archive)
        plan['probes'][0].update(archive_sha256=batch.inventory.sha256(archive),
                                 decoded_sha256=batch.inventory.sha256(data))
        rejected = batch.bulk_extract(self.repo, self.inputs, self.local/'conflict', plan, log)
        self.assertEqual((rejected['conflicted'], rejected['extracted']), (1, 1))
        accepted = batch.load(self.local/'conflict/handoff/index.json')
        self.assertTrue(set(accepted['runtime']['conflicted']).isdisjoint(accepted['by_code_sha1_16']))

    def test_bulk_bounds_runtime_log_and_stage_exclusions(self):
        plan, log = self.bulk_fixture(2)
        for count in (0, 129, True):
            with self.assertRaises(ValueError):
                batch.bulk_extract(self.repo, self.inputs, self.local/'limit', plan, log, count)
        bad = copy.deepcopy(plan)
        bad['probes'] *= 5
        with self.assertRaises(ValueError):
            batch.bulk_extract(self.repo, self.inputs, self.local/'probes', bad, log)
        with self.assertRaises(ValueError):
            batch.runtime_requests(log, '0'*64)
        log.write_text(log.read_text().replace('/private/', '/private/f'))
        with self.assertRaises(ValueError):
            batch.runtime_requests(log, batch.inventory.sha256(log.read_bytes()))
        for magic in (b'CSO\0', b'BAD\0'):
            wrapper = magic + graphics_fixture('vertex')[4:]
            data = dat_fixture(payload=wrapper)
            archive = pkz_fixture(payload=data)
            (self.inputs/'bulk0.pkz').write_bytes(archive)
            plan['probes'][0].update(archive_sha256=batch.inventory.sha256(archive),
                                     decoded_sha256=batch.inventory.sha256(data))
            # Restore valid log; excluded stages never gain a requested association.
            plan2, log2 = self.bulk_fixture(2)
            (self.inputs/'bulk0.pkz').write_bytes(archive)
            plan2['probes'][0].update(plan['probes'][0])
            r = batch.bulk_extract(self.repo, self.inputs, self.local/magic[:3].decode(), plan2, log2)
            self.assertEqual(r['extracted'], 1)
            self.assertEqual(sum(r['excluded_wrappers'].values()), 1)

    def test_bulk_decodes_each_dat_once_and_unsafe_paths(self):
        plan, log = self.bulk_fixture(2)
        original = batch.inventory.Zstd.decode
        calls = []
        def decoded(decoder, data, size, limits):
            calls.append(size)
            return original(decoder, data, size, limits)
        with mock.patch.object(batch.inventory.Zstd, 'decode', decoded):
            batch.bulk_extract(self.repo, self.inputs, self.local/'once', plan, log)
        self.assertEqual(len(calls), len(plan['probes']))
        huge = self.local/'once/handoff/oversized'
        with huge.open('wb') as stream:
            stream.truncate(batch.MAX_PRODUCT+1)
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            batch.validate_handoff(self.repo, self.local/'once/handoff')
        huge.unlink()
        (self.local/'link').symlink_to(self.inputs, target_is_directory=True)
        for output in (self.repo/'public', self.local/'link/escape', self.local/'once'):
            with self.assertRaises(ValueError):
                batch.bulk_extract(self.repo, self.inputs, output, plan, log)
        rows = copy.deepcopy(self.selection['representatives'])
        with self.assertRaisesRegex(ValueError, 'bulk product limit'):
            batch.selectors(dict(schema=2, mode='bulk-graphics', products=rows*65))


    def test_bulk_no_matches_preserves_exact_unmatched_requests(self):
        plan, log = self.bulk_fixture(2)
        h = 'e'*16
        log.write_text('nvn: shader '+h+' (code 0x200 bytes, control abc): no /private/'+h+'.spv\n')
        plan['log_sha256'] = batch.inventory.sha256(log.read_bytes())
        with self.assertRaises(ValueError):
            batch.bulk_extract(self.repo, self.inputs, self.local/'unmatched', plan, log)
        progress = batch.load(self.local/'unmatched/runtime.json')
        self.assertEqual(progress['requested'], [h])
        self.assertEqual(progress['unmatched'], [h])
        self.assertEqual(progress['matched'], [])
        self.assertFalse((self.local/'unmatched/handoff').exists())

    def test_bulk_wall_deadline(self):
        # Exercise interruption and cleanup of the same blocking subprocess API
        # used by the unchanged translator, allowing normal OS timer scheduling.
        with self.assertRaisesRegex(ValueError, 'wall time'):
            with batch.bounded_seconds(1):
                subprocess.run([sys.executable, '-c', 'import time; time.sleep(10)'], check=True)

    def test_duplicate_json_and_size_limits(self):
        self.selectfile.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            batch.load(self.selectfile)
        self.selectfile.write_bytes(b' ' * (batch.MAX_JSON + 1))
        with self.assertRaisesRegex(ValueError, 'size limit'):
            batch.load(self.selectfile)


if __name__ == '__main__':
    unittest.main()
