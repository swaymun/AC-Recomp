"""Parse only fixed NACP parental/rating encodings; never decide policy.

See docs/NACP_METADATA.md for the retained contracts and validation boundary.
No file access, extraction, association, or runtime integration is performed.
"""

from dataclasses import dataclass


class NacpFormatError(ValueError):
    """A fixed, input-independent diagnostic for unsupported input/layout."""


@dataclass(frozen=True, slots=True)
class RatingEncoding:
    index: int
    encoded: int
    signed: int
    position: str
    interpretation: str


@dataclass(frozen=True, slots=True)
class NacpMetadata:
    parental_flags: int
    ratings: tuple[RatingEncoding, ...]


def parse_nacp(data: bytes | bytearray | memoryview) -> NacpMetadata:
    """Decode an exact 0x4000-byte buffer into detached immutable values.

    Accept exact built-in bytes, bytearray, or live, one-dimensional,
    C-contiguous memoryview with byte format B/b/c. Reject other types/views.
    The caller must prevent concurrent mutation while this function snapshots
    the input. Later mutation cannot affect the returned values.

    Only flag bit 0 is supported. Zero flags and nonnegative ratings carry no
    authorization meaning. Negative values remain unknown; positions 13..31
    remain reserved regardless of value. Unexamined NACP fields are not validated.
    """
    if type(data) not in (bytes, bytearray, memoryview):
        raise NacpFormatError("unsupported NACP input type")
    try:
        with memoryview(data) as view:
            if (view.ndim != 1 or not view.c_contiguous
                    or view.itemsize != 1 or view.format not in ("B", "b", "c")):
                raise NacpFormatError("unsupported NACP buffer layout")
            if view.nbytes != 0x4000:
                raise NacpFormatError("invalid NACP size")
            snapshot = view.tobytes()
    except NacpFormatError:
        raise
    except (ValueError, TypeError, BufferError):
        raise NacpFormatError("unsupported NACP buffer layout") from None

    flags = int.from_bytes(snapshot[0x3030:0x3034], "little", signed=False)
    if flags & ~0x00000001:
        raise NacpFormatError("unsupported NACP parental flags")
    ratings = tuple(
        RatingEncoding(
            index=index,
            encoded=value,
            signed=value if value < 128 else value - 256,
            position="defined" if index < 13 else "reserved",
            interpretation=("reserved" if index >= 13 else
                            "unknown_negative" if value >= 128 else
                            "uninterpreted_nonnegative"),
        )
        for index, value in enumerate(snapshot[0x3040:0x3060])
    )
    return NacpMetadata(parental_flags=flags, ratings=ratings)
