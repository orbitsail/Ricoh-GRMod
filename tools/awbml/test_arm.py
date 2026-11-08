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
from unicorn import UC_HOOK_MEM_READ
from test_host import OBJ_SIZE, gen_random, pack_case, lv_store, make_rd, f32bits, CFG, PAD

CODE, BLOB, CTX, MEM, OBJ, STACK, HEAP, STUB = 0x10000000, 0x20000000, 0x30000000, 0x40000000, 0x50000000, 0x60000000, 0x70000000, 0x80000000


def build_code(extra=()):
    cc, ld, oc = gen.tools()
    with tempfile.TemporaryDirectory() as t:
        return gen.build(cc, ld, oc, Path(t), CODE, extra)


def main(n_scenes=40, n_random=80):
    tab, blob, offs = ref.build_tables()
    ccfg = {k: v + MEM for k, v in CFG.items()}
    code = build_code(tuple('-DAWBML_%s=0x%08Xu' % (n, ccfg[k]) for n, k in (('GUARD_ADDR', 'guard'), ('ESLOT_ADDR', 'eslot'), ('RAM_LO', 'lo'), ('RAM_HI', 'hi'), ('RAM2_LO', 'lo2'), ('RAM2_HI', 'hi2'))))   # the test's property store addresses
    rng = np.random.default_rng(777)
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for base, size in ((CODE, 0x10000), (BLOB, 0x20000), (CTX, 0x1000), (MEM, 0x400000), (OBJ, 0x10000), (STACK, 0x10000), (HEAP, 0x20000), (STUB, 0x1000)):
        uc.mem_map(base, size, UC_PROT_ALL)
    uc.mem_write(CODE, code)
    uc.mem_write(BLOB, blob)
    uc.mem_write(STUB, struct.pack('<II', 0xE3A00207, 0xE12FFF1E))     # alloc: mov r0, #0x70000000; bx lr
    uc.mem_write(STUB + 8, struct.pack('<I', 0xE320F000) * 2)           # return address: nop
    ctx = [ref.MAGIC, STUB, CTX + 0x100] + [BLOB + offs[n] for n in ref.TABLE_ORDER] + [1, 0, 0, 0]   # lv_scale off here; period 1: every call computes; AF89 clearing off; live-view exposure mode 0
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
    uc.mem_write(CTX + 4 * (len(ctx) - 4), struct.pack('<I', ref.PERIOD))
    sbad = scalls = 0
    nrec = [0]
    ccfg_off = {k: v + MEM for k, v in CFG.items()}
    pool = [c for c in cases[:n_scenes + 6]]
    for q in range(24):
        af89 = q % 2
        lv = int(rng.choice([0, 1, 2, 2, 2]))
        uc.mem_write(CTX + 4 * (len(ctx) - 3), struct.pack('<I', af89))
        uc.mem_write(CTX + 4 * (len(ctx) - 2), struct.pack('<I', lv))
        lvs = int(rng.random() < 0.75)
        unity = lvs and q % 4 == 3                       # S words all 0x2000: lv_scale on must equal the unscaled model (final3)
        uc.mem_write(CTX + 4 * (len(ctx) - 1), struct.pack('<I', lvs))
        seq = ref.AwbmlSeq(tab, ref.PERIOD, lv, 0 if unity else lvs)
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
            rec, tears, info, s70 = None, [], None, 2
            if lv == 2 and rng.random() < 0.8:
                lab, rec, info = lv_store(rng)
                if rng.random() < 0.06: s70 = 4
                if rng.random() < 0.15:
                    cand = [info['X'], info['X'] + 4] + [info['a'] + 0x4D8 + 4 * k for k in range(3)] + [info['b'] + 0x4D8]
                    for _ in range(int(rng.choice([1, 1, 2]))):
                        tears.append((int(rng.integers(4, 24)), int(rng.choice(cand)), int(rng.choice([0, info['b'] + MEM, info['a'] + MEM, int(rng.integers(0, 2 ** 32)), f32bits(4.0), f32bits(7.0)]))))
            mem, s_off, obj, a = pack_case(*arrs, p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], rng, rec=rec, s70=s70)
            mem = bytearray(mem).ljust(PAD + 0x1000, b'\0')
            if rec is not None:                          # the four pointer slots hold absolute addresses here
                for ad in (CFG['eslot'], info['E'] + 0x518, info['X'], info['X'] + 4):
                    if ad + 4 <= PAD and struct.unpack_from('<I', mem, ad)[0]:
                        struct.pack_into('<I', mem, ad, (struct.unpack_from('<I', mem, ad)[0] + MEM) & 0xFFFFFFFF)
            if unity:
                struct.pack_into('<H', mem, s_off + 0x68, 0x2000); struct.pack_into('<H', mem, s_off + 0x6E, 0x2000)
            for k in range(5):
                struct.pack_into('<I', mem, s_off + 4 * k, MEM + struct.unpack_from('<I', mem, s_off + 4 * k)[0])
            rd0 = make_rd(mem, tears)
            raddr = []
            _rd = rd0
            def rd0(a, _rd=_rd): raddr.append(a); return _rd(a)
            lv_ev = ref.lv_exposure(lambda ad: rd0((ad - MEM) & 0xFFFFFFFF), s70, ccfg_off)
            nrec[0] += lv_ev is not None
            hk = None
            cnt_ = [0]; carr = []
            if True:
                def on_read(uc_, access, address, size, value, ud):
                    carr.append(address)
                    for n_, ad_, v_ in tears:
                        if n_ == cnt_[0]: uc_.mem_write(MEM + ad_, struct.pack('<I', v_))
                    cnt_[0] += 1
                hk = uc.hook_add(UC_HOOK_MEM_READ, on_read, begin=MEM, end=MEM + PAD - 1)
            uc.mem_write(MEM, bytes(mem)); uc.mem_write(OBJ, obj)
            uc.reg_write(UC_ARM_REG_R0, CTX); uc.reg_write(UC_ARM_REG_R1, OBJ); uc.reg_write(UC_ARM_REG_R2, MEM + s_off); uc.reg_write(UC_ARM_REG_R3, still * 0x12345)
            uc.reg_write(UC_ARM_REG_SP, STACK + 0x10000); uc.reg_write(UC_ARM_REG_LR, STUB + 8)
            slot_before = struct.unpack('<I', bytes(uc.mem_read(CTX + 0x100, 4)))[0]
            region_a = bytes(uc.mem_read(HEAP, 35468)) if still and slot_before else None
            uc.emu_start(CODE, STUB + 8)
            if hk is not None: uc.hook_del(hk)
            o = bytes(uc.mem_read(OBJ, OBJ_SIZE))
            if region_a is not None and bytes(uc.mem_read(HEAP, 35468)) != region_a :
                sbad += 1; print('STILL WROTE THE LIVE VIEW REGION')
            got = None if o == obj else (struct.unpack_from('<H', o, 4)[0], struct.unpack_from('<H', o, 0xA)[0])
            want = seq.call(*[x.astype(np.int64) for x in a], p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], still=bool(still), still_s=(struct.unpack_from('<H', mem, s_off + 0x68)[0], struct.unpack_from('<H', mem, s_off + 0x6E)[0]), lv_ev=lv_ev)
            scalls += 1
            if want is None:
                if o[0xAF89] != obj[0xAF89]: sbad += 1; print('AF89 touched without a result')
            elif af89 and o[0xAF89] != 0:
                sbad += 1; print('AF89 not cleared')
            elif not af89 and o[0xAF89] != obj[0xAF89]:
                sbad += 1; print('AF89 changed while off')
            if rec is not None and carr and not still and [x - MEM for x in carr] != [x & 0xFFFFFFFF for x in raddr][:len(carr)]:
                sbad += 1; print('READ ORDER MISMATCH', [hex(x - MEM) for x in carr][:30], [hex(x & 0xffffffff) for x in raddr][:30])
            if got != want:
                sbad += 1; print('SEQ MISMATCH', got, want, 'still', still, 'lv', lv, 'rec', rec and lab, 'tears', tears, 's70', s70, 'lv_ev', lv_ev, 'scale', lvs, unity)
                print('   C reads', [hex(x - MEM) for x in carr][:30], '\n   ref reads', [hex(x & 0xffffffff) for x in raddr][:30])
    print(f'ARM (unicorn) sequences (period {ref.PERIOD}, temporal filter, interleaved stills, AF89 on/off, live view exposure modes 0/1/2): {scalls} calls ({nrec[0]} with a usable record), {sbad} mismatches')
    bad += sbad
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main(*[int(x) for x in sys.argv[1:]])
