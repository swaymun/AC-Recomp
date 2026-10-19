#!/usr/bin/env python3
"""Opt-in 60 fps mode for Astral Chain 1.0.0: patch five instructions of the player's own `main` NSO before the lift.

    python3 tools/astral_fps60.py <exefs/main> <patched main>      # write a patched copy (the input is not changed)
    python3 tools/astral_fps60.py --check <exefs/main>             # only verify the build id and the original words

tools/acr_build.py calls this from its lift stage when the build is made with `--fps 60` (or NX_FPS=60). The game's
code is lifted to C++ ahead of time, so the choice is made at build time; a runtime switch cannot change lifted code.

What the five sites do (docs/ASTRAL_60FPS.md has the analysis and the references):
  * The game loop asks the graphics system for "vsync mode" 1 every frame (interval 2, 30 fps). Mode 0 makes the game
    call nvnWindowSetPresentInterval(window, 1) itself; the runtime then paces presents at 60 Hz.
  * The game advances its world by a measured step in units of 1/30 s, clamped to at least 1.0 (one 30 fps frame).
    The clamp (two compares and the stored minimum) is lowered to 0.5 so a 60 fps frame steps half as far.
  * Fixed-step frames (cutscenes) skip the measurement and step a constant 1.0, which would run them at double speed.
    That branch is removed so they take the measured step too (as community research on 1.0.1 found).

Every site is checked against the original word before any is written; the build id must be 1.0.0's. The patched
NSO keeps the header and module name, stores its three segments uncompressed and updates their SHA-256 hashes.
Game-derived: the patched file belongs in the private build directory, never in Git. Standard library only.
"""
import argparse
import hashlib
import struct
import sys

# Astral Chain 1.0.0 (title 01007300020FA000), main: the first 16 bytes of the NSO build id.
BUILD_ID = bytes.fromhex('ed2026b20685971f8b332095a7ff80ff')

# (module offset, original word, replacement word, meaning). Offsets are module-relative (text starts at 0).
SITES = (
    (0x3DF7C0, 0x320003E0, 0x52800000,
     'game loop: mov w0, #1 -> mov w0, #0 (vsync mode 0 = present interval 1, set via main+0x9c9c70)'),
    (0x907A70, 0x340001D5, 0xD503201F,
     'game speed: cbz w21 (fixed-step frame) -> nop (cutscenes take the measured step as well)'),
    (0x907AF4, 0x1E2E1001, 0x1E2C1001,
     'game speed: fmov s1, #1.0 -> #0.5 (compare against the minimum step)'),
    (0x907B00, 0x1E2E1001, 0x1E2C1001,
     'game speed: fmov s1, #1.0 -> #0.5 (carry = minimum - measured)'),
    (0x907B0C, 0x32091BE8, 0x52A7E008,
     'game speed: mov w8, #0x3f800000 -> #0x3f000000 (store the minimum step 0.5)'),
)

NSO_MAGIC = b'NSO0'
HEADER_SIZE = 0x100


class PatchError(Exception):
    pass


def lz4_block_decompress(src, size):
    """Decompress one raw LZ4 block (as NSO segments are stored) of exactly `size` bytes."""
    src = bytes(src)
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break
        if i + 2 > n:
            raise PatchError('LZ4 block truncated')
        off = src[i] | src[i + 1] << 8
        i += 2
        if off == 0 or off > len(out):
            raise PatchError('LZ4 block has a bad match offset')
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        if off >= ml:
            out += out[start:start + ml]
        else:  # overlapping copy: repeat the last `off` bytes
            chunk = out[start:]
            reps, rem = divmod(ml, off)
            out += chunk * reps + chunk[:rem]
    if len(out) != size:
        raise PatchError(f'LZ4 segment decompressed to {len(out)} bytes, expected {size}')
    return out


