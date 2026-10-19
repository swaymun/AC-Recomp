"""Contract tests for the original-code alignment proof."""

import unittest

from proof.alignment import align_up


class AlignUpTests(unittest.TestCase):
    def test_zero_and_power_of_two_boundaries(self):
        for exponent in (0, 1, 2, 3, 8, 16, 32, 64, 127, 1024):
            alignment = 2 ** exponent
            for multiple in (0, 1, 2, 7, 100):
                boundary = multiple * alignment
                for value, expected in (
                    (boundary, boundary),
                    (boundary + 1, boundary + alignment),
                    (boundary + alignment - 1,
                     boundary if alignment == 1 else boundary + alignment),
                ):
                    with self.subTest(value=value, alignment=alignment):
                        self.assertEqual(align_up(value, alignment), expected)

    def test_large_integers(self):
        alignment = 2 ** 2048
        boundary = (2 ** 4096 + 17) * alignment
        self.assertEqual(align_up(boundary - 1, alignment), boundary)
        self.assertEqual(align_up(boundary, alignment), boundary)
        self.assertEqual(align_up(boundary + 1, alignment), boundary + alignment)
        self.assertEqual(align_up(2 ** 8192 + 1, 1), 2 ** 8192 + 1)

    def test_independent_divisibility_and_minimality(self):
        values = list(range(513)) + [2 ** 4096 - 1, 2 ** 4096, 2 ** 4096 + 1]
        for exponent in (*range(12), 128, 4097):
            alignment = 2 ** exponent
            for value in values:
                with self.subTest(value=value, alignment=alignment):
                    result = align_up(value, alignment)
                    self.assertIs(type(result), int)
                    self.assertEqual(result % alignment, 0)
                    self.assertGreaterEqual(result, value)
                    self.assertLess(result - alignment, value)

    def test_invalid_values(self):
        for value in (True, False, -1, -(2 ** 4096), 0.0, 1.5,
                      float("inf"), float("nan"), "1", None, [], {}, 1j, b"1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    align_up(value, 8)

    def test_invalid_alignments(self):
        for alignment in (True, False, 0, -1, -8, 3, 6, 7, 9,
                          2 ** 1024 - 1, 2 ** 1024 + 1,
                          1.0, 2.0, float("inf"), float("nan"),
                          "8", None, [], {}, 1j, b"8"):
            with self.subTest(alignment=alignment):
                with self.assertRaises(ValueError):
                    align_up(7, alignment)


if __name__ == "__main__":
    unittest.main()
