#!/usr/bin/env python3
"""Experimental, build-time Dynamic FPS port for the owner's Astral Chain 1.0.0 NSO.

Modes: 30, 60-fixed (the existing 0.5-floor patch), dynamic-60-cap, dynamic-unlocked.
Patch a private copy, lift that copy, and build with the matching NX_ASTRAL_FPS_MODE.
See docs/ASTRAL_HIGH_FPS.md for the explicit build recipe and acceptance gates.

Adapted from yogesh1239/AstralChain-Dynamic-FPS v1.1.1, MIT, copyright (c) 2026
 yogesh1239. Full notice, including the mod's own credit, in THIRD_PARTY_NOTICES.md.
No dump, lifted code or third-party patch file is distributed here. Standard library only.
"""
import argparse
from pathlib import Path
import struct
import sys

import astral_fps60 as fixed

PatchError = fixed.PatchError
BUILD_ID = fixed.BUILD_ID
MODES = ('30', '60-fixed', 'dynamic-60-cap', 'dynamic-unlocked')
TEXT_SIZE = 0x9F85F0
RODATA_START = 0x9F9000
CAVE = TEXT_SIZE
TIMER_GOT = 0xD9E998


def leaf_hook(kind):
    return kind.startswith('rumble') or kind in ('hs16', 'raw16')

