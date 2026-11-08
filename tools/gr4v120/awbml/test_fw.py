# SPDX-License-Identifier: GPL-2.0-only
"""Runs the built firmware's RTOS (with awbLearn) in the unicorn emulator, calling the Auto estimate 0x53960B8C as the
camera does, against the same firmware without it (the v6 RTOS) and against ref.py:

  mode 0, computing call:  obj+4 / obj+0xA == ref.awbml_ref; the other gains and n20 as in v6; fallback scenes: all as v6;
  modes 1 and 2:           all four gains and n20 as in v6;
  sequences (period 4) of mixed scenes and modes against ref.AwbmlSeq;
  operator new called once and the RAM word holds the pointer; the canary check passes; r4-r11 preserved.

usage: test_fw.py [build RTOS.bin] [v6 RTOS.bin]  (default $GRIV_BASELINES/final5 and v6). Needs unicorn, GRIV_DATA, GRIV_BASELINES, GRIV_RTOS (docs/griv-re/testing.md section 4)."""
import gc
import glob
import random
import struct
import sys

_HERE = __import__('pathlib').Path(__file__).resolve().parent
sys.path[:0] = [str(_HERE.parent / 're'), str(_HERE)]
import griv_env
V7 = sys.argv[1] if len(sys.argv) > 1 else griv_env.baseline('final5')
V6 = sys.argv[2] if len(sys.argv) > 2 else griv_env.baseline('v6')

import numpy as np
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_PC, UC_ARM_REG_SP

import awb_ref as R
import fwemu
import hcommon as H
import synth_scenes as SC
from emuutil import A_OBJ

import importlib.util
import ref
_spec = importlib.util.spec_from_file_location('awbml_scenes', __import__('pathlib').Path(__file__).resolve().parent / 'scenes.py')
MY = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(MY)

ALLOC, SLOT, CANARY_FAIL, CANARY_CMP = 0x539084BC, 0x5583901C, 0x53960EB4, 0x53960E9C
STILL = 0x60700000
# the fake property store: guard 0x5537b298, slot 0x5537b2a0 -> E (vtable at E, X at E + 0x518), X = {a, b}, the buffers (Tv, Av, Sv at a + 0x4D8 / 4DC / 4E0)
GUARD, ESLOT, FE, FX, FA = 0x5537b298, 0x5537b2a0, 0x55A10000, 0x55A20000, 0x55A30000
VTAB = 0x53FC54D8


def store_of(words, **kw):
    """{addr: u32} of a valid fake property store holding the Tv, Av, Sv words; kw overrides: guard, vt, E, X, a, b."""
    E, X, a = kw.get('E', FE), kw.get('X', FX), kw.get('a', FA)
    b = kw.get('b', a + 0x1090)
    w = {GUARD: kw.get('guard', 1), ESLOT: E, E: kw.get('vt', VTAB), E + 0x518: X, X: a, X + 4: b}
    for i, x in enumerate(words):
        w[a + 0x4D8 + 4 * i] = x
    return w


def _ctx_addr(path):
    r = open(path, 'rb').read()
    wd = lambda x: struct.unpack_from('<I', r, x - 0x53000000)[0]
    w = wd(0x53960E90); off = struct.unpack('<i', struct.pack('<I', (w & 0xffffff) << 8))[0] >> 8
    st = 0x53960E90 + 8 + off * 4
    dec = lambda x: ((x >> 4) & 0xf000) | (x & 0xfff)
    return (dec(wd(st + 16)) << 16) | dec(wd(st + 12))


CTX7 = _ctx_addr(V7)
LIMS = [0x400, 0x400, 0x80, 0x80]
TAB = ref.build_tables()[0]


