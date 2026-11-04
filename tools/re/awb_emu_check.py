#!/usr/bin/env python3
"""Run the real RICOH GR IV 1.11 AWB functions (RTOS.bin, ARM32) in unicorn on random synthetic inputs and compare
with awb_ref.py.  Usage: python3 awb_emu_check.py [seed] [scale]      (scale multiplies the number of trials)

Every line printed is  <test name>: <matches>/<trials>.  Exit status 0 only if all trials match bit-exactly.
Helper modules next to this file: fwemu.py (unicorn setup), emuutil.py (frame/object helpers), hcommon.py (settings block).
"""
import os, sys, random, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
import awb_ref as R
from emuutil import *
from hcommon import *

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
scale = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
rng = random.Random(seed)
e = new_emu()
results = []
def report(name, ok, tot, note=''):
    results.append((name, ok, tot))
    print('%-58s %4d/%-4d %s' % (name, ok, tot, note))
def N(n): return max(1, int(n * scale))

# ---------------------------------------------------------------------------------------------
# 1. 0x5393C4D4: bilinear accumulation of (a,b,c,d) into two brightness rows of a frame
ok = tot = 0
for _ in range(N(400)):
    fi = rng.randrange(33)
    fr = R.Frame(fi, 0)
    fields = [[rng.getrandbits(32) for _ in range(4)] for _ in range(24)]
    write_frame_fields(e, A_OBJ, fi, fields); fr.f = [list(r) for r in fields]
    pos = rng.choice([rng.randrange(-3000, 6500), rng.randrange(-2**31, 2**31), 256 * rng.randrange(-8, 22)])
    a, b, c = [rng.choice([rng.randrange(-5000, 5000), rng.randrange(-2**31, 2**31)]) for _ in range(3)]
    d = rng.choice([rng.randrange(0, 5000), rng.getrandbits(32)])
    e.call(0x5393C4D4, frame_addr(A_OBJ, fi), pos, a, b, c, d)
    fr.acc(pos, a, b, c, d)
    ok += read_frames(e, A_OBJ)[fi][0] == fr.f; tot += 1
report('0x5393C4D4 row accumulation (random pos/values, wraps)', ok, tot)

# ---------------------------------------------------------------------------------------------
# 2. 0x5393926C angle / magnitude and 0x538D3298 log table
ok = tot = 0
MAGP = 0x60800000
for _ in range(N(2000)):
    x = rng.choice([rng.randrange(-300, 300), rng.randrange(-4000, 4000), rng.randrange(-2**20, 2**20), 0])
    y = rng.choice([rng.randrange(-300, 300), rng.randrange(-4000, 4000), rng.randrange(-2**20, 2**20), 0])
    ang = e.call(0x5393926C, 0, x, y, MAGP) & 0xffffffff
    mag = R.s32(e.r32(MAGP))
    ra, rm = R.AwbObject.angle_mag(x, y)
    ok += (ang, mag) == (ra, rm); tot += 1
report('0x5393926C atan2-in-degrees + magnitude', ok, tot)
ok = tot = 0
for x in range(1, 0x201):
    ok += (e.call(0x538D3298, 0, x) & 0xffffffff) == R.AwbObject.log2_8_8(x); tot += 1
report('0x538D3298 log2 table (x = 1..0x200, all)', ok, tot)

# ---------------------------------------------------------------------------------------------
# 3. per-block entry points (Auto 0x53936E1C for 3 tunings, CTE 0x5393931C)
def rnd_blk():
    Y = rng.choice([rng.randrange(32, 300), rng.randrange(32, 4000)])
    sc = rng.choice([0.2, 0.6, 1.2])
    u = int(rng.uniform(-sc, sc) * Y); v = int(rng.uniform(-0.4, 0.5) * Y) if rng.random() < 0.7 else int(rng.uniform(-sc, sc) * Y)
    pos = rng.choice([rng.randrange(-1500, 5200), 256 * rng.randrange(-6, 20)])
    return Y, u, v, pos, rng.randrange(0, 300), rng.choice([0, 0, 0, 1])
