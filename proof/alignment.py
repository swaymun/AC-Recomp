"""Integer alignment helpers."""


def align_up(value: int, alignment: int) -> int:
    """Return the least multiple of alignment >= value; reject invalid inputs."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("value must be a nonnegative integer")
    if (
        isinstance(alignment, bool)
        or not isinstance(alignment, int)
        or alignment <= 0
        or alignment & (alignment - 1)
    ):
        raise ValueError("alignment must be a positive power-of-two integer")
    return (value + alignment - 1) & -alignment
