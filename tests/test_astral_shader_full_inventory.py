"""Synthetic bytes only: whole-archive wrapper discovery, manifest, validation and assembly."""
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/astral_shader_full_inventory.py'
SPEC = importlib.util.spec_from_file_location('astral_shader_full_inventory', TOOL)
full = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = full
SPEC.loader.exec_module(full)
HAVE_ZSTD = True
try:
    full.pkz.Zstd()
except full.Invalid:
    HAVE_ZSTD = False


def zstd_raw(payload):
    # Standard single-segment frame holding raw (uncompressed) blocks of <= 128 KiB.
    if len(payload) < 256:
        header = bytes([0x20, len(payload)])
    elif len(payload) < 65536 + 256:
        header = b'\x60' + struct.pack('<H', len(payload) - 256)
    else:
        header = b'\xa0' + struct.pack('<I', len(payload))
    blocks = bytearray()
    chunks = [payload[i:i + (128 << 10)] for i in range(0, len(payload), 128 << 10)] or [b'']
    for i, chunk in enumerate(chunks):
        last = i == len(chunks) - 1
        blocks += ((len(chunk) << 3) | int(last)).to_bytes(3, 'little') + chunk
    return b'\x28\xb5\x2f\xfd' + header + bytes(blocks)


def wrapper(stage, program=b'', const=b'', tag=0x0f011411, workgroup=(64, 1, 1, 0), start=None,
            ctrl_tail=b''):
    """Original synthetic wrapper: header, control section, code block (no game bytes)."""
    graphics = stage != 'compute'
    start = (0x30 if graphics else 0) if start is None else start
    program = program or (b'\x11' * 0x40)
    end = start + len(program)
    const_off = (end + 255) & ~255
    size = (const_off + len(const) + 255) & ~255
    code = bytearray(size)
    if graphics:
        struct.pack_into('<I', code, 0, 0x12345678)
    code[start:end] = program
    if graphics:
        struct.pack_into('<I', code, start, ({'vertex': 1, 'fragment': 5}[stage] << 10) | 0x40)
    code[const_off:const_off + len(const)] = const
    ctrl = bytearray(0x758) + bytearray(ctrl_tail)
    struct.pack_into('<I', ctrl, 0, 0x98761234)
    struct.pack_into('<5I', ctrl, 0x6f8, len(program), len(const), const_off, size, start)
    struct.pack_into('<4I', ctrl, 0x748, *workgroup)
    magic = {'vertex': b'VSO\0', 'fragment': b'PSO\0', 'compute': b'CSO\0'}[stage]
    header = struct.pack('<4s5I', magic, tag, len(ctrl), 24, len(code), 24 + len(ctrl))
    return header + bytes(ctrl) + bytes(code), bytes(code), bytes(ctrl)


def dat(children):
    count = len(children)
    width = max(len(n) for n, _ in children) + 1
    offsets, extensions, names = 28, 28 + 4 * count, 28 + 8 * count
    sizes = names + 4 + width * count
    hashes = sizes + 4 * count
    cursor = (hashes + 16 + 15) & ~15
    out = bytearray(cursor)
    struct.pack_into('<4s6I', out, 0, b'DAT\0', count, offsets, extensions, names, sizes, hashes)
    struct.pack_into('<I', out, names, width)
    for i, (name, payload) in enumerate(children):
        struct.pack_into('<I', out, offsets + 4 * i, len(out))
        out[extensions + 4 * i:extensions + 4 * i + 4] = name.rsplit(b'.', 1)[1].ljust(4, b'\0')
        out[names + 4 + width * i:names + 4 + width * i + len(name)] = name
        struct.pack_into('<I', out, sizes + 4 * i, len(payload))
        out += payload + b'\0' * (-len(payload) % 16)
    return bytes(out)


