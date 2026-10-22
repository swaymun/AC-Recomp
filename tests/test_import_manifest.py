"""Synthetic boundary tests; no keys, dumps, network or cloud resources."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

SPEC = importlib.util.spec_from_file_location('owned_import', Path(__file__).parents[1] / 'tools/import_owned_dump.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        subprocess.run(['git', '-C', str(self.repo), 'config', 'core.autocrlf', 'false'], check=True)
        (self.repo / '.gitignore').write_text('.local/\n')
        self.out = self.repo / '.local/game-private/sample'



class ManifestTests(FixtureCase):
    def test_private_boundary(self):
        self.assertEqual(m.private_path(self.repo, self.out), self.out)
        for path in [self.repo / 'public', self.repo / '.local/elsewhere', self.repo / '.local/game-private']:
            with self.assertRaises(m.ImportFailure):
                m.private_path(self.repo, path)

    def test_tracked_output_rejected_even_if_ignored(self):
        self.out.mkdir(parents=True)
        p = self.out / 'tracked'
        p.write_text('fixture')
        subprocess.run(['git', '-C', str(self.repo), 'add', '-f', str(p)], check=True)
        with self.assertRaises(m.ImportFailure):
            m.private_path(self.repo, self.out)

    def test_symlink_and_hardlink_rejected(self):
        self.out.parent.mkdir(parents=True)
        (self.repo / 'else').mkdir()
        self.out.symlink_to(self.repo / 'else', target_is_directory=True)
        with self.assertRaises(m.ImportFailure):
            m.private_path(self.repo, self.out)
        self.out.unlink()
        self.out.mkdir()
        p = self.out / 'a'
        p.write_bytes(b'a')
        (self.out / 'b').hardlink_to(p)
        with self.assertRaises(m.ImportFailure):
            m.secure_tree(self.out)

    def test_nsp_header_boundaries(self):
        p = self.repo / 'fixture.nsp'
        for blob in [b'', b'NSP0' + bytes(12), b'PFS0' + struct.pack('<III', 100, 0, 0)]:
            p.write_bytes(blob)
            with self.assertRaises(m.ImportFailure):
                m.validate_dump(p)
        p.write_bytes(b'PFS0' + struct.pack('<III', 1, 2, 0) + struct.pack('<QQII', 0, 1, 0, 0) + b'a\0x')
        self.assertEqual(m.validate_dump(p), p.stat().st_size)

    def test_journal_malformed_traversal_duplicate_crc_mismatch(self):
        self.out.mkdir(parents=True)
        p = self.out / 'analysis/main.bin'
        p.parent.mkdir()
        p.write_bytes(b'test')
        valid = 'exefs\t4\t%08x\tanalysis/main.bin\n' % zlib.crc32(b'test')
        self.assertEqual(len(m.parse_index(valid)), 1)
        for text in ['bad', valid + valid, valid.replace('analysis/main.bin', '../escape'), valid.replace('4\t', '-4\t'), valid.replace('d87f7e0c', 'notacrc')]:
            with self.assertRaises(m.ImportFailure):
                m.parse_index(text)
        m.verify_index(self.out, m.parse_index(valid))
        p.write_bytes(b'fail')
        with self.assertRaises(m.ImportFailure):
            m.verify_index(self.out, m.parse_index(valid))

    def test_identity_mismatch(self):
        identity = {'sha256': 'a' * 64, 'size': 12}
        m.check_identity(identity, identity)
        with self.assertRaises(m.ImportFailure):
            m.check_identity(identity, {'sha256': 'b' * 64, 'size': 12})
        with self.assertRaises(m.ImportFailure):
            m.check_title('0100000000001000', '0100000000002000')

    def test_lz4_bounds(self):
        self.assertEqual(m.lz4_block(b'\x40test', 4), b'test')
        self.assertEqual(m.lz4_block(b'\x11a\x01\x00', 6), b'aaaaaa')
        for data, size in [(b'\xf0', 1), (b'\x00\x00\x00', 4), (b'\x40test', 3)]:
            with self.assertRaises(m.ImportFailure):
                m.lz4_block(data, size)

    def test_nso_malformed_and_segment_mismatch(self):
        raw = bytearray(0x103)
        raw[:4] = b'NSO0'
        struct.pack_into('<III', raw, 0x10, 0x100, 0, 3)
        struct.pack_into('<III', raw, 0x20, 0, 3, 0)
        struct.pack_into('<III', raw, 0x30, 0, 3, 0)
        struct.pack_into('<I', raw, 0x60, 3)
        raw[0x100:] = b'abc'
        result = m.nso_inventory(bytes(raw), b'abc', 'extra')
        self.assertEqual(result['name'], 'extra')
        self.assertIsNone(result['imports'])
        for blob, flat in [(b'NSO0', b''), (bytes(raw), b'abd'), (bytes(raw[:-1]), b'abc')]:
            with self.assertRaises(m.ImportFailure):
                m.nso_inventory(blob, flat, 'extra')

    @staticmethod
    def symbol_fixture(with_hash=False):
        # Construct an NSO header independently, including distinct dynstr/dynsym
        # fields and a nonzero ro base. Offsets here follow the NSO file layout,
        # not constants or helpers imported from the implementation under test.
        header = bytearray(256)
        header[:4] = b'NSO0'
        struct.pack_into('<III', header, 0x10, 256, 0, 256)
        struct.pack_into('<III', header, 0x20, 512, 256, 256)
        struct.pack_into('<III', header, 0x30, 768, 512, 0)
        struct.pack_into('<II', header, 0x90, 128, 16)  # dynstr
        struct.pack_into('<II', header, 0x98, 32, 48)   # dynsym: two Elf64_Sym
        image = bytearray(512)
        struct.pack_into('<I', image, 4, 32)
        image[32:36] = b'MOD0'
        struct.pack_into('<i', image, 36, 32)
        entries = [(5, 384), (6, 288), (10, 16), (11, 24)]
        if with_hash:
            entries.append((4, 192))
            # Valid SysV hash: one bucket and two chains (including null symbol).
            struct.pack_into('<IIIII', image, 192, 1, 2, 1, 0, 0)
        entries.append((0, 0))
        for i, pair in enumerate(entries):
            struct.pack_into('<qQ', image, 64 + i * 16, *pair)
        image[384:393] = b'\0fixture\0'
        struct.pack_into('<IBBHQQ', image, 312, 1, 0x12, 0, 0, 0, 0)
        return header, image

    def test_independent_nso_header_import_fixture(self):
        header, image = self.symbol_fixture()
        result = m.nso_inventory(bytes(header + image), bytes(image), 'fixture')
        self.assertIsNone(result['imports_unavailable_reason'])
        self.assertEqual(result['imports'], [{'name': 'fixture', 'binding': 1, 'type': 2}])
        self.assertEqual(result['segments'][1]['memory_offset'], 256)

    def test_dynamic_import_symbols_and_malformed_offsets(self):
        header, image = self.symbol_fixture()
        struct.pack_into('<I', image, 312, 99)
        with self.assertRaisesRegex(m.ImportFailure, 'symbol_string_bounds'):
            m.imports_inventory(bytes(image), bytes(header))

    def test_symbol_extent_errors_never_fall_back_to_hash(self):
        for with_hash in (False, True):
            for offset, value, code in [
                    (0x9c, 1, 'invalid_symbol_size'),
                    (0x98, 33, 'symbol_extent_mismatch'),
                    (0x98, 232, 'symbol_extent_bounds'),
                    (0x9c, 0, 'invalid_symbol_extent'),
                    (0x94, 15, 'string_extent_mismatch')]:
                with self.subTest(hash=with_hash, offset=offset, value=value):
                    header, image = self.symbol_fixture(with_hash)
                    struct.pack_into('<I', header, offset, value)
                    with self.assertRaisesRegex(m.ImportFailure, code):
                        m.imports_inventory(bytes(image), bytes(header))

    def test_hash_fallback_only_when_nso_extent_absent(self):
        header, image = self.symbol_fixture(True)
        header[0x98:0xa0] = bytes(8)
        imports, reason = m.imports_inventory(bytes(image), bytes(header))
        self.assertIsNone(reason)
        self.assertEqual(len(imports), 1)
        # Hash bounds and nchain must be checked even if an NSO extent exists.
        for extent in (False, True):
            for count in (3, 100):
                header, image = self.symbol_fixture(True)
                if not extent:
                    header[0x98:0xa0] = bytes(8)
                struct.pack_into('<I', image, 196, count)
                with self.subTest(extent=extent, count=count):
                    if not extent and count == 3:
                        # This is structurally bounded, and has three valid symbols.
                        self.assertEqual(len(m.imports_inventory(bytes(image), bytes(header))[0]), 1)
                    else:
                        with self.assertRaises(m.ImportFailure):
                            m.imports_inventory(bytes(image), bytes(header))
        header, image = self.symbol_fixture()
        header[0x98:0xa0] = bytes(8)
        self.assertEqual(m.imports_inventory(bytes(image), bytes(header)),
                         (None, 'symbol_count_unavailable'))

    def test_present_dynamic_metadata_errors_rejected(self):
        for address, value in [(72, 510), (88, 511), (104, 513), (120, 1), (64, 12)]:
            header, image = self.symbol_fixture(True)
            struct.pack_into('<Q', image, address, value)
            with self.subTest(address=address):
                with self.assertRaises(m.ImportFailure):
                    m.imports_inventory(bytes(image), bytes(header))
        header, image = self.symbol_fixture(True)
        struct.pack_into('<I', header, 0x9c, 1)
        image[32:36] = bytes(4)
        with self.assertRaisesRegex(m.ImportFailure, 'invalid_symbol_size'):
            m.imports_inventory(bytes(image), bytes(header))

    def test_npdm_bounds(self):
        for raw in [b'', b'META' + bytes(0x7c)]:
            with self.assertRaises(m.ImportFailure):
                m.npdm_inventory(raw)
        raw = bytearray(0xc0)
        raw[:4] = b'META'
        struct.pack_into('<II', raw, 0x70, 0x80, 0x40)
        raw[0x80:0x84] = b'ACI0'
        struct.pack_into('<Q', raw, 0x90, 0x0100000000001000)
        self.assertEqual(m.npdm_inventory(raw)['title_id'], '0100000000001000')

    def test_process_output_never_logged(self):
        self.out.mkdir(parents=True)
        log = self.out / 'progress.jsonl'
        # A malicious/mock child can print arbitrary secret-like material. Discard all of it.
        rc = m.run_child([sys.executable, '-c', 'print("secret_fixture_value"); raise SystemExit(4)'], log, 'fixture')
        self.assertEqual(rc, 4)
        self.assertNotIn('secret_fixture_value', log.read_text())
        self.assertIn('exit_code', log.read_text())

    def test_git_reference_mismatch(self):
        with self.assertRaises(m.ImportFailure):
            m.validate_reference(self.repo)


class IntegrationTests(FixtureCase):
    def test_reference_source_clean_and_modified(self):
        from unittest.mock import patch
        source = self.repo / m.SOURCE
        source.mkdir(parents=True)
        for name in m.SOURCES:
            (source / name).write_text('// synthetic fixture\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@invalid', 'commit', '-qm', 'fixture'], check=True)
        pin = m.git(self.repo, 'rev-parse', 'HEAD').decode().strip()
        with patch.object(m, 'PIN', pin):
            self.assertEqual(len(m.validate_reference(self.repo)), len(m.SOURCES))
            (source / m.SOURCES[0]).write_text('// modified\n')
            with self.assertRaises(m.ImportFailure):
                m.validate_reference(self.repo)

    def test_fresh_import_reuse_and_input_change(self):
        from argparse import Namespace
        from unittest.mock import patch
        dump = self.repo / 'fixture.nsp'
        dump.write_bytes(b'PFS0' + struct.pack('<III', 1, 2, 0) + struct.pack('<QQII', 0, 1, 0, 0) + b'a\0x')
        key = self.repo / 'synthetic.keys'
        key.write_text('synthetic placeholder; never read by wrapper')
        mock_tool = self.repo / 'mock_importer.py'
        mock_tool.write_text('''#!/usr/bin/env python3
import sys, struct, pathlib, zlib
out = pathlib.Path(sys.argv[sys.argv.index('--out')+1])
with (out / '.wrapper/invocations').open('a') as f:
    f.write(('verify' if '--verify' in sys.argv else 'extract') + '\\n')
if '--verify' in sys.argv:
    sys.exit(0)
for p in ['exefs','analysis','extract/romfs','.import']:
    (out/p).mkdir(parents=True, exist_ok=True)
raw=bytearray(0x103); raw[:4]=b'NSO0'
struct.pack_into('<III',raw,0x10,0x100,0,3)
for off in (0x20,0x30): struct.pack_into('<III',raw,off,0,3,0)
raw[0x100:]=b'abc'
(out/'exefs/main').write_bytes(raw)
npdm=bytearray(0xc0); npdm[:4]=b'META'; npdm[0x80:0x84]=b'ACI0'
struct.pack_into('<II',npdm,0x70,0x80,0x40)
struct.pack_into('<Q',npdm,0x90,0x0100000000001000)
files={'analysis/main.bin':b'abc','analysis/main.npdm':npdm,'extract/romfs/fixture.pkz':b'fixture'}
rows=[]
for path,blob in files.items():
    (out/path).write_bytes(blob)
    rows.append('%s\\t%d\\t%08x\\t%s\\n'%('exefs' if path.startswith('analysis/') else 'romfs',len(blob),zlib.crc32(blob),path))
for name in ('index.tsv','journal.tsv'):
    (out/'.import'/name).write_text(''.join(rows))
source='0100000000001000 fixture.nsp/fixture.nca 1 -'
(out/'.import/source.txt').write_text(source+'\\n')
(out/'.import/complete').write_text(source+'\\n1 romfs files, 7 bytes\\n')
''')
        mock_tool.chmod(0o700)
        args = Namespace(repo=self.repo, out=self.out, reference=self.repo, dump=dump,
                         prod_keys=key, title_keys=None, expected_title=None, expected_size=None,
                         expected_sha256=None, adopt_state=None, adopt_tool=None, adopt_log=None)
        def build(ref, out, log):
            mock_tool.chmod(0o700)
            return mock_tool, {'revision': m.PIN, 'fixture': True}
        run_child = m.run_child
        def run_fixture(command, log, phase, **kw):
            # Windows does not execute Python shebangs through CreateProcess.
            if command[0] == str(mock_tool):
                command = [sys.executable, *command]
            return run_child(command, log, phase, **kw)
        with patch.object(m, 'build_importer', build), patch.object(m, 'run_child', run_fixture):
            m.execute(args)
            manifest = json.loads((self.out / '.wrapper/manifest.json').read_text())
            self.assertEqual(manifest['title_id'], '0100000000001000')
            self.assertEqual(manifest['modules'][0]['name'], 'main')
            m.execute(args)
            invocations = (self.out / '.wrapper/invocations').read_text().splitlines()
            self.assertEqual(invocations, ['extract', 'verify', 'verify'])
            dump.write_bytes(dump.read_bytes()[:-1] + b'y')
            with self.assertRaisesRegex(m.ImportFailure, 'dump_identity_mismatch'):
                m.execute(args)

    def test_journal_last_revision_and_index_duplicates(self):
        text = 'exefs\t1\t00000000\tanalysis/main.bin\nexefs\t2\t00000001\tanalysis/main.bin\n'
        self.assertEqual(m.parse_index(text, allow_revisions=True)['analysis/main.bin']['size'], 2)
        with self.assertRaises(m.ImportFailure):
            m.parse_index(text)


if __name__ == '__main__':
    unittest.main()