class Fw:
    def __init__(self, rtos):
        fwemu.RTOS = rtos
        self.e = e = H.new_emu()
        c30, c34, c5c = R.default_cal()
        e.wb(H.CALA, struct.pack('<12H', *c30, *c34, *c5c))
        e.w32(H.CAL + 0x30, H.CALA); e.w32(H.CAL + 0x34, H.CALA + 8); e.w32(H.CAL + 0x5c, H.CALA + 16)
        self.allocs = 0
        self.canary_fail = 0
        self.canary_seen = 0
        self.insn = 0
        self.count_on = False
        def on_alloc(uc, a, s, u): self.allocs += 1
        def on_fail(uc, a, s, u): self.canary_fail += 1
        def on_cmp(uc, a, s, u): self.canary_seen += 1
        def on_any(uc, a, s, u): self.insn += 1
        e.mu.hook_add(UC_HOOK_CODE, on_alloc, begin=ALLOC, end=ALLOC + 4)
        e.mu.hook_add(UC_HOOK_CODE, on_fail, begin=CANARY_FAIL, end=CANARY_FAIL + 4)
        e.mu.hook_add(UC_HOOK_CODE, on_cmp, begin=CANARY_CMP, end=CANARY_CMP + 4)
        self.on_any = on_any
        self.callee_ok = True

    def track_sp(self):
        mu = self.e.mu
        self.sp_entry = None; self.sp_min = 1 << 40; self.sp_min_mod = 1 << 40
        def on(uc, a, s, u):
            sp = uc.reg_read(UC_ARM_REG_SP)
            if self.sp_entry is None: self.sp_entry = sp
            if sp < self.sp_min: self.sp_min = sp
            if a >= CTX7 and sp < self.sp_min_mod: self.sp_min_mod = sp
        return mu.hook_add(UC_HOOK_CODE, on)

    def run(self, S, mode, count_insns=False, r2=0, stack=False, store=None):
        e = self.e
        S = dict(S); S['s34'] = mode
        nblk = 64 * 64
        S['flags'] = [0] * nblk
        H.setup_S(e, S, nblk)
        if store is not None:
            for ad, v in store.items():
                if 0x55000000 <= ad < 0x56000000 - 4: e.w32(ad, v)
        e.wb(e.r32(A_OBJ + 0xAF8C), bytes(nblk + 4))
        for i, l in enumerate(LIMS): e.w16(A_OBJ + 0x6A68 + 2 * i, l)
        regs = [0xA0A0A000 + i for i in range(8)]
        for i, v in enumerate(regs): e.mu.reg_write(UC_ARM_REG_R4 + i, v)
        h = e.mu.hook_add(UC_HOOK_CODE, self.on_any) if count_insns else None
        hs = self.track_sp() if stack else None
        self.insn = 0
        e.call(0x53960B8C, A_OBJ, H.SBASE, r2, count=20_000_000)
        if h is not None: e.mu.hook_del(h)
        if hs is not None: e.mu.hook_del(hs)
        for i, v in enumerate(regs):
            if e.mu.reg_read(UC_ARM_REG_R4 + i) != v: self.callee_ok = False
        self.m = (e.r16(A_OBJ + 0xC), e.r16(A_OBJ + 0x12))
        return [e.r16(A_OBJ + 4 + 2 * i) for i in range(4)], e.r16(A_OBJ + 0x20)


def sw(S):
    return (S['g68'], S['g6e'])


def ref_args(S, live=False):
    P = [np.array(S['P'][k], dtype=np.int64) for k in range(5)]
    return (P[0], P[1], P[2], P[3], P[4], S['x0'], S['y0'], S['w'], S['h'], S['stride'], -0x880 if live else S['v24'], S['e30'])


def sc_of(d):
    s = np.asarray(d['s']).astype(np.int64)
    return dict(R=s[0], G=s[1], B=s[2], D=s[3], Av=d['Av'], Sv=d['Sv'], e30=int(round(d['ev'] * 256)))


