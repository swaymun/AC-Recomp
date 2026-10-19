"""Synthetic, independently laid-out CNMT bytes; no game data or file I/O."""

from array import array
from dataclasses import FrozenInstanceError
import random
import struct
import unittest

from tools.cnmt_metadata import (
    APPLICATION_15_16, CnmtFormatError, NCM_CONTROL, NCM_PROGRAM, parse_cnmt,
)


# Deliberately literal offsets/widths rather than parser helpers/constants.
def content(seed=1, kind=1, offset=0, size=0x9876543210, attr=0):
    digest = seed.to_bytes(16, "little") + bytes(range(16))
    return (digest + digest[:16] + size.to_bytes(5, "little")
            + bytes((attr, kind, offset)))


def package(entries=(), metadata=(), digest=bytes(range(32))):
    header = bytearray(32)
    struct.pack_into("<QI", header, 0, 0x8877665544332211, 0xC4B3A291)
    header[12] = 0x80
    struct.pack_into("<HHH", header, 14, 16, len(entries), len(metadata))
    struct.pack_into("<I", header, 24, 0xD8C7B6A5)
    extended = struct.pack("<QII", 0xFEDCBA9876543210, 0xF4E3D2C1, 0xB4A39281)
    return bytes(header) + extended + b"".join(entries) + b"".join(metadata) + digest


def decode(data):
    return parse_cnmt(data, layout=APPLICATION_15_16)