def pkz(members):
    names = bytearray(b'ZStandard' + b'\0' * 7)
    name_offsets = []
    for name, _ in members:
        name_offsets.append(len(names))
        names += name + b'\0'
    table = 32
    data_off = (table + 32 * len(members) + len(names) + 63) & ~63
    frames = [zstd_raw(payload) for _, payload in members]
    out = bytearray(data_off)
    records = []
    for (name, payload), frame, no in zip(members, frames, name_offsets):
        records.append((no, len(payload), len(out), len(frame)))
        out += frame
    struct.pack_into('<4sIQIIQ', out, 0, b'pkzl', 0x10000, len(out), len(members), table, len(names))
    for i, record in enumerate(records):
        struct.pack_into('<4Q', out, table + 32 * i, *record)
    out[table + 32 * len(members):table + 32 * len(members) + len(names)] = names
    return bytes(out)


def key(code):
    return hashlib.sha1(code).hexdigest()[:16]


class WrapperTests(unittest.TestCase):
    def test_graphics_and_headerless_compute_extracted_exactly(self):
        for stage in ('vertex', 'fragment', 'compute'):
            blob, code, ctrl = wrapper(stage, const=b'\x07' * 12)
            got_stage, got_code, got_ctrl, info = full.parse_wrapper(b'pad!' + blob, 4)
            self.assertEqual((got_stage, got_code, got_ctrl), (stage, code, ctrl))
            self.assertEqual(info['start'], 0 if stage == 'compute' else 0x30)
            self.assertTrue(info['wonder_layout'])

    def test_compute_code_is_not_given_a_header(self):
        blob, code, _ = wrapper('compute', program=b'\x22' * 0x80)
        _, got, _, _ = full.parse_wrapper(blob, 0)
        self.assertEqual(got[:0x80], b'\x22' * 0x80)
        self.assertNotEqual(struct.unpack_from('<I', got)[0], 0x12345679)
        self.assertEqual(len(got), len(code))

    def test_rejections(self):
        blob = wrapper('vertex')[0]
        cases = {
            'unknown wrapper magic': b'XSO\0' + blob[4:],
            'wrapper extents': blob[:12] + struct.pack('<I', 28) + blob[16:],
            'code extent': blob[:-1],
            'control code length': wrapper('vertex')[0][:24 + 0x704] + b'\0\0\0\0' + blob[24 + 0x708:],
            'graphics program start': wrapper('vertex', start=0x40)[0],
            'compute program start': wrapper('compute', start=0x30)[0],
            'SPH stage': b'PSO\0' + blob[4:],
        }
        for reason, data in cases.items():
            with self.subTest(reason=reason), self.assertRaisesRegex(full.Invalid, reason):
                full.parse_wrapper(data, 0)

    def test_unknown_tag_is_extracted_and_reported(self):
        blob, code, _ = wrapper('vertex', tag=0xdeadbeef)
        _, got, _, info = full.parse_wrapper(blob, 0)
        self.assertEqual((got, info['tag']), (code, 0xdeadbeef))


class ScanTests(unittest.TestCase):
    def test_scan_finds_dat_children_nested_and_orphans(self):
        v, vcode, _ = wrapper('vertex')
        c, ccode, _ = wrapper('compute')
        inner = dat([(b'a.eff', b'junk' + c + b'tail')])
        member = dat([(b'one.vso', v), (b'nest.dat', inner),
                      (b'raw.bin', b'\0' * 24 + full.CTRL_MAGIC + b'\0' * 64)])
        found, stats = full.scan_member(member, '.dtt')
        self.assertEqual(sorted(key(f[1]) for f in found), sorted([key(vcode), key(ccode)]))
        self.assertEqual(stats['wrapper_location|.dtt/.vso exact'], 1)
        self.assertEqual(stats['wrapper_location|.dtt/.dat/.eff nested'], 1)
        orphans = [k for k in stats if k.startswith('orphan_ctrl_magic|.dtt|')]
        self.assertEqual(len(orphans), 1)

    def test_malformed_dat_is_reported_but_still_scanned(self):
        v, vcode, _ = wrapper('fragment')
        member = b'DAT\0' + b'\xff' * 24 + v
        found, stats = full.scan_member(member, '.dat')
        self.assertEqual([key(f[1]) for f in found], [key(vcode)])
        self.assertTrue(any(k.startswith('dat_parse_failure|.dat|') for k in stats))