def build_scenes():
    out = []
    for d in MY.load_gallery(): out.append(('gallery ' + d['name'], sc_of(d)))
    for d in MY.load_studio(): out.append(('studio ' + d['name'], sc_of(d)))
    cube, _ = MY.load_cube()
    for i in np.linspace(0, len(cube) - 1, 300).astype(int): out.append(('cube ' + cube[i]['name'], sc_of(cube[i])))
    scs = [(f'day {rid}', SC.clean(SC.day_scene(rid))) for rid in sorted(SC.ROWS)]
    rng = np.random.default_rng(4)
    for rid in list(SC.DAYLIT)[:6]:
        room = SC.relit_scene(rid, 2700, 3.5)
        scs.append((f'room {rid}', room))
        scs.append((f'lamp {rid}', SC.add_lamp(room, rng=rng, frac=0.15, dEV=3.0, wash=2.0)))
    for p in sorted(glob.glob(str(griv_env.data('fivek_gr')) + '/*.npz'))[::40]:
        room = SC.fivek_relit(p, 2700, 3.0)
        scs.append(('fivek room', room)); scs.append(('fivek lamp', SC.add_lamp(room, rng=rng, frac=0.2, dEV=3.0, wash=2.0)))
    # too few usable blocks: the camera's own result must stay (fallback), and a scene just above the 5 % line
    base = out[0][1]
    r = np.random.default_rng(11)
    for name, frac in (('sparse 1%', 0.01), ('sparse 3%', 0.03), ('sparse 0', 0.0), ('sparse 9%', 0.09), ('sparse 20%', 0.2)):
        sc = dict(base); keep = r.random(base['D'].shape) < frac
        sc['D'] = np.where(keep, np.maximum(base['D'], 1584), 100)
        out.append((name, sc))
    return out + scs


