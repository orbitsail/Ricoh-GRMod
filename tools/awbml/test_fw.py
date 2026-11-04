# SPDX-License-Identifier: GPL-2.0-only
"""Runs the built firmware's RTOS (with awbLearn) in the unicorn emulator, calling the Auto estimate 0x53938B28 as the
camera does, against the same firmware without it (the v6 RTOS) and against ref.py:

  mode 0, computing call:  obj+4 / obj+0xA == ref.awbml_ref; the other gains and n20 as in v6; fallback scenes: all as v6;
  modes 1 and 2:           all four gains and n20 as in v6;
  sequences (period 4) of mixed scenes and modes against ref.AwbmlSeq;
  operator new called once and the RAM word holds the pointer; the canary check passes; r4-r11 preserved.

usage: test_fw.py [v7 RTOS.bin] [v6 RTOS.bin]  (SP paths below). Needs unicorn and the scratchpad's awbsim / grdng modules."""
import gc
import glob
import random
import struct
import sys

SPD = '/tmp/claude-0/-home-claude/4982966f-5cf0-5c25-b5a9-c2b6bab6cd69/scratchpad'
sys.path[:0] = [f'{SPD}/awbsim', f'{SPD}/grdng', str(__import__('pathlib').Path(__file__).resolve().parent)]
V7 = sys.argv[1] if len(sys.argv) > 1 else f'{SPD}/cpulut/fw8/v7/RTOS.bin'
V6 = sys.argv[2] if len(sys.argv) > 2 else f'{SPD}/cpulut/fw8/v6/RTOS.bin'

import numpy as np
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_PC, UC_ARM_REG_SP

import awb_ref as R
import fwemu
import hcommon as H
import scenes as SC
from emuutil import A_OBJ

import importlib.util
import ref
_spec = importlib.util.spec_from_file_location('awbml_scenes', __import__('pathlib').Path(__file__).resolve().parent / 'scenes.py')
MY = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(MY)

ALLOC, SLOT, CANARY_FAIL, CANARY_CMP = 0x538E09B0, 0x558372DC, 0x53938E50, 0x53938E38
STILL = 0x60700000
REC_P = 0x55A00000