for obj, kind, fn, rst in ((A_OBJ, 'auto', 0x53936E1C, 0x53936FEC), (C_OBJ, 'cte', 0x5393931C, 0x539391D8)):
    ok = tot = 0; blocks = 0; hit_ranges = set()
    for trial in range(N(60)):
        mode = rng.choice([0, 1, 2]) if kind == 'auto' else 3
        if kind == 'auto': e.wb(obj + 0xAF88, bytes([mode]))
        e.call(rst, obj)
        py = R.AwbObject(kind, mode)
        good = True
        for _ in range(60):
            args = rnd_blk()
            r = e.call(fn, obj, *args); rp = py.slot5(*args); blocks += 1
            if (r & 0xffffffff) != (rp & 0xffffffff): good = False
        efr = read_frames(e, obj)
        good = good and all(efr[i][0] == py.frames[i].f for i in range(33))
        ok += good; tot += 1
        hit_ranges.update(i for i in range(33) if any(any(r) for r in py.frames[i].f))
    report('per-block entry %s (%s), state+return value' % (hex(fn), kind), ok, tot, '%d blocks, %d distinct frames touched' % (blocks, len(hit_ranges)))

# ---------------------------------------------------------------------------------------------
# 4. 0x53937BFC row weights h
ok = tot = 0
for trial in range(N(30)):
    obj, kind, rst = rng.choice([(A_OBJ, 'auto', 0x53936FEC), (C_OBJ, 'cte', 0x539391D8)])
    mode = 3 if kind == 'cte' else rng.choice([0, 1, 2])
    if kind == 'auto': e.wb(obj + 0xAF88, bytes([mode]))
    e.call(rst, obj)
    py = R.AwbObject(kind, mode)
    for i in range(33):
        if rng.random() < 0.7:
            f = [[rng.randrange(0, 5000), rng.randrange(0, 2**32), rng.randrange(0, 2**32), rng.randrange(0, 70000)] for _ in range(24)]
            write_frame_fields(e, obj, i, f); py.frames[i].f = [list(r) for r in f]
    e.call(0x53937BFC, obj); py.compute_h()
    ok += all(read_frames(e, obj)[i][1] == py.frames[i].h for i in range(33)); tot += 1
report('0x53937BFC row weights h = w*256/max', ok, tot)

# ---------------------------------------------------------------------------------------------
# 5. 0x539376A8 block loop (stub in place of the per-block virtual call, real log2 function)
FAKEVT, STUB = 0x60300000, 0x60300100
vt = bytearray(e.rb(0x5421B510, 7 * 4)); struct.pack_into('<I', vt, 5 * 4, STUB)
e.wb(FAKEVT, vt); e.wb(STUB, struct.pack('<I', 0xE320F000))
log = []
def stub(uc, addr, size, user):
    sp = uc.reg_read(UC_ARM_REG_SP); st = struct.unpack('<3I', bytes(uc.mem_read(sp, 12)))
    r = [uc.reg_read(x) for x in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)]
    log.append((R.s32(r[0]), R.s32(r[1]), R.s32(r[2]), R.s32(st[0]), st[1], st[2] & 0xff))
    uc.reg_write(UC_ARM_REG_R0, len(log)); uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