def main():
    scs = build_scenes()
    import os as _os
    quick = bool(_os.environ.get('AWBML_QUICK'))
    if quick: scs = scs[::4]
    SS = [(n, SC.settings(sc, R)) for n, sc in scs]
    kinds = {}
    for n, _ in scs: kinds[n.split()[0]] = kinds.get(n.split()[0], 0) + 1
    print('scenes', len(scs), kinds, flush=True)
    bad = []
    cnt = dict(mode0=0, mode0_ref=0, mode0_fallback=0, modes12=0)
    all_ok = dict(alloc=0, canary=0, regs=0, slot=0, fresh=0)
    ins = dict(v6=[], compute=[], cached=[], mode1=[], still=[])
    # ---- 1. every scene, modes 0, 1, 2; a fresh pair of emulators per scene and mode (so every mode 0 call computes)
    for si, (n, S) in enumerate(SS):
        if si % 50 == 0: print('  scene', si, 'of', len(SS), flush=True)
        for mode, r2 in ((0, 0), (0, STILL), (1, 0), (2, 0)):
            a, b = Fw(V6), Fw(V7)
            g6, n6 = a.run(S, mode, r2=r2)
            g7, n7 = b.run(S, mode, r2=r2)
            fresh = True
            if mode == 0:
                cnt['mode0'] += 1
                want = ref.awbml_ref(TAB, *ref_args(S, r2 == 0), 0, still_s=sw(S))     # live view: the exposure data is treated as missing; both paths scaled by S+0x68/6E
                if want is None:
                    cnt['mode0_fallback'] += 1
                    same = g7 == g6
                else:
                    cnt['mode0_ref'] += 1
                    same = (g7[0], g7[3]) == want and g7[1:3] == g6[1:3]
                    if not same: bad.append((n, mode, g7, g6, want))
                same = same and n7 == n6
            else:
                cnt['modes12'] += 1
                same = g7 == g6 and n7 == n6
            if not same: bad.append((n, mode, g7, g6, n7, n6))
            # a mode 0 call allocates once and stores the pointer; modes 1 and 2 never allocate
            exp_alloc = 1 if mode == 0 and ref.awbml_ref(TAB, *ref_args(S), 0) is not None or mode == 0 else 0
            ok_alloc = b.allocs == exp_alloc and (b.e.r32(SLOT) != 0) == (exp_alloc == 1)
            all_ok['alloc'] += ok_alloc
            all_ok['canary'] += b.canary_fail == 0 and a.canary_fail == 0 and b.canary_seen == a.canary_seen > 0
            all_ok['regs'] += b.callee_ok and a.callee_ok
            del a, b
            gc.collect()
    nrun = 4 * len(SS)
    print(f'1. per scene, mode and path (live r2=0 / still r2=record), fresh emulators: {nrun} calls ({cnt}); mismatches {len([b for b in bad])}')
    print(f'   operator new / slot as expected {all_ok["alloc"]}/{nrun}; canary check passed {all_ok["canary"]}/{nrun}; r4-r11 preserved {all_ok["regs"]}/{nrun}')
    # ---- 2. sequences with the build's period, one emulator pair per sequence, against ref.AwbmlSeq
    rng = random.Random(9)
    nseq, ncalls, seqbad = (12 if quick else 60), 0, 0
    allocs_ok = 0
    nstill = nlive_same = naf = 0
    for q in range(nseq):
        a, b, c = Fw(V6), Fw(V7), Fw(V7)       # camera alone; interleaved lives and stills; the lives alone
        af = q % 4 != 1                      # the build has it on; every fourth sequence switches it off
        lvx = (1, 0, 2)[q % 3]               # live-view exposure mode: 1, 0 (use S) or 2 (the build; no record here, so the same as 1)
        lvs = (1, 1, 0, 1)[q % 4]            # live view scaling by S+0x68/6E (the build: on)
        for fw_ in (b, c): fw_.e.w32(CTX7 + 68, int(af)); fw_.e.w32(CTX7 + 72, lvx); fw_.e.w32(CTX7 + 76, lvs)
        seq = ref.AwbmlSeq(TAB, ref.PERIOD, lvx, lvs)
        ptr = None
        still_p = rng.choice([0.0, 0.3, 0.5])
        for step in range(rng.randrange(10, 36)):
            n, S = SS[rng.randrange(len(SS))]
            mode = rng.choice([0] * 7 + [1, 2])
            still = rng.random() < still_p
            r2 = STILL if still else 0
            g6, n6 = a.run(S, mode, r2=r2)
            g7, n7 = b.run(S, mode, r2=r2)
            want = seq.call(*ref_args(S), mode, still=still, still_s=sw(S))
            if still:                          # (a) a still equals the single-call reference on its own stats
                nstill += 1
                if want != ref.awbml_ref(TAB, *ref_args(S), mode, still_s=sw(S)): seqbad += 1; bad.append(('still != single-call ref', q, step, n))
            else:                              # (b) the live output sequence is the same without the stills
                g8, n8 = c.run(S, mode, r2=0)
                nlive_same += 1
                if g8 != g7: seqbad += 1; bad.append(('live changed by stills', q, step, n, g7, g8))
            if mode != 0: same = g7 == g6
            elif want is None: same = g7 == g6
            else: same = (g7[0], g7[3]) == want and g7[1:3] == g6[1:3]
            same = same and n7 == n6
            if af and mode == 0 and want is not None:
                naf += 1
                if bytes(b.e.mu.mem_read(A_OBJ + 0xAF89, 1)) != b'\0': seqbad += 1; bad.append(('AF89 not cleared', q, step))
            ncalls += 1
            if not same:
                seqbad += 1; bad.append(('seq', q, step, n, mode, still, g7, g6, want))
            w = b.e.r32(SLOT)
            if w and ptr is None: ptr = w
            if w and w != ptr: seqbad += 1; bad.append(('slot changed', q, step))
        allocs_ok += (b.allocs == (1 if ptr else 0)) and b.allocs <= 1 and b.canary_fail == 0 and b.callee_ok
        del a, b, c
        gc.collect()
    print(f'2. interleaved sequences (live r2=0 and stills r2=record, period {ref.PERIOD}): {nseq} sequences, {ncalls} calls ({nstill} stills; {nlive_same} live outputs compared with a run without stills; {naf} AF89-cleared checks), mismatches {seqbad}; allocation once and pointer stable, no canary failure, registers kept: {allocs_ok}/{nseq}')
    # ---- 2b. the capture gain words S+0x68 / S+0x6E: a still equals ref.awbml_ref(still_s = those words), so it scales exactly with
    # them; at 0x2000 / 0x2000 it is bit-for-bit the previous build's (v8c); a live view call ignores them (byte-identical to v8c).
    import os
    V8C = griv_env.baseline_env('V8C_RTOS', 'v8c')
    sbad2 = nsc = nunity = nlive_same = 0
    ratios = []
    for si in list(range(0, len(SS), 11))[:30]:
        n, S0 = SS[si]
        if n.startswith('sparse'): continue
        pv_s = Fw(V8C); gp_s, _ = pv_s.run(S0, 0, r2=STILL); pv_l = Fw(V8C); gp_l, _ = pv_l.run(S0, 0, r2=0)
        for cond, (s68, s6e) in (('unity', (0x2000, 0x2000)), ('capture', (round(0x2000 * 1.563), round(0x2000 * 3.019))), ('other', (0x1800 + 37 * si, 0x3000 + 91 * si))):
            S = dict(S0); S['g68'], S['g6e'] = s68, s6e
            for lab, r2 in (('live', 0), ('still', STILL)):
                ours = Fw(V7); go, _ = ours.run(S, 0, r2=r2)
                want = ref.awbml_ref(TAB, *ref_args(S, lab == 'live'), 0, still_s=(s68, s6e))     # live view scaled too
                nsc += 1
                if want is None: continue
                if (go[0], go[3]) != want: sbad2 += 1; bad.append(('scaling != ref', n, cond, lab, go, want))
                if lab == 'still':
                    if cond == 'unity':
                        nunity += 1
                        if go != gp_s: sbad2 += 1; bad.append(('still at unity differs from v8c', n, go, gp_s))
                    base_g = gp_s
                    ratios.append(((go[0] / base_g[0]) / (s68 / 0x2000), (go[3] / base_g[3]) / (s6e / 0x2000)))
                else:
                    nlive_same += 1
                    if go[:] != gp_l and cond == 'unity' and go != gp_l: sbad2 += 1; bad.append(('live differs from v8c', n, go, gp_l))
                    if cond != 'unity' and (go[0], go[3]) != want: sbad2 += 1
            gc.collect()
    r = np.array(ratios)
    print(f'2b. S+0x68/0x6E (unity / x1.563,x3.019 / other): {nsc} calls, mismatches vs ref {sbad2}; still at unity bit-identical to v8c {nunity}; live view checks {nlive_same}; '
          f'still output divided by (unity output x word / 0x2000): R {r[:, 0].min():.4f}..{r[:, 0].max():.4f}, B {r[:, 1].min():.4f}..{r[:, 1].max():.4f}')
    # ---- 5. live view exposure mode 2 (the build's default): the AE's current Tv / Av / Sv from the property store (a fake store in the emulated RAM).
    #  (a) parity with the stock still builder (0x5395BDE8, run in the emulator on a fake record with P[0xB98 / B9C / BA0] set to the same floats):
    #      its S+0x24 / S+0x30 == the module's v24 / e30, and the live output == a still call (unity words, unscaled) with that S, == ref;
    #  (b) every broken link / movie / zero words: live == the 8.1 firmware's live (mode 1) at unity words, and scaled by the words at other values;
    #  (c) stills with a store == 8.1's stills.
    import struct as _st, importlib
    from unicorn import UC_HOOK_CODE as _HC
    from unicorn.arm_const import UC_ARM_REG_R0 as _R0, UC_ARM_REG_R1 as _R1, UC_ARM_REG_SP as _SP, UC_ARM_REG_LR as _LR, UC_ARM_REG_PC as _PC
    V81 = griv_env.baseline_env('V81_RTOS', 'final2')
    fb = lambda x: _st.unpack('<I', _st.pack('<f', x))[0]
    eb = Fw(V81).e                                              # an emulator with the stock still builder
    eb.mu.hook_add(_HC, lambda uc, a_, s_, u_: uc.reg_write(_PC, uc.reg_read(_LR)), begin=0x5391f1d4, end=0x5391f1d4 + 4)
    PREC, THIS, SBP = 0x60800000, 0x60900000, 0x60A00000
    def stock_s(tv, av, sv):
        eb.wb(PREC, bytes(0x1000)); eb.wb(THIS, bytes(0x100)); eb.wb(SBP, bytes(0x100))
        eb.w32(THIS + 0x40, SBP); eb.w32(PREC + 0xB98, av); eb.w32(PREC + 0xB9C, tv); eb.w32(PREC + 0xBA0, sv)
        eb.mu.reg_write(_R0, THIS); eb.mu.reg_write(_R1, PREC); eb.mu.reg_write(_SP, 0x7e100000); eb.mu.reg_write(_LR, 0x7e000000)
        eb.mu.emu_start(0x5395BDE8, 0x5395BFD4, count=200000)
        return _st.unpack('<i', eb.rb(SBP + 0x24, 4))[0], _st.unpack('<i', eb.rb(SBP + 0x30, 4))[0]
    rr = random.Random(5)
    trip = [(4.0, 7.0, 7.5), (2.0, 9.0, 4.0), (6.5, 5.0, 9.0), (3.0, 0.5, 5.0), (8.0, 3.0, 12.5), (5.0, 7.25, 8.0), (1.0, -5.0, 3.0), (10.125, 15.125, 15.125)]
    for _ in range(40 if quick else 220):
        k = rr.random()
        av, sv = rr.uniform(0.5, 10.5), rr.uniform(2.5, 15.5)
        tv = max(-5.5, min(15.5, sv - av + rr.uniform(-3, 3)))
        if k < 0.35: av, tv, sv = (round(x * 8) / 8 for x in (av, tv, sv))
        w = [fb(tv), fb(av), fb(sv)]
        if k > 0.6: w = [(x + rr.choice([-3, -2, -1, 0, 1, 2, 3])) & 0xFFFFFFFF for x in w]
        trip.append(tuple(_st.unpack('<f', _st.pack('<I', x))[0] for x in w))
    n5 = bad5 = nacc = nst5 = nstock = 0
    for si in list(range(3, len(SS), 23 if quick else 11))[:12 if quick else 30]:
        n, S0 = SS[si]
        if n.startswith('sparse'): continue
        S0 = dict(S0, g68=0x2000, g6e=0x2000, mode70=2)
        g81_l, _ = Fw(V81).run(S0, 0, r2=0)
        for tv, av, sv in trip[:8] + trip[8 + (si % 5)::5]:
            words = [fb(tv), fb(av), fb(sv)]
            s24, s30 = stock_s(*words); nstock += 1
            q = [ref.fl8(words[1], 68), ref.fl8(words[0], 68), ref.fl8(words[2], -8)]
            if None not in q:
                na, nt, ns = q[0] - 68, q[1] - 68, q[2] + 8
                if (32 * na, 32 * (na + nt - ns)) != (s24, s30): bad5 += 1; bad.append(('module quantiser != stock still builder', words, (32 * na, 32 * (na + nt - ns)), (s24, s30)))
            stw = store_of(words)
            exp = ref.lv_exposure(lambda ad: stw.get(ad, 0), 2, ref.FW_CFG)
            gl, _ = Fw(V7).run(S0, 0, r2=0, store=stw)
            n5 += 1
            if exp is not None:
                nacc += 1
                if exp != (s24, s30): bad5 += 1; bad.append(('module exposure != stock', words, exp, (s24, s30)))
                Ss = dict(S0, v24=s24, e30=s30)
                gs, _ = Fw(V7).run(Ss, 0, r2=STILL)
                want = ref.awbml_ref(TAB, *ref_args(Ss), 0)
                if want is not None and (gl[0], gl[3]) != want: bad5 += 1; bad.append(('live with store != ref', n, words, gl, want))
                if gl != gs: bad5 += 1; bad.append(('live with store != still with the stock S', n, words, gl, gs))
            elif gl != g81_l: bad5 += 1; bad.append(('rejected exposure: live != 8.1', n, words, gl, g81_l))
            gc.collect()
        ok = [fb(4.0), fb(7.0), fb(7.5)]
        broken = [dict(guard=0), dict(guard=2), dict(vt=VTAB + 4), dict(E=FE + 2), dict(E=0x55000000 - 4), dict(E=0x80000000), dict(X=FX + 1), dict(X=0), dict(a=FA + 2), dict(a=0),
                  dict(b=FA + 0x1094), dict(b=FA), dict(b=0), dict(a=0x55000000 - 4, b=0x55000000 - 4 + 0x1090), dict(a=0x80000000 - 0x1090 + 4, b=0x80000000 + 4), dict(a=0x53000000 - 0x1090 + 4, b=0x53000000 + 4),
                  dict(a=0x54000000, b=0x54000000 + 0x1090)]
        stores = [store_of(ok, **kw) for kw in broken] + [store_of([0, 0, 0]), store_of([0x7FC00000, fb(5.0), fb(8.0)]), store_of([fb(5.0), 0x7F800000, fb(8.0)])]
        for st_ in stores:
            gl, _ = Fw(V7).run(S0, 0, r2=0, store=st_)
            n5 += 1
            if gl != g81_l: bad5 += 1; bad.append(('broken store: live != 8.1', n, gl, g81_l))
        gl, _ = Fw(V7).run(dict(S0, mode70=4), 0, r2=0, store=store_of(ok))             # movie
        g81m, _ = Fw(V81).run(dict(S0, mode70=4), 0, r2=0)
        n5 += 1
        if gl != g81m: bad5 += 1; bad.append(('movie: live != 8.1', n, gl, g81m))
        S1 = dict(S0, g68=0x2800 + 7 * si, g6e=0x1900 + 11 * si)                          # fallback live view is 8.1's scaled by the words
        gl, _ = Fw(V7).run(S1, 0, r2=0)
        want = (ref.scale_gain(g81_l[0], S1['g68']), ref.scale_gain(g81_l[3], S1['g6e']))
        n5 += 1
        if (gl[0], gl[3]) != want or gl[1:3] != g81_l[1:3]: bad5 += 1; bad.append(('fallback live != 8.1 scaled', n, gl, g81_l, want))
        g81_s, _ = Fw(V81).run(S0, 0, r2=STILL)
        for words in (ok, [0x7FC00000, 1, 2]):
            gs, _ = Fw(V7).run(S0, 0, r2=STILL, store=store_of(words))
            nst5 += 1
            if gs != g81_s: bad5 += 1; bad.append(('still with a store != 8.1', n, gs, g81_s))
        for mode in (1, 2):                                       # the other modes are untouched
            gl, _ = Fw(V7).run(S0, mode, r2=0, store=store_of(ok))
            g8, _ = Fw(V81).run(S0, mode, r2=0)
            if gl != g8: bad5 += 1; bad.append(('mode != 0 differs from 8.1', n, mode))
        gc.collect()
    print(f'5. live view exposure from the property store: {n5} live calls ({nstock} stock still builder runs, {nacc} accepted exposures), {nst5} stills; mismatches {bad5}')
    # ---- 6. final5 vs the previous firmware (final4) where the exposure source is unusable (no store): identical live and still outputs with S+0x68/6E = 0x2000, computing / cached / interleaved
    V3 = griv_env.baseline_env('FINAL3_RTOS', 'final4')
    n6 = bad6 = 0
    for si in list(range(1, len(SS), 17 if quick else 7))[:8 if quick else 30]:
        n, S0 = SS[si]
        if n.startswith('sparse'): continue
        S = dict(S0, g68=0x2000, g6e=0x2000)
        old, new = Fw(V3), Fw(V7)
        for step, (r2, mode) in enumerate([(0, 0), (0, 0), (STILL, 0), (0, 0), (0, 0), (0, 0), (0, 0), (STILL, 0), (0, 1), (0, 0)]):
            go, no = old.run(S, mode, r2=r2); gn, nn = new.run(S, mode, r2=r2)
            n6 += 1
            if (go, no) != (gn, nn): bad6 += 1; bad.append(('final5 != previous at unity words without a store', n, step, go, gn))
        del old, new
        gc.collect()
    print(f'6. final5 vs the previous firmware, no usable store, S+0x68/6E = 0x2000 (live computing / cached / interleaved stills / mode 1): {n6} calls, mismatches {bad6}')
    # ---- 3. instruction counts (unicorn) on a few scenes: the camera's own Auto estimate, ours computing / cached / leaving
    pick = [SS[i % len(SS)] for i in (0, 10, 36, 80, 140, 200, len(SS) - 30, len(SS) - 5)]
    for n, S in pick:
        a = Fw(V6); g, _ = a.run(S, 0, True); ins['v6'].append(a.insn)
        b = Fw(V7)
        b.run(S, 0, True); ins['compute'].append(b.insn)
        b.run(S, 0, True); ins['cached'].append(b.insn)
        b.run(S, 1, True); ins['mode1'].append(b.insn)
        d_ = Fw(V7); d_.run(S, 0, True, r2=STILL); ins['still'].append(d_.insn)
    for label, r2 in (('live view', 0), ('still', STILL)):
        lo, lom = [], []
        for n, S in pick[:5]:
            for fresh in (True, False):
                w = Fw(V7)
                if not fresh: w.run(S, 0, r2=r2)
                w.run(S, 0, r2=r2, stack=True); lo.append(w.sp_entry - w.sp_min); lom.append(w.sp_entry - w.sp_min_mod)
        print(f'3. stack, {label}: deepest SP below the estimate entry {max(lo)} bytes (the camera\'s own estimate included); the module and stub alone reach {max(lom)} bytes below the entry SP')
    for k, v in ins.items(): print(f'3. instructions {k:8s} per call: min {min(v):,} mean {int(np.mean(v)):,} max {max(v):,}')
    v6m = np.mean(ins['v6'])
    print(f'   v6 Auto estimate alone {int(v6m):,}; this firmware: computing call +{int(np.mean(ins["compute"]) - v6m):,}, cached call +{int(np.mean(ins["cached"]) - v6m):,}; '
          f'average over a period of {ref.PERIOD}: +{int((np.mean(ins["compute"]) + (ref.PERIOD - 1) * np.mean(ins["cached"])) / ref.PERIOD - v6m):,}')
    # ---- 4. the image against the previous verified build: only the call word and the appended context / module / stub / tables differ
    import os
    if not os.environ.get('PREV_RTOS'): os.environ.setdefault('ALLOW_SHADOW_HOOKS', '1')      # the default previous build (final4) has the shadow hooks too
    prev = griv_env.baseline_env('PREV_RTOS', 'final4')
    if os.path.exists(prev):
        a, b = open(prev, 'rb').read(), open(V7, 'rb').read()
        base = 0x53000000
        wd = lambda r, x: struct.unpack_from('<I', r, x - base)[0]
        def stub_of(r):
            w = wd(r, 0x53960E90); off = struct.unpack('<i', struct.pack('<I', (w & 0xffffff) << 8))[0] >> 8
            return 0x53960E90 + 8 + off * 4
        def ctx_of(r):
            st = stub_of(r); dec = lambda x: ((x >> 4) & 0xf000) | (x & 0xfff)
            return (dec(wd(r, st + 16)) << 16) | dec(wd(r, st + 12))
        ctx = ctx_of(b)
        diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
        outside = [hex(base + i) for i in diff if base + i < ctx and not 0x53960E90 <= base + i < 0x53960E94]
        if os.environ.get('EXPECT_SHADOW') or os.environ.get('ALLOW_SHADOW_HOOKS'): outside = [h for h in outside if not (0x539473A4 <= int(h, 16) < 0x539473A8 or 0x54080044 <= int(h, 16) < 0x54080048)]   # (checked strictly below)
        tail = hex(base + diff[-1]) if diff else None
        print(f'4. image vs {prev.split("/")[-2]}: lengths {len(a)} / {len(b)}; {len(diff)} bytes differ; outside the call word and the appended module area: {len(outside)}; '
              f'ctx {ctx_of(a):#x} -> {ctx:#x}, stub {stub_of(a):#x} -> {stub_of(b):#x}, last differing byte {tail}')
        if outside or len(a) != len(b): bad.append(('image differs elsewhere', outside[:5]))
        if os.environ.get('EXPECT_SHADOW'):
            # the final image (learned shadow correction added after this module) against the build without it: exactly the shadow hook
            # word, the Auto gain TB[4], the shadow area appended into previously zero padding, and the checksum compensation word
            hw = wd(b, 0x539473A4); off = struct.unpack('<i', struct.pack('<I', (hw & 0xffffff) << 8))[0] >> 8
            assert hw >> 24 == 0xEA
            sstub = 0x539473A4 + 8 + 4 * off                                           # the shadow stub; its first appended item is the context
            dec_ = lambda x: ((x >> 4) & 0xf000) | (x & 0xfff)
            end = (dec_(wd(b, sstub + 36)) << 16 | dec_(wd(b, sstub + 32))) - base      # the shadow context: the start of the appended shadow area
            allowed_words = {0x539473A4, 0x54080044}
            extra = []
            for i in diff:
                ad = base + i
                if any(ad - w_ in range(4) for w_ in allowed_words): continue
                if i >= len(a) - 4: continue                       # compensation word
                if i >= end and i < len(a) - 16 and a[i] == 0: continue
                extra.append(hex(ad))
            print(f'4b. final vs {prev.split("/")[-2]}: hook word, TB[4], appended shadow area from {base + end:#x} (bytes that were zero) and the compensation word differ; anything else: {len(extra)} {extra[:5]}')
            if extra or len(a) != len(b): bad.append(('image differs beyond the shadow allowance', extra[:5]))
    for b_ in bad[:10]: print('MISMATCH', b_)
    print('RESULT', 'FAIL' if bad else 'all passed')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