class CnmtMetadataTests(unittest.TestCase):
    def assert_error(self, data, message):
        with self.assertRaises(CnmtFormatError) as caught:
            decode(data)
        self.assertEqual(str(caught.exception), message)

    def test_wide_little_endian_fields_and_complete_content(self):
        raw = package((content(), content(2, 3, 0xFE, 0x0123456789)))
        result = decode(raw)
        self.assertEqual(result.application_id, 0x8877665544332211)
        self.assertEqual(result.version, 0xC4B3A291)
        self.assertEqual(result.metadata_type, 0x80)
        self.assertEqual(result.patch_id, 0xFEDCBA9876543210)
        self.assertEqual(result.required_download_system_version, 0xD8C7B6A5)
        self.assertEqual(result.required_system_version, 0xF4E3D2C1)
        self.assertEqual(result.required_application_version, 0xB4A39281)
        self.assertEqual(result.layout, APPLICATION_15_16)
        first, second = result.contents
        self.assertEqual(first.expected_sha256, bytes.fromhex("01" + "00" * 15) + bytes(range(16)))
        self.assertEqual(first.content_id, bytes.fromhex("01" + "00" * 15))
        self.assertEqual(first.byte_size, 0x9876543210)
        self.assertEqual(first.attributes, 0)
        self.assertEqual(first.content_type, 1)
        self.assertEqual(second.content_type, 3)
        self.assertEqual(second.id_offset, 254)
        self.assertEqual(second.byte_size, 0x0123456789)

    def test_ncm_types_are_not_nca_types(self):
        self.assertEqual((NCM_PROGRAM, NCM_CONTROL), (1, 3))
        result = decode(package(tuple(content(i + 1, i, 255) for i in range(7))))
        self.assertEqual(tuple(c.content_type for c in result.contents), tuple(range(7)))
        self.assertEqual(result.contents[0].content_type, 0)  # NCM Meta, not Program.
        self.assertEqual(result.contents[2].content_type, 2)  # NCM Data, not Control.

    def test_zero_contents_is_decoding_without_association(self):
        result = decode(package())
        self.assertEqual(result.contents, ())
        self.assertEqual(result.unverified_digest, bytes(range(32)))

    def test_no_selection_or_ordering_assumption(self):
        entries = (content(1, 3, 8), content(2, 1, 9), content(3, 3, 7), content(4, 1, 0))
        result = decode(package(entries))
        self.assertEqual(tuple((c.content_type, c.id_offset) for c in result.contents),
                         ((3, 8), (1, 9), (3, 7), (1, 0)))

    def test_size40_limits_and_each_byte_significance(self):
        for size in (0, 1, 0xFF, 0x100, 1 << 16, 1 << 24, 1 << 32,
                     0xFFFFFFFFFF):
            with self.subTest(size=size):
                self.assertEqual(decode(package((content(size=size),))).contents[0].byte_size, size)

    def test_layout_is_explicit_no_firmware_autodetection(self):
        for layout in (None, "", "legacy-size48", "application-17", 1, b"modern"):
            with self.subTest(layout=layout), self.assertRaises(CnmtFormatError) as caught:
                parse_cnmt(package(), layout=layout)
            self.assertEqual(str(caught.exception), "unsupported CNMT layout")
        with self.assertRaises(TypeError):
            parse_cnmt(package())
        # An old u48 with high byte 1 overlaps a modern nonzero attribute.
        raw = bytearray(package((content(),)))
        raw[48 + 53] = 1
        self.assert_error(raw, "unsupported CNMT content attributes")
        # With that byte zero the encodings are indistinguishable; the caller's
        # external layout assertion is required even for apparently valid bytes.
        raw[48 + 53] = 0
        self.assertEqual(decode(raw).contents[0].byte_size, 0x9876543210)

    def test_all_unsupported_metadata_types(self):
        for kind in range(256):
            if kind == 0x80:
                continue
            raw = bytearray(package())
            raw[12] = kind
            self.assert_error(raw, "unsupported CNMT metadata type")

    def test_extended_header_size_exact(self):
        for size in (0, 1, 15, 17, 24, 32, 0xFFFF):
            raw = bytearray(package())
            struct.pack_into("<H", raw, 14, size)
            self.assert_error(raw, "unsupported CNMT extended header")

    def test_every_reserved_header_byte_and_platform(self):
        for position in (13, 21, 22, 23, 28, 29, 30, 31):
            for value in (1, 128, 255):
                raw = bytearray(package())
                raw[position] = value
                self.assert_error(raw, "unsupported CNMT header encoding")

    def test_metadata_attribute_mask(self):
        for value in range(256):
            raw = bytearray(package())
            raw[20] = value
            if value < 8:
                self.assertEqual(decode(raw).metadata_attributes, value)
            else:
                self.assert_error(raw, "unsupported CNMT metadata attributes")

    def test_every_unsupported_content_attribute(self):
        for value in range(1, 256):
            self.assert_error(package((content(attr=value),)),
                              "unsupported CNMT content attributes")

    def test_every_unsupported_content_type(self):
        for value in range(7, 256):
            self.assert_error(package((content(kind=value),)), "unsupported CNMT content type")

    def test_zero_application_id_rejected_without_other_title_assumptions(self):
        raw = bytearray(package())
        raw[:8] = bytes(8)
        self.assert_error(raw, "invalid CNMT application identity")
        for value in (1, (1 << 64) - 1):
            struct.pack_into("<Q", raw, 0, value)
            self.assertEqual(decode(raw).application_id, value)

    def test_every_truncation_across_all_supported_boundaries(self):
        raw = package((content(), content(2, 3)))
        # Every prefix, including header, extended header, every entry byte and
        # digest byte. None may consume the digest as missing table bytes.
        for length in range(len(raw)):
            with self.subTest(length=length):
                self.assert_error(raw[:length], "invalid CNMT extent")

    def test_trailing_junk_including_full_extra_entry(self):
        raw = package((content(),))
        for suffix in (b"\0", b"secret-report", bytes(16), bytes(32), content(2)):
            self.assert_error(raw + suffix, "invalid CNMT extent")

    def test_declared_counts_do_not_wrap_or_skip_bytes(self):
        for field in (16, 18):
            for count in (1, 255, 256, 0x8000, 0xFFFF):
                raw = bytearray(package())
                struct.pack_into("<H", raw, field, count)
                self.assert_error(raw, "invalid CNMT extent")
        raw = bytearray(package((content(), content(2, 3))))
        for count in (0, 1, 3, 0xFFFF):
            struct.pack_into("<H", raw, 16, count)
            self.assert_error(raw, "invalid CNMT extent")

    def test_metadata_table_boundary_is_checked_but_application_use_unsupported(self):
        # ContentMetaInfo: u64 ID, u32 version, u8 type, u8 attr, 2 reserved.
        meta = struct.pack("<QIBB2s", 0xF1E2D3C4B5A69788, 0xA1B2C3D4, 1, 0, bytes(2))
        for count in (1, 2, 257):
            raw = package((content(),), (meta,) * count)
            self.assert_error(raw, "unsupported CNMT Application metadata table")
            start = 48 + 56
            for end in range(start, len(raw)):
                self.assert_error(raw[:end], "invalid CNMT extent")
            self.assert_error(raw + b"\0", "invalid CNMT extent")

    def test_counts_use_both_bytes_and_no_tiny_fixture_limit(self):
        entries = tuple(content(1 + kind * 256 + offset, kind, offset)
                        for kind in range(7) for offset in range(256))
        result = decode(package(entries))
        self.assertEqual(len(result.contents), 1792)
        self.assertEqual(result.contents[-1].id_offset, 255)
        # Maximum encoded count gets full extent validation, not u8 truncation
        # or an invented size cap; repeated entries then fail identity checks.
        raw = package((content(),) * 65535)
        self.assert_error(raw, "duplicate or conflicting CNMT content identity")
        self.assert_error(raw[:-1], "invalid CNMT extent")

    def test_duplicate_and_conflicting_content_ids(self):
        for second in (content(), content(kind=3), content(offset=1), content(size=7)):
            self.assert_error(package((content(), second)),
                              "duplicate or conflicting CNMT content identity")
        second = bytearray(content(kind=3))
        second[31] ^= 1  # Same truncated ID, different full expected hash.
        self.assert_error(package((content(), second)),
                          "duplicate or conflicting CNMT content identity")

    def test_conflicting_type_offset_lookup_identity(self):
        self.assert_error(package((content(), content(2))),
                          "duplicate or conflicting CNMT content identity")
        self.assertEqual(len(decode(package((content(), content(2, offset=1)))).contents), 2)

    def test_each_content_id_byte_must_match_expected_hash_prefix(self):
        for index in range(16):
            entry = bytearray(content())
            entry[32 + index] ^= 0x80
            self.assert_error(package((entry,)), "inconsistent CNMT content identity")

    def test_trailing_digest_is_preserved_not_verified(self):
        for digest in (bytes(32), bytes([255]) * 32, bytes(reversed(range(32)))):
            self.assertEqual(decode(package((content(),), digest=digest)).unverified_digest, digest)

    def test_buffer_inputs_and_detached_immutable_snapshot(self):
        raw = package((content(),))
        inputs = (raw, bytearray(raw), memoryview(raw), memoryview(bytearray(raw)),
                  memoryview(array("b", raw)), memoryview(raw).cast("c"))
        expected = decode(raw)
        for value in inputs:
            self.assertEqual(decode(value), expected)
        mutable = bytearray(raw)
        view = memoryview(mutable)
        result = decode(view)
        mutable[:] = bytes(len(mutable))
        view.release()
        self.assertEqual(result, expected)
        self.assertIsInstance(result.contents, tuple)
        for target, field, value in ((result, "version", 0),
                                     (result.contents[0], "byte_size", 0)):
            with self.assertRaises((FrozenInstanceError, AttributeError)):
                setattr(target, field, value)
            self.assertFalse(hasattr(target, "__dict__"))
        self.assertIs(type(result.contents[0].content_id), bytes)
        self.assertIs(type(result.contents[0].expected_sha256), bytes)
        self.assertIs(type(result.unverified_digest), bytes)
        self.assertIsInstance(hash(result), int)

    def test_unsupported_objects_never_invoke_user_code(self):
        class Hostile:
            def __repr__(self):
                raise AssertionError("must not render input")

            def __iter__(self):
                raise AssertionError("must not iterate input")

        class BytesSubclass(bytes):
            pass

        for value in (None, "private-text", [], {}, 123, Hostile(), BytesSubclass(package())):
            self.assert_error(value, "unsupported CNMT input type")

    def test_unsupported_and_released_memoryviews(self):
        raw = package()
        released = memoryview(raw)
        released.release()
        for value in (memoryview(raw)[::2], memoryview(array("H", [0] * 40)),
                      memoryview(raw).cast("B", shape=[8, 10]), released):
            self.assert_error(value, "unsupported CNMT buffer layout")

    def test_deterministic_malformed_bytes_have_safe_errors(self):
        rng = random.Random(23)
        allowed = {"invalid CNMT extent", "unsupported CNMT metadata type"}
        for size in range(300):
            with self.assertRaises(CnmtFormatError) as caught:
                decode(rng.randbytes(size))
            self.assertIn(str(caught.exception), allowed)


if __name__ == "__main__":
    unittest.main()

class LegacyApplicationTests(unittest.TestCase):
    def test_explicit_legacy_size48_uses_sixth_byte(self):
        from tools.cnmt_metadata import APPLICATION_PRE15
        raw = bytearray(package((content(size=0x123456789A),)))
        raw[0x30 + 0x35] = 0xAB
        result = parse_cnmt(raw, layout=APPLICATION_PRE15)
        self.assertEqual(result.contents[0].byte_size, 0xAB123456789A)
        self.assertEqual(result.contents[0].attributes, 0)
        with self.assertRaisesRegex(CnmtFormatError, 'unsupported CNMT content attributes'):
            parse_cnmt(raw, layout=APPLICATION_15_16)

    def test_legacy_common_zero_high_byte_still_requires_explicit_layout(self):
        from tools.cnmt_metadata import APPLICATION_PRE15
        raw = package((content(size=123),))
        result = parse_cnmt(raw, layout=APPLICATION_PRE15)
        self.assertEqual(result.contents[0].byte_size, 123)
        self.assertEqual(result.layout, APPLICATION_PRE15)
        with self.assertRaises(TypeError):
            parse_cnmt(raw)


if __name__ == '__main__':
    unittest.main()
