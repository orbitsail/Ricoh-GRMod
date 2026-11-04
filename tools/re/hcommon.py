import random, struct
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from fwemu import Emu
import awb_ref as R
from emuutil import *

SBASE = 0x60400000; CAL = 0x553A130C; CALA = 0x60500000; BLOCKS = 0x60600000

def new_emu():
    e = Emu(); make_objs(e)
    e.w32(0x553A136C, 1)           # guard variable of the calibration singleton (5393CD00): treat as constructed
    # 0x5393808C builds the per-block weight map from a tuning struct: bypassed (the weight buffer is written by the test)
    def skip(uc, addr, size, user):
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
    e.mu.hook_add(UC_HOOK_CODE, skip, begin=0x5393808C, end=0x5393808C + 4)
    return e

def setup_S(e, S, nblk):
    ptrs = [BLOCKS + 0x10000 * k for k in range(5)]
    for k in range(5): e.wb(ptrs[k], struct.pack('<%dI' % nblk, *S['P'][k]))
    sb = bytearray(0x74 + nblk + 8)
    for k in range(5): struct.pack_into('<I', sb, 4 * k, ptrs[k])
    struct.pack_into('<H', sb, 0x14, S['stride']); struct.pack_into('<I', sb, 0x18, S['m18'])
    struct.pack_into('<HHHH', sb, 0x1c, S['x0'], S['y0'], S['w'], S['h'])
    struct.pack_into('<i', sb, 0x24, S['v24']); struct.pack_into('<i', sb, 0x2c, S['v2c']); struct.pack_into('<i', sb, 0x30, S['e30'])
    struct.pack_into('<I', sb, 0x34, S['s34'])
    sb[0x50] = S['b50']; sb[0x51] = S['b51']; sb[0x54] = S['b54']; sb[0x5c] = S['b5c']
    struct.pack_into('<i', sb, 0x60, S['v60'])
    for k, g in enumerate(('g64', 'g66', 'g68', 'g6a', 'g6c', 'g6e')): struct.pack_into('<H', sb, 0x64 + 2 * k, S[g])
    struct.pack_into('<I', sb, 0x70, S['mode70'])
    sb[0x74:0x74 + nblk] = bytes(S['flags'])
    e.wb(SBASE, sb)

def rand_S(rng):
    w = rng.randrange(8, 40); h = rng.randrange(6, 30); stride = w + rng.randrange(0, 4); x0 = rng.randrange(0, 3); y0 = rng.randrange(0, 3)
    nblk = (y0 + h) * stride + x0 + w + 2
    P = [[], [], [], [], []]
    base = [rng.uniform(300, 2500) for _ in range(3)]
    for i in range(nblk):
        lum = rng.uniform(0.1, 1.6)
        r = base[0] * lum * rng.uniform(0.6, 1.6); g = base[1] * lum * rng.uniform(0.8, 1.2); b = base[2] * lum * rng.uniform(0.6, 1.6)
        vals = [r, g * rng.uniform(0.97, 1.03), g * rng.uniform(0.97, 1.03), b]
        for k in range(4):
            v = int(min(vals[k], 4094)) if rng.random() > 0.03 else rng.randrange(0, 4095)
            P[k].append(max(v, 0))
        P[4].append(rng.randrange(1, 300))
    S = dict(P=P, stride=stride, m18=rng.randrange(1, 5), x0=x0, y0=y0, w=w, h=h, v24=rng.choice([-0x880, 0, 5, 0, 0]),
             v2c=rng.choice([0x800, 0xb80, 0xc00, 0xd00, 0xe00, 0xf00, 0x1000, 0x1100, rng.randrange(0, 0x1200)]),
             e30=rng.randrange(-1500, 2500), b50=rng.choice([0, 0, 1]), b51=rng.choice([0, 1]), b54=rng.choice([0, 1]), b5c=rng.choice([0, 1]),
             v60=rng.choice([rng.randrange(0, 400), rng.randrange(0xb0, 0x120)]), s34=rng.choice([0, 1, 2, 3]),
             g64=rng.randrange(0x1800, 0x2800), g66=rng.randrange(0x1800, 0x2800), g68=rng.randrange(0x1000, 0x6000), g6a=rng.randrange(0x1000, 0x6000),
             g6c=rng.randrange(0x1000, 0x6000), g6e=rng.randrange(0x1000, 0x6000),
             mode70=rng.choice([0, 1, 2, 3, 4]), flags=[rng.choice([0, 0, 0, 0, 1]) for _ in range(nblk)])
    return S, nblk

def setup_cal(e, rng):
    c30 = [rng.randrange(0x1000, 0x6000) for _ in range(4)]; c34 = [rng.randrange(0x1000, 0x6000) for _ in range(4)]; c5c = [rng.randrange(0x1000, 0x6000) for _ in range(4)]
    e.wb(CALA, struct.pack('<12H', *c30, *c34, *c5c))
    e.w32(CAL + 0x30, CALA); e.w32(CAL + 0x34, CALA + 8); e.w32(CAL + 0x5c, CALA + 16)
    return c30, c34, c5c
