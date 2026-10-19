"""Synthetic binary contract tests: no dump, credentials, or runtime required."""

from array import array
from dataclasses import FrozenInstanceError
import struct
import unittest

from tools.nacp_metadata import NacpFormatError, parse_nacp


def fixture(flags=1, ratings=None):
    # Independently specify literal offsets and widths; do not import constants.
    data = bytearray(b'\xa5' * 16384)
    struct.pack_into('<I', data, 12336, flags)
    struct.pack_into('32B', data, 12352, *(range(32) if ratings is None else ratings))
    return data


class NacpMetadataTests(unittest.TestCase):
    def assert_safe_error(self, data, message):
        with self.assertRaises(NacpFormatError) as caught:
            parse_nacp(data)
        self.assertEqual(str(caught.exception), message)
        self.assertEqual(caught.exception.args, (message,))
        self.assertIsNone(caught.exception.__cause__)

    def test_exact_fields_ignore_adjacent_sentinels(self):
        result = parse_nacp(fixture())
        self.assertEqual(result.parental_flags, 1)
        self.assertEqual(len(result.ratings), 32)
        self.assertEqual(tuple(r.index for r in result.ratings), tuple(range(32)))
        self.assertEqual(tuple(r.encoded for r in result.ratings), tuple(range(32)))
        self.assertEqual(tuple(r.signed for r in result.ratings), tuple(range(32)))

    def test_little_endian_low_bit_and_zero(self):
        for flags in (0, 1):
            data = fixture(flags)
            self.assertEqual(data[12336:12340], bytes([flags, 0, 0, 0]))
            self.assertEqual(parse_nacp(data).parental_flags, flags)
        data = fixture()
        struct.pack_into('>I', data, 12336, 1)
        self.assert_safe_error(data, 'unsupported NACP parental flags')

    def test_every_unsupported_bit_in_full_u32_is_rejected(self):
        for bit in range(1, 32):
            for low in (0, 1):
                with self.subTest(bit=bit, low=low):
                    self.assert_safe_error(fixture((1 << bit) | low),
                                           'unsupported NACP parental flags')
        self.assert_safe_error(fixture(0xffffffff), 'unsupported NACP parental flags')

    def test_all_byte_encodings_at_all_32_positions(self):
        # Exhaustive signed boundaries, including every negative encoding and
        # every reserved position. Different bytes also detect reordering.
        for shift in range(256):
            values = [(shift + index) % 256 for index in range(32)]
            result = parse_nacp(fixture(ratings=values))
            for index, (rating, value) in enumerate(zip(result.ratings, values)):
                with self.subTest(shift=shift, index=index):
                    expected_signed = struct.unpack('b', bytes([value]))[0]
                    self.assertEqual((rating.index, rating.encoded, rating.signed),
                                     (index, value, expected_signed))
                    self.assertEqual(rating.position, 'defined' if index < 13 else 'reserved')
                    expected = ('reserved' if index >= 13 else
                                'unknown_negative' if expected_signed < 0 else
                                'uninterpreted_nonnegative')
                    self.assertEqual(rating.interpretation, expected)

    def test_no_missing_or_negative_default(self):
        self.assert_safe_error(None, 'unsupported NACP input type')
        self.assert_safe_error(b'', 'invalid NACP size')
        result = parse_nacp(fixture(0, [255] * 32))
        self.assertEqual(result.parental_flags, 0)
        self.assertTrue(all(r.encoded == 255 and r.signed == -1 for r in result.ratings))
        self.assertTrue(all(r.interpretation == 'unknown_negative' for r in result.ratings[:13]))
        self.assertTrue(all(r.interpretation == 'reserved' for r in result.ratings[13:]))

    def test_short_and_long_sizes(self):
        for size in (0, 1, 12336, 12340, 12352, 12384, 16383, 16385, 32768):
            for convert in (bytes, bytearray, memoryview):
                with self.subTest(size=size, convert=convert):
                    self.assert_safe_error(convert(b'X' * size), 'invalid NACP size')

    def test_supported_buffers_detach_from_mutation(self):
        expected = parse_nacp(bytes(fixture()))
        for convert in (bytes, bytearray, memoryview,
                        lambda b: memoryview(b).cast('b'),
                        lambda b: memoryview(b).cast('c'),
                        lambda b: memoryview(bytes(b))):
            original = fixture()
            supplied = convert(original)
            result = parse_nacp(supplied)
            original[:] = b'\xff' * len(original)
            if type(supplied) is bytearray:
                supplied[:] = b'\xff' * len(supplied)
            self.assertEqual(result, expected)
            if type(supplied) is memoryview:
                supplied.release()
                self.assertEqual(result, expected)

    def test_return_values_are_immutable(self):
        result = parse_nacp(fixture())
        with self.assertRaises(FrozenInstanceError):
            result.parental_flags = 0
        with self.assertRaises(FrozenInstanceError):
            result.ratings[0].encoded = 99
        with self.assertRaises(TypeError):
            result.ratings[0] = result.ratings[1]
        self.assertEqual(hash(result), hash(parse_nacp(fixture())))

    def test_unsupported_views_and_released_view(self):
        released = memoryview(fixture())
        released.release()
        for view in (released, memoryview(bytearray(32768))[::2],
                     memoryview(fixture()).cast('B', shape=[128, 128]),
                     memoryview(array('I', [0] * 4096))):
            self.assert_safe_error(view, 'unsupported NACP buffer layout')

    def test_types_and_errors_never_format_input(self):
        class Hostile:
            def __repr__(self):
                raise AssertionError('input repr accessed')
            def __bytes__(self):
                raise AssertionError('input bytes accessed')
        class BytesSubclass(bytes):
            pass
        for value in (Hostile(), BytesSubclass(fixture()), 'PRIVATE_SENTINEL',
                      16384, True, [0] * 16384, array('B', fixture()), {}):
            self.assert_safe_error(value, 'unsupported NACP input type')
        self.assert_safe_error(b'PRIVATE_SENTINEL', 'invalid NACP size')


if __name__ == '__main__':
    unittest.main()
