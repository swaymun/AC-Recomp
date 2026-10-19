"""Decode explicitly selected pre-15 or 15/16 Application CNMT layouts, offline only.

No extraction, content verification, association, or policy decision occurs.
See docs/CNMT_METADATA.md for the primary contracts and deliberately narrow scope.
"""

from dataclasses import dataclass


APPLICATION_PRE15 = "application-1.0.0-14.1.2-size48"
APPLICATION_15_16 = "application-15.0.0-16.1.0-size40-attributes0"
NCM_PROGRAM = 1
NCM_CONTROL = 3


class CnmtFormatError(ValueError):
    """A fixed diagnostic containing no caller-supplied data."""


@dataclass(frozen=True, slots=True)
class ContentReference:
    content_type: int
    id_offset: int
    content_id: bytes
    expected_sha256: bytes
    byte_size: int
    attributes: int


@dataclass(frozen=True, slots=True)
class ApplicationCnmt:
    layout: str
    application_id: int
    version: int
    metadata_type: int
    metadata_attributes: int
    required_download_system_version: int
    patch_id: int
    required_system_version: int
    required_application_version: int
    contents: tuple[ContentReference, ...]
    unverified_digest: bytes


def parse_cnmt(data: bytes | bytearray | memoryview, *, layout: str) -> ApplicationCnmt:
    """Snapshot and parse the explicitly selected Application encoding.

    The caller must establish the layout externally and prevent concurrent writes
    during snapshot creation. The file has no discriminator for the firmware-15
    size/attribute change. No default, firmware guessing, or fallback is used.
    Accept exact built-in bytes/bytearray or a live contiguous 1-D byte view.
    Results retain all references in wire order; no Program/Control is selected.
    """
    if type(layout) is not str or layout not in (APPLICATION_PRE15, APPLICATION_15_16):
        raise CnmtFormatError("unsupported CNMT layout")
    if type(data) not in (bytes, bytearray, memoryview):
        raise CnmtFormatError("unsupported CNMT input type")
    try:
        with memoryview(data) as view:
            if (view.ndim != 1 or not view.c_contiguous or view.itemsize != 1
                    or view.format not in ("B", "b", "c")):
                raise CnmtFormatError("unsupported CNMT buffer layout")
            # This lower bound protects all fixed-header field reads. All later
            # extents are checked before any table entry is sliced.
            if view.nbytes < 0x20:
                raise CnmtFormatError("invalid CNMT extent")
            snapshot = view.tobytes()
    except CnmtFormatError:
        raise
    except (ValueError, TypeError, BufferError):
        raise CnmtFormatError("unsupported CNMT buffer layout") from None

    def uint(offset: int, width: int) -> int:
        return int.from_bytes(snapshot[offset:offset + width], "little")

    if snapshot[0x0C] != 0x80:
        raise CnmtFormatError("unsupported CNMT metadata type")
    if uint(0x0E, 2) != 0x10:
        raise CnmtFormatError("unsupported CNMT extended header")
    # Reserved in the selected pre-17 packaged-header contract. Newer contracts
    # assign meanings to some of these bytes; they are not accepted here.
    if (snapshot[0x0D] or any(snapshot[0x15:0x18])
            or any(snapshot[0x1C:0x20])):
        raise CnmtFormatError("unsupported CNMT header encoding")
    metadata_attributes = snapshot[0x14]
    if metadata_attributes & ~0x07:
        raise CnmtFormatError("unsupported CNMT metadata attributes")

    content_count = uint(0x10, 2)
    metadata_count = uint(0x12, 2)
    contents_start = 0x20 + 0x10
    metadata_start = contents_start + content_count * 0x38
    digest_start = metadata_start + metadata_count * 0x10
    # Python integers cannot wrap. Counts use their full u16 range; there is no
    # fixture-size cap. Application has no extended-data block in this contract.
    if len(snapshot) != digest_start + 0x20:
        raise CnmtFormatError("invalid CNMT extent")
    # The primary declarations identify ContentMetaInfo as SystemUpdate-only.
    # Establish its boundary above, but do not invent Application semantics.
    if metadata_count:
        raise CnmtFormatError("unsupported CNMT Application metadata table")
    application_id = uint(0, 8)
    if application_id == 0:
        raise CnmtFormatError("invalid CNMT application identity")

    contents = []
    seen_ids: set[bytes] = set()
    seen_slots: set[tuple[int, int]] = set()
    for index in range(content_count):
        start = contents_start + index * 0x38
        expected_hash = snapshot[start:start + 0x20]
        content_id = snapshot[start + 0x20:start + 0x30]
        size = uint(start + 0x30, 6 if layout == APPLICATION_PRE15 else 5)
        attributes = 0 if layout == APPLICATION_PRE15 else snapshot[start + 0x35]
        content_type = snapshot[start + 0x36]
        id_offset = snapshot[start + 0x37]
        if attributes:
            raise CnmtFormatError("unsupported CNMT content attributes")
        if content_type > 6:
            raise CnmtFormatError("unsupported CNMT content type")
        # This checks only consistency of encoded claims, never actual content.
        if content_id != expected_hash[:0x10]:
            raise CnmtFormatError("inconsistent CNMT content identity")
        slot = (content_type, id_offset)
        # NCM exposes lookup by content ID and by (type, id-offset). Reject
        # repeated lookup identities, even when all bytes are identical.
        if content_id in seen_ids or slot in seen_slots:
            raise CnmtFormatError("duplicate or conflicting CNMT content identity")
        seen_ids.add(content_id)
        seen_slots.add(slot)
        contents.append(ContentReference(content_type, id_offset, content_id,
                                         expected_hash, size, attributes))

    return ApplicationCnmt(
        layout=layout,
        application_id=application_id,
        version=uint(8, 4),
        metadata_type=snapshot[0x0C],
        metadata_attributes=metadata_attributes,
        required_download_system_version=uint(0x18, 4),
        patch_id=uint(0x20, 8),
        required_system_version=uint(0x28, 4),
        required_application_version=uint(0x2C, 4),
        contents=tuple(contents),
        unverified_digest=snapshot[digest_start:digest_start + 0x20],
    )
