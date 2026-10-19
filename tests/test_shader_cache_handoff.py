"""Original synthetic fixtures; selected preflight is never a full-cache claim."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import check_shader_cache_handoff as checker
from test_astral_pkz import graphics_fixture

ROOT = Path(__file__).resolve().parents[1]


def identity(data):
    return {'bytes': len(data), 'sha256': checker.sha256(data)}


def module(stage):
    # Only reflection structure, deliberately not a SPIR-V validator fixture.
    words = [0x07230203, 0x00010000, 0, 2, 0, (5 << 16) | 15,
             0 if stage == 'vertex' else 4, 1, 0x6e69616d, 0]
    return struct.pack('<' + 'I' * len(words), *words)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.handoff = self.root / 'handoff'
        self.handoff.mkdir()
        selections, records, rows = [], {}, []
        for stage in ('vertex', 'fragment'):
            wrapper = graphics_fixture('vertex' if stage == 'vertex' else 'pixel')
            code, ctrl, _ = checker.batch.inventory.graphics_pair(wrapper)
            h = hashlib.sha1(code).hexdigest()[:16]
            selected = dict(archive=stage+'.pkz', member='original.dat', index=0,
                            stage=stage, wrapper_sha256=checker.sha256(wrapper), code_sha1_16=h)
            _, _, row = checker.batch.pair_row(wrapper, selected)
            selections.append(selected)
            rows.append(row)
            records[h] = dict(manifest=row, wrapper_header_hex=wrapper[:24].hex(),
                              code_sha256=checker.sha256(code), ctrl_sha256=checker.sha256(ctrl))
            (self.handoff / (h + '.code.bin')).write_bytes(code)
            (self.handoff / (h + '.ctrl.bin')).write_bytes(ctrl)
        manifest = checker.batch.manifest_bytes(rows)
        (self.handoff / 'manifest.tsv').write_bytes(manifest)
        self.index = dict(schema=1, pipeline='unproven',
                          selection=dict(schema=1, representatives=selections),
                          by_code_sha1_16=records, manifest_sha256=checker.sha256(manifest))
        self.save_index()
        self.inputs, _ = checker.selected_inputs(self.handoff, self.anchor)
        self.tsv = ('hash\tstage\tstatus\tspv_bytes\tresources\n' + ''.join(
            h+'\t'+stage+'\tok\t40\t\n' for h, (_, _, stage) in self.inputs.items())).encode()

    def save_index(self):
        path = self.handoff / 'index.json'
        path.write_text(json.dumps(self.index))
        self.anchor = checker.sha256(path.read_bytes())

    def test_hash_is_whole_control_sized_code_not_program_slice(self):
        for h, (codepath, ctrlpath, _) in self.inputs.items():
            code, ctrl = codepath.read_bytes(), ctrlpath.read_bytes()
            size = struct.unpack_from('<I', ctrl, 0x704)[0]
            self.assertEqual(size, len(code))
            self.assertEqual(h, hashlib.sha1(code[:size]).hexdigest()[:16])
            self.assertNotEqual(h, hashlib.sha1(code[0x30:0xc0]).hexdigest()[:16])

    def test_selected_input_rejections(self):
        h = next(iter(self.inputs))
        for kind in ('code', 'size', 'stage', 'anchor'):
            with self.subTest(kind=kind):
                codepath, ctrlpath, _ = self.inputs[h]
                code, ctrl, index = codepath.read_bytes(), ctrlpath.read_bytes(), copy.deepcopy(self.index)
                try:
                    if kind == 'code':
                        codepath.write_bytes(code[:-1] + b'X')
                    elif kind == 'size':
                        changed = bytearray(ctrl)
                        struct.pack_into('<I', changed, 0x704, len(code)-1)
                        ctrlpath.write_bytes(changed)
                        self.index['by_code_sha1_16'][h]['ctrl_sha256'] = checker.sha256(changed)
                        self.save_index()
                    elif kind == 'stage':
                        self.index['selection']['representatives'][0]['stage'] = 'fragment'
                        self.save_index()
                    else:
                        self.anchor = '0'*64
                    with self.assertRaises(ValueError):
                        checker.selected_inputs(self.handoff, self.anchor)
                finally:
                    codepath.write_bytes(code)
                    ctrlpath.write_bytes(ctrl)
                    self.index = index
                    self.save_index()

    def test_tsv_empty_resource_is_valid_but_missing_duplicate_stage_status_not(self):
        rows = checker.result_rows(self.tsv, self.inputs)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['resources'] == '' for row in rows.values()))
        lines = self.tsv.splitlines(keepends=True)
        cases = [b''.join(lines[:2]), self.tsv+lines[1], self.tsv.replace(b'\tvertex\t', b'\tfragment\t'),
                 self.tsv.replace(b'\tok\t', b'\tfail\t'), self.tsv.replace(b'resources', b'absent'),
                 self.tsv.replace(b'\t40\t', b'\tbad\t'), self.tsv.replace(b'\t40\t', b'\t40')]
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                checker.result_rows(bad, self.inputs)

    def test_spirv_stage_and_instruction_extents(self):
        checker.stage_model(module('vertex'), 'vertex')
        for bad, stage in ((module('vertex'), 'fragment'), (b'bad', 'vertex'),
                           (module('vertex')+b'\0'*4, 'vertex'), (module('fragment')[:-4], 'fragment')):
            with self.assertRaises(ValueError):
                checker.stage_model(bad, stage)

    def retry_results(self):
        # Actual upstream WriteResults columns. A successful second attempt can
        # retain the first attempt's exception in Error; status is authoritative
        # only alongside independently anchored/validated products.
        header = ('hash\tgroup\tstage\tstages_using\tstatus\tms\tspv_bytes\tresources\t'
                  'translator_messages\terror\tdraw_time_queries\n')
        return (header + ''.join(h+'\t.\t'+stage+'\t1\t'+
            ('ok-retry' if stage == 'fragment' else 'ok')+
            '\t1.0\t40\t\t\tfirst attempt exception\tcoordNormalized\n'
            for h, (_, _, stage) in self.inputs.items())).encode()

    def test_retry_real_tsv_contract_and_strict_status_inventory(self):
        tsv = self.retry_results()
        rows = checker.result_rows(tsv, self.inputs)
        self.assertEqual({r['status'] for r in rows.values()}, {'ok', 'ok-retry'})
        self.assertTrue(all(r['error'] == 'first attempt exception' for r in rows.values()))
        for status in ('fail', 'failed', 'invalid', 'exception', 'timeout', 'no-output',
                       'unknown', '', 'OK', 'ok-retry ', 'ok-retry-again'):
            with self.subTest(status=status), self.assertRaises(ValueError):
                checker.result_rows(tsv.replace(b'\tok-retry\t', ('\t'+status+'\t').encode()),
                                    self.inputs)
        lines = tsv.splitlines(keepends=True)
        bad_rows = (tsv.replace(b'\tfragment\t', b'\tvertex\t'),
                    tsv.replace(next(iter(self.inputs)).encode(), b'f'*16),
                    tsv.replace(b'\t40\t', b'\t-40\t'),
                    tsv.replace(b'\t40\t', b'\t\t'),
                    b''.join(lines[:-1]), tsv+lines[-1])
        for bad in bad_rows:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                checker.result_rows(bad, self.inputs)

    def reanchor_package(self, args):
        index = json.loads(args.result_index.read_text())
        index['files'] = {str(p.relative_to(args.translation_root)): identity(p.read_bytes())
                         for p in args.translation_root.rglob('*') if p.is_file()}
        args.result_index.write_text(json.dumps(index))
        receipt = json.loads(args.accepted_receipt.read_text())
        receipt['result_index_sha256'] = checker.sha256(args.result_index.read_bytes())
        args.accepted_receipt.write_text(json.dumps(receipt))
        args.accepted_receipt_sha256 = checker.sha256(args.accepted_receipt.read_bytes())

    def test_retry_production_parser_and_anchored_integrity(self):
        native = self.native_source()
        if not shutil.which('c++') or not (native/'runtime/src/nvn/nvn_shaders.cpp').is_file():
            self.skipTest('set SHADER_NATIVE_SOURCE to a local production source tree and install c++')
        self.tsv = self.retry_results()
        args = self.prepare_package(native)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = checker.check(args)
        self.assertEqual(len(report['products']), 2)
        self.assertEqual(report['standalone_compile_exit'], 0)
        self.assertTrue(all(p['production_parser_exit'] == 0 for p in report['products']))
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        h = next(h for h, (_, _, stage) in self.inputs.items() if stage == 'fragment')
        for mutation, error in (
                ('validation', 'accepted product stage/validation'),
                ('stage', 'accepted product stage/validation'),
                ('size', 'cache product identity/size mismatch'),
                ('tsv-size', 'cache product identity/size mismatch'),
                ('hash', 'cache product identity/size mismatch'),
                ('missing-product', 'accepted product identifiers'),
                ('resources', 'production parser rejected selected shader')):
            with self.subTest(mutation=mutation):
                # Restore original fixture bytes, then reanchor deliberate semantic
                # inconsistencies so byte-integrity checks alone cannot hide them.
                for path, data in before.items():
                    path.write_bytes(data)
                translated_path = args.translation_root/'translation.json'
                translated = json.loads(translated_path.read_text())
                if mutation in ('validation', 'stage', 'size', 'hash'):
                    key, value = {'validation': ('validation_exit', 1),
                                  'stage': ('stage', 'vertex'), 'size': ('size', 44),
                                  'hash': ('sha256', '0'*64)}[mutation]
                    translated['products'][h][key] = value
                elif mutation == 'missing-product':
                    del translated['products'][h]
                elif mutation == 'tsv-size':
                    data = self.tsv.replace(b'\t40\t', b'\t44\t')
                    (args.translation_root/'products/results.tsv').write_bytes(data)
                    (args.data_root/'spirv/results.tsv').write_bytes(data)
                else:
                    # A syntactically valid token names a nonexistent binding.
                    data = self.tsv.replace(b'\t40\t\t', b'\t40\tcb3=s0b99\t')
                    (args.translation_root/'products/results.tsv').write_bytes(data)
                    (args.data_root/'spirv/results.tsv').write_bytes(data)
                translated_path.write_text(json.dumps(translated))
                self.reanchor_package(args)
                with self.assertRaisesRegex(ValueError, error):
                    checker.check(args)

    def test_symlinks_and_missing_products_fail_without_writes(self):
        code, _, _ = next(iter(self.inputs.values()))
        before = code.read_bytes()
        saved = code.with_suffix('.saved')
        code.rename(saved)
        code.symlink_to(saved)
        with self.assertRaises(ValueError):
            checker.selected_inputs(self.handoff, self.anchor)
        self.assertEqual(saved.read_bytes(), before)
        with self.assertRaises(OSError):
            checker.read(self.root / 'missing.spv', checker.MAX)

    def native_source(self):
        if os.environ.get('SHADER_NATIVE_SOURCE'):
            return Path(os.environ['SHADER_NATIVE_SOURCE'])
        common = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', '--git-common-dir'],
                                check=True, capture_output=True, text=True).stdout.strip()
        canonical = (ROOT / common).resolve().parent
        return canonical / '.local/orchestrate/2026-10-18-evening/native-current/source'

    def prepare_package(self, native):
        stage = self.root / 'accepted'
        products = stage / 'products'
        products.mkdir(parents=True)
        cache = self.root / 'data/spirv'
        cache.mkdir(parents=True)
        translated = {}
        for h, (_, _, kind) in self.inputs.items():
            data = module(kind)
            (products / (h+'.spv')).write_bytes(data)
            (cache / (h+'.spv')).write_bytes(data)
            translated[h] = dict(size=len(data), sha256=checker.sha256(data), validation_exit=0,
                                 stage='pixel' if kind == 'fragment' else kind)
        (products / 'results.tsv').write_bytes(self.tsv)
        (cache / 'results.tsv').write_bytes(self.tsv)
        translation = dict(status='translated-validated', products=translated,
                           input_manifest_sha256=self.index['manifest_sha256'])
        (stage / 'translation.json').write_text(json.dumps(translation))
        index = dict(files={str(p.relative_to(stage)): identity(p.read_bytes())
                            for p in stage.rglob('*') if p.is_file()})
        result_index = self.root / 'result-index.json'
        result_index.write_text(json.dumps(index))
        receipt = self.root / 'receipt.json'
        receipt.write_text(json.dumps(dict(state='translated-validated', exit_code=0,
            result_index_sha256=checker.sha256(result_index.read_bytes()),
            products={name: item for name, item in index['files'].items() if name.endswith('.spv')})))
        return argparse.Namespace(handoff=self.handoff, handoff_index_sha256=self.anchor,
            data_root=cache.parent, native_source=native, accepted_receipt=receipt,
            accepted_receipt_sha256=checker.sha256(receipt.read_bytes()), result_index=result_index,
            translation_root=stage, cxx='c++')

    def test_production_parser_subprocess_and_rejections(self):
        native = self.native_source()
        if not shutil.which('c++') or not (native / 'runtime/src/nvn/nvn_shaders.cpp').is_file():
            self.skipTest('set SHADER_NATIVE_SOURCE to a local production source tree and install c++')
        args = self.prepare_package(native)
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = checker.check(args)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(report['counts'], dict(vertex=1, fragment=1))
        self.assertEqual(report['runtime_consumption'], 'unmeasured')
        self.assertTrue(all(p['production_parser_exit'] == 0 for p in report['products']))
        h = next(iter(self.inputs))
        product = args.data_root / 'spirv' / (h+'.spv')
        original = product.read_bytes()
        product.unlink()
        with self.assertRaises(OSError):
            checker.check(args)
        product.write_bytes(original[:-1]+b'X')
        with self.assertRaises(ValueError):
            checker.check(args)
        # Invoke the same production adapter on deliberately malformed resources,
        # then a valid resource referring to a nonexistent reflected binding.
        product.write_bytes(original)
        nvn = native / 'runtime/src/nvn'
        adapter, exe = self.root / 'adapter.cpp', self.root / 'probe'
        adapter.write_text(checker.HARNESS)
        subprocess.run(['c++', '-std=c++17', '-DNX_SHADERS_STANDALONE', '-I', str(nvn),
                        str(adapter), str(nvn/'nvn_shaders.cpp'), str(nvn/'nvn_spirv_reflect.cpp'),
                        '-o', str(exe)], check=True, capture_output=True, timeout=90)
        code, ctrl, kind = self.inputs[h]
        tsv = self.root / 'bad.tsv'
        for resources in ('garbage', 'cb3=s0b99'):
            tsv.write_text('hash\tresources\n'+h+'\t'+resources+'\n')
            run = subprocess.run([str(exe), str(code), str(ctrl), str(product), str(tsv), h, kind],
                                 capture_output=True, timeout=15)
            self.assertEqual(run.returncode, 6, run.stderr)
        tsv.write_text('hash\tresources\n'+h+'\t\n')
        run = subprocess.run([str(exe), str(code), str(ctrl), str(product), str(tsv), h, 'fragment'],
                             capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 7)

    def test_accepted_index_rejects_tampering_missing_identity_and_unsafe_paths(self):
        args = self.prepare_package(self.root)
        receipt = json.loads(args.accepted_receipt.read_text())
        original = json.loads(args.result_index.read_text())
        for mutation in ('changed-output', 'missing-metadata', 'unsafe-path'):
            index = copy.deepcopy(original)
            if mutation == 'changed-output':
                index['files']['translation.json']['sha256'] = '0'*64
            elif mutation == 'missing-metadata':
                del index['files']['translation.json']
            else:
                index['files']['../outside'] = identity(b'')
            args.result_index.write_text(json.dumps(index))
            receipt['result_index_sha256'] = checker.sha256(args.result_index.read_bytes())
            args.accepted_receipt.write_text(json.dumps(receipt))
            digest = checker.sha256(args.accepted_receipt.read_bytes())
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                checker.accepted_products(args.accepted_receipt, digest, args.result_index,
                                          args.translation_root)

    def test_explicit_bulk_selected_inputs_and_no_legacy_bypass(self):
        selections = self.index['selection']['representatives']
        hashes = sorted(self.inputs)
        self.index.update(schema=2, mode='bulk-graphics',
            selection=dict(schema=2, mode='bulk-graphics', products=selections),
            runtime=dict(conflicted=[], requested=hashes+['f'*16], matched=hashes, completed=hashes,
                         unmatched=['f'*16], remaining_matched=[], log_sha256='a'*64,
                         plan_sha256='b'*64, source_sha256='c'*64))
        self.save_index()
        inputs, digest = checker.selected_inputs(self.handoff, self.anchor)
        self.assertEqual(inputs, self.inputs)
        huge = self.handoff/'oversized'
        with huge.open('wb') as stream:
            stream.truncate(checker.MAX+1)
        with self.assertRaisesRegex(ValueError, 'byte limit'):
            checker.selected_inputs(self.handoff, self.anchor)
        huge.unlink()
        args = self.prepare_package(self.root)
        # A legacy translation receipt cannot authorize a bulk handoff even if bytes match.
        with self.assertRaisesRegex(ValueError, 'explicit bulk'):
            checker.check(args)
        self.index.pop('mode')
        self.save_index()
        with self.assertRaises(ValueError):
            checker.selected_inputs(self.handoff, self.anchor)

    def test_bulk_over_four_selected_provenance_and_exact_result_set(self):
        selections = self.index['selection']['representatives']
        rows = list(r['manifest'] for r in self.index['by_code_sha1_16'].values())
        for n in range(4):
            wrapper = bytearray(graphics_fixture('vertex'))
            wrapper[24+0x758+0x38] = n+1
            wrapper = bytes(wrapper)
            code, ctrl, _ = checker.batch.inventory.graphics_pair(wrapper)
            h = hashlib.sha1(code).hexdigest()[:16]
            selected = dict(archive='extra.pkz', member='original.dat', index=n, stage='vertex',
                            wrapper_sha256=checker.sha256(wrapper), code_sha1_16=h)
            _, _, row = checker.batch.pair_row(wrapper, selected)
            rows.append(row)
            selections.append(selected)
            self.index['by_code_sha1_16'][h] = dict(manifest=row, wrapper_header_hex=wrapper[:24].hex(),
                code_sha256=checker.sha256(code), ctrl_sha256=checker.sha256(ctrl))
            (self.handoff/(h+'.code.bin')).write_bytes(code)
            (self.handoff/(h+'.ctrl.bin')).write_bytes(ctrl)
        manifest = checker.batch.manifest_bytes(rows)
        (self.handoff/'manifest.tsv').write_bytes(manifest)
        hashes = sorted(self.index['by_code_sha1_16'])
        self.index.update(schema=2, mode='bulk-graphics', manifest_sha256=checker.sha256(manifest),
            selection=dict(schema=2, mode='bulk-graphics', products=selections),
            runtime=dict(conflicted=[], requested=hashes, matched=hashes, completed=hashes, unmatched=[],
                         remaining_matched=[], log_sha256='a'*64, plan_sha256='b'*64, source_sha256='c'*64))
        self.save_index()
        inputs, _ = checker.selected_inputs(self.handoff, self.anchor)
        self.assertEqual(len(inputs), 6)
        tsv = ('hash\tstage\tstatus\tspv_bytes\tresources\n'+''.join(
            h+'\t'+stage+'\tok\t40\t\n' for h, (_,_,stage) in inputs.items())).encode()
        self.assertEqual(len(checker.result_rows(tsv, inputs)), 6)
        with self.assertRaises(ValueError):
            checker.result_rows(self.tsv, inputs)
        native = self.native_source()
        if shutil.which('c++') and (native/'runtime/src/nvn/nvn_shaders.cpp').is_file():
            self.inputs, self.tsv = inputs, tsv
            args = self.prepare_package(native)
            path = args.translation_root/'translation.json'
            translated = json.loads(path.read_text())
            translated.update(schema=2, mode='bulk-graphics', input_index_sha256=self.anchor)
            path.write_text(json.dumps(translated))
            result_index = json.loads(args.result_index.read_text())
            result_index['files']['translation.json'] = identity(path.read_bytes())
            args.result_index.write_text(json.dumps(result_index))
            accepted = json.loads(args.accepted_receipt.read_text())
            accepted['result_index_sha256'] = checker.sha256(args.result_index.read_bytes())
            args.accepted_receipt.write_text(json.dumps(accepted))
            args.accepted_receipt_sha256 = checker.sha256(args.accepted_receipt.read_bytes())
            report = checker.check(args)
            self.assertEqual(report['counts'], dict(vertex=5, fragment=1))
            self.assertEqual(len(report['products']), 6)
        self.index['schema'] = 1
        self.save_index()
        with self.assertRaises(ValueError):
            checker.selected_inputs(self.handoff, self.anchor)

    def test_cli_missing_inputs_nonzero_no_output_files(self):
        before = set(self.root.rglob('*'))
        run = subprocess.run([sys.executable, str(Path(checker.__file__)), '--data-root', str(self.root),
            '--handoff', str(self.handoff), '--native-source', str(self.root),
            '--accepted-receipt', str(self.root/'absent'), '--accepted-receipt-sha256', '0'*64,
            '--result-index', str(self.root/'absent-index'), '--translation-root', str(self.root),
            '--handoff-index-sha256', self.anchor], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(run.stdout, '')
        self.assertEqual(before, set(self.root.rglob('*')))


if __name__ == '__main__':
    unittest.main()
