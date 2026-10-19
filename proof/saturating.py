"""Dependency-free unsigned-byte arithmetic."""


def saturating_add_u8(a: int, b: int) -> int:
    """Add two integers in 0..255, clamping to 255; reject invalid inputs."""
    for value in (a, b):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError("operands must be integers in 0..255 (excluding bools)")
    return min(255, a + b)
