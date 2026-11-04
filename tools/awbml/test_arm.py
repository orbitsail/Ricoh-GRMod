# SPDX-License-Identifier: GPL-2.0-only
"""Runs the real ARM module (as gen.py builds it, linked at 0x10000000) in the unicorn CPU emulator against ref.py:
scenes from every data set plus random inputs. Also counts executed instructions for one scene. Optional (needs `unicorn`)."""
import struct
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_PROT_ALL
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

import gen
import ref
import scenes
from test_host import OBJ_SIZE, gen_random, pack_case

CODE, BLOB, CTX, MEM, OBJ, STACK, HEAP, STUB = 0x10000000, 0x20000000, 0x30000000, 0x40000000, 0x50000000, 0x60000000, 0x70000000, 0x80000000


def build_code(extra=()):
    cc, ld, oc = gen.tools()
    with tempfile.TemporaryDirectory() as t:
        return gen.build(cc, ld, oc, Path(t), CODE, extra)


def main(n_scenes=40, n_random=80):
    tab, blob, offs = ref.build_tables()
    code = build_code()
    rng = np.random.default_rng(777)
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for base, size in ((CODE, 0x10000), (BLOB, 0x20000), (CTX, 0x1000), (MEM, 0x400000), (OBJ, 0x10000), (STACK, 0x10000), (HEAP, 0x20000), (STUB, 0x1000)):
        uc.mem_map(base, size, UC_PROT_ALL)
    uc.mem_write(CODE, code)
    uc.mem_write(BLOB, blob)
    uc.mem_write(STUB, struct.pack('<II', 0xE3A00207, 0xE12FFF1E))     # alloc: mov r0, #0x70000000; bx lr
    uc.mem_write(STUB + 8, struct.pack('<I', 0xE320F000) * 2)           # return address: nop
    ctx = [ref.MAGIC, STUB, CTX + 0x100] + [BLOB + offs[n] for n in ref.TABLE_ORDER] + [1, 0, 0]   # period 1: every call computes; AF89 clearing off; live-view exposure mode 0
    uc.mem_write(CTX, struct.pack('<%dI' % len(ctx), *ctx))
    cases = []
    cube, _ = scenes.load_cube()
    sel = list(range(0, len(cube), max(1, len(cube) // n_scenes)))[:n_scenes]
    for i in sel:
        a = scenes.scene_args(cube[i]['s'], cube[i]['ev'])
        cases.append(([a[k] for k in ('R', 'Gr', 'Gb', 'B', 'cnt')], {k: a[k] for k in ('x0', 'y0', 'w', 'h', 'stride', 'v24', 'e30', 'mode')}))
    for sc in scenes.load_studio() + scenes.load_gallery()[:6]:
        a = scenes.scene_args(sc['s'], sc['ev'])
        cases.append(([a[k] for k in ('R', 'Gr', 'Gb', 'B', 'cnt')], {k: a[k] for k in ('x0', 'y0', 'w', 'h', 'stride', 'v24', 'e30', 'mode')}))
    for _ in range(n_random):
        cases.append(gen_random(rng))
    bad = ok = fb = 0
    count = [0]
    def hook(uc_, addr, size, ud):
        count[0] += 1
    first = True
    for arrs, p in cases:
        mem, s_off, obj, a = pack_case(*arrs, p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], rng)
        mem = bytearray(mem)
        for k in range(5):
            struct.pack_into('<I', mem, s_off + 4 * k, MEM + struct.unpack_from('<I', mem, s_off + 4 * k)[0])
        uc.mem_write(MEM, bytes(mem))
        uc.mem_write(OBJ, obj)
        uc.mem_write(CTX + 0x100, b'\0\0\0\0')              # slot empty: alloc is called each time
        uc.mem_write(HEAP, b'\xa5' * 0x12000)
        uc.reg_write(UC_ARM_REG_R0, CTX); uc.reg_write(UC_ARM_REG_R1, OBJ); uc.reg_write(UC_ARM_REG_R2, MEM + s_off); uc.reg_write(UC_ARM_REG_R3, 0)
        uc.reg_write(UC_ARM_REG_SP, STACK + 0x10000); uc.reg_write(UC_ARM_REG_LR, STUB + 8)
        h = None
        if first and p['mode'] == 0:
            h = uc.hook_add(UC_HOOK_CODE, hook); first = False
        t0 = time.time()
        uc.emu_start(CODE, STUB + 8)
        if h is not None:
            uc.hook_del(h); print(f'instructions for one full scene: {count[0]:,} ({time.time() - t0:.1f} s emulated)')
        o = bytes(uc.mem_read(OBJ, OBJ_SIZE))
        got = None if o == obj else (struct.unpack_from('<H', o, 4)[0], struct.unpack_from('<H', o, 0xA)[0])
        want = ref.awbml_ref(tab, *[x.astype(np.int64) for x in a], p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'])
        if got != want:
            bad += 1; print('MISMATCH', got, want, p)
        else:
            ok += 1; fb += want is None
    print(f'ARM (unicorn) vs ref: {ok + bad} cases, {bad} mismatches, {fb} fallbacks')
    # sequences with the build's period and the temporal filter: the scratch buffer stays, ref.AwbmlSeq is the model
    uc.mem_write(CTX + 4 * (len(ctx) - 3), struct.pack('<I', ref.PERIOD))
    sbad = scalls = 0
    pool = [c for c in cases[:n_scenes + 6]]
    for q in range(12):
        af89 = q % 2
        lv = int(rng.random() < 0.6)
        uc.mem_write(CTX + 4 * (len(ctx) - 2), struct.pack('<I', af89))
        uc.mem_write(CTX + 4 * (len(ctx) - 1), struct.pack('<I', lv))
        seq = ref.AwbmlSeq(tab, ref.PERIOD, lv)
        uc.mem_write(CTX + 0x100, b'\0\0\0\0')
        last = None
        for step in range(40):
            if last is not None and rng.random() < 0.55:
                arrs, p = last[0], dict(last[1])
            else:
                arrs, p = pool[int(rng.integers(0, len(pool)))]
                if not isinstance(arrs, list): arrs = list(arrs)
            last = (arrs, dict(p))
            p['mode'] = int(rng.choice([0] * 9 + [1, 2]))
            still = int(rng.random() < 0.3)
            mem, s_off, obj, a = pack_case(*arrs, p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], rng)
            mem = bytearray(mem)
            for k in range(5):
                struct.pack_into('<I', mem, s_off + 4 * k, MEM + struct.unpack_from('<I', mem, s_off + 4 * k)[0])
            uc.mem_write(MEM, bytes(mem)); uc.mem_write(OBJ, obj)
            uc.reg_write(UC_ARM_REG_R0, CTX); uc.reg_write(UC_ARM_REG_R1, OBJ); uc.reg_write(UC_ARM_REG_R2, MEM + s_off); uc.reg_write(UC_ARM_REG_R3, still * 0x12345)
            uc.reg_write(UC_ARM_REG_SP, STACK + 0x10000); uc.reg_write(UC_ARM_REG_LR, STUB + 8)
            slot_before = struct.unpack('<I', bytes(uc.mem_read(CTX + 0x100, 4)))[0]
            region_a = bytes(uc.mem_read(HEAP, 35468)) if still and slot_before else None
            uc.emu_start(CODE, STUB + 8)
            o = bytes(uc.mem_read(OBJ, OBJ_SIZE))
            if region_a is not None and bytes(uc.mem_read(HEAP, 35468)) != region_a :
                sbad += 1; print('STILL WROTE THE LIVE VIEW REGION')
            got = None if o == obj else (struct.unpack_from('<H', o, 4)[0], struct.unpack_from('<H', o, 0xA)[0])
            want = seq.call(*[x.astype(np.int64) for x in a], p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], still=bool(still), still_s=(struct.unpack_from('<H', mem, s_off + 0x68)[0], struct.unpack_from('<H', mem, s_off + 0x6E)[0]))
            scalls += 1
            if want is None:
                if o[0xAF89] != obj[0xAF89]: sbad += 1; print('AF89 touched without a result')
            elif af89 and o[0xAF89] != 0:
                sbad += 1; print('AF89 not cleared')
            elif not af89 and o[0xAF89] != obj[0xAF89]:
                sbad += 1; print('AF89 changed while off')
            if got != want:
                sbad += 1; print('SEQ MISMATCH', got, want)
    print(f'ARM (unicorn) sequences (period {ref.PERIOD}, temporal filter, interleaved stills, AF89 on/off): {scalls} calls, {sbad} mismatches')
    bad += sbad
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main(*[int(x) for x in sys.argv[1:]])
