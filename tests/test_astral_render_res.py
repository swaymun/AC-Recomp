"""tools/astral_render_res.py and its tools/acr_build.py lift integration, on synthetic NSOs (no game bytes)."""
import io
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import astral_render_res as rr  # noqa: E402
import acr_build as acr  # noqa: E402
import test_acr_build as tab  # noqa: E402

TEXT_SIZE = 0x430000
BUILD_ID = bytes.fromhex(rr.BUILD_ID_100) + bytes(16)


def lz4_literals(data):
    """A valid raw LZ4 block holding data as one literal-only sequence."""
    n = len(data)
    out = bytearray([min(n, 15) << 4])
    if n >= 15:
        rest = n - 15
        while rest >= 255:
            out.append(255)
            rest -= 255
        out.append(rest)
    return bytes(out + data)


def make_text(words=None, size=TEXT_SIZE):
    text = bytearray(b'\x1f\x20\x03\xd5' * (size // 4))  # nop filler
    for off, orig, *_ in rr.SITES:
        struct.pack_into('<I', text, off, orig)
    struct.pack_into('<I', text, rr.MEMORY_SITE[0], rr.MEMORY_SITE[1])
    for off, w in (words or {}).items():
        struct.pack_into('<I', text, off, w)
    return bytes(text)


def make_nso(text, compressed=True, build_id=BUILD_ID):
    ro, data = b'RO' * 64, b'DATA' * 32
    segs = [text, ro, data]
    blobs = [lz4_literals(s) if compressed else s for s in segs]
    hdr = bytearray(0x100)
    hdr[:4] = b'NSO0'
    struct.pack_into('<I', hdr, 0x0C, 0x3F if compressed else 0)
    off, mem = 0x100, 0
    for i, (seg, blob) in enumerate(zip(segs, blobs)):
        struct.pack_into('<III', hdr, 0x10 + i * 0x10, off, mem, len(seg))
        struct.pack_into('<I', hdr, 0x60 + i * 4, len(blob))
        off += len(blob)
        mem += len(seg)
    hdr[0x40:0x60] = build_id
    return bytes(hdr) + b''.join(blobs)


class EncodingTest(unittest.TestCase):
    def test_words_match_known_encodings(self):
        # Community 1.0.1 patch words (little-endian bytes as written there).
        self.assertEqual(struct.pack('<I', rr.movz_w(8, 0x760)).hex(), '08ec8052')
        self.assertEqual(struct.pack('<I', rr.cmp_w(0, 0x760)).hex(), '1f801d71')
        self.assertEqual(struct.pack('<I', rr.movz_w(22, 0x426)).hex(), 'd6848052')
        stock_min = {0x40AF98: 1440, 0x40AFA4: 810}  # DRS minimum, locked to the maximum by the patch
        for off, orig, kind, which, reg, _ in rr.SITES:  # each original word re-encodes from its stock value
            value = stock_min.get(off, rr.STOCK[0] if which == 'w' else rr.STOCK[1])
            self.assertEqual(rr.encode(kind, reg, value), orig, hex(off))
        off, orig, reg, _ = rr.MEMORY_SITE
        self.assertEqual(rr.movz_w_lsl16(reg, rr.STOCK_MEMORY_MIB * 16), orig)

    def test_parse_res(self):
        self.assertEqual(rr.parse_res('2560x1440'), (2560, 1440))
        self.assertEqual(rr.parse_res(' 3200X1800 '), (3200, 1800))
        for bad in ('', '2560', '1280x720', '4096x2304', '2561x1440', 'axb'):
            with self.assertRaises(rr.PatchError, msg=bad):
                rr.parse_res(bad)

    def test_memory_budget(self):
        self.assertEqual(rr.default_memory_mib(1600, 900), rr.STOCK_MEMORY_MIB)
        self.assertEqual(rr.default_memory_mib(2560, 1440), 560)  # booted in the 1440p run
        self.assertNotIn(rr.MEMORY_SITE[0], [e[0] for e in rr.plan(1600, 900)])
        self.assertIn(rr.MEMORY_SITE[0], [e[0] for e in rr.plan(2560, 1440)])
        with self.assertRaises(rr.PatchError):
            rr.plan(2560, 1440, memory_mib=100)

    def test_pure_lz4_decoder_handles_matches_and_long_literals(self):
        block = bytes([0x44]) + b'abcd' + b'\x04\x00' + bytes([0x10]) + b'z'
        self.assertEqual(rr.lz4_block_decompress_pure(block, 13), b'abcdabcdabcdz')
        overlap = bytes([0x1F]) + b'a' + b'\x01\x00' + bytes([0x02, 0x10]) + b'b'  # run-length match, ml 4+15+2
        self.assertEqual(rr.lz4_block_decompress_pure(overlap, 23), b'a' * 22 + b'b')
        data = bytes(range(256)) * 3
        self.assertEqual(rr.lz4_block_decompress_pure(lz4_literals(data), len(data)), data)
        with self.assertRaises(rr.PatchError):
            rr.lz4_block_decompress_pure(lz4_literals(data), len(data) + 1)


class PatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_patches_only_the_listed_words_into_an_uncompressed_nso(self):
        text = make_text()
        src, dst = self.tmp / 'main', self.tmp / 'out/main'
        src.write_bytes(make_nso(text))
        ev = rr.patch_file(src, dst, 2560, 1440)
        self.assertEqual((ev['sites'], ev['graphics_memory_mib']), (len(rr.SITES) + 1, 560))
        out = dst.read_bytes()
        flags, segs = rr.read_nso(out)
        self.assertEqual(flags, 0)
        self.assertEqual(out[0x40:0x60], BUILD_ID)
        self.assertEqual((bytes(segs[1]), bytes(segs[2])), (b'RO' * 64, b'DATA' * 32))
        changed = {i for i in range(0, TEXT_SIZE, 4) if segs[0][i:i + 4] != text[i:i + 4]}
        self.assertEqual(changed, {s[0] for s in rr.SITES} | {rr.MEMORY_SITE[0]})
        word = lambda off: struct.unpack_from('<I', segs[0], off)[0]  # noqa: E731
        self.assertEqual(word(0x4093D4), rr.movz_w(9, 2560))
        self.assertEqual(word(0x4093E0), rr.movz_w(9, 1440))
        self.assertEqual(word(0x40AF74), rr.cmp_w(0, 2560))
        self.assertEqual(word(0x40AFA4), rr.movz_w(22, 1440))
        self.assertEqual(word(0x42E5F8), rr.movz_w(8, 1440))
        self.assertEqual(word(0x409EA0), rr.movz_w_lsl16(8, 560 * 16))
        # A patched NSO no longer holds the original words, so it is refused.
        with self.assertRaisesRegex(rr.PatchError, 'already patched'):
            rr.patch_file(dst, self.tmp / 'again', 1920, 1080)

    def test_refuses_on_any_mismatch_and_writes_nothing(self):
        src, dst = self.tmp / 'main', self.tmp / 'out/main'
        src.write_bytes(make_nso(make_text({0x42E5F0: 0x5280EC08}), compressed=False))  # already 0x760
        with self.assertRaisesRegex(rr.PatchError, '0x42e5f0: found 5280ec08, expected 5280c808'):
            rr.patch_file(src, dst, 2560, 1440)
        self.assertFalse(dst.exists())

    def test_refuses_other_build_ids(self):
        src = self.tmp / 'main'
        src.write_bytes(make_nso(make_text(), build_id=bytes.fromhex('4b159f0f7a360669738390ee8657b4f0') + bytes(16)))
        with self.assertRaisesRegex(rr.PatchError, 'not Astral Chain 1.0.0'):
            rr.patch_file(src, self.tmp / 'o', 2560, 1440)
        src.write_bytes(b'NOPE' + bytes(0x200))
        with self.assertRaises(rr.PatchError):
            rr.patch_file(src, self.tmp / 'o', 2560, 1440)

    def test_cli(self):
        src = self.tmp / 'main'
        src.write_bytes(make_nso(make_text()))
        with mock.patch('sys.stdout', io.StringIO()) as out:
            self.assertEqual(rr.main(['--in', str(src), '--out', str(self.tmp / 'o'), '--res', '1920x1080',
                                      '--graphics-memory-mib', '310']), 0)
        self.assertIn('"graphics_memory_mib": 310', out.getvalue())
        with mock.patch('sys.stderr', io.StringIO()):
            self.assertEqual(rr.main(['--in', str(src), '--out', str(self.tmp / 'o'), '--res', '100x100']), 1)


class BuildIntegrationTest(tab.Base):
    upstream = tab.StageTest.upstream
    fake_root = tab.StageTest.fake_root

    def lift(self, *extra, up=None, pin=None):
        ctx = self.ctx(*extra, root=self.root)
        ctx.upstream = up
        ctx.venv_python = lambda: Path(sys.executable)
        with mock.patch.object(acr, 'PIN', pin), \
                mock.patch('prepare_runtime.validate_inputs', return_value=({}, 'h')), \
                mock.patch('prepare_runtime.generated_evidence'):
            return ctx, acr.stage_lift(ctx)

    def setUp(self):
        super().setUp()
        self.up, self.pin = self.upstream()
        sqshl = tab.make_patch(self.up, 'recomp/emit_neon.py', 'MARK = "sqshl"\n')
        self.root = self.fake_root(self.up, {'astral-sqshl.patch': sqshl})
        (self.root / 'tools').mkdir()
        shutil.copy2(ROOT / 'tools/astral_render_res.py', self.root / 'tools/astral_render_res.py')
        exefs = self.tmp / 'out/.local/game-private/astral/exefs'
        exefs.mkdir(parents=True)
        self.nso = make_nso(make_text())
        (exefs / 'main').write_bytes(self.nso)
        (exefs / 'sdk').write_bytes(b'sdk')

    def test_render_res_lifts_the_patched_main_and_keeps_unchanged_files(self):
        ctx, ev = self.lift('--fps', '30', up=self.up, pin=self.pin)  # no 60 fps sites here
        self.assertNotIn('render_res', ev)
        main_cpp, sdk_cpp = ctx.gen / 'main/code_000.cpp', ctx.gen / 'sdk/code_000.cpp'
        self.assertEqual(main_cpp.read_text(), f'// main 0x4000000000 {len(self.nso)} sqshl\n')
        os.utime(sdk_cpp, (1, 1))
        ctx, ev = self.lift('--fps', '30', '--render-res', '2560x1440', up=self.up, pin=self.pin)
        patched = ctx.work / 'render-res/main'
        self.assertEqual(main_cpp.read_text(), f'// main 0x4000000000 {patched.stat().st_size} sqshl\n')
        self.assertNotEqual(patched.stat().st_size, len(self.nso))  # the uncompressed, patched copy was lifted
        self.assertEqual(sdk_cpp.stat().st_mtime, 1)  # identical output: untouched, so not recompiled
        self.assertEqual(ev['sdk']['unchanged_files_kept'], 2)
        self.assertEqual(ev['render_res']['resolution'], '2560x1440')
        self.assertEqual(ev['render_res']['graphics_memory_mib'], 560)
        self.assertFalse((ctx.gen / 'main.new').exists())

    def test_render_res_and_fps60_compose_on_one_copy(self):
        import astral_fps60
        words = {off: orig for off, orig, _, _ in astral_fps60.SITES}
        exefs = self.tmp / 'out/.local/game-private/astral/exefs'
        (exefs / 'main').write_bytes(make_nso(make_text(words, size=0x910000)))
        ctx, ev = self.lift('--fps', '60', '--render-res', '2560x1440', up=self.up, pin=self.pin)
        self.assertEqual((ev['fps'], ev['render_res']['resolution']), (60, '2560x1440'))
        _, segs = rr.read_nso((ctx.work / 'render-res/main').read_bytes())
        word = lambda off: struct.unpack_from('<I', segs[0], off)[0]  # noqa: E731
        for off, _, new, _ in astral_fps60.SITES:
            self.assertEqual(word(off), new, hex(off))
        self.assertEqual(word(0x4093D4), rr.movz_w(9, 2560))
        self.assertEqual(word(0x409EA0), rr.movz_w_lsl16(8, 560 * 16))
        main_cpp = ctx.gen / 'main/code_000.cpp'
        self.assertIn(str((ctx.work / 'render-res/main').stat().st_size), main_cpp.read_text())

    def test_render_res_applies_to_both_frame_rates(self):
        import astral_fps60
        words = {off: orig for off, orig, _, _ in astral_fps60.SITES}
        exefs = self.tmp / 'out/.local/game-private/astral/exefs'
        (exefs / 'main').write_bytes(make_nso(make_text(words, size=0x910000)))
        ctx, ev = self.lift('--render-res', '2560x1440', up=self.up, pin=self.pin)  # the default: both
        self.assertEqual((ev['fps'], ev['render_res']['resolution']), ('30+60', '2560x1440'))
        for copy, fps60 in (('render-res', False), ('render-res-60fps', True)):
            _, segs = rr.read_nso((ctx.work / copy / 'main').read_bytes())
            word = lambda off: struct.unpack_from('<I', segs[0], off)[0]  # noqa: E731
            for off, orig, new, _ in astral_fps60.SITES:
                self.assertEqual(word(off), new if fps60 else orig, (copy, hex(off)))
            self.assertEqual(word(0x4093D4), rr.movz_w(9, 2560), copy)
        self.assertIn(str((ctx.work / 'render-res-60fps/main').stat().st_size),
                      (ctx.gen_variant / 'main/code_000.cpp').read_text())

    def test_render_res_refusal_is_a_build_error(self):
        (self.tmp / 'out/.local/game-private/astral/exefs/main').write_bytes(make_nso(make_text({0x4093D4: 0})))
        with self.assertRaisesRegex(acr.BuildError, '--render-res: original words do not match'):
            self.lift('--render-res', '2560x1440', up=self.up, pin=self.pin)

    def test_stage_inputs_change_only_with_render_res(self):
        stock = acr.stage_inputs(self.ctx())['lift']
        self.assertNotIn('render-res', stock)
        a = acr.stage_inputs(self.ctx('--render-res', '2560x1440'))['lift']
        b = acr.stage_inputs(self.ctx('--render-res', '2560x1440', '--graphics-memory-mib', '600'))['lift']
        self.assertTrue(a.startswith(stock) and len({stock, a, b}) == 3)

    def test_cli_validation(self):
        self.assertEqual(self.args('--render-res', '2560X1440').render_res, '2560x1440')
        for extra in (['--render-res', '640x360'], ['--graphics-memory-mib', '400'],
                      ['--render-res', '2560x1440', '--graphics-memory-mib', '10']):
            with mock.patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
                self.args(*extra)


if __name__ == '__main__':
    unittest.main()
