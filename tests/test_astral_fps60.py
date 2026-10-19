"""Tests for tools/astral_fps60.py, the opt-in 60 fps patch of Astral Chain 1.0.0's main before the lift.

Synthetic NSOs only: a text segment that is all zeros except the original words at the five sites, compressed with
a small LZ4 encoder below. No game data is read.
"""
import hashlib
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import astral_fps60 as fps  # noqa: E402

TEXT_SIZE = 0x907C00
NAME = b'\x00\x00\x00\x00main.nss\x00'


def lz4_compress(data):
    """A valid but simple LZ4 block: runs of one repeated byte become offset-1 (overlapping) matches, the rest are
    literals; the block ends with literals as the format requires."""
    out, lit, i, n = bytearray(), bytearray(), 0, len(data)

    def length(v):
        while v >= 255:
            out.append(255)
            v -= 255
        out.append(v)

    def emit(literals, match):
        tok = (min(len(literals), 15) << 4) | (min(match - 4, 15) if match else 0)
        out.append(tok)
        if len(literals) >= 15:
            length(len(literals) - 15)
        out.extend(literals)
        if match:
            out.extend(b'\x01\x00')
            if match - 4 >= 15:
                length(match - 4 - 15)

    while i < n:
        r = 0
        if i > 0 or lit:
            prev = data[i - 1]
            while i + r < n - 5 and data[i + r] == prev:
                r += 1
        if r >= 4 and (i > 0):
            emit(lit, r)
            lit = bytearray()
            i += r
        else:
            lit.append(data[i])
            i += 1
    emit(lit, 0)
    return bytes(out)


def synthetic_text(words=None):
    text = bytearray(TEXT_SIZE)
    text[0:4] = b'\x01\x02\x03\x04'
    for addr, orig, _, _ in fps.SITES:
        struct.pack_into('<I', text, addr, (words or {}).get(addr, orig))
    return text


def synthetic_nso(build_id=fps.BUILD_ID, words=None, compress=True):
    segs = [(0, synthetic_text(words)), (TEXT_SIZE, bytearray(b'rodata' * 50)), (TEXT_SIZE + 0x1000, bytearray(b'd' * 77))]
    head = bytearray(fps.HEADER_SIZE)
    head[:4] = b'NSO0'
    struct.pack_into('<I', head, 0x0C, 0x3F if compress else 0x38)
    head[0x40:0x40 + len(build_id)] = build_id
    body = bytearray(NAME)
    for k, (mem, blob) in enumerate(segs):
        stored = lz4_compress(bytes(blob)) if compress else bytes(blob)
        struct.pack_into('<III', head, 0x10 + k * 0x10, fps.HEADER_SIZE + len(body), mem, len(blob))
        struct.pack_into('<I', head, 0x60 + k * 4, len(stored))
        head[0xA0 + k * 0x20:0xC0 + k * 0x20] = hashlib.sha256(blob).digest()
        body += stored
    return bytes(head + body), segs


class Lz4Test(unittest.TestCase):
    def test_hand_made_block(self):
        # 8 literals, a non-overlapping match (offset 8, length 4), then 1 literal.
        block = b'\x80abcdefgh\x08\x00' + b'\x10z'
        self.assertEqual(fps.lz4_block_decompress(block, 13), b'abcdefghabcdz')
        # an overlapping match repeats the last bytes: offset 2, length 7
        self.assertEqual(fps.lz4_block_decompress(b'\x23ab\x02\x00\x10!', 10), b'ababababa!')

    def test_long_lengths_round_trip(self):
        data = bytes(range(256)) * 3 + b'\0' * 5000 + b'xyz' * 40 + b'\7' * 300 + b'tail!'
        self.assertEqual(bytes(fps.lz4_block_decompress(lz4_compress(data), len(data))), data)

    def test_bad_blocks(self):
        with self.assertRaises(fps.PatchError):
            fps.lz4_block_decompress(b'\x10a\x05\x00', 10)  # offset beyond the output
        with self.assertRaises(fps.PatchError):
            fps.lz4_block_decompress(b'\x30abc', 4)  # wrong size


class PatchTest(unittest.TestCase):
    def test_patches_exactly_the_five_sites(self):
        raw, segs = synthetic_nso()
        out = fps.patch(raw)
        flags, got = fps.read_segments(out)
        self.assertEqual(flags & 7, 0)  # stored uncompressed
        self.assertEqual(flags & 0x38, 0x38)
        self.assertEqual(out[0x40:0x60], raw[0x40:0x60])
        self.assertEqual(out[fps.HEADER_SIZE:fps.HEADER_SIZE + len(NAME)], NAME)  # module name kept
        expected = bytearray(segs[0][1])
        for addr, _, new, _ in fps.SITES:
            struct.pack_into('<I', expected, addr, new)
        self.assertEqual(got[0], (0, expected))
        self.assertEqual(got[1:], segs[1:])
        for k, (_, blob) in enumerate(got):
            self.assertEqual(out[0xA0 + k * 0x20:0xC0 + k * 0x20], hashlib.sha256(blob).digest())
            self.assertEqual(struct.unpack_from('<I', out, 0x60 + k * 4)[0], len(blob))
        with self.assertRaisesRegex(fps.PatchError, 'already patched'):
            fps.check(out)

    def test_uncompressed_input(self):
        raw, _ = synthetic_nso(compress=False)
        _, got = fps.read_segments(fps.patch(raw))
        self.assertEqual(struct.unpack_from('<I', got[0][1], 0x907B0C)[0], 0x52A7E008)

    def test_refuses_another_build(self):
        raw, _ = synthetic_nso(build_id=bytes(16))
        with self.assertRaisesRegex(fps.PatchError, 'not Astral Chain 1.0.0'):
            fps.patch(raw)

    def test_refuses_a_changed_site_and_names_it(self):
        raw, _ = synthetic_nso(words={0x907B00: 0x1E201001})
        with self.assertRaisesRegex(fps.PatchError, r'0x907b00: found 0x1e201001, expected 0x1e2e1001'):
            fps.patch(raw)

    def test_refuses_non_nso(self):
        with self.assertRaisesRegex(fps.PatchError, 'not an NSO'):
            fps.patch(b'x' * 0x200)

    def test_site_table(self):
        addrs = [a for a, _, _, _ in fps.SITES]
        self.assertEqual(addrs, sorted(set(addrs)))
        self.assertTrue(all(a % 4 == 0 and o != n for a, o, n, _ in fps.SITES))


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fps.main([str(a) for a in argv])
        return rc, out.getvalue(), err.getvalue()

    def test_check_and_write(self):
        raw, _ = synthetic_nso()
        src = self.d / 'main'
        src.write_bytes(raw)
        self.assertEqual(self.run_cli('--check', src)[0], 0)
        rc, out, _ = self.run_cli(src, self.d / 'patched')
        self.assertEqual(rc, 0)
        self.assertIn('main+0x3df7c0: 0x320003e0 -> 0x52800000', out)
        self.assertEqual(src.read_bytes(), raw)  # input untouched
        self.assertEqual(self.run_cli('--check', self.d / 'patched')[0], 1)

    def test_mismatch_writes_nothing(self):
        raw, _ = synthetic_nso(words={0x3DF7C0: 0})
        (self.d / 'main').write_bytes(raw)
        rc, _, err = self.run_cli(self.d / 'main', self.d / 'patched')
        self.assertEqual(rc, 1)
        self.assertIn('0x3df7c0', err)
        self.assertFalse(os.path.exists(self.d / 'patched'))


if __name__ == '__main__':
    unittest.main()
