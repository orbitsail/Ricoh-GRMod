"""Run the real firmware shadow-correction core (0x53947230) in unicorn on synthetic block-luma arrays."""
import os
import sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fwemu import Emu
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
import numpy as np

F_CORE = 0x53947230
SB, PREC, THIS, OUTB, CURVE, LVL = 0x60000000, 0x60100000, 0x60800000, 0x60810000, 0x60820000, 0x60830000

def new_emu():
    e = Emu()
    e.mu.mem_map(0x60000000 + 0x04000000 if False else 0x64000000, 0x1000) if False else None
    def skip(uc, addr, size, user): uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
    e.mu.hook_add(UC_HOOK_CODE, skip, begin=0x5391F1D4, end=0x5391F1D4+4)   # stat->Y builder: array is supplied by the test
    return e

def run(e, ysamples, w=64, h=62, setting=0, hl=0, idx44=40, mode=0, b8a=0, b8b=0):
    """ysamples: u16 array of w*h block luma values (P+0x24BD0). Returns dict."""
    mu = e.mu
    mu.mem_write(SB, bytes(0x200)); mu.mem_write(THIS, bytes(0x900)); mu.mem_write(OUTB, bytes(0x2000)); mu.mem_write(CURVE, bytes(0x800)); mu.mem_write(LVL, bytes(8))
    e.w32(0x553A284C, 0); mu.mem_write(0x553A283C, bytes(2)); mu.mem_write(0x553A2840, bytes(10))
    e.w16(PREC + 0xBB8, w); e.w16(PREC + 0xBBA, h)
    arr = np.asarray(ysamples, dtype='<u2')
    assert arr.size == w*h
    mu.mem_write(PREC + 0x24BD0, arr.tobytes())
    e.w32(SB + 0x130, PREC)
    mu.mem_write(SB + 0x53, bytes([hl])); mu.mem_write(SB + 0x54, bytes([setting]))
    e.w16(SB + 0x44, idx44); mu.mem_write(SB + 0x8D, bytes([mode]))
    mu.mem_write(SB + 0x8A, bytes([b8a])); mu.mem_write(SB + 0x8B, bytes([b8b]))
    e.w32(THIS + 0x828, CURVE)
    r = e.call(F_CORE, THIS, THIS + 0x14, OUTB, SB, LVL)
    return dict(ret=r, level=e.r16(LVL), strength=e.r16(THIS+0x822), lut=bytes(mu.mem_read(OUTB, 0x1000)), curve=bytes(mu.mem_read(CURVE, 0x800)),
                recomputed=e.rb(THIS+0x821,1)[0], hist_dummy=None)

if __name__ == '__main__':
    e = new_emu()
    rng = np.random.default_rng(1)
    for base in (0, 20, 40, 60, 80, 100):
        y = rng.integers(base, base+400, 64*62)
        r = run(e, y, setting=0)
        print('auto base', base, 'ret', r['ret'], 'strength', r['strength'], 'level', r['level'])