# (1.0.0 address, original word, helper). Mapped by field accesses and branch structure;
# full 1.0.1 -> 1.0.0 map and disassembly evidence stay in ignored private storage.
HOOKS = (
    (0x0D529C, 0x71000508, 'hs8'),
    (0x0D52F0, 0x71000508, 'hs8'),
    (0x0E72B4, 0x71000508, 'hs8'),
    (0x0F6F3C, 0x71000508, 'hs8'),
    (0x0F7944, 0x71000508, 'hs8'),
    (0x27FEF4, 0x71000508, 'hs8'),
    (0x280680, 0x51000508, 'bank'),
    (0x280690, 0x51000508, 'bank'),
    (0x2806A0, 0x51000508, 'bank'),
    (0x2806B0, 0x51000508, 'bank'),
    (0x2806C0, 0x51000508, 'bank'),
    (0x2806D0, 0x51000508, 'bank'),
    (0x2806E0, 0x51000508, 'bank'),
    (0x2806F0, 0x51000508, 'bank'),
    (0x280700, 0x51000508, 'bank'),
    (0x280710, 0x51000508, 'bank'),
    (0x280720, 0x51000508, 'bank'),
    (0x280730, 0x51000508, 'bank'),
    (0x28073C, 0x71000508, 'hs8'),
    (0x280758, 0x71000508, 'hs8'),
    (0x280778, 0x51000508, 'bank'),
    (0x280788, 0x51000508, 'bank'),
    (0x280798, 0x51000508, 'bank'),
    (0x2807A8, 0x51000508, 'bank'),
    (0x2807B8, 0x51000508, 'bank'),
    (0x2807C8, 0x51000508, 'bank'),
    (0x2807D8, 0x51000508, 'bank'),
    (0x2807E8, 0x51000508, 'bank'),
    (0x2807F8, 0x51000508, 'bank'),
    (0x280808, 0x51000508, 'bank'),
    (0x28081C, 0x51000508, 'bank'),
    (0x280864, 0x71000529, 'hs9'),
    (0x280934, 0x71000508, 'hs8'),
    (0x28106C, 0x7100054A, 'hs10'),
    (0x281CAC, 0x1100052A, 'up10from9'),
    (0x28208C, 0x71000508, 'hs8'),
    (0x2820A8, 0x71000508, 'hs8'),
    (0x2820B8, 0x71000508, 'hs8'),
    (0x282174, 0x71000508, 'hs8'),
    (0x2821B0, 0x71000508, 'hs8'),
    (0x282A14, 0x71000508, 'hs8'),
    (0x282BDC, 0x71000529, 'hs9'),
    (0x284138, 0x11000529, 'upmin9'),
    (0x28432C, 0x71000508, 'hs8'),
    (0x28450C, 0x71000508, 'hs8'),
    (0x2845B8, 0x71000508, 'hs8'),
    (0x284A0C, 0x71000508, 'hs8'),
    (0x284A1C, 0x71000508, 'hs8'),
    (0x284A2C, 0x71000508, 'hs8'),
    (0x284A3C, 0x71000508, 'hs8'),
    (0x284A4C, 0x71000508, 'hs8'),
    (0x284B04, 0x71000549, 'hs9from10'),
    (0x284B44, 0x71000508, 'hs8'),
    (0x284B94, 0x71000549, 'hs9from10'),
    (0x284BA8, 0x71000529, 'hs9'),
    (0x284CAC, 0x71000529, 'hs9'),
    (0x286380, 0x71000529, 'hs9'),
    (0x28639C, 0x71000529, 'hs9'),
    (0x2863B8, 0x71000529, 'hs9'),
    (0x2863D4, 0x71000529, 'hs9'),
    (0x2863F0, 0x71000529, 'hs9'),
    (0x28640C, 0x71000529, 'hs9'),
    (0x286428, 0x71000529, 'hs9'),
    (0x286444, 0x71000529, 'hs9'),
    (0x286460, 0x71000529, 'hs9'),
    (0x28647C, 0x71000529, 'hs9'),
    (0x286684, 0x71000529, 'hs9'),
    (0x2866A0, 0x71000529, 'hs9'),
    (0x2866BC, 0x71000529, 'hs9'),
    (0x3055DC, 0x71000508, 'hs8'),
    (0x328978, 0x71000529, 'hs9'),
    (0x328C70, 0x71000529, 'hs9'),
    (0x328F68, 0x71000529, 'hs9'),
    (0x4E9C80, 0x71000508, 'hs8'),
    (0x4E9CAC, 0x71000508, 'hs8'),
    (0x4E9CE8, 0x71000508, 'hs8'),
    (0x4E9D00, 0x71000508, 'hs8'),
    (0x4E9D9C, 0x71000508, 'hs8'),
    (0x4E9DB4, 0x71000508, 'hs8'),
    (0x4E9DC8, 0x71000508, 'hs8'),
    (0x4E9E54, 0x71000508, 'hs8'),
    (0x4E9E64, 0x71000508, 'hs8'),
    (0x4E9E8C, 0x71000508, 'hs8'),
    (0x4E9EA4, 0x71000508, 'hs8'),
    (0x4E9ED8, 0x71000508, 'hs8'),
    (0x4E9F44, 0x11000508, 'up8'),
    (0x4EA0CC, 0x71000508, 'hs8'),
    (0x907CB0, 0x71000610, 'hs16'),
    (0x907D48, 0x71000610, 'raw16'),
    (0x995AC8, 0x71000509, 'rumble8'),
    (0x995ADC, 0x7100052A, 'rumble9'),
    (0x995B20, 0x7100052A, 'rumble9'),
    (0x995B3C, 0x7100052A, 'rumble9'),
    (0x995B94, 0x7100052A, 'rumble9'),
    (0x995BB0, 0x7100052A, 'rumble9'),
    (0x995BCC, 0x7100052A, 'rumble9'),
    (0x995C30, 0x7100052A, 'rumble9'),
    (0x995C4C, 0x7100052A, 'rumble9'),
    (0x995CEC, 0x7100052A, 'rumble9'),
    (0x995DA0, 0x11000529, 'up9'),
)