@unittest.skipUnless(HAVE_ZSTD, 'libzstd unavailable')
class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        self.romfs = self.root / 'romfs'
        (self.romfs / 'sub').mkdir(parents=True)
        self.v, self.vcode, self.vctrl = wrapper('vertex')
        self.f, self.fcode, _ = wrapper('fragment', const=b'\x05' * 8)
        self.c, self.ccode, self.cctrl = wrapper('compute', workgroup=(64, 1, 1, 0))
        # Same compute code, different workgroup (translation-relevant) and different tail (not).
        self.c2 = wrapper('compute', workgroup=(32, 2, 1, 0))[0]
        self.c3 = wrapper('compute', workgroup=(64, 1, 1, 0), ctrl_tail=b'\x01' * 8)[0]
        (self.romfs / 'a.pkz').write_bytes(pkz([
            (b'x.dat', dat([(b'v.vso', self.v), (b'c.cso', self.c)])),
            (b'y.eff', b'EFF0' + self.f)]))
        (self.romfs / 'sub/b.pkz').write_bytes(pkz([
            (b'z.dtt', dat([(b'c.cso', self.c), (b'd.cso', self.c2), (b'e.cso', self.c3)]))]))

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([sys.executable, '-I', str(TOOL), *map(str, args)],
                              capture_output=True, text=True, env=env, timeout=120)

    def test_extract_manifest_matches_harness_columns_and_keys(self):
        out = self.root / 'extract'
        p = self.run_cli('extract', '--input', self.romfs, '--out', out, '--jobs', 2)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        report = json.loads(p.stdout)
        self.assertEqual(report['archives'], 2)
        self.assertEqual(report['members'], 3)
        self.assertEqual(report['wrappers'], dict(vertex=1, fragment=1, compute=4))
        self.assertEqual(report['distinct_by_stage'], dict(compute=1, fragment=1, vertex=1))
        self.assertEqual(report['keys_with_multiple_controls'], 1)
        self.assertEqual(report['keys_with_relevant_control_conflicts'], 1)
        with open(out / 'batch/manifest.tsv', newline='') as stream:
            rows = list(csv.reader(stream, delimiter='\t'))
        self.assertEqual(rows[0], full.MANIFEST_HEADER)
        by_key = {r[10]: r for r in rows[1:]}
        self.assertEqual(set(by_key), {key(self.vcode), key(self.fcode), key(self.ccode)})
        for code in (self.vcode, self.fcode, self.ccode):
            row = by_key[key(code)]
            data = (out / 'batch' / row[11]).read_bytes()
            self.assertEqual(data, code)
            self.assertEqual(hashlib.sha1(data).hexdigest()[:16], row[10])
        # Majority control wins (two identical relevant fields + one tail-only difference).
        chosen = (out / 'batch' / by_key[key(self.ccode)][12]).read_bytes()
        self.assertEqual(full.relevant(chosen), full.relevant(self.cctrl))
        self.assertEqual(by_key[key(self.ccode)][6], '0x0')
        variant = list(csv.reader((out / 'variants/1/manifest.tsv').read_text().splitlines(), delimiter='\t'))
        self.assertEqual(len(variant), 2)
        vctrl = (out / 'variants/1' / variant[1][12]).read_bytes()
        self.assertEqual(struct.unpack_from('<I', vctrl, 0x748)[0], 32)
        inventory = json.loads((out / 'inventory.json').read_text())
        self.assertIn('wrapper_location|.eff nested', inventory['stats'])
        self.assertNotEqual(self.run_cli('extract', '--input', self.romfs, '--out', out).returncode, 0)

    def make_products(self, out, keys, statuses, payload=b'\x03\x02\x23\x07'):
        out.mkdir()
        header = ['hash', 'group', 'stage', 'stages_using', 'status', 'ms', 'spv_bytes', 'resources',
                  'translator_messages', 'error', 'draw_time_queries']
        lines = ['\t'.join(header)]
        for k, (stage, status) in zip(keys, statuses):
            lines.append('\t'.join([k, '.', stage, '1', status, '1.0', '4', '', '', '', '']))
            if status in ('ok', 'ok-retry'):
                (out / (k + '.spv')).write_bytes(payload + k.encode())
        (out / 'results.tsv').write_text('\n'.join(lines) + '\n')

    def test_validate_and_assemble(self):
        extract_dir = self.root / 'extract'
        self.assertEqual(self.run_cli('extract', '--input', self.romfs, '--out', extract_dir).returncode, 0)
        kv, kf, kc = key(self.vcode), key(self.fcode), key(self.ccode)
        reference = self.root / 'ref'
        (reference / 'user').mkdir(parents=True)
        os.symlink('/nonexistent/extract', reference / 'extract')
        self.make_products(reference / 'spirv', [kv], [('vertex', 'ok')])
        (self.root / 'ref-receipt.json').write_text('{}')
        out = self.root / 'out'
        self.make_products(out, [kv, kf, kc], [('vertex', 'ok'), ('fragment', 'ok-retry'),
                                                ('compute', 'invalid')])
        dumps = self.root / 'dumps'
        dumps.mkdir()
        (dumps / ('code_%s.bin' % kv)).write_bytes(self.vcode)
        (dumps / ('ctrl_%s.bin' % kv)).write_bytes(self.vctrl)
        p = self.run_cli('validate', '--batch', extract_dir / 'batch', '--out', out,
                         '--reference', reference / 'spirv', '--dumps', dumps)
        report = json.loads(p.stdout)
        self.assertTrue(report['matches'])
        self.assertEqual(report['dump_control_checks']['ctrl_identical'], 1)
        self.assertEqual(report['statuses'], {'ok': 1, 'ok-retry': 1, 'invalid': 1})
        # A differing product is reported, never treated as a match.
        (out / (kv + '.spv')).write_bytes(b'\0\0\0\0')
        report = json.loads(self.run_cli('validate', '--batch', extract_dir / 'batch', '--out', out,
                                         '--reference', reference / 'spirv').stdout)
        self.assertFalse(report['matches'])
        self.assertEqual(report['different'][0]['key'], kv)
        dataset, receipt = self.root / 'new', self.root / 'new-receipt.json'
        p = self.run_cli('assemble', '--reference', reference, '--reference-receipt',
                         self.root / 'ref-receipt.json', '--out', out, '--dataset', dataset,
                         '--receipt', receipt, '--source', 's', '--translator', 't', '--validation', 'v')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        data = json.loads(receipt.read_text())
        self.assertEqual(set(data['added']), {kf})
        self.assertEqual(data['product_count'], 2)
        # Reference product kept even though the new run's differs.
        self.assertEqual((dataset / 'spirv' / (kv + '.spv')).read_bytes(),
                         (reference / 'spirv' / (kv + '.spv')).read_bytes())
        self.assertEqual(os.readlink(dataset / 'extract'), '/nonexistent/extract')
        results = (dataset / 'spirv/results.tsv').read_text()
        self.assertTrue(results.startswith((reference / 'spirv/results.tsv').read_text()))
        self.assertEqual(data['results_tsv_sha256'],
                         hashlib.sha256((dataset / 'spirv/results.tsv').read_bytes()).hexdigest())
        self.assertEqual(json.loads(p.stdout)['receipt_sha256'],
                         hashlib.sha256(receipt.read_bytes()).hexdigest())
        self.assertNotEqual(self.run_cli('assemble', '--reference', reference, '--reference-receipt',
                                         self.root / 'ref-receipt.json', '--out', out, '--dataset', dataset,
                                         '--receipt', receipt, '--source', 's', '--translator', 't',
                                         '--validation', 'v').returncode, 0)


if __name__ == '__main__':
    unittest.main()
