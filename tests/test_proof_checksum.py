"""Compare the proof checksum with the standard-library reference."""

import random
import unittest
import zlib

from proof.checksum import crc32


class CRC32Tests(unittest.TestCase):
    def assert_matches_reference(self, data):
        result = crc32(data)
        self.assertIs(type(result), int)
        self.assertGreaterEqual(result, 0)
        self.assertLessEqual(result, 0xFFFFFFFF)
        self.assertEqual(result, zlib.crc32(data))

    def test_empty(self):
        self.assertEqual(crc32(b""), 0)
        self.assert_matches_reference(b"")

    def test_standard_vector(self):
        self.assertEqual(crc32(b"123456789"), 0xCBF43926)
        self.assert_matches_reference(b"123456789")

    def test_all_binary_values(self):
        self.assert_matches_reference(bytes(range(256)))
        for value in range(256):
            with self.subTest(value=value):
                self.assert_matches_reference(bytes([value]))

    def test_deterministic_varied_samples(self):
        rng = random.Random(0xC32)
        for length in (1, 2, 3, 7, 8, 15, 16, 31, 32, 255, 256, 257, 1024, 4096):
            samples = (
                bytes(length),
                b"\xff" * length,
                bytes(rng.randrange(256) for _ in range(length)),
            )
            for index, data in enumerate(samples):
                with self.subTest(length=length, sample=index):
                    self.assert_matches_reference(data)

    def test_rejects_non_bytes(self):
        for data in (None, "", "123456789", bytearray(b"abc"), memoryview(b"abc"),
                     [], [1, 2, 3], (), {}, 0, 1.0, True, object()):
            with self.subTest(type=type(data).__name__, value=repr(data)):
                with self.assertRaises(TypeError):
                    crc32(data)


if __name__ == "__main__":
    unittest.main()
