# SPDX-License-Identifier: GPL-2.0-only
"""Runs the camera's CbCr / Y second-pass switches in the unicorn emulator, before and after the chroma NR patch.

GetCbCrFilterFlag (0x539245c0) and GetYFilterFlag (0x539244ac) are called as the camera does, with the nominal ISO
in r2, for every ISO of the camera's table (0x541d7734) and for the platform ids the lazy threshold set-up
switches on (0x538e7fd0 is stubbed to return the id). Checks:
  - platform id 2 and 5 (GR IV): CbCr flag is iso >= 12800 in the base image and iso >= 3200 in the patched image
    (off at 2500, on at 3200); the Y flag is identical in both images for every ISO (iso >= 819200, the top
    entry of the table, i.e. never in practice);
  - platform id 4: neither flag is ever on, before and after;
  - the threshold words in RAM (0x55052c5c, 0x55052c60) after the first call.

usage: emu_check.py BASE.rtos PATCHED.rtos     (the RTOS sections; build.ts writes OUT.bin.rtos next to the firmware)
"""
import struct
import sys

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UcError
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_LR, UC_ARM_REG_SP, UC_ARM_REG_PC

BASE_VA, RAM_VA, RAM_IMAGE_VA, RAM_LEN = 0x53000000, 0x55000000, 0x5437B640, 0x57480
CBCR, YFLT, PLATFORM = 0x539245C0, 0x539244AC, 0x538E7FD0
ISO_TABLE = 0x541D7734
CBCR_THR, Y_THR = 0x55052C5C, 0x55052C60
SENTINEL, STACK = 0x60001000, 0x60100000
OFFICIAL_RTOS_LEN = 0x13D2AC0


def call(rtos, fn, iso, platform):
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    size = (len(rtos) + 0xFFFF) & ~0xFFFF
    uc.mem_map(BASE_VA, size)
    uc.mem_write(BASE_VA, rtos)
    uc.mem_map(RAM_VA, 0x500000)  # RAM (image copy + the zeroed flag bytes at 0x553a0b58/9)
    off = RAM_IMAGE_VA - BASE_VA
    uc.mem_write(RAM_VA, rtos[off:off + RAM_LEN])
    uc.mem_map(0x60000000, 0x200000)
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_LR, SENTINEL)
    uc.reg_write(UC_ARM_REG_R0, 0x60080000)
    uc.reg_write(UC_ARM_REG_R1, 1)
    uc.reg_write(UC_ARM_REG_R2, iso)
    uc.reg_write(UC_ARM_REG_R3, 0)
    seen = {'bad': None}

    def hook(u, address, size, _):
        if address == PLATFORM:  # stub: the platform id of the board
            u.reg_write(UC_ARM_REG_R0, platform)
            u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))
        elif address == 0x538EC838 or address == 0x538ED930:  # the error reporting of an unknown id
            seen['bad'] = address
            u.emu_stop()
        elif address == SENTINEL:
            u.emu_stop()

    uc.hook_add(UC_HOOK_CODE, hook)
    try:
        uc.emu_start(fn, SENTINEL, count=5000)
    except UcError as e:
        raise SystemExit(f'emulation error at iso {iso}: {e}')
    if seen['bad']:
        raise SystemExit(f'error path {seen["bad"]:#x} reached (platform {platform}, iso {iso})')
    r0 = uc.reg_read(UC_ARM_REG_R0)
    thr = struct.unpack('<II', bytes(uc.mem_read(CBCR_THR, 4)) + bytes(uc.mem_read(Y_THR, 4)))
    return r0, thr


def main():
    base = open(sys.argv[1], 'rb').read()
    patched = open(sys.argv[2], 'rb').read()
    table = []
    for i in range(200):  # the camera's nominal ISO table runs up to 819200, then holds other data
        v = struct.unpack_from('<I', base, ISO_TABLE - BASE_VA + 4 * i)[0]
        if table and v < table[-1]:
            break
        table.append(v)
    isos = sorted(set(i for i in table if i >= 100))
    fails = 0
    diff = [i for i in range(min(len(base), len(patched), OFFICIAL_RTOS_LEN)) if base[i] != patched[i]]
    print('official-length RTOS bytes that differ:', [hex(BASE_VA + i) for i in diff])
    for platform in (2, 5, 4):
        rows = []
        for iso in isos:
            cb0, t0 = call(base, CBCR, iso, platform)
            cb1, t1 = call(patched, CBCR, iso, platform)
            y0, ty0 = call(base, YFLT, iso, platform)
            y1, ty1 = call(patched, YFLT, iso, platform)
            rows.append((iso, cb0, cb1, y0, y1))
            if platform in (2, 5):
                want0, want1, wanty = int(iso >= 12800), int(iso >= 3200), int(iso >= 819200)
            else:
                want0 = want1 = wanty = 0
            if cb0 != want0 or cb1 != want1 or y0 != y1 or y0 != wanty:
                fails += 1
                print('FAIL', platform, iso, cb0, cb1, y0, y1)
        _, t0 = call(base, CBCR, 100, platform)
        _, t1 = call(patched, CBCR, 100, platform)
        print(f'platform {platform}: CbCr threshold base={t0[0]} patched={t1[0]}; Y threshold (word at 0x55052c60) base={t0[1]} patched={t1[1]}')
        print('  iso : CbCr base -> patched | Y base -> patched')
        for iso, a, b, c, d in rows:
            if iso in (800, 1600, 2000, 2500, 3200, 4000, 6400, 12800, 25600, 204800, 819200):
                print(f'  {iso:6d}: {a} -> {b}            | {c} -> {d}')
    print('ISO values tested:', len(isos), ' failures:', fails)
    sys.exit(1 if fails else 0)


main()
