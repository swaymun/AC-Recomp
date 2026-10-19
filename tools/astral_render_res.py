#!/usr/bin/env python3
"""Lift-time internal-resolution patch for Astral Chain 1.0.0 (docs/ASTRAL_RENDER_RES.md).

Astral Chain renders docked at a fixed 1600x900 (immediates in main's text). This rewrites those immediates in a
copy of the player's own main NSO before it is lifted, so the engine itself allocates and presents larger targets:

    python3 tools/astral_render_res.py --in <import>/exefs/main --out <work>/render-res/main --res 2560x1440

Every site's original instruction word is checked first; any mismatch (another game version, an already patched
file) refuses the whole patch. The output is an uncompressed NSO (segment flags cleared) that the pinned recompiler
loads exactly like the original; only the listed text words differ. Nothing game-derived is printed. Standard
library only (lz4 is used when importable, otherwise a small pure-Python LZ4 block decoder).
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

# NSO build id of Astral Chain 1.0.0 main (title 01007300020FA000), first 16 bytes; the rest of the 32 are zero.
BUILD_ID_100 = 'ed2026b20685971f8b332095a7ff80ff'
STOCK = (1600, 900)
MAX_DIM = 4095  # the cmp sites take a 12-bit unsigned immediate

# (module-relative text offset, original word, operand, register, meaning). Operand 'w'/'h' is the new width/height.
# 'mov' sites are MOVZ Wd,#imm16; 'cmp' sites are CMP Wn,#imm12 (SUBS WZR,Wn,#imm12).
SITES = (
    (0x4093D4, 0x5280C809, 'mov', 'w', 9, 'graphics init: docked scene/window width (handheld 1280)'),
    (0x4093E0, 0x52807089, 'mov', 'h', 9, 'graphics init: docked scene/window height (handheld 720)'),
    (0x40AF74, 0x7119001F, 'cmp', 'w', 0, 'DRS setup: "main target is docked width" test for slot 0 (max)'),
    (0x40AF78, 0x52807088, 'mov', 'h', 8, 'DRS slot 0 (max) docked height'),
    (0x40AF98, 0x5280B409, 'mov', 'w', 9, 'DRS slot 1 (min) docked width 1440 -> locked to max (no dynamic res)'),
    (0x40AF9C, 0x7119001F, 'cmp', 'w', 0, 'DRS setup: docked-width test for slot 1 (min)'),
    (0x40AFA4, 0x52806556, 'mov', 'h', 22, 'DRS slot 1 (min) docked height 810 -> locked to max (no dynamic res)'),
    (0x40AFC0, 0x7119001F, 'cmp', 'w', 0, 'DRS setup: docked-width test for slot 2'),
    (0x40B8F4, 0x5280C809, 'mov', 'w', 9, 'operation-mode change: docked width for re-created targets'),
    (0x40B904, 0x52807089, 'mov', 'h', 9, 'operation-mode change: docked height for re-created targets'),
    (0x42E5F0, 0x5280C808, 'mov', 'w', 8, 'docked display-size getter (writes *x0 = width)'),
    (0x42E5F8, 0x52807088, 'mov', 'h', 8, 'docked display-size getter (writes *x1 = height)'),
)
# Graphic::Startup's graphics-memory budget (bytes, MOVZ W8,#0x1360,LSL #16 = 0x13600000 = 310 MiB). Larger targets
# exhaust it ("Graphic::Startup() FAILED. No Graphic Memory", then a null dereference in nnMain).
MEMORY_SITE = (0x409EA0, 0x52A26C08, 8, 'Graphic::Startup config: graphics memory budget 0x13600000 (310 MiB)')
STOCK_MEMORY_MIB = 0x136


class PatchError(Exception):
    pass


def movz_w(rd, imm):
    if not 0 <= imm <= 0xFFFF:
        raise PatchError(f'mov immediate {imm} out of range')
    return 0x52800000 | (imm << 5) | rd


def cmp_w(rn, imm):
    if not 0 <= imm <= 0xFFF:
        raise PatchError(f'cmp immediate {imm} out of range')
    return 0x7100001F | (imm << 10) | (rn << 5)


def movz_w_lsl16(rd, imm):
    if not 0 < imm <= 0xFFFF:
        raise PatchError(f'mov immediate {imm:#x} out of range')
    return 0x52A00000 | (imm << 5) | rd


def default_memory_mib(w, h):
    """Stock budget plus room for the larger targets: +160 MiB per extra 1600x900 of pixels (measured, see docs)."""
    extra = max(0.0, w * h / (STOCK[0] * STOCK[1]) - 1.0)
    return STOCK_MEMORY_MIB + -(-int(extra * 160 * 16) // 16)  # rounded up to whole MiB


def encode(kind, reg, value):
    return movz_w(reg, value) if kind == 'mov' else cmp_w(reg, value)


def parse_res(text):
    m = re.fullmatch(r'\s*(\d+)\s*[xX]\s*(\d+)\s*', text or '')
    if not m:
        raise PatchError(f'resolution must look like 2560x1440, not {text!r}')
    w, h = int(m.group(1)), int(m.group(2))
    if not (STOCK[0] <= w <= MAX_DIM and STOCK[1] <= h <= MAX_DIM):
        raise PatchError(f'resolution {w}x{h} must be between {STOCK[0]}x{STOCK[1]} and {MAX_DIM}x{MAX_DIM}')
    if w % 2 or h % 2:
        raise PatchError(f'resolution {w}x{h} must have even width and height')
    return w, h


def lz4_block_decompress(src, size):
    """Decode one raw LZ4 block (no frame) of known decompressed size."""
    try:
        import lz4.block
        return lz4.block.decompress(bytes(src), uncompressed_size=size)
    except ImportError:
        return lz4_block_decompress_pure(src, size)


def lz4_block_decompress_pure(src, size):
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
        off = src[i] | (src[i + 1] << 8)
        i += 2
        if off == 0 or off > len(out):
            raise PatchError('corrupt LZ4 block')
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
        else:
            for k in range(ml):
                out.append(out[start + k])
    if len(out) != size:
        raise PatchError(f'LZ4 block decoded to {len(out)} bytes, expected {size}')
    return bytes(out)


def read_nso(raw):
    if raw[:4] != b'NSO0':
        raise PatchError('not an NSO (bad magic)')
    flags = struct.unpack_from('<I', raw, 0x0C)[0]
    segs = []
    for i in range(3):
        file_off, mem_off, size = struct.unpack_from('<III', raw, 0x10 + i * 0x10)
        comp = struct.unpack_from('<I', raw, 0x60 + i * 4)[0]
        blob = raw[file_off:file_off + (comp if flags & (1 << i) else size)]
        if flags & (1 << i):
            blob = lz4_block_decompress(blob, size)
        if len(blob) != size:
            raise PatchError(f'segment {i} is truncated')
        segs.append(bytearray(blob))
    return flags, segs


def write_nso(raw, segs):
    """An uncompressed NSO with the original header fields, sequential segments and no hash checks."""
    hdr = bytearray(raw[:0x100])
    struct.pack_into('<I', hdr, 0x0C, 0)
    off, body = 0x100, bytearray()
    for i, seg in enumerate(segs):
        struct.pack_into('<I', hdr, 0x10 + i * 0x10, off)
        struct.pack_into('<I', hdr, 0x60 + i * 4, len(seg))
        body += seg
        off += len(seg)
    return bytes(hdr + body)


def build_id(raw):
    return raw[0x40:0x60].hex()


def plan(w, h, memory_mib=None):
    edits = [(off, orig, encode(kind, reg, w if which == 'w' else h), meaning)
             for off, orig, kind, which, reg, meaning in SITES]
    mib = default_memory_mib(w, h) if memory_mib is None else memory_mib
    if not STOCK_MEMORY_MIB <= mib <= 4095:
        raise PatchError(f'graphics memory {mib} MiB must be between {STOCK_MEMORY_MIB} and 4095')
    if mib != STOCK_MEMORY_MIB:
        off, orig, reg, meaning = MEMORY_SITE
        edits.append((off, orig, movz_w_lsl16(reg, mib * 16), meaning))
    return edits


def patch_nso_bytes(raw, w, h, memory_mib=None):
    bid = build_id(raw)
    if not bid.startswith(BUILD_ID_100):
        raise PatchError(f'main NSO build id {bid[:32]} is not Astral Chain 1.0.0 ({BUILD_ID_100}); refusing')
    _, segs = read_nso(raw)
    text_mem = struct.unpack_from('<I', raw, 0x14)[0]
    text = segs[0]
    edits = plan(w, h, memory_mib)
    bad = []
    for off, orig, new, _ in edits:
        rel = off - text_mem
        if not 0 <= rel <= len(text) - 4:
            bad.append(f'{off:#x} outside text')
            continue
        have = struct.unpack_from('<I', text, rel)[0]
        if have != orig:
            bad.append(f'{off:#x}: found {have:08x}, expected {orig:08x}')
    if bad:
        raise PatchError('original words do not match (wrong version or already patched): ' + '; '.join(bad))
    for off, _, new, _ in edits:
        struct.pack_into('<I', text, off - text_mem, new)
    return write_nso(raw, segs), edits


def patch_file(src, dst, w, h, memory_mib=None):
    raw = Path(src).read_bytes()
    out, edits = patch_nso_bytes(raw, w, h, memory_mib)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + '.tmp')
    tmp.write_bytes(out)
    tmp.replace(dst)
    mem = next((b for o, _, b, _ in edits if o == MEMORY_SITE[0]), None)
    return {'resolution': f'{w}x{h}', 'graphics_memory_mib': ((mem >> 5) & 0xFFFF) // 16 if mem else STOCK_MEMORY_MIB,
            'build_id': BUILD_ID_100, 'sites': len(edits),
            'edits': [{'offset': f'{o:#x}', 'original': f'{a:08x}', 'patched': f'{b:08x}'} for o, a, b, _ in edits],
            'output_sha256': hashlib.sha256(out).hexdigest()}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--in', dest='src', type=Path, required=True, help='the original main NSO (exefs/main)')
    p.add_argument('--out', type=Path, required=True, help='where to write the patched, uncompressed NSO')
    p.add_argument('--res', required=True, help='docked internal resolution, e.g. 2560x1440')
    p.add_argument('--graphics-memory-mib', type=int,
                   help='graphics memory budget in MiB (default: scaled with the resolution; stock 310)')
    a = p.parse_args(argv)
    try:
        w, h = parse_res(a.res)
        print(json.dumps(patch_file(a.src, a.out, w, h, a.graphics_memory_mib), indent=2))
    except (PatchError, OSError) as e:
        print('error: ' + str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
