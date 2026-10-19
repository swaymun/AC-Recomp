"""Dependency-free IEEE CRC-32 for byte strings."""


def crc32(data: bytes) -> int:
    """Return the unsigned IEEE CRC-32 of data; reject non-bytes inputs."""
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF
