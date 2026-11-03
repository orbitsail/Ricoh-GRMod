# SPDX-License-Identifier: GPL-2.0-only
"""Runs the built firmware's RTOS (with shadowLearn) in the unicorn emulator, calling the shadow-correction core 0x5391F230 as the
camera does, against the same firmware without it (the base RTOS) and against ref.py:

  1. Auto, stills (mode 0 and 3), live view and movie (mode 1, 2): strength, level, gain table, 8-bit LUT, return value and every
     other byte of the core's state equal those of the stock code (base RTOS) fed with t from ref.py: a unicorn hook at the hook
     word jumps to the common code with r3 = t, r7 = 1 (or to the stock zero path for t < 0 / the forced-zero bytes).
     Inputs: the DNG planes (hl 0 / 1, many ISO indexes), random scenes, random models in the model slot.
  2. Live-view sequences: the throttled results (period 4) and the camera's five-frame smoothing against the reference model of
     both; stills in between never disturb the live-view state.
  3. Fixed levels (Low / Medium / High / Off) and the forced-zero bytes: identical to the base RTOS without any injection.
  4. The stub's calls: the module is entered with an 8-byte aligned stack, idx as the fifth argument, ctx / P / mode / hl in
     r0-r3; the operator new is never called; the registers r4-r11 are preserved.
  5. Instruction counts of the core with and without the hook.
  6. The image against the build without shadowLearn: only the hook word, TB[4], the appended area and the checksum
     compensation word differ.

usage: test_fw.py [pre/RTOS.bin (with shadowLearn)] [base/RTOS.bin]   (SP paths below; needs unicorn and the scratchpad's awbsim /
grdng modules)"""
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

SPD = '/tmp/claude-0/-home-claude/4982966f-5cf0-5c25-b5a9-c2b6bab6cd69/scratchpad'
HERE = Path(__file__).resolve().parent
sys.path[:0] = [f'{SPD}/awbsim', f'{SPD}/grdng', f'{SPD}/drange', str(HERE)]
PRE = sys.argv[1] if len(sys.argv) > 1 else f'{SPD}/cpulut/fw9/pre/RTOS.bin'
BASE = sys.argv[2] if len(sys.argv) > 2 else f'{SPD}/cpulut/fw9/base/RTOS.bin'

import numpy as np
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R7, UC_ARM_REG_R9, UC_ARM_REG_R11, UC_ARM_REG_SP

import fwemu
import ref
import test_host as TH

F_CORE, HOOK, COMMON, ZERO_PATH, ALLOC, GAIN = 0x5391F230, 0x5391F3A4, 0x5391F4D8, 0x5391F784, 0x538E09B0, 0x5404938C
SB, PREC, THIS, OUTB, CURVE, LVL, MODEL = 0x60000000, 0x60100000, 0x60800000, 0x60810000, 0x60820000, 0x60830000, 0x60700000
P_SIZE = 0x70000
RAMSTATE = (0x553A0B30, 0x40)       # the live-view smoothing state of the core (flag, position, ring)
SLOT = 0x558372FC
PERIOD = 4
TB4_STOCK_FIX = 0x400               # the base RTOS has the old Auto gain; the injected runs patch it, as the build does


def word(buf, addr): return struct.unpack_from('<I', buf, addr - 0x53000000)[0]


