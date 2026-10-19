"""Exhaustive valid-domain and invalid-input checks for byte addition."""

import unittest

from proof.saturating import saturating_add_u8


class SaturatingAddU8Tests(unittest.TestCase):
    def test_all_valid_pairs(self):
        for a in range(256):
            for b in range(256):
                self.assertEqual(saturating_add_u8(a, b), min(255, a + b), (a, b))

    def test_invalid_operands(self):
        invalid_values = (
            True, False, -1, 256, -(10**100), 10**100,
            0.0, 1.5, 255.0, float("inf"), float("nan"),
            1 + 0j, "0", b"0", None, [], {}, (), object(),
        )
        for invalid in invalid_values:
            for valid in (0, 127, 255):
                with self.subTest(invalid=repr(invalid), valid=valid, position="a"):
                    with self.assertRaises(ValueError):
                        saturating_add_u8(invalid, valid)
                with self.subTest(invalid=repr(invalid), valid=valid, position="b"):
                    with self.assertRaises(ValueError):
                        saturating_add_u8(valid, invalid)


if __name__ == "__main__":
    unittest.main()