def branch(pc, target, opcode=0x14000000, bits=26, shift=0):
    """Encode an aligned, signed PC-relative AArch64 branch; never truncate a bad target."""
    delta = target - pc
    if delta % 4 or not -(1 << (bits + 1)) <= delta < (1 << (bits + 1)):
        raise PatchError(f'branch out of range or unaligned: {pc:#x} -> {target:#x}')
    return opcode | (((delta // 4) & ((1 << bits) - 1)) << shift)


def adrp(pc, target, reg):
    delta = (target >> 12) - (pc >> 12)
    if not -(1 << 20) <= delta < (1 << 20):
        raise PatchError('ADRP out of range')
    return 0x90000000 | ((delta & 3) << 29) | (((delta >> 2) & 0x7FFFF) << 5) | reg


class Program:
    def __init__(self):
        self.words = []
        self.labels = {}
        self.refs = []

    @property
    def pc(self):
        return CAVE + 4 * len(self.words)

    def label(self, name):
        if name in self.labels:
            raise PatchError(f'duplicate cave label {name}')
        self.labels[name] = self.pc

    def emit(self, *words):
        self.words.extend(words)

    def jump(self, target, opcode=0x14000000, bits=26, shift=0):
        self.refs.append((len(self.words), target, opcode, bits, shift))
        self.emit(0)

    def cbz(self, reg, target, wide=False):
        self.jump(target, (0xB4000000 if wide else 0x34000000) | reg, 19, 5)

    def cond(self, cond, target):
        self.jump(target, 0x54000000 | cond, 19, 5)

    def ticks(self, reg):
        self.emit(adrp(self.pc, TIMER_GOT, reg),
                  0xF9400000 | (((TIMER_GOT & 0xFFF) // 8) << 10) | (reg << 5) | reg,
                  0xB940D800 | (reg << 5) | reg)  # ldr wR,[xR,#0xd8]

    def finish(self):
        for k, target, op, bits, shift in self.refs:
            dest = self.labels[target] if isinstance(target, str) else target
            self.words[k] = branch(CAVE + 4 * k, dest, op, bits, shift)
        if self.pc > RODATA_START:
            raise PatchError('cave would overlap rodata')
        return struct.pack('<' + 'I' * len(self.words), *self.words)


def dynamic_program(cutscene_clock='original'):
    """MIT mod semantics, with shared helpers and 1.0.0 addresses; no assembler dependency.

    D0 = clamp(measured milliseconds * 0.03 * eligible correction, 1/16, 2).
    D4 accumulates fractional ticks, D8 publishes their integer part. The first frame
    clears D4. D0 never feeds back D4, so fractional rendering does not accelerate time.
    """
    if cutscene_clock not in ('original', 'carry'):
        raise PatchError(f'unknown cutscene clock {cutscene_clock!r}')
    p = Program()
    p.label('measured')
    p.emit(0xBD40DE61, 0x1E210808)  # ldr s1,[x19,#dc]; fmul s8,s0,s1
    p.cbz(21, 'clamp')
    p.jump(0x893410, 0x94000000)  # game's positive audio correction, variable frames only
    p.emit(0x1E202008)
    p.cond(13, 'clamp')  # b.le
    p.emit(0x1E200908)  # fmul s8,s8,s0 (relative correction, not an absolute step)
    p.label('clamp')
    p.emit(0x52A7B008, 0x1E270101, 0x1E216900, 0x1E201001, 0x1E217800,
           0xBD00D260, 0xBD40D661, 0x1E202821, 0x1E390028, 0x1E230102,
           0x1E223821, 0xBD00D661, 0xB900DA68, 0xB900E67F)
    p.jump(0x907B14)
    p.label('first')
    p.emit(0xB900D67F)  # clear integer remainder; original incoming s8 is 1.0
    p.jump('clamp')

    # Saturating signed countdown with the original exact-zero transition and flags.
    # No whole tick: positive values stay positive; zero/expired values take b.lt so
    # exact-zero actions do not fire again on each fractional render frame.
    for n in (8, 9, 10, 16):
        s = n + 1
        p.label(f'hs{n}')
        p.emit(0xF81F0FE0 | s)  # preserve scratch on aligned stack
        p.ticks(s)
        p.cbz(s, f'hold{n}')
        p.emit(0x7100041F | (n << 5),
               0x7A40A000 | (s << 16) | (n << 5),
               0x1A80B000 | (s << 16) | (n << 5) | s,
               0x6B000000 | (s << 16) | (n << 5) | n,
               0xF84107E0 | s, 0xD65F03C0)
        p.label(f'hold{n}')
        p.emit(0x7100001F | (n << 5), 0x7A40C808 | (n << 5),
               0xF84107E0 | s, 0xD65F03C0)
    p.label('hs9from10')
    p.emit(0x2A0A03E9)  # mov w9,w10
    p.jump('hs9')

    p.label('bank')
    p.emit(0xA9BF2BE9, 0xD53B420A)  # preserve scratch pair and incoming NZCV (original SUB has no S)
    p.ticks(9)
    p.emit(0x6B090109, 0x1A9F8129, 0x7100011F, 0x1A88C128,
           0xD51B420A, 0xA8C12BE9, 0xD65F03C0)
    for name, dest, src, scratch in [('up8', 8, 8, 9), ('up9', 9, 9, 10),
                                     ('up10from9', 10, 9, 11), ('upmin9', 9, 9, 10)]:
        p.label(name)
        p.emit(0xA9BF2FEA if name == 'upmin9' else 0xF81F0FE0 | scratch)
        if name == 'upmin9':
            p.emit(0xD53B420B)
        p.ticks(scratch)
        if name == 'upmin9':  # preserve the first tap/hold sample even before a whole tick
            p.emit(0x7100013F, 0x7A400940, 0x1A9F154A)
        p.emit(0x0B000000 | (scratch << 16) | (src << 5) | dest)
        if name == 'upmin9':
            p.emit(0xD51B420B, 0xA8C12FEA)
        else:
            p.emit(0xF84107E0 | scratch)
        p.emit(0xD65F03C0)
    p.label('raw16')  # this duration intentionally crosses zero (b.gt), unlike exact-zero delays
    p.emit(0xF81F0FF1)
    p.ticks(17)
    p.emit(0x6B110210, 0xF84107F1, 0xD65F03C0)

    for n, dest in [(8, 9), (9, 10)]:
        p.label(f'rumble{n}')
        p.emit(0xF81F0FEC)
        p.ticks(12)
        p.emit(0x7100041F | (n << 5), 0x1A9F158C)  # terminal 1 is a sentinel: consume it now
        p.cbz(12, f'rumblehold{n}')
        p.emit(0x7100041F | (n << 5), 0x7A4CA000 | (n << 5),
               0x1A8CB000 | (n << 5) | 12,
               0x6B0C0000 | (n << 5) | dest,
               0xF84107EC, 0xD65F03C0)
        p.label(f'rumblehold{n}')
        p.emit(0x2A0003E0 | (n << 16) | dest, 0x7100001F | (n << 5),
               0x7A40C808 | (n << 5), 0xF84107EC, 0xD65F03C0)

    p.label('ramp')
    # 1.0.0's constant is at b47cd0, NOT 1.0.1's b48e1c. Preserve the original load ordering.
    p.emit(0xBD4CD101)  # ldr s1,[x8,#0xcd0]
    p.emit(0xF81F0FE8)
    p.ticks(8)
    p.emit(0x1E220100, 0x1E200821, 0xBD407E60, 0xF84107E8)
    p.jump(0x4E9FA0)

    # Time-normalised exponential camera blend: 1 - powf(1 - alpha, step).
    # Preserve 30 fps exactly and endpoints 0/1; never quantise the camera to whole ticks.
    p.label('eye')
    p.emit(0x1E2A5800)
    p.jump('camera')
    p.label('look')
    p.emit(0x1E2A5820)
    p.jump('camera')
    p.label('up')
    p.emit(0xA9BF7BFD, 0x910003FD, 0x1E204120)
    p.jump('camera', 0x94000000)
    p.emit(0x1E204109, 0xBD421660, 0x1E202008, 0x1E29CD48, 0xA8C17BFD, 0xD65F03C0)
    p.label('camera')
    p.emit(0x1E204008, 0xA9BD7BFD, 0x910003FD, 0xA90107E0, 0xF90013E2,
           adrp(p.pc + 20, TIMER_GOT, 16), 0xF944CE10)
    p.cbz(16, 'cameraend', wide=True)
    p.emit(0xBD40D201, 0x1E2E1002, 0x1E222020)
    p.cond(0, 'cameraend')
    p.emit(0x1E202008)
    p.cond(13, 'cameraend')
    p.emit(0x1E222000)
    p.cond(10, 'cameraend')
    p.emit(0x2F00E403, 0x1E236821, 0x1E221003, 0x1E237821, 0x1E203840)
    p.jump(0x9F7440, 0x94000000)  # powf PLT, checked below
    p.emit(0x1E2E1002, 0x1E203848)
    p.label('cameraend')
    p.emit(0xA94107E0, 0xF94013E2, 0xA8C37BFD, 0xD65F03C0)

    # Rumble and clock-channel update have leaf paths. Preserve their incoming LR;
    # a bare BL would lose it. Other hooked functions save LR (guarded below).
    for addr, _, kind in HOOKS:
        if leaf_hook(kind):
            p.label(f'return{addr:x}')
            p.emit(0xF81F0FFE)
            p.jump(kind, 0x94000000)
            p.emit(0xF84107FE)
            p.jump(addr + 4)
    if cutscene_clock == 'carry':
        # The authored final frame is inclusive: duration = last-index + 1.
        # Original code clamps fractional overshoot to the last index, then clears
        # it at the next render. Carry keeps both that final frame and its residual,
        # without quantising motion or changing any audio clock / playback rate.
        p.label('cutscene_carry')
        p.emit(0x1E2E1002, 0x1E222821, 0x1E212000)
        p.cond(10, 'cutscene_crossed')
        p.jump(0x8AC414)
        p.label('cutscene_crossed')
        p.emit(0x1E213801, 0xB9000277, 0xBD000661)
        p.jump(0x8AC414)
    return p, p.finish()


def sites(mode='dynamic-60-cap', cutscene_clock='original'):
    if mode not in MODES:
        raise PatchError(f'unknown frame-rate mode {mode!r}')
    if mode in ('30', '60-fixed'):
        return fixed.SITES
    p, _ = dynamic_program(cutscene_clock)
    cap = 0x52800001 if mode == 'dynamic-unlocked' else 0x52800021  # mov w1,#0 / #1
    result = [(0x9D2BB4, 0x1A9F1501, cap, 'initial present interval'),
              (0x9C54EC, 0x1A9F1521, cap, 'per-frame present interval'),
              (0x907A3C, 0xB40006C8, branch(0x907A3C, p.labels['first'], 0xB4000008, 19, 5),
               'first timer sample'),
              (0x907A70, 0x340001D5, branch(0x907A70, p.labels['measured']), 'real-time timer'),
              (0x485994, 0x1E380008, 0xB940D908, 'counter: whole 30 Hz ticks'),
              (0x57225C, 0xBD40D300, 0xB940DB08, 'parity counter: whole ticks'),
              (0x572260, 0x1E390008, branch(0x572260, 0x572290, 0x34000008, 19, 5),
               'parity counter: skip when no whole tick'),
              (0x39EC80, 0x1E2A5808, branch(0x39EC80, p.labels['eye'], 0x94000000), 'camera eye'),
              (0x39ECC0, 0x1E2A5828, branch(0x39ECC0, p.labels['look'], 0x94000000), 'camera look-at'),
              (0x39ED00, 0x1E29CD48, branch(0x39ED00, p.labels['up'], 0x94000000), 'camera up/blend'),
              (0x4E9F98, 0xBD407E60, branch(0x4E9F98, p.labels['ramp']), 'whole-tick freeze ramp')]
    if cutscene_clock == 'carry':
        result.append((0x8AC3FC, 0xBD400680, branch(0x8AC3FC, p.labels['cutscene_carry']),
                       'cutscene inclusive final frame and fractional carry'))
    for addr, original, kind in HOOKS:
        leaf = leaf_hook(kind)
        dest = p.labels[f'return{addr:x}' if leaf else kind]
        result.append((addr, original, branch(addr, dest, 0x14000000 if leaf else 0x94000000), kind))
    return tuple(sorted(result))


# Structural dependencies checked as well as each replaced instruction. These establish
# the timer pointer, powf PLT, caller input registers, camera constant and return targets.
# Although the new timer bypasses the legacy floor, refuse a partially applied
# five-site patch too. A pristine hook alone must not bless a mixed input.
GUARDS = tuple((addr, word) for addr, word, _, _ in fixed.SITES if addr != 0x907A70) + (
          (0x907A24, 0x4EA01C08), (0x907A6C, 0xBD00E260), (0x907B14, 0xF9006674),
          (0x48598C, 0xF944CD08), (0x572138, 0x90004178),
          (0x4E9F94, 0xD00032E8), (0x4E9F9C, 0xBD4CD101),
          (0x9F7440, 0xD0001D30), (0x9F7444, 0xF944C611), (0x9F744C, 0xD61F0220),
          # Prologues establish that the non-leaf BL hooks preserve their callers' LR.
          (0x0D2854, 0xA9057BFD), (0x0E6FD8, 0xA9067BFD), (0x0F63A8, 0xA9027BFD),
          (0x27FEDC, 0xA9077BFD), (0x285D3C, 0xA9037BFD), (0x3051EC, 0xA9137BFD),
          (0x328958, 0xA9027BFD), (0x4E9C70, 0xA9137BFD), (0x995D28, 0xA9027BFD),
          (0x907A1C, 0xA9027BFD), (0x39EB18, 0xA90C7BFD))

CUTSCENE_GUARDS = ((0x8AC3EC, 0x1E220301), (0x8AC3F0, 0x1E283821),
                   (0x8AC3F4, 0x1E212000), (0x8AC3F8, 0x540000E9),
                   (0x8AC400, 0x1E212000), (0x8AC404, 0x54000064),
                   (0x8AC408, 0x1E2703E1), (0x8AC40C, 0xB9000277),
                   (0x8AC410, 0xBD000661), (0x8AC414, 0xA9447BFD))


def check(raw, mode='dynamic-60-cap', cutscene_clock='original'):
    """Validate the pristine build, exact segment layout and all original words before writing."""
    if mode not in MODES:
        raise PatchError(f'unknown frame-rate mode {mode!r}')
    if cutscene_clock not in ('original', 'carry'):
        raise PatchError(f'unknown cutscene clock {cutscene_clock!r}')
    if cutscene_clock == 'carry' and mode in ('30', '60-fixed'):
        raise PatchError('cutscene carry requires a dynamic build')
    table = sites(mode, cutscene_clock)
    if mode in ('30', '60-fixed'):
        return fixed.check(raw)
    # The exact original text length also rejects an already-extended/patched cave.
    flags, segs = fixed.check(raw, table)
    if segs[0][0] != 0 or len(segs[0][1]) != TEXT_SIZE or segs[1][0] != RODATA_START:
        raise PatchError('unexpected text/rodata layout; refusing to extend the lift range')
    for addr, word in (*GUARDS, *(CUTSCENE_GUARDS if cutscene_clock == 'carry' else ())):
        got = struct.unpack_from('<I', segs[0][1], addr)[0]
        if got != word:
            raise PatchError(f'guard {addr:#x}: found {got:#010x}, expected {word:#010x}')
    return flags, segs


def patch(raw, mode='dynamic-60-cap', cutscene_clock='original'):
    """Return a new NSO; caller's input is unchanged. 30 returns the pristine bytes."""
    raw = bytes(raw)
    _, segs = check(raw, mode, cutscene_clock)
    if mode == '30':
        return raw
    if mode == '60-fixed':
        return fixed.patch(raw)
    _, cave = dynamic_program(cutscene_clock)
    segs[0][1].extend(cave)  # extend .text itself; padding outside it is invisible to the lifter
    for addr, _, new, _ in sites(mode, cutscene_clock):
        struct.pack_into('<I', segs[0][1], addr, new)
    return fixed.write_segments(raw, segs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mode', choices=MODES, default='dynamic-60-cap')
    parser.add_argument('--cutscene-clock', choices=('original', 'carry'), default='original',
                        help='optional fractional scene-boundary correction; see measured acceptance gates')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('main', type=Path)
    parser.add_argument('out', type=Path, nargs='?')
    args = parser.parse_args(argv)
    if not args.check and not args.out:
        parser.error('give an output path or --check')
    try:
        raw = args.main.read_bytes()
        if args.check:
            check(raw, args.mode, args.cutscene_clock)
        else:
            data = patch(raw, args.mode, args.cutscene_clock)
            fixed.write_copy(args.main, args.out, data)
    except (OSError, PatchError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print(f'ok: Astral Chain 1.0.0, {args.mode}, cutscene={args.cutscene_clock}, '
          f'{len(sites(args.mode, args.cutscene_clock))} original sites checked' +
          ('' if args.check else f'; wrote {args.out}'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
