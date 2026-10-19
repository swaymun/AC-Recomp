"""Original synthetic bytes only; exercise the production PKZ/DAT parser and CLI."""
import dataclasses
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('astral_pkz', Path(__file__).resolve().parents[1] / 'tools/inventory_astral_pkz.py')
pkz = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pkz
SPEC.loader.exec_module(pkz)


def zstd_raw(payload):
    # Standard single-segment frame containing one final uncompressed block.
    if len(payload) < 256:
        header = bytes([0x20, len(payload)])
    else:
        header = b'\x60' + struct.pack('<H', len(payload) - 256)
    return b'\x28\xb5\x2f\xfd' + header + ((len(payload) << 3) | 1).to_bytes(3, 'little') + payload


def dat_fixture(name=b'original.vso', payload=b'VSO\0' + b'fixture' * 8):
    width = len(name) + 1
    names = 40
    sizes = names + 4 + width
    hashes = sizes + 4
    offset = hashes + 16
    out = bytearray(offset + len(payload))
    struct.pack_into('<4s6I', out, 0, b'DAT\0', 1, 32, 36, names, sizes, hashes)
    struct.pack_into('<I', out, 32, offset)
    out[36:40] = name.rsplit(b'.', 1)[1].ljust(4, b'\0')
    struct.pack_into('<I', out, names, width)
    out[names + 4:names + 4 + width] = name + b'\0'
    struct.pack_into('<I', out, sizes, len(payload))
    out[offset:] = payload
    return bytes(out)



def graphics_fixture(stage='vertex'):
    code = bytearray(0x100)
    struct.pack_into('<I', code, 0, 0x12345678)
    struct.pack_into('<I', code, 0x30, (1 if stage == 'vertex' else 5) << 10)
    struct.pack_into('<Q', code, 0x30 + 0x90 - 8, 0xe30000000007000f)
    ctrl = bytearray(0x758)
    struct.pack_into('<I', ctrl, 0, 0x98761234)
    struct.pack_into('<5I', ctrl, 0x6f8, 0x90, 0, 0x100, 0x100, 0x30)
    header = struct.pack('<4s5I', b'VSO\0' if stage == 'vertex' else b'PSO\0',
                         0x0f011411, len(ctrl), 24, len(code), 24 + len(ctrl))
    return header + ctrl + code