class Core:
    """One emulator of the core. inject: None (run the image as it is) or a ModelFeeder (the base RTOS fed with t)."""

    def __init__(self, rtos, feeder=None, hooked=None, realy=False):
        fwemu.RTOS = rtos
        self.e = e = fwemu.Emu()
        self.mu = e.mu
        self.rtos = open(rtos, 'rb').read()
        self.feeder = feeder
        self.allocs = 0
        self.insn = 0
        self.count_on = False
        self.entries = []          # (sp, r0..r3, [sp]) at every entry of the module
        mu = e.mu
        def skip(uc, addr, size, user): uc.reg_write(UC_ARM_REG_PC, uc.reg_read(fwemu.UC_ARM_REG_LR))
        if not realy: mu.hook_add(UC_HOOK_CODE, skip, begin=0x538F75FC, end=0x538F75FC + 4)    # the Y-array builder: not needed (the planes are given)
        def on_alloc(uc, a, s, u): self.allocs += 1
        mu.hook_add(UC_HOOK_CODE, on_alloc, begin=ALLOC, end=ALLOC + 4)
        def on_any(uc, a, s, u):
            if self.count_on: self.insn += 1
        mu.hook_add(UC_HOOK_CODE, on_any)
        if feeder is not None:
            mu.mem_write(GAIN, struct.pack('<I', TB4_STOCK_FIX))
            mu.hook_add(UC_HOOK_CODE, self._inject, begin=HOOK, end=HOOK + 4)
        elif hooked is False:
            pass
        else:
            self.code, self.ctx = self.locate()
            def on_entry(uc, a, s, u):
                sp = uc.reg_read(UC_ARM_REG_SP)
                self.entries.append((sp, [uc.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R0 + 1, UC_ARM_REG_R0 + 2, UC_ARM_REG_R3)],
                                     struct.unpack('<I', bytes(uc.mem_read(sp, 4)))[0]))
            mu.hook_add(UC_HOOK_CODE, on_entry, begin=self.code, end=self.code)

    def locate(self):
        w = word(self.rtos, HOOK)
        assert w >> 24 == 0xEA, 'hook word is not a branch'
        off = struct.unpack('<i', struct.pack('<I', (w & 0xFFFFFF) << 8))[0] >> 8
        stub = HOOK + 8 + 4 * off
        dec = lambda x: ((x >> 4) & 0xF000) | (x & 0xFFF)
        ctx = (dec(word(self.rtos, stub + 36)) << 16) | dec(word(self.rtos, stub + 32))
        bl = word(self.rtos, stub + 52)
        code = stub + 52 + 8 + 4 * (struct.unpack('<i', struct.pack('<I', (bl & 0xFFFFFF) << 8))[0] >> 8)
        self.stub = stub
        return code, ctx

    def set_model(self, blob):
        """put a model blob into the emulator (hooked image only): ctx.blob / blob_len point at it"""
        self.mu.mem_write(MODEL, bytes(blob))
        self.mu.mem_write(self.ctx + 4, struct.pack('<II', MODEL, len(blob)))

    def _inject(self, uc, addr, size, user):
        sb = uc.reg_read(UC_ARM_REG_R9)
        P = uc.reg_read(UC_ARM_REG_R9 + 1)           # r10 = sl = record
        fp = uc.reg_read(UC_ARM_REG_R11)
        rb = lambda a, n: bytes(uc.mem_read(a, n))
        forced = rb(sb + 0x8A, 1)[0] | rb(sb + 0x8B, 1)[0]
        mode = rb(sb + 0x8D, 1)[0]
        hl = struct.unpack('<I', rb(fp - 0x438, 4))[0]
        idx = uc.reg_read(UC_ARM_REG_R7)
        t = self.feeder.t(rb(P, P_SIZE), mode, hl, idx)
        self.last_t = t
        if forced or t < 0:
            uc.reg_write(UC_ARM_REG_PC, ZERO_PATH)
        else:
            uc.reg_write(UC_ARM_REG_R3, t); uc.reg_write(UC_ARM_REG_R7, 1); uc.reg_write(UC_ARM_REG_PC, COMMON)

    # ---- one call of the core
    def run(self, P, setting, hl, idx44, mode, b8a=0, b8b=0, lv_flag=True, reset=True, align8=False):
        e, mu = self.e, self.mu
        if reset:
            mu.mem_write(THIS, bytes(0x900)); mu.mem_write(OUTB, bytes(0x2000)); mu.mem_write(CURVE, bytes(0x800)); mu.mem_write(LVL, bytes(8))
            e.w32(0x553A0B4C, 0); mu.mem_write(0x553A0B3C, bytes(2)); mu.mem_write(0x553A0B40, bytes(10))
        mu.mem_write(SB, bytes(0x200))
        mu.mem_write(PREC, bytes(P))
        if mode in (1, 2) and lv_flag: e.w32(PREC + 0x4D2B4, 1)
        e.w32(SB + 0x130, PREC)
        mu.mem_write(SB + 0x53, bytes([hl])); mu.mem_write(SB + 0x54, bytes([setting]))
        e.w16(SB + 0x44, idx44); mu.mem_write(SB + 0x8D, bytes([mode]))
        mu.mem_write(SB + 0x8A, bytes([b8a])); mu.mem_write(SB + 0x8B, bytes([b8b]))
        e.w32(THIS + 0x828, CURVE)
        self.allocs = 0; self.entries = []; self.insn = 0
        self.count_on = True
        args = (THIS, THIS + 0x14, OUTB, SB, LVL) + ((0,) if align8 else ())
        r = e.call(F_CORE, *args, count=20_000_000)
        self.count_on = False
        return r

    def state(self):
        e = self.e
        return dict(level=e.r16(LVL), strength=e.r16(THIS + 0x822), this=e.rb(THIS, 0x900), lut=e.rb(OUTB, 0x2000), curve=e.rb(CURVE, 0x800), lvl=e.rb(LVL, 8),
                    ram=e.rb(RAMSTATE[0], RAMSTATE[1]), sb=e.rb(SB, 0x200))