def read_segments(raw):
    """The NSO's three segments (text, rodata, data), decompressed: [(mem_offset, bytearray)]."""
    if len(raw) < HEADER_SIZE or raw[:4] != NSO_MAGIC:
        raise PatchError('not an NSO')
    flags = struct.unpack_from('<I', raw, 0x0C)[0]
    segs = []
    for k in range(3):
        file_off, mem_off, size = struct.unpack_from('<III', raw, 0x10 + k * 0x10)
        comp = struct.unpack_from('<I', raw, 0x60 + k * 4)[0]
        blob = raw[file_off:file_off + comp]
        if len(blob) != comp:
            raise PatchError(f'segment {k} runs past the end of the file')
        blob = lz4_block_decompress(blob, size) if flags & (1 << k) else bytearray(blob)
        if len(blob) != size:
            raise PatchError(f'segment {k} is {len(blob)} bytes, expected {size}')
        segs.append((mem_off, blob))
    return flags, segs


def check(raw, sites=SITES, build_id=BUILD_ID):
    """Verify the build id and every original word. Returns (flags, segments). Raises PatchError on any mismatch,
    naming every bad site; a fully patched input is reported as such."""
    if raw[:4] != NSO_MAGIC:
        raise PatchError('not an NSO')
    if raw[0x40:0x40 + len(build_id)] != build_id:
        raise PatchError(f'build id {raw[0x40:0x50].hex()} is not Astral Chain 1.0.0 ({build_id.hex()}); the 60 fps '
                         'sites are known only for 1.0.0')
    flags, segs = read_segments(raw)
    text_off, text = segs[0]
    words = []
    for addr, orig, new, what in sites:
        rel = addr - text_off
        if rel < 0 or rel + 4 > len(text) or rel % 4:
            raise PatchError(f'site {addr:#x} is outside the text segment')
        words.append(struct.unpack_from('<I', text, rel)[0])
    if all(w == new for w, (_, _, new, _) in zip(words, sites)):
        raise PatchError('this main is already patched for 60 fps')
    bad = [f'{a:#x}: found {w:#010x}, expected {o:#010x}' for w, (a, o, _, _) in zip(words, sites) if w != o]
    if bad:
        raise PatchError('main does not match Astral Chain 1.0.0 at ' + '; '.join(bad))
    return flags, segs


def patch(raw, sites=SITES, build_id=BUILD_ID):
    """The patched NSO (bytes). Verifies everything before changing anything."""
    raw = bytes(raw)
    _, segs = check(raw, sites, build_id)
    text_off, text = segs[0]
    for addr, _, new, _ in sites:
        struct.pack_into('<I', text, addr - text_off, new)
    first = min(struct.unpack_from('<I', raw, 0x10 + k * 0x10)[0] for k in range(3))
    head = bytearray(raw[:max(first, HEADER_SIZE)])  # header plus the module name that follows it
    struct.pack_into('<I', head, 0x0C, struct.unpack_from('<I', head, 0x0C)[0] & ~0x7)  # segments uncompressed
    body = bytearray()
    for k, (mem_off, blob) in enumerate(segs):
        file_off = len(head) + len(body)
        struct.pack_into('<III', head, 0x10 + k * 0x10, file_off, mem_off, len(blob))
        struct.pack_into('<I', head, 0x60 + k * 4, len(blob))
        head[0xA0 + k * 0x20:0xC0 + k * 0x20] = hashlib.sha256(blob).digest()
        body += blob
    return bytes(head + body)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--check', action='store_true', help='verify only; write nothing')
    p.add_argument('main', help="the player's exefs/main (NSO)")
    p.add_argument('out', nargs='?', help='where to write the patched NSO')
    a = p.parse_args(argv)
    if not a.check and not a.out:
        p.error('give an output path or --check')
    raw = open(a.main, 'rb').read()
    try:
        if a.check:
            check(raw)
            print(f'ok: {len(SITES)} sites match Astral Chain 1.0.0')
            return 0
        data = patch(raw)
    except PatchError as e:
        print('error: ' + str(e), file=sys.stderr)
        return 1
    with open(a.out, 'wb') as f:
        f.write(data)
    for addr, orig, new, what in SITES:
        print(f'main+{addr:#08x}: {orig:#010x} -> {new:#010x}  {what}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