def _ctx_addr(path):
    r = open(path, 'rb').read()
    wd = lambda x: struct.unpack_from('<I', r, x - 0x53000000)[0]
    w = wd(0x53938E2C); off = struct.unpack('<i', struct.pack('<I', (w & 0xffffff) << 8))[0] >> 8
    st = 0x53938E2C + 8 + off * 4
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

    def run(self, S, mode, count_insns=False, r2=0, stack=False, rec=None):
        e = self.e
        saved_blocks = H.BLOCKS
        if rec is not None:                  # a fake live view record P = 0x55A00000 with S[0] = P + 0x4D2C0 and the three float words
            H.BLOCKS = REC_P + 0x4D2C0
        S = dict(S); S['s34'] = mode
        nblk = 64 * 64
        S['flags'] = [0] * nblk
        H.setup_S(e, S, nblk)
        H.BLOCKS = saved_blocks
        if rec is not None: e.wb(REC_P + 0x38D20, struct.pack('<3I', *rec))
        e.wb(e.r32(A_OBJ + 0xAF8C), bytes(nblk + 4))
        for i, l in enumerate(LIMS): e.w16(A_OBJ + 0x6A68 + 2 * i, l)
        regs = [0xA0A0A000 + i for i in range(8)]
        for i, v in enumerate(regs): e.mu.reg_write(UC_ARM_REG_R4 + i, v)
        h = e.mu.hook_add(UC_HOOK_CODE, self.on_any) if count_insns else None
        hs = self.track_sp() if stack else None
        self.insn = 0
        e.call(0x53938B28, A_OBJ, H.SBASE, r2, count=20_000_000)
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
    for p in sorted(glob.glob(f'{SPD}/fivek_gr/*.npz'))[::40]:
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
    V8C = os.environ.get('V8C_RTOS', f'{SPD}/cpulut/fw8/v8c/RTOS.bin')
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
    # ---- 5. live view exposure mode 2 (the build's default): the exposure floats of a fake live view record at S[0] - 0x4D2C0.
    #  (a) a live call with a valid triple == a still call (at S+0x68/6E unity, so unscaled) with the same stats and v24 / e30 from the triple, == ref;
    #  (b) a live call with a rejected record, or S[0] outside RAM, == the 8.1 firmware's live call (mode 1); (c) stills with a record == 8.1's stills.
    import struct as _st
    V81 = _os.environ.get('V81_RTOS', f'{SPD}/cpulut/final2/RTOS.bin')
    fb = lambda x: _st.unpack('<I', _st.pack('<f', x))[0]
    valid = [(4.0, 7.0, 7.5), (2.0, 9.0, 4.0), (6.5, 5.0, 9.0), (3.0, 0.5, 5.0), (8.0, 3.0, 12.5), (5.0, 7.25, 8.0)]
    rejects = [(0, 0, 0), (0x7FC00000, fb(7.0), fb(7.5)), (fb(4.0), 0x7F800000, fb(7.5)), (fb(4.0), fb(7.0), 0xFF800000),
               (fb(-4.0), fb(7.0), fb(7.5)), (fb(4.0), fb(7.0), fb(-7.5)), (fb(0.5), fb(7.0), fb(7.5)), (fb(11.0), fb(7.0), fb(7.5)), (fb(4.0), fb(-6.0), fb(7.5)),
               (fb(4.0), fb(16.0), fb(7.5)), (fb(4.0), fb(7.0), fb(2.0)), (fb(4.0), fb(7.0), fb(16.0)), (fb(10.0), fb(15.0), fb(3.0)), (fb(1.0), fb(-5.0), fb(15.0)),
               (fb(1e9), fb(7.0), fb(7.5)), (0x80000000, fb(7.0), fb(7.5))]
    n5 = bad5 = nfb = nst5 = 0
    f8 = lambda x: ref.float8(fb(x))
    for si in list(range(3, len(SS), 23 if quick else 11))[:12 if quick else 30]:
        n, S0 = SS[si]
        if n.startswith('sparse'): continue
        S0 = dict(S0, g68=0x2000, g6e=0x2000)       # unity words: live equals 8.1's unscaled live
        for av, tv, sv in valid:
            na, nt, ns = f8(av), f8(tv), f8(sv)
            e = 32 * (na + nt - ns)
            if not -1800 <= e <= 3100: continue
            S = dict(S0); S['g68'] = S['g6e'] = 0x2000
            gl, _ = Fw(V7).run(S, 0, r2=0, rec=(fb(av), fb(tv), fb(sv)))
            Ss = dict(S, v24=32 * na, e30=e)
            gs, _ = Fw(V7).run(Ss, 0, r2=STILL)
            a5 = ref_args(Ss); want = ref.awbml_ref(TAB, *a5, 0)
            n5 += 1
            if want is not None and (gl[0], gl[3]) != want: bad5 += 1; bad.append(('live with record != ref', n, (av, tv, sv), gl, want))
            if gl != gs: bad5 += 1; bad.append(('live with record != still with the same exposure', n, (av, tv, sv), gl, gs))
            if want is None: nfb += 1
            gc.collect()
        g81_l, _ = Fw(V81).run(S0, 0, r2=0)
        g81_s, _ = Fw(V81).run(S0, 0, r2=STILL)
        for words in rejects:
            gl, _ = Fw(V7).run(S0, 0, r2=0, rec=words)
            n5 += 1
            if gl != g81_l: bad5 += 1; bad.append(('rejected record: live != 8.1', n, words, gl, g81_l))
        gl, _ = Fw(V7).run(S0, 0, r2=0)                           # S[0] outside RAM (the emulator's default test layout)
        n5 += 1
        if gl != g81_l: bad5 += 1; bad.append(('S[0] out of RAM: live != 8.1', n, gl, g81_l))
        for words in (valid[0], rejects[1]):
            ws = tuple(fb(x) if isinstance(x, float) else x for x in words)
            gs, _ = Fw(V7).run(S0, 0, r2=STILL, rec=ws)
            nst5 += 1
            if gs != g81_s: bad5 += 1; bad.append(('still with a record != 8.1', n, gs, g81_s))
        for mode in (1, 2):                                       # the other modes are untouched
            gl, _ = Fw(V7).run(S0, mode, r2=0, rec=(fb(4.0), fb(7.0), fb(7.5)))
            g8, _ = Fw(V81).run(S0, mode, r2=0)
            if gl != g8: bad5 += 1; bad.append(('mode != 0 differs from 8.1', n, mode))
        gc.collect()
    print(f'5. live view exposure from the record: {n5} live calls ({nfb} valid ones with a fallback result), {nst5} stills; mismatches {bad5} '
          f'(valid triple == still with the equivalent e30 == ref; rejected / out of RAM == 8.1 live; stills and modes 1, 2 == 8.1)')
    # ---- 6. live view scaling by S+0x68/6E (ctx lv_scale): with the words at 0x2000 this firmware equals the previous one (final3) on every live and still call
    #  (computing and cached, with and without a record, stills interleaved); with other words live equals the scaled reference (2b above, and the sequences of 2).
    V3 = _os.environ.get('FINAL3_RTOS', f'{SPD}/cpulut/final3/RTOS.bin')
    n6 = bad6 = 0
    for si in list(range(1, len(SS), 17 if quick else 7))[:8 if quick else 30]:
        n, S0 = SS[si]
        if n.startswith('sparse'): continue
        S = dict(S0, g68=0x2000, g6e=0x2000)
        old, new = Fw(V3), Fw(V7)
        for step, (r2, rc, mode) in enumerate([(0, None, 0), (0, None, 0), (STILL, None, 0), (0, None, 0), (0, None, 0), (0, (fb(4.0), fb(7.0), fb(7.5)), 0), (0, None, 0), (STILL, (fb(4.0), fb(7.0), fb(7.5)), 0), (0, None, 1), (0, None, 0)]):
            go, no = old.run(S, mode, r2=r2, rec=rc); gn, nn = new.run(S, mode, r2=r2, rec=rc)
            n6 += 1
            if (go, no) != (gn, nn): bad6 += 1; bad.append(('final4 != final3 at unity words', n, step, go, gn))
        del old, new
        gc.collect()
    print(f'6. live view scaling (final4 vs final3 with S+0x68/6E = 0x2000, live computing / cached / record / interleaved stills / mode 1): {n6} calls, mismatches {bad6}')
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
    prev = os.environ.get('PREV_RTOS', f'{SPD}/cpulut/fw8/v7b/RTOS.bin')
    if os.path.exists(prev):
        a, b = open(prev, 'rb').read(), open(V7, 'rb').read()
        base = 0x53000000
        wd = lambda r, x: struct.unpack_from('<I', r, x - base)[0]
        def stub_of(r):
            w = wd(r, 0x53938E2C); off = struct.unpack('<i', struct.pack('<I', (w & 0xffffff) << 8))[0] >> 8
            return 0x53938E2C + 8 + off * 4
        def ctx_of(r):
            st = stub_of(r); dec = lambda x: ((x >> 4) & 0xf000) | (x & 0xfff)
            return (dec(wd(r, st + 16)) << 16) | dec(wd(r, st + 12))
        ctx = ctx_of(b)
        diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
        outside = [hex(base + i) for i in diff if base + i < ctx and not 0x53938E2C <= base + i < 0x53938E30]
        if os.environ.get('EXPECT_SHADOW') or os.environ.get('ALLOW_SHADOW_HOOKS'): outside = [h for h in outside if not (0x5391F3A4 <= int(h, 16) < 0x5391F3A8 or 0x5404938C <= int(h, 16) < 0x54049390)]   # (checked strictly below)
        tail = hex(base + diff[-1]) if diff else None
        print(f'4. image vs {prev.split("/")[-2]}: lengths {len(a)} / {len(b)}; {len(diff)} bytes differ; outside the call word and the appended module area: {len(outside)}; '
              f'ctx {ctx_of(a):#x} -> {ctx:#x}, stub {stub_of(a):#x} -> {stub_of(b):#x}, last differing byte {tail}')
        if outside or len(a) != len(b): bad.append(('image differs elsewhere', outside[:5]))
        if os.environ.get('EXPECT_SHADOW'):
            # the final image (learned shadow correction added after this module) against the build without it: exactly the shadow hook
            # word, the Auto gain TB[4], the shadow area appended into previously zero padding, and the checksum compensation word
            hw = wd(b, 0x5391F3A4); off = struct.unpack('<i', struct.pack('<I', (hw & 0xffffff) << 8))[0] >> 8
            assert hw >> 24 == 0xEA
            sstub = 0x5391F3A4 + 8 + 4 * off                                           # the shadow stub; its first appended item is the context
            dec_ = lambda x: ((x >> 4) & 0xf000) | (x & 0xfff)
            end = (dec_(wd(b, sstub + 36)) << 16 | dec_(wd(b, sstub + 32))) - base      # the shadow context: the start of the appended shadow area
            allowed_words = {0x5391F3A4, 0x5404938C}
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