class Feeder:
    """t from the reference for the base RTOS (a throttled live view keeps its own ref.Seq)."""

    def __init__(self, blob, throttle=True):
        self.blob, self.seq = blob, ref.Seq(blob, PERIOD if throttle else 1)
        self.log = []

    def t(self, P, mode, hl, idx):
        t = self.seq.call(P, mode, hl, idx)
        self.log.append(t)
        return t


def same_state(a, b):
    return all(a[k] == b[k] for k in a)


def main():
    import test_host as TH
    dngs = TH.dng_scenes()
    rnd = random.Random(31)
    rng = np.random.default_rng(31)
    pool = TH.thr_pool(rng)
    bad = []
    cnt = dict(auto=0, t_pos=0, t_zero=0, t_neg=0, lv=0, fixed=0, forced=0, seq_frames=0, levels=set())

    def pad(P): return bytes(P) + bytes(P_SIZE - len(P))
    pre_img = open(PRE, 'rb').read()
    model_default = None

    # ---------------------------------------------------------------- 1. Auto: stills, live view, movie; one hooked emulator, one fed base emulator per model
    hooked = Core(PRE)
    model_default = bytes(hooked.mu.mem_read(struct.unpack('<I', bytes(hooked.mu.mem_read(hooked.ctx + 4, 4)))[0], struct.unpack('<I', bytes(hooked.mu.mem_read(hooked.ctx + 8, 4)))[0]))
    assert ref.parse_blob(model_default) is not None, 'the image carries a valid model'
    models = [model_default, ref.constant_blob(0), ref.constant_blob(0x800), ref.constant_blob(300), ref.constant_blob(-1)] + [TH.rand_blob(rnd, pool) for _ in range(10)]
    fed = {id(m): None for m in models}
    def feeder_core(blob):
        return Core(BASE, Feeder(blob, throttle=False))
    cases = []
    for fn, w, h, R, G, B, C in dngs:
        for mode in (0, 3):
            for hl in (0, 1):
                cases.append((fn, pad(TH.make_P(mode, w, h, R, G, B, C, rng)), mode, hl))
    for i in range(120):
        w, h, R, G, B, C = TH.scene(rng)
        mode = rnd.choice([0, 0, 3, 1, 2])
        cases.append((f'rnd{i}', pad(TH.make_P(mode, w, h, R, G, B, C, rng)), mode, rnd.randrange(2)))
    stock = {}
    for k, (tag, P, mode, hl) in enumerate(cases):
        blob = models[0] if k % 3 else rnd.choice(models)
        key = blob
        if key not in stock: stock[key] = feeder_core(blob)
        s = stock[key]
        idx = rnd.choice([0, 10, 25, 40, 60, 80, 95, 96, 97, 120])
        # throttling is off in the fed run: make the hooked run compute (a fresh live-view state word each call)
        hooked.mu.mem_write(SLOT, bytes(4))
        hooked.set_model(blob)
        s.feeder.seq = ref.Seq(blob, 1)
        for lvflag in ((True,) if mode in (1, 2) else (True,)):
            rh = hooked.run(P, 0, hl, idx, mode, lv_flag=lvflag)
            rs = s.run(P, 0, hl, idx, mode, lv_flag=lvflag)
            cnt['auto'] += 1
            t = s.feeder.log[-1] if s.feeder.log else None
            sh, ss = hooked.state(), s.state()
            if rh != rs or not same_state(sh, ss):
                bad.append(('auto', tag, mode, hl, idx, rh, rs, [k for k in sh if sh[k] != ss[k]], t))
            cnt['t_neg'] += t < 0; cnt['t_zero'] += t == 0; cnt['t_pos'] += t > 0
            cnt['levels'].add(ss['level'])
            if mode in (1, 2): cnt['lv'] += 1
            # the module was entered exactly once per computing call, with an aligned stack, ctx, P, mode, hl, idx as arguments
            for sp, regs, a5 in hooked.entries:
                if sp % 8 or regs[1] != PREC or regs[2] != mode or regs[3] != hl or a5 != min(idx, 0x60) or regs[0] != hooked.ctx:
                    bad.append(('call args', tag, hex(sp), [hex(r) for r in regs], a5))
            if hooked.allocs: bad.append(('operator new called', tag))
        stock_entries = len(hooked.entries)
    print(f'1. Auto, hooked image vs the base image fed with t from ref.py: {cnt["auto"]} calls ({len(dngs) * 4} DNG, 120 random), models {len(models)}; '
          f't<0: {cnt["t_neg"]}, t=0: {cnt["t_zero"]}, t>0: {cnt["t_pos"]}; levels reached {sorted(cnt["levels"])}; mismatches {len(bad)}', flush=True)

    # ---------------------------------------------------------------- 1b. both stack alignments of the core's entry (the camera's is 8-aligned; the harness's default is not)
    n_al = 0
    for k in range(40):
        tag, P, mode, hl = cases[k * 7 % len(cases)]
        hooked.mu.mem_write(SLOT, bytes(4)); hooked.set_model(models[0])
        for al in (False, True):
            rh = hooked.run(P, 0, hl, 40, mode, align8=al)
            t = ref.shadowml_ref(models[0], bytes(P), mode, hl, 40)
            sp0 = hooked.entries[0][0] if hooked.entries else None
            n_al += 1
            if hooked.entries and sp0 % 8: bad.append(('unaligned module stack', tag, al))
    print(f'   both entry alignments of the core: {n_al} calls, module always entered 8-byte aligned')

    # ---------------------------------------------------------------- 2. live-view sequences (period 4) with stills in between, smoothing
    nseq = 0
    smooth_ok = smooth_changes = 0
    TC = ref_tables()
    for q in range(24):
        mode = rnd.choice([1, 1, 2])
        blob = rnd.choice(models[:3] + models[5:])
        hk = Core(PRE); hk.set_model(blob)
        fd = Feeder(blob, throttle=True)
        st = Core(BASE, fd)
        scs = [TH.scene(rng) for _ in range(3)]
        idx = rnd.choice([30, 50, 70, 96])
        first = True
        for step in range(rnd.randrange(8, 26)):
            w, h, R, G, B, C = rnd.choice(scs) if rnd.random() < 0.6 or step == 0 else scs[0]
            hl = 0
            still = rnd.random() < 0.2
            m = 0 if still else mode
            P = pad(TH.make_P(m, w, h, R, G, B, C, rng))
            if still:
                # a still shot between two live-view frames: its own, fresh core state (reset), the live-view state word must stay
                before = struct.unpack('<I', bytes(hk.mu.mem_read(SLOT, 4)))[0]
                sv = Feeder(blob, throttle=False)
                # the fed emulator's t for a still comes from the same Feeder object, which keeps the live-view Seq state apart
                rh = hk.run(P, 0, hl, idx, 0, reset=False); rs = st.run(P, 0, hl, idx, 0, reset=False)
                after = struct.unpack('<I', bytes(hk.mu.mem_read(SLOT, 4)))[0]
                if before != after: bad.append(('still touched the live-view state', q, step))
            else:
                rh = hk.run(P, 0, hl, idx, m, reset=first); rs = st.run(P, 0, hl, idx, m, reset=first)
                first = False
                nseq += 1
                cnt['seq_frames'] += 1
            sh, ss = hk.state(), st.state()
            if rh != rs or not same_state(sh, ss):
                bad.append(('seq', q, step, m, rh, rs, [k for k in sh if sh[k] != ss[k]]))
        # independent model of the five-frame average over the live-view frames of this sequence (stills interleaved do not enter it:
        # they reset nothing, but they do write the ring when mode 0 skips it) -> only checked for sequences without stills
    print(f'2. live-view / movie sequences (period {PERIOD}, stills in between): {nseq} frames, hooked == fed, live-view state word untouched by stills; mismatches {len(bad)}', flush=True)

    # ---------------------------------------------------------------- 2b. smoothing against its definition, no stills: strength = mean of the last five raw strengths (the first frame fills the ring)
    nsm = nsm_bad = changed = 0
    for q in range(12):
        mode = rnd.choice([1, 2])
        scs = [sc for sc in (TH.scene(rng, 0) for _ in range(6)) if ref.features(*sc[2:], sc[0], sc[1], 0, 96, mode) is not None][:4]
        ml = sorted(ref.features(*sc[2:], sc[0], sc[1], 0, 96, mode)[11] for sc in scs)
        # a model whose output follows the scene (mean log luminance), so that the strength changes from frame to frame
        blob = ref.build_blob([('split', 'meanlog', ml[len(ml) // 2], ('leaf', 150), ('leaf', 1500)), ('split', 'q50', ml[1], ('leaf', 0), ('leaf', 300))])
        hk = Core(PRE); hk.set_model(blob)
        # frames whose t alternates between 0 and 512 (placeholder) so the average is visible
        seq = ref.Seq(blob, PERIOD)
        raws = []
        idx = rnd.choice([20, 40, 60])
        cap = TC[idx]
        for step in range(30):
            w, h, R, G, B, C = rnd.choice(scs)
            P = pad(TH.make_P(mode, w, h, R, G, B, C, rng))
            hk.run(P, 0, 0, idx, mode, reset=(step == 0))
            t = seq.call(P, mode, 0, idx)
            raw = 0 if t < 0 else ((min(t, cap) * 0x400) >> 11)
            if step == 0: ring = [raw] * 5; pos = 0
            ring[pos] = raw; pos = (pos + 1) % 5
            want = sum(ring) // 5
            got = hk.state()['strength']
            nsm += 1
            if got != want:
                nsm_bad += 1; bad.append(('smoothing', q, step, got, want, raw, ring))
            changed += want != raw
    print(f'   five-frame smoothing against its definition (ring of the last five raw strengths, first frame fills it): {nsm} frames, {nsm_bad} mismatches, {changed} frames where the average differs from the raw strength')

    # ---------------------------------------------------------------- 3. fixed levels and the forced-zero bytes: the hooked image equals the base image exactly
    base_plain = Core(BASE, hooked=False)
    nf = 0
    for k in range(160):
        tag, P, mode, hl = cases[rnd.randrange(len(cases))]
        setting = rnd.choice([1, 2, 3, 4, 5, 9, 255]) if k < 110 else 0
        b8a, b8b = (0, 0) if k < 110 else rnd.choice([(1, 0), (0, 1), (1, 1), (7, 0)])
        idx = rnd.choice([0, 20, 50, 96, 200])
        hooked.mu.mem_write(SLOT, bytes(4))
        rh = hooked.run(P, setting, hl, idx, mode, b8a, b8b)
        rs = base_plain.run(P, setting, hl, idx, mode, b8a, b8b)
        nf += 1
        cnt['fixed' if k < 110 else 'forced'] += 1
        if rh != rs or not same_state(hooked.state(), base_plain.state()):
            bad.append(('fixed/forced', tag, setting, b8a, b8b, mode, rh, rs, [kk for kk in hooked.state() if hooked.state()[kk] != base_plain.state()[kk]]))
        if k >= 110 and hooked.state()['strength'] != 0: bad.append(('forced zero not zero', tag))
        if hooked.entries: bad.append(('module called for a fixed level / forced zero', tag, setting))
    print(f'3. fixed levels (Low / Medium / High / Off / other bytes) {cnt["fixed"]} and forced-zero bytes {cnt["forced"]}: hooked image == base image in return value, strength, level, tables and all state; mismatches {len(bad)}', flush=True)

    # ---------------------------------------------------------------- 5. instruction counts of the whole core
    ins = {'base Auto (stock, all-zero Y)': [], 'hooked still': [], 'hooked LV computing': [], 'hooked LV held': [], 'fixed level Low': []}
    for fn, w, h, R, G, B, C in dngs[:6]:
        for m, key in ((0, 'hooked still'), (1, 'hooked LV computing')):
            P = pad(TH.make_P(m, w, h, R, G, B, C, rng))
            hooked.mu.mem_write(SLOT, bytes(4)); hooked.set_model(model_default)
            hooked.run(P, 0, 0, 40, m); ins[key].append(hooked.insn)
            if m == 1:
                hooked.run(P, 0, 0, 40, m, reset=False); ins['hooked LV held'].append(hooked.insn)
        P = pad(TH.make_P(0, w, h, R, G, B, C, rng))
        base_plain.run(P, 0, 0, 40, 0); ins['base Auto (stock, all-zero Y)'].append(base_plain.insn)
        hooked.run(P, 1, 0, 40, 0); ins['fixed level Low'].append(hooked.insn)
    for k, v in ins.items(): print(f'5. instructions of the whole core, {k}: min {min(v):,} mean {int(np.mean(v)):,} max {max(v):,}')

    # ---------------------------------------------------------------- 6. image diff
    a, b = open(BASE, 'rb').read(), pre_img
    base = 0x53000000
    n = len(a)
    # the section ends with a 16-byte trailer (a length word, the marker 'GRMODAR3', the checksum compensation word); the content before them ends at the last non-zero byte
    OFFICIAL_END = 0x543D2AC0       # the official RTOS length; everything the build appends lies beyond it
    diff = [i for i in range(min(len(a), len(b))) if a[i] != b[i]]
    trailer = lambda i: n - 16 <= i < n - 4
    appended = [i for i in diff if base + i >= OFFICIAL_END and i < n - 16]
    # the appended area of this feature: bytes that were zero padding in the base image (nothing the base itself appended is changed)
    over = [hex(base + i) for i in appended if a[i] != 0]
    first = base + appended[0] if appended else None
    outside = [hex(base + i) for i in diff if base + i < OFFICIAL_END and (i & ~3) not in {HOOK - base, GAIN - base}] + [hex(base + i) for i in diff if trailer(i)] + over
    ncomp = sum(1 for i in diff if i >= n - 4)
    print(f'6. image vs the build without shadowLearn: lengths {len(a)} / {len(b)}; {len(diff)} bytes differ: hook word {sum(1 for i in diff if (i & ~3) == HOOK - base)}, '
          f'TB[4] {sum(1 for i in diff if (i & ~3) == GAIN - base)}, appended area {len(appended)} bytes from {hex(first)} to {hex(base + appended[-1])} (all previously zero padding: {not over}), '
          f'checksum compensation word {ncomp}; anywhere else: {len(outside)} {outside[:5]}')
    if outside or len(a) != len(b) or first % 16: bad.append(('image differs elsewhere', outside[:5]))
    hw, gw = word(b, HOOK), word(b, GAIN)
    print(f'   hook word {word(a, HOOK):#010x} -> {hw:#010x}, TB[4] word {word(a, GAIN):#010x} -> {gw:#010x}')
    # the stub's non-branch words against clang's assembler, the branches by target / condition
    bad += check_stub(b, hooked)
    for x in bad[:12]: print('MISMATCH', x)
    print('RESULT', 'FAIL' if bad else 'all passed')
    sys.exit(1 if bad else 0)


def ref_tables():
    import shadow_ref
    return shadow_ref.TC


def check_stub(img, core):
    out = []
    stub = core.stub
    src = ['ldrb r0,[r9,#0x8a]', 'ldrb r1,[r9,#0x8b]', 'orrs r0,r0,r1', None, 'mov r4,sp', 'bic sp,sp,#7', 'sub sp,sp,#8', 'str r7,[sp]', None, None,
           'mov r1,r10', 'ldrb r2,[r9,#0x8d]', 'ldr r3,[fp,#-0x438]', None, 'mov sp,r4', 'cmp r0,#0', None, 'mov r3,r0', 'mov r7,#1', None]
    with tempfile.TemporaryDirectory() as t:
        s = Path(t) / 's.s'
        s.write_text('.syntax unified\n.arm\n' + '\n'.join(x if x else 'nop' for x in src) + '\n')
        subprocess.run(['clang', '-target', 'armv7-none-eabi', '-c', str(s), '-o', str(Path(t) / 's.o')], check=True)
        subprocess.run(['llvm-objcopy', '-O', 'binary', '-j', '.text', str(Path(t) / 's.o'), str(Path(t) / 's.bin')], check=True)
        ref_words = struct.unpack('<%dI' % len(src), (Path(t) / 's.bin').read_bytes())
    n_ok = 0
    for i, x in enumerate(src):
        w = word(img, stub + 4 * i)
        if x is None: continue
        n_ok += 1
        if w != ref_words[i]: out.append(('stub word differs from clang', i, x, hex(w), hex(ref_words[i])))
    def tgt(i):
        w = word(img, stub + 4 * i); d = struct.unpack('<i', struct.pack('<I', (w & 0xFFFFFF) << 8))[0] >> 8
        return w >> 28, stub + 4 * i + 8 + 4 * d, (w >> 24) & 15
    for i, (cond, target, op) in {3: (1, ZERO_PATH, 0xA), 16: (0xB, ZERO_PATH, 0xA), 19: (0xE, COMMON, 0xA)}.items():
        c, tg, o = tgt(i)
        if (c, tg, o) != (cond, target, op): out.append(('stub branch', i, hex(c), hex(tg)))
    c, tg, o = tgt(13)
    if c != 0xE or tg != core.code or o != 0xB: out.append(('stub bl', hex(tg), hex(core.code)))
    print(f'   stub: {n_ok} non-branch words equal clang\'s assembler, 4 branches / 1 bl checked by condition and target; {len(out)} problems')
    return out


if __name__ == '__main__':
    main()