def pkz_fixture(name=b'original.dat', payload=None):
    payload = dat_fixture() if payload is None else payload
    compressed = zstd_raw(payload)
    names = b'ZStandard' + b'\0' * 7 + name + b'\0'
    offset = ((64 + len(names) + 63) // 64) * 64
    total = offset + len(compressed)
    out = bytearray(total)
    struct.pack_into('<4sIQIIQ', out, 0, b'pkzl', 0x10000, total, 1, 32, len(names))
    struct.pack_into('<4Q', out, 32, 16, len(payload), offset, len(compressed))
    out[64:64 + len(names)] = names
    out[offset:] = compressed
    return bytes(out)


def mutate(data, offset, fmt, value):
    out = bytearray(data)
    struct.pack_into(fmt, out, offset, value)
    return bytes(out)


class ParserTests(unittest.TestCase):
    def parse(self, data, limits=pkz.Limits()):
        return pkz.parse_pkz(io.BytesIO(data), len(data), limits)

    def test_valid_actual_parsers(self):
        raw = dat_fixture()
        archive = self.parse(pkz_fixture(payload=raw))
        self.assertEqual(archive['members'][0]['name'], 'original.dat')
        rows = pkz.parse_dat(raw)
        self.assertEqual(rows[0]['magic_hex'][:8], '56534f00')
        self.assertEqual(rows[0]['sha256'], pkz.sha256(raw[rows[0]['offset']:]))

    def test_pkz_header_table_and_payload_bounds(self):
        good = pkz_fixture()
        cases = [good[:12], good[:-1], mutate(good, 4, '<I', 2),
                 mutate(good, 16, '<I', 0), mutate(good, 16, '<I', 17000),
                 mutate(good, 20, '<I', 0), mutate(good, 20, '<I', len(good)),
                 mutate(good, 24, '<Q', 1 << 40), mutate(good, 32, '<Q', 1),
                 mutate(good, 32, '<Q', 1 << 40), mutate(good, 32, '<Q', 17),
                 mutate(good, 48, '<Q', 32),
                 mutate(good, 48, '<Q', len(good)), mutate(good, 56, '<Q', 1 << 40),
                 mutate(good, 40, '<Q', 1 << 40)]
        for data in cases:
            with self.subTest(data=data[:64]), self.assertRaises(pkz.Invalid):
                self.parse(data)
        with self.assertRaises(pkz.Invalid):
            self.parse(good, dataclasses.replace(pkz.Limits(), archive_bytes=100))
        out = bytearray(good)
        out[64:73] = b'UnknownXX'
        with self.assertRaisesRegex(pkz.Invalid, 'compression'):
            self.parse(out)

    def test_names_traversal_encoding_and_termination(self):
        for name in [b'../escape.dat', b'/absolute.dat', b'a//b.dat', b'a/./b.dat',
                     b'a\\b.dat', b'C:escape.dat', b'a\n.dat', b'\xff.dat', b'x' * 257]:
            with self.subTest(name=name), self.assertRaises(pkz.Invalid):
                self.parse(pkz_fixture(name=name))
        data = bytearray(pkz_fixture())
        data[64 + 16 + len(b'original.dat')] = ord('x')
        with self.assertRaisesRegex(pkz.Invalid, 'unterminated'):
            self.parse(data)

    def test_actual_archive_parser_rejects_duplicate_and_overlap(self):
        names = b'ZStandard' + b'\0' * 7 + b'first.dat\0second.dat\0'
        frame = zstd_raw(b'original')
        offset = 160
        data = bytearray(offset + 2 * len(frame))
        struct.pack_into('<4sIQIIQ', data, 0, b'pkzl', 0x10000, len(data), 2, 32, len(names))
        struct.pack_into('<4Q', data, 32, 16, 8, offset, len(frame))
        struct.pack_into('<4Q', data, 64, 26, 8, offset + len(frame), len(frame))
        data[96:96 + len(names)] = names
        data[offset:offset + len(frame)] = frame
        data[offset + len(frame):] = frame
        self.assertEqual(len(self.parse(data)['members']), 2)
        with self.assertRaisesRegex(pkz.Invalid, 'duplicate'):
            self.parse(mutate(data, 64, '<Q', 16))
        with self.assertRaisesRegex(pkz.Invalid, 'overlapping'):
            self.parse(mutate(data, 80, '<Q', offset))

    def test_overlap_is_rejected(self):
        with self.assertRaisesRegex(pkz.Invalid, 'overlapping'):
            pkz.disjoint([(32, 20), (48, 16)])
        pkz.disjoint([(32, 16), (48, 16), (0, 0)])

    def test_dat_limits_and_truncated_extents(self):
        good = dat_fixture()
        cases = [good[:20], mutate(good, 4, '<I', 17000), mutate(good, 8, '<I', 0),
                 mutate(good, 40, '<I', 1 << 30), mutate(good, 32, '<I', len(good)),
                 mutate(good, 24, '<I', 0), dat_fixture(name=b'../bad.vso')]
        for data in cases:
            with self.subTest(data=data[:48]), self.assertRaises(pkz.Invalid):
                pkz.parse_dat(data)

    def test_graphics_pair_manifest_and_rejected_boundaries(self):
        good = graphics_fixture()
        code, ctrl, manifest = pkz.graphics_pair(good)
        self.assertEqual((len(code), len(ctrl)), (0x100, 0x758))
        self.assertEqual(manifest.decode().splitlines()[0].split('\t'), pkz.MANIFEST_HEADER)
        self.assertEqual(manifest.decode().splitlines()[1].split('\t')[10],
                         pkz.hashlib.sha1(code).hexdigest()[:16])
        cases = [good[:-1], mutate(good, 0, '<I', 0x004f5343), mutate(good, 4, '<I', 0),
                 mutate(good, 8, '<I', 0x700), mutate(good, 12, '<I', 0),
                 mutate(good, 20, '<I', 0), mutate(good, 24, '<I', 0),
                 mutate(good, 24 + 0x704, '<I', 0x200),
                 mutate(good, 24 + 0x708, '<I', 0),
                 mutate(good, 24 + 0x6f8, '<I', 0x10000),
                 mutate(good, 24 + 0x758 + 0x30, '<I', 5 << 10),
                 mutate(good, len(good) - 4, '<I', 1)]
        for data in cases:
            with self.subTest(data=data[:24]), self.assertRaises(pkz.Invalid):
                pkz.graphics_pair(data)
        self.assertIn(b'pixel', pkz.graphics_pair(graphics_fixture('pixel'))[2])

    def test_zstd_compression_bounds_before_native_decode(self):
        raw = b'original synthetic input'
        encoded = zstd_raw(raw)
        pkz.zstd_envelope(encoded, len(raw), pkz.Limits())
        cases = [(encoded, len(raw) + 1, pkz.Limits()),
                 (encoded, len(raw), dataclasses.replace(pkz.Limits(), decoded_bytes=1)),
                 (encoded, len(raw), dataclasses.replace(pkz.Limits(), compressed_bytes=1)),
                 (encoded, len(raw), dataclasses.replace(pkz.Limits(), window_bytes=1)),
                 (encoded[:5], len(raw), pkz.Limits()),
                 (encoded, len(encoded) * 1024 + 1, pkz.Limits()),
                 (b'\x28\xb5\x2f\xfd\x00\xff\x01\x00\x00', 1, pkz.Limits()),
                 (b'\x28\xb5\x2f\xfd\x21\x01\x01\x01\x00\x00', 1, pkz.Limits())]
        for data, expected, limits in cases:
            with self.subTest(data=data), self.assertRaises(pkz.Invalid):
                pkz.zstd_envelope(data, expected, limits)

    def test_native_decompression_and_malformed_frames(self):
        if not pkz.ctypes.util.find_library('zstd'):
            self.skipTest('optional libzstd absent; envelope limits still tested')
        decoder = pkz.Zstd()
        raw = dat_fixture()
        encoded = zstd_raw(raw)
        self.assertEqual(decoder.decode(encoded, len(raw)), raw)
        for bad in [encoded[:-1], encoded + b'x', encoded + encoded,
                    encoded[:6] + b'\xff\xff\xff' + encoded[9:]]:
            with self.subTest(bad=bad[:10]), self.assertRaises(pkz.Invalid):
                decoder.decode(bad, len(raw))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        (self.repo / '.gitignore').write_text('.local/\n')
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()
        (self.inputs / 'original.pkz').write_bytes(pkz_fixture())

    def run_inventory(self, name='fresh', probes=(), limits=pkz.Limits()):
        return pkz.inventory(self.repo, self.inputs, self.repo / '.local' / name, probes, limits)

    def test_inventory_hashes_and_no_input_mutation(self):
        before = (self.inputs / 'original.pkz').read_bytes()
        report, receipt = self.run_inventory()
        self.assertEqual(report['status'], 'ok')
        self.assertEqual((report['archive_count'], report['member_count']), (1, 1))
        self.assertEqual(report['archives'][0]['sha256'], pkz.sha256(before))
        saved = self.repo / '.local/fresh/inventory.json'
        self.assertEqual(receipt['sha256'], pkz.sha256(saved.read_bytes()))
        self.assertIsNone(report['shader_code_control_pairs'])
        self.assertEqual(before, (self.inputs / 'original.pkz').read_bytes())
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(pkz.Invalid, 'fresh'):
            self.run_inventory()

    def test_explicit_bounded_probe_and_generated_output_names(self):
        if not pkz.ctypes.util.find_library('zstd'):
            self.skipTest('optional libzstd absent')
        report, _ = self.run_inventory(probes=['original.pkz::original.dat'])
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['probes'][0]['types'], {'.vso': 1})
        self.assertEqual(len(report['artifacts']), 3)
        for item in report['artifacts']:
            self.assertNotIn('original', item['path'])
            self.assertEqual(item['sha256'], pkz.sha256((self.repo / '.local/fresh' / item['path']).read_bytes()))

    def test_total_limits_and_missing_probe_leave_rejection_receipt(self):
        report, _ = self.run_inventory('small', limits=dataclasses.replace(pkz.Limits(), input_bytes=1))
        self.assertEqual(report['status'], 'rejected')
        report, _ = self.run_inventory('missing', probes=['original.pkz::missing.dat'])
        self.assertIn('not found', report['error'])
        report, _ = self.run_inventory('bomb', probes=['original.pkz::original.dat'],
                                       limits=dataclasses.replace(pkz.Limits(), total_decoded_bytes=1))
        self.assertIn('total decoded', report['error'])

    def test_output_confinement_tracked_and_unignored_paths(self):
        for output in [self.root / 'outside', self.repo / '.local/../outside', self.inputs / 'out']:
            with self.subTest(output=output), self.assertRaises(pkz.Invalid):
                pkz.fresh_output(self.repo, output, self.inputs)
        (self.repo / '.local').mkdir()
        (self.repo / '.local/tracked').write_text('original')
        subprocess.run(['git', '-C', str(self.repo), 'add', '-f', '.local/tracked'], check=True)
        with self.assertRaisesRegex(pkz.Invalid, 'tracked'):
            pkz.fresh_output(self.repo, self.repo / '.local/tracked', self.inputs)
        (self.repo / '.gitignore').write_text('')
        with self.assertRaisesRegex(pkz.Invalid, 'ignored'):
            self.run_inventory()

    def test_symlink_and_hardlink_inputs_and_outputs(self):
        (self.inputs / 'escape').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(pkz.Invalid, 'symlink'):
            self.run_inventory()
        (self.inputs / 'escape').unlink()
        (self.repo / '.local').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(pkz.Invalid, 'symlink'):
            self.run_inventory()
        (self.repo / '.local').unlink()
        pkz.os.link(self.inputs / 'original.pkz', self.inputs / 'other.pkz')
        report, _ = self.run_inventory()
        self.assertEqual(report['status'], 'rejected')
        self.assertIn('single-link', report['error'])

    def test_single_pair_export_and_unsupported_compute(self):
        if not pkz.ctypes.util.find_library('zstd'):
            self.skipTest('optional libzstd absent')
        (self.inputs / 'original.pkz').write_bytes(pkz_fixture(
            payload=dat_fixture(payload=graphics_fixture())))
        report, _ = pkz.inventory(self.repo, self.inputs, self.repo / '.local/pair',
                                  ['original.pkz::original.dat'],
                                  extract_pair='original.pkz::original.dat::0')
        self.assertEqual(report['status'], 'ok', report.get('error'))
        self.assertEqual(report['shader_code_control_pairs'], 1)
        self.assertTrue((self.repo / '.local/pair/manifest.tsv').is_file())
        with self.assertRaises(pkz.Invalid):
            pkz.inventory(self.repo, self.inputs, self.repo / '.local/bad-pair',
                          extract_pair='original.pkz::original.dat::0')
        bad = mutate(graphics_fixture(), 0, '<I', 0x004f5343)
        (self.inputs / 'original.pkz').write_bytes(pkz_fixture(payload=dat_fixture(payload=bad)))
        report, _ = pkz.inventory(self.repo, self.inputs, self.repo / '.local/compute',
                                  ['original.pkz::original.dat'],
                                  extract_pair='original.pkz::original.dat::0')
        self.assertEqual(report['status'], 'rejected')
        self.assertIn('compute', report['error'])
        self.assertFalse((self.repo / '.local/compute/manifest.tsv').exists())

    def test_malformed_archive_retains_hash(self):
        bad = pkz_fixture()[:-1]
        (self.inputs / 'original.pkz').write_bytes(bad)
        report, _ = self.run_inventory()
        self.assertEqual(report['status'], 'rejected')
        self.assertEqual(report['parsed_archives'], 0)
        self.assertEqual(report['archives'][0]['sha256'], pkz.sha256(bad))

    def test_cli_subprocess(self):
        command = [sys.executable, str(Path(pkz.__file__).resolve()), '--repo', str(self.repo),
                   '--input', str(self.inputs), '--output', str(self.repo / '.local/cli')]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'ok')
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