e.mu.hook_add(UC_HOOK_CODE, stub, begin=STUB, end=STUB + 4)
ok = tot = 0; calls = rejects = 0
vt_saved = e.r32(A_OBJ)
for trial in range(N(80)):
    e.w32(A_OBJ, FAKEVT)
    S, nblk = rand_S(rng); setup_S(e, S, nblk)
    Wb = bytes(rng.randrange(256) for _ in range(nblk + 4)); e.wb(e.r32(A_OBJ + 0xAF8C), Wb)
    ms = [rng.randrange(0x1000, 0x5000) for _ in range(4)]
    for i, m in enumerate(ms): e.w16(A_OBJ + 0xC + 2 * i, m)
    e.wb(A_OBJ + 0x24, bytes(4 * (nblk + 2))); log.clear()
    e.call(0x539376A8, A_OBJ, SBASE)
    py = R.AwbObject('auto', 0); py.m = list(ms); plog = []
    def pc(Y, u, v, pos, d, flag): plog.append((Y, u, v, pos, d, flag)); return len(plog)
    out = py.block_loop(S, Wb, call=pc)
    same = plog == log and {i: e.r32(A_OBJ + 0x24 + 4 * i) for i in out} == out and e.r32(A_OBJ + 0x14) == R.u32(py.e14) \
        and e.rb(A_OBJ + 0x18, 1)[0] == py.f18 and e.r32(A_OBJ + 0x1C) == py.n1c
    ok += same; tot += 1; calls += len(log); rejects += sum(1 for v in out.values() if v == 0)
e.w32(A_OBJ, vt_saved)
report('0x539376A8 block loop (args of per-block call, results)', ok, tot, '%d accepted blocks, %d rejected' % (calls, rejects))

# ---------------------------------------------------------------------------------------------
# 6. whole estimators on synthetic statistics
def run_est(kind, ntr):
    ok = tot = 0; extra = {}
    obj = C_OBJ if kind == 'cte' else A_OBJ
    fn = 0x53938E78 if kind == 'cte' else 0x53938B28
    for trial in range(ntr):
        S, nblk = rand_S(rng); setup_S(e, S, nblk)
        Wb = bytes(rng.randrange(256) for _ in range(nblk + 4)); e.wb(e.r32(obj + 0xAF8C), Wb)
        c30, c34, c5c = setup_cal(e, rng)
        lims = [rng.choice([0x400, 0x300, 0x500]), rng.choice([0x400, 0x300]), rng.choice([0x80, 0x100, 0x40]), rng.choice([0x80, 0x100, 0x40])]
        for i, l in enumerate(lims): e.w16(obj + 0x6A68 + 2 * i, l)
        e.call(fn, obj, SBASE, 0x60700000)
        gem = [e.r16(obj + 4 + 2 * i) for i in range(4)]
        py = R.AwbObject(kind); py.lim = lims
        if kind == 'cte': g = py.estimate_cte(S, Wb, c30, c34)
        else: g = py.estimate_auto(S, Wb, c30, c34, c5c)
        same = gem == g and [e.r16(obj + 0xC + 2 * i) for i in range(4)] == py.m
        if kind == 'auto':
            pwe = [[e.r16(obj + 0x4028 + 0x2A4 * k + o) for o in (0x21A, 0x21C, 0x21E)] for k in range(16)]
            same = same and pwe == py.pw and e.r16(obj + 0x20) == py.n20 and e.rb(obj + 0xAF88, 1)[0] == py.mode
        ok += same; tot += 1
        extra[(py.raw_gains[0] != 256) or (py.raw_gains[1] != 256)] = extra.get((py.raw_gains[0] != 256) or (py.raw_gains[1] != 256), 0) + 1
    return ok, tot, extra
ok, tot, ex = run_est('cte', N(120))
report('CTE estimate 0x53938E78 end-to-end (R,B gains + multipliers)', ok, tot, 'non-trivial gains in %d trials' % ex.get(True, 0))
ok, tot, ex = run_est('auto', N(240))
report('Auto estimate 0x53938B28 end-to-end (gains, parent weights)', ok, tot, 'non-trivial gains in %d trials' % ex.get(True, 0))

tot_ok = sum(r[1] for r in results); tot_all = sum(r[2] for r in results)
print('TOTAL %d/%d trials bit-exact (%.2f%%)' % (tot_ok, tot_all, 100.0 * tot_ok / tot_all))
sys.exit(0 if tot_ok == tot_all else 1)
