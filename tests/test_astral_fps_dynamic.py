"""Synthetic NSOs: dynamic step, cave layout, instruction/metadata guards and CLI refusal.

No game data, cloud calls, graphics, account tokens or owner saves are used.
"""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import astral_fps_dynamic as fps
import astral_fps60 as fixed


def synthetic_nso():
    text = bytearray(fps.TEXT_SIZE)
    for a, orig, _, _ in (*fixed.SITES, *fps.sites(cutscene_clock='carry')):
        struct.pack_into('<I', text, a, orig)
    for a, orig in (*fps.GUARDS, *fps.CUTSCENE_GUARDS):
        struct.pack_into('<I', text, a, orig)
    raw = bytearray(0x100)
    raw[:4] = b'NSO0'
    raw[0x40:0x50] = fps.BUILD_ID
    struct.pack_into('<I', raw, 0x0C, 0x38)
    # write_segments reads the original file offsets to preserve any pre-segment metadata.
    for k in range(3):
        struct.pack_into('<I', raw, 0x10 + k * 16, 0x100)
    return fixed.write_segments(raw, [(0, text), (fps.RODATA_START, bytearray(b'synthetic readonly')),
                                      (0xD1B000, bytearray(b'synthetic data'))])


class DynamicTests(unittest.TestCase):
    def test_optional_cutscene_carry_is_guarded_and_inside_lift_range(self):
        raw = synthetic_nso()
        p, cave = fps.dynamic_program('carry')
        _, segs = fixed.read_segments(fps.patch(raw, cutscene_clock='carry'))
        self.assertEqual(segs[0][1][fps.CAVE:], cave)
        self.assertEqual(len(segs[0][1]), p.pc)
        self.assertEqual([a for a, _, _, _ in fps.sites(cutscene_clock='carry')
                          if a not in {s[0] for s in fps.sites()}], [0x8AC3FC])
        # A changed transition/epilogue must not be accepted even when the hook still matches.
        _, segs = fixed.read_segments(raw)
        a, word = fps.CUTSCENE_GUARDS[-1]
        struct.pack_into('<I', segs[0][1], a, word ^ 1)
        damaged = fixed.write_segments(raw, segs)
        with self.assertRaisesRegex(fps.PatchError, hex(a)):
            fps.patch(damaged, cutscene_clock='carry')
        with self.assertRaisesRegex(fps.PatchError, 'requires a dynamic build'):
            fps.patch(raw, '30', cutscene_clock='carry')
        with self.assertRaisesRegex(fps.PatchError, 'unknown cutscene clock'):
            fps.patch(raw, cutscene_clock='audio')

    def test_dynamic_modes_exact_output_and_lift_range(self):
        raw = synthetic_nso()
        _, before = fps.check(raw)
        p, cave = fps.dynamic_program()
        for mode in fps.MODES[2:]:
            patched = fps.patch(raw, mode)
            flags, got = fixed.read_segments(patched)
            expected = before[0][1] + cave
            for a, _, new, _ in fps.sites(mode):
                struct.pack_into('<I', expected, a, new)
            self.assertEqual(got[0], (0, expected))
            self.assertEqual(got[1:], before[1:])
            self.assertEqual(flags & 7, 0)
            self.assertEqual(patched[0x40:0x60], raw[0x40:0x60])
            self.assertEqual(len(got[0][1]), p.pc)
            self.assertLessEqual(p.pc, fps.RODATA_START)
            for k, (_, blob) in enumerate(got):
                self.assertEqual(patched[0xA0 + k*32:0xC0 + k*32], hashlib.sha256(blob).digest())
                self.assertEqual(struct.unpack_from('<I', patched, 0x60 + k*4)[0], len(blob))
            with self.assertRaises(fps.PatchError):
                fps.patch(patched, mode)
        _, still = fps.check(raw)
        self.assertEqual(still, before)

    def test_legacy_modes_unchanged(self):
        raw = synthetic_nso()
        self.assertEqual(fps.patch(raw, '30'), raw)
        self.assertEqual(fps.patch(raw, '60-fixed'), fixed.patch(raw))
        with self.assertRaisesRegex(fps.PatchError, 'unknown frame-rate mode'):
            fps.patch(raw, '120')

    def test_build_word_guard_and_layout_fail_closed(self):
        raw = bytearray(synthetic_nso())
        raw[0x40] ^= 1
        with self.assertRaisesRegex(fps.PatchError, 'not Astral Chain 1.0.0'):
            fps.patch(raw)
        pristine = synthetic_nso()
        for a, expected in [(fps.sites()[10][0], fps.sites()[10][1]), fps.GUARDS[0]]:
            _, segs = fixed.read_segments(pristine)
            struct.pack_into('<I', segs[0][1], a, expected ^ 1)
            with self.assertRaisesRegex(fps.PatchError, hex(a)):
                fps.patch(fixed.write_segments(pristine, segs))
        _, segs = fixed.read_segments(pristine)
        segs[0][1].extend(bytes(4))
        with self.assertRaisesRegex(fps.PatchError, 'layout'):
            fps.patch(fixed.write_segments(pristine, segs))
        _, segs = fixed.read_segments(pristine)
        segs[1] = (fps.RODATA_START - 4, segs[1][1])
        with self.assertRaisesRegex(fps.PatchError, 'layout'):
            fps.patch(fixed.write_segments(pristine, segs))

    def test_relative_branches_and_leaf_lr(self):
        p, cave = fps.dynamic_program()
        for k, target, op, bits, shift in p.refs:
            pc = fps.CAVE + 4*k
            target = p.labels[target] if isinstance(target, str) else target
            word = struct.unpack_from('<I', cave, 4*k)[0]
            immediate = (word >> shift) & ((1 << bits) - 1)
            if immediate & (1 << (bits-1)):
                immediate -= 1 << bits
            self.assertEqual(pc + 4*immediate, target)
            self.assertEqual(word & ~(((1 << bits)-1) << shift), op)
        for a, _, kind in fps.HOOKS:
            if fps.leaf_hook(kind):
                start = p.labels[f'return{a:x}'] - fps.CAVE
                self.assertEqual(struct.unpack_from('<I', cave, start)[0], 0xF81F0FFE)
                self.assertEqual(struct.unpack_from('<I', cave, start+8)[0], 0xF84107FE)
        for pc, dest in [(0, 1), (0, 1 << 28), (0, -(1 << 28))]:
            with self.assertRaises(fps.PatchError):
                fps.branch(pc, dest)

    def test_partial_legacy_patch_is_refused_even_in_bypassed_code(self):
        raw = synthetic_nso()
        for address, _, replacement, _ in fixed.SITES:
            _, segments = fixed.read_segments(raw)
            struct.pack_into('<I', segments[0][1], address, replacement)
            mixed = fixed.write_segments(raw, segments)
            with self.subTest(address=hex(address)):
                with self.assertRaisesRegex(fps.PatchError, hex(address)):
                    fps.patch(mixed)

    def test_cap_modes_differ_only_at_present_requests(self):
        a, b = fps.sites('dynamic-60-cap'), fps.sites('dynamic-unlocked')
        self.assertEqual([x[0] for x, y in zip(a,b) if x != y], [0x9C54EC, 0x9D2BB4])
        self.assertEqual(len(set(x[0] for x in a)), len(a))
        self.assertTrue(all(x[0] % 4 == 0 and x[1] != x[2] for x in a))

    def test_cli_copy_refuses_aliases_and_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp)/'main', Path(tmp)/'out'
            raw = synthetic_nso(); src.write_bytes(raw)
            def run(*args):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return fps.main(list(map(str,args)))
            self.assertEqual(run('--check', src), 0)
            self.assertEqual(run('--mode','dynamic-unlocked', src,out), 0)
            self.assertEqual(src.read_bytes(),raw)
            self.assertEqual(run(src,src),1)
            out.unlink(); out.symlink_to(src)
            self.assertEqual(run(src,out),1)
            out.unlink(); out.hardlink_to(src)
            self.assertEqual(run(src,out),1)
            self.assertEqual(src.read_bytes(),raw)
            out.unlink(); src.write_bytes(bytes(0x100))
            self.assertEqual(run(src,out),1)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
