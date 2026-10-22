#!/usr/bin/env python3
"""Compare aligned RGB PPM captures without resizing or aligning away defects.

Convert other formats with ffmpeg first. Metrics measure pixel differences, not
visual correctness: scene, pose, exposure and capture time must be controlled.
Only Python's standard library is required; game captures stay outside Git.
"""
import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    rgb: bytes

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0 or len(self.rgb) != self.width * self.height * 3:
            raise ValueError('invalid RGB frame geometry or byte count')


def load_ppm(path):
    """Read one binary 8-bit RGB PPM, preserving whitespace-valued first pixels."""
    data = Path(path).read_bytes()
    at = 0

    def token():
        nonlocal at
        while at < len(data):
            if data[at] in b' \t\r\n\v\f':
                at += 1
            elif data[at] == ord('#'):
                end = data.find(b'\n', at)
                at = len(data) if end < 0 else end + 1
            else:
                break
        start = at
        while at < len(data) and data[at] not in b' \t\r\n\v\f#':
            at += 1
        if start == at:
            raise ValueError('truncated PPM header')
        return data[start:at]

    if token() != b'P6':
        raise ValueError('expected binary RGB PPM (P6)')
    width, height, maximum = int(token()), int(token()), int(token())
    if maximum != 255:
        raise ValueError('expected 8-bit PPM with maximum 255')
    if at >= len(data) or data[at] not in b' \t\r\n\v\f':
        raise ValueError('missing PPM raster separator')
    at += 2 if data[at:at + 2] == b'\r\n' else 1
    return Frame(width, height, data[at:])


def compare(before, after, *, roi=None, tolerance=0):
    """Return RGB-channel errors and fraction of pixels exceeding tolerance.

    ROI is (x, y, width, height) in source pixels. PSNR is null for identical
    inputs so reports remain strict JSON (no Infinity/NaN values).
    """
    if (before.width, before.height) != (after.width, after.height):
        raise ValueError('capture dimensions differ; explicit alignment is required')
    if not isinstance(tolerance, int) or not 0 <= tolerance <= 255:
        raise ValueError('tolerance must be an integer in 0..255')
    x, y, width, height = roi if roi is not None else (0, 0, before.width, before.height)
    if (not all(isinstance(v, int) for v in (x, y, width, height)) or
            min(x, y) < 0 or min(width, height) <= 0 or
            x + width > before.width or y + height > before.height):
        raise ValueError('ROI must be a nonempty rectangle inside both captures')
    absolute = squared = maximum = changed = 0
    for row in range(y, y + height):
        start = (row * before.width + x) * 3
        stop = start + width * 3
        a, b = before.rgb[start:stop], after.rgb[start:stop]
        for k in range(0, len(a), 3):
            pixel_max = 0
            for channel in range(3):
                delta = abs(a[k + channel] - b[k + channel])
                absolute += delta
                squared += delta * delta
                pixel_max = max(pixel_max, delta)
            maximum = max(maximum, pixel_max)
            changed += pixel_max > tolerance
    pixels = width * height
    mse = squared / (pixels * 3)
    return dict(roi=[x, y, width, height], pixels=pixels,
                mae=absolute / (pixels * 3), rmse=math.sqrt(mse),
                max_channel_error=maximum, changed_pixels=changed,
                changed_fraction=changed / pixels, tolerance=tolerance,
                psnr_db=10 * math.log10(255 * 255 / mse) if mse else None)


def rectangle(value):
    try:
        result = tuple(map(int, value.split(',')))
    except ValueError as error:
        raise argparse.ArgumentTypeError('ROI must be x,y,width,height') from error
    if len(result) != 4:
        raise argparse.ArgumentTypeError('ROI must be x,y,width,height')
    return result


def finite_limit(value):
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise argparse.ArgumentTypeError('MAE limit must be finite and nonnegative')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--roi', type=rectangle)
    parser.add_argument('--tolerance', type=int, default=0)
    parser.add_argument('--max-mae', type=finite_limit,
                        help='exit 1 if measured MAE exceeds this explicit limit')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        metrics = compare(load_ppm(args.before), load_ppm(args.after),
                          roi=args.roi, tolerance=args.tolerance)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    passed = None if args.max_mae is None else metrics['mae'] <= args.max_mae
    report = dict(schema=1, before=str(args.before), after=str(args.after),
                  metrics=metrics, max_mae=args.max_mae, passed=passed)
    output = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(output)
    print(output, end='')
    return 1 if passed is False else 0


if __name__ == '__main__':
    raise SystemExit(main())
