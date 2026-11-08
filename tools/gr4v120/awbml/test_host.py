# SPDX-License-Identifier: GPL-2.0-only
"""Bit-exact test: awbml.c (gcc, x86, -DAWBML_HOST via host.c) against ref.py on the SimpleCube++ scenes, the GR IV gallery
scenes, the studio shots and random synthetic inputs (odd grids, clipped / zero blocks, empty scenes, v24 = -0x880,
extreme e30, mode byte != 0, failing alloc). The C code is built twice: -O2 and with UBSan + ASan (-O1)."""
import ctypes
import os
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

import ref
import scenes

HERE = Path(__file__).resolve().parent
OBJ_SIZE = 0xAF90
NSEQ = int(os.environ.get('AWBML_NSEQ', 300))
NCASE_RANDOM = int(os.environ.get('AWBML_NRANDOM', 3000))


def build_libs(tmp):
    libs = {}
    for name, flags in (('o2', ['-O2']), ('san', ['-O1', '-g', '-fsanitize=undefined,address', '-fno-sanitize-recover=undefined'])):
        out = Path(tmp) / f'libawbml_{name}.so'
        subprocess.run(['gcc', '-Wall', '-Wextra', '-DAWBML_HOST', '-shared', '-fPIC', *flags, str(HERE / 'host.c'), '-o', str(out)], check=True)
        libs[name] = out
    return libs


def load(path):
    lib = ctypes.CDLL(str(path))
    lib.host_run.restype = ctypes.c_int
    lib.host_run.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
                             ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
    lib.host_set_tears.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
    return lib


# The property store of the camera as the host / ARM tests lay it out (addresses are offsets into the test memory; the ARM test adds its base):
# guard word, the singleton pointer slot, E (vtable at E, X at E + 0x518), X = {a, b}, the two 0x1090 buffers, Tv / Av / Sv at a + 0x4D8 / 4DC / 4E0.
CFG = dict(guard=0x100, eslot=0x110, lo=0x10000, hi=0x100000, lo2=0x2000, hi2=0xA000)
HOST_LO, HOST_HI = CFG['lo'], CFG['hi']
PAD = 0x101000                      # test memory below the stats arrays when a property store is laid out
VT = ref.VTABLE


def f32bits(x):
    return struct.unpack('<I', struct.pack('<f', x))[0]


def lv_words(rng):
    """(label, [Tv, Av, Sv] float words): valid triples (also near the quantiser's rounding points) and the rejected kinds."""
    k = str(rng.choice(['valid'] * 8 + ['near'] * 4 + ['zero', 'nan', 'inf', 'denorm', 'neg', 'big', 'avlo', 'avhi', 'tvlo', 'tvhi', 'svlo', 'svhi', 'e30hi', 'e30lo', 'part0', 'negzero', 'edge', 'exact', 'tiny']))
    av, sv = rng.uniform(1, 10), rng.uniform(3, 15)
    tv = float(np.clip(sv - av + rng.uniform(-3, 3), -5, 15))
    w = [f32bits(tv), f32bits(av), f32bits(sv)]
    ulp = lambda wd, d: (wd + d) & 0xFFFFFFFF
    if k == 'valid' and rng.random() < 0.4:
        w = [f32bits(round(x * 8) / 8) for x in (tv, av, sv)]            # exactly on the 1/8 grid
    elif k == 'near':                                                     # a hair off the grid: the rounding of 68 + 8 x decides
        w = [ulp(f32bits(round(x * 8) / 8), int(rng.choice([-3, -2, -1, 0, 1, 2, 3]))) for x in (tv, av, sv)]
    elif k == 'exact':
        w = [f32bits(float(rng.choice([-5.0, 0.0, 15.0, 7.125]))), f32bits(float(rng.choice([1.0, 5.0, 10.0]))), f32bits(float(rng.choice([3.0, 8.0, 15.0])))]
    elif k == 'zero':
        w = [0, 0, 0]
    elif k == 'part0':
        w[int(rng.integers(0, 3))] = 0
    elif k == 'nan':
        w[int(rng.integers(0, 3))] = int(rng.choice([0x7FC00000, 0xFFC00001, 0x7F800001]))
    elif k == 'inf':
        w[int(rng.integers(0, 3))] = int(rng.choice([0x7F800000, 0xFF800000]))
    elif k in ('denorm', 'tiny'):
        w[int(rng.integers(0, 3))] = int(rng.choice([1, 0x7FFFFF, 0x80000001, 0x00400000, 0x80000000 | 0x7FFFFF, 0x00800000, 0x33000000, 0x32FFFFFF]))
    elif k == 'neg':
        w[int(rng.integers(0, 3))] = f32bits(-abs(rng.uniform(0.1, 20)))
    elif k == 'negzero':
        w[int(rng.integers(0, 3))] = 0x80000000
    elif k == 'big':
        w[int(rng.integers(0, 3))] = f32bits(float(rng.choice([16.0, 15.999999, 16384.0, 1e6, 3e38, 31.5, 100.0])))
    elif k in ('avlo', 'avhi', 'tvlo', 'tvhi', 'svlo', 'svhi'):
        i = {'t': 0, 'a': 1, 's': 2}[k[0]]
        w[i] = f32bits(rng.uniform(*{'avlo': (0.0, 0.99), 'avhi': (10.2, 15.9), 'tvlo': (-9, -5.2), 'tvhi': (15.2, 15.9), 'svlo': (0.5, 2.9), 'svhi': (15.2, 15.9)}[k]))
    elif k == 'e30hi':
        w = [f32bits(15.0), f32bits(10.0), f32bits(3.0)]
    elif k == 'e30lo':
        w = [f32bits(-5.0), f32bits(1.0), f32bits(15.0)]
    elif k == 'edge':
        w = [f32bits(float(rng.choice([-5.0, 15.0, -5.125, 15.125, 14.99]))), f32bits(float(rng.choice([1.0, 10.0, 10.125, 0.99]))), f32bits(float(rng.choice([3.0, 15.0, 2.875, 15.125])))]
    return k, w


def lv_store(rng, words=None):
    """-> (label, writes {addr: u32}, info) for a laid out property store: mostly valid, else one broken link (every rejection path)."""
    k = str(rng.choice(['ok'] * 14 + ['noguard', 'guard2', 'e0', 'e_unal', 'e_lo', 'e_hi', 'e_far', 'vt', 'vt_near', 'x0', 'x_unal', 'x_lo', 'x_hi', 'x_far', 'a0', 'b0', 'a_unal', 'b_unal',
                                       'dist_p4', 'dist_m4', 'dist_same', 'dist_2x', 'buf_lo', 'buf_gap', 'buf_hi', 'buf_lo2', 'b_range', 'guard3']))
    wl, ws = lv_words(rng) if words is None else ('given', words)
    c = CFG
    E = int(rng.choice([0x20000, 0x10000, 0x7F000, c['hi'] - 0x524, 0x21000]))
    X = int(rng.choice([0x40000, 0x50000, c['hi'] - 0x14, c['lo'] + 4]))
    if rng.random() < 0.5:
        a = int(rng.choice([0x2000, 0x3000, 0x4004, c['hi2'] - 0x1090 - 0x1090]))
        b = a + 0x1090
    else:
        a = int(rng.choice([c['lo'] + 0x3000, 0x60000, 0x70000, c['hi'] - 0x1090]))
        b = a - 0x1090
    if rng.random() < 0.3 and a > c['lo2'] + 0x1090:
        a, b = (c['lo2'] + 0x1090 + 4, c['lo2'] + 4) if a < c['hi2'] else (a, b)
    guard, vt = 1, VT
    if k == 'noguard': guard = 0
    elif k == 'guard2': guard = 2
    elif k == 'guard3': guard = 0xFFFFFFFF
    elif k == 'e0': E = 0
    elif k == 'e_unal': E += 2
    elif k == 'e_lo': E = c['lo'] - 4
    elif k == 'e_hi': E = c['hi'] - 0x520
    elif k == 'e_far': E = 0xFFFFFFFC
    elif k == 'vt': vt = int(rng.integers(0, 2 ** 32))
    elif k == 'vt_near': vt = VT ^ int(rng.choice([1, 4, 0x100, 0x80000000]))
    elif k == 'x0': X = 0
    elif k == 'x_unal': X += 1
    elif k == 'x_lo': X = c['lo'] - 4
    elif k == 'x_hi': X = c['hi'] - 0x10
    elif k == 'x_far': X = 0xFFFFFFF0
    elif k == 'a0': a = 0
    elif k == 'b0': b = 0
    elif k == 'a_unal': a += 2
    elif k == 'b_unal': b += 1
    elif k == 'dist_p4': b = a + 0x1094
    elif k == 'dist_m4': b = a - 0x108C
    elif k == 'dist_same': b = a
    elif k == 'dist_2x': b = a + 0x2120
    elif k == 'buf_lo': a, b = c['lo2'] - 4, c['lo2'] - 4 + 0x1090
    elif k == 'buf_gap': a, b = c['hi2'] - 0x1090 + 4, c['hi2'] + 4
    elif k == 'buf_hi': a, b = c['hi'] - 0x1090 + 4, c['hi'] + 4
    elif k == 'buf_lo2': a, b = c['hi2'] - 0x1090, c['hi2']
    elif k == 'b_range': a, b = 0xFFFFE000, 0xFFFFE000 + 0x1090
    w = {c['guard']: guard, c['eslot']: E, E: vt, E + 0x518: X, X: a, X + 4: b}
    for i, x in enumerate(ws):
        w[a + 0x4D8 + 4 * i] = x
    return f'{k}/{wl}', w, dict(E=E, X=X, a=a, b=b)


def make_rd(mem, tears=()):
    """The memory as awbml_host_rd32 reads it (zero outside), with the same counted tear schedule: [(n, addr, value)]."""
    mm, cnt = bytearray(mem), [0]
    def rd(a):
        for n, ad, v in tears:
            if n == cnt[0] and ad + 4 <= len(mm):
                struct.pack_into('<I', mm, ad, v)
        cnt[0] += 1
        a &= 0xFFFFFFFF
        return struct.unpack_from('<I', mm, a)[0] if a + 4 <= len(mm) else 0
    return rd


def pack_case(R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, mode, rng, rec=None, s70=2):
    arrs = [np.asarray(a).astype('<u4') for a in (R, Gr, Gb, B, cnt)]
    n = len(arrs[0])
    mem = bytearray()
    if rec is not None:                      # rec = {addr: u32}: a property store laid out in the memory below the arrays
        mem += bytes(PAD)
        for ad, v in rec.items():
            if ad + 4 <= PAD:
                struct.pack_into('<I', mem, ad, v)
    ptrs = []
    for a in arrs:
        ptrs.append(len(mem)); mem += a.tobytes()
    while len(mem) % 8:
        mem.append(0)
    s_off = len(mem)
    sb = bytearray(rng.integers(0, 256, 0x80, dtype=np.uint8).tobytes())
    struct.pack_into('<5I', sb, 0, *ptrs)
    struct.pack_into('<H', sb, 0x14, stride)
    struct.pack_into('<HHHH', sb, 0x1c, x0, y0, w, h)
    struct.pack_into('<i', sb, 0x24, v24)
    struct.pack_into('<i', sb, 0x30, e30)
    struct.pack_into('<I', sb, 0x70, s70)
    for off in (0x68, 0x6E):                                      # the R and B gain words: unity, the capture factors, extreme or zero
        v = int(rng.choice([0x2000, 0x2000, round(0x2000 * 1.563), round(0x2000 * 3.019), int(rng.integers(0, 65536)), 0, 1, 65535]))
        struct.pack_into('<H', sb, off, v)
    mem += sb
    obj = bytearray(rng.integers(0, 256, OBJ_SIZE, dtype=np.uint8).tobytes())
    obj[4:6] = b'\0\0'; obj[0xA:0xC] = b'\0\0'; obj[0xAF88] = mode
    return bytes(mem), s_off, bytes(obj), arrs


def s68_6e(mem, s_off):
    return struct.unpack_from('<H', mem, s_off + 0x68)[0], struct.unpack_from('<H', mem, s_off + 0x6E)[0]


class Runner:
    def __init__(self, lib, blob, offs):
        self.lib, self.blob = lib, blob
        self.offs = (ctypes.c_uint * len(ref.TABLE_ORDER))(*[offs[n] for n in ref.TABLE_ORDER])
        self.first = True

    def run(self, mem, s_off, obj, fail_alloc=0, period=1, reset=None, still=0, af89=0, lv_exp=0, lv_scale=0, tears=()):
        out = ctypes.create_string_buffer(OBJ_SIZE)
        tn = len(tears)
        self.lib.host_set_tears(tn, (ctypes.c_uint * 4)(*[x[0] for x in tears]), (ctypes.c_uint * 4)(*[x[1] for x in tears]), (ctypes.c_uint * 4)(*[x[2] for x in tears]))
        na = self.lib.host_run(mem, len(mem), s_off, obj, out, self.blob, len(self.blob), self.offs, fail_alloc, fail_alloc if reset is None else reset, period, af89, still, lv_exp, lv_scale)
        assert na <= 1
        o = out.raw
        if o == obj:
            return None, na
        changed = [i for i in range(OBJ_SIZE) if o[i] != obj[i]]
        assert set(changed) <= {4, 5, 0xA, 0xB, 0xAF89}, changed
        assert af89 or 0xAF89 not in changed
        if af89:
            assert o[0xAF89] == 0
        return (struct.unpack_from('<H', o, 4)[0], struct.unpack_from('<H', o, 0xA)[0]), na


def with_kf(tab, blob, offs, rmin=None, rmax=None, q=None, rconf=None, gate=None, rbase=None, flags=None, knot_scale=None):
    """The reference tables and blob with other filter parameters (the KF table); sds in log units."""
    kf = [int(x) for x in tab['KF']]
    sq = lambda x: round(x ** 2 * 2 ** 32)
    for i, v in ((0, rmin), (1, rmax), (2, q), (3, rconf), (5, rbase)):
        if v is not None:
            kf[i] = sq(v)
    if gate is not None:
        kf[4] = gate
    if flags is not None:
        kf[6] = flags
    if knot_scale is not None:
        kf[8:25] = [min(round(x * knot_scale), 2 ** 32 - 1) for x in kf[8:25]]
    tab2 = dict(tab); tab2['KF'] = np.array(kf, dtype=np.int64)
    b = bytearray(blob); b[offs['KF']:offs['KF'] + 128] = np.array(kf, dtype='<u4').tobytes()
    return tab2, bytes(b)


def gen_random(rng):
    kind = rng.choice(['scene'] * 6 + ['clip', 'clip', 'empty', 'noise', 'uniform'])
    w = int(rng.choice([int(rng.integers(1, 65)), 64, 1, 2, 3, 63, 17])) if rng.random() < 0.95 else int(rng.choice([0, 65, 100, 65535]))
    h = int(rng.choice([int(rng.integers(1, 65)), 62, 1, 2, 3, 63, 33, 64])) if rng.random() < 0.95 else int(rng.choice([0, 65, 66, 65535]))
    x0 = int(rng.choice([0, 0, 1, 2, 5, int(rng.integers(0, 9))]))
    y0 = int(rng.choice([0, 1, 1, 3, int(rng.integers(0, 9))]))
    stride = int(max(1, min(max(w, 1), 64) + x0 + rng.choice([0, 0, 0, 1, 2, 7]) - (rng.choice([0, 0, 0, 0, 3]))))
    if rng.random() < 0.1:
        stride = int(rng.integers(1, 80))
    wi, hi = min(max(w, 1), 64), min(max(h, 1), 64)
    n = (y0 + hi - 1) * stride + x0 + wi
    base = rng.uniform(0.15, 0.8, 3)                  # illuminant-ish colour (R, G(=1), B per G)
    lum = np.exp(rng.normal(0, 0.5, n)) * rng.choice([60, 300, 900, 2500])
    mix = rng.uniform(0.5, 1.6, (n, 3))
    chroma = base[None, :] ** rng.uniform(0.3, 1.2) * mix
    R = lum * chroma[:, 0] * 0.5; G = lum * 0.8; B = lum * chroma[:, 2] * 0.5
    Gr = G * rng.uniform(0.97, 1.03, n); Gb = G * rng.uniform(0.97, 1.03, n)
    if rng.random() < 0.5:
        Gb = Gr.copy()
    cnt = rng.integers(200, 1585, n).astype(np.float64)
    if kind == 'clip':
        for a in (R, Gr, Gb, B):
            k = rng.random(n) < 0.15; a[k] = rng.choice([0, 1, 3, 4, 0xF6D, 0xF6E, 4095, 100000], k.sum())
            k = rng.random(n) < 0.05; a[k] = 0
        cnt[rng.random(n) < 0.2] = rng.choice([0, 100, 316, 317, 318, 70000, 2 ** 32 - 1], 1)[0]
    elif kind == 'empty':
        cnt = rng.integers(0, 330, n).astype(np.float64)
        if rng.random() < 0.5:
            cnt[:] = 0
        if rng.random() < 0.3:
            cnt[rng.random(n) < 0.05] = 1584
    elif kind == 'noise':
        R, Gr, Gb, B = (rng.integers(0, 4200, n).astype(np.float64) for _ in range(4))
        cnt = rng.integers(0, 2000, n).astype(np.float64)
    elif kind == 'uniform':
        R[:] = R[0]; Gr[:] = Gr[0]; Gb[:] = Gb[0]; B[:] = B[0]; cnt[:] = 1584
    arrs = []
    for a in (R, Gr, Gb, B):
        arrs.append(np.clip(np.floor(a), 0, 2 ** 32 - 1).astype(np.uint64))
    if kind == 'scene' and rng.random() < 0.2:
        arrs[0][rng.random(n) < 0.02] = 2 ** 32 - 1
        arrs[1][rng.random(n) < 0.02] = 2 ** 32 - 1
    arrs.append(np.clip(cnt, 0, 2 ** 32 - 1).astype(np.uint64))
    v24 = int(rng.choice([-0x880, -0x880, 0, 5, -1, int(rng.integers(-2 ** 31, 2 ** 31))]))
    e30 = int(rng.choice([int(rng.integers(-1500, 3500)), int(rng.integers(-1500, 3500)), 0, 1024, 2 ** 31 - 1, -2 ** 31, 4000, -3000,
                          int(rng.integers(-2 ** 31, 2 ** 31))]))
    mode = int(rng.choice([0] * 14 + [1, 2, 255]))
    return arrs, dict(x0=x0, y0=y0, w=w, h=h, stride=stride, v24=v24, e30=e30, mode=mode)


def quant_check(rng, n=int(os.environ.get('AWBML_NQUANT', 3000000))):
    """1.20 reference quantisation versus independent vectorised double arithmetic,
    on random patterns, near the 1/8 grid and stratified exponent patterns."""
    bits = [rng.integers(0, 2 ** 32, n // 3, dtype=np.uint64).astype(np.uint32)]
    g = np.round(rng.uniform(-20, 20, n // 3) * 8) / 8
    bits.append((g.astype(np.float32).view(np.uint32).astype(np.int64) + rng.integers(-4, 5, n // 3)).astype(np.uint32))
    e = rng.integers(95, 133, n // 3).astype(np.uint32)
    bits.append((e << 23) | rng.integers(0, 2 ** 23, n // 3).astype(np.uint32) | (rng.integers(0, 2, n // 3).astype(np.uint32) << 31))
    allb = np.concatenate(bits).astype(np.uint32)
    x = allb.view(np.float32)
    bad = 0
    with np.errstate(all='ignore'):
        for base in (68, -8):
            y = (x.astype(np.float64) + 8.5 + 0.0625) * 8 if base == 68 else ((x - np.float32(1)).astype(np.float64) + 0.0625) * 8
            ok = np.isfinite(y) & (np.abs(y) < 2 ** 30)
            for b, yy, o in zip(allb.tolist(), y.tolist(), ok.tolist()):
                got = ref.fl8(b, base)
                if o and got is not None and got != int(yy): bad += 1
                if got is not None and not o: bad += 1
                if got is None and o and ((-40 <= int(yy) - 68 <= 120) if base == 68 else (16 <= int(yy) <= 112)): bad += 1       # a rejection must be outside the accepted range anyway
    print('quantiser (ref.fl8 vs 1.20 double arithmetic):', 2 * len(allb), 'patterns, mismatches', bad)
    return bad


def main():
    tab, blob, offs = ref.build_tables()
    rng = np.random.default_rng(12345)
    qbad = quant_check(rng)
    stats = {}
    with tempfile.TemporaryDirectory() as tmp:
        libs = build_libs(tmp)
        runners = {k: Runner(load(v), blob, offs) for k, v in libs.items()}
        # sanitizer lib needs libasan preloaded when loaded into python; if that fails the test script re-executes itself
        def check(tag, arrs, p, fail_alloc=False):
            mem, s_off, obj, a = pack_case(*arrs, p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], rng)
            want = None if fail_alloc else ref.awbml_ref(tab, *[x.astype(np.int64) for x in a], p['x0'], p['y0'], p['w'], p['h'], p['stride'],
                                                         p['v24'], p['e30'], p['mode'])
            for name, r in runners.items():
                got, na = r.run(mem, s_off, obj, int(fail_alloc), reset=1)   # a fresh scratch: the filter starts from this observation
                gs, _ = r.run(mem, s_off, obj, int(fail_alloc), reset=1, still=1)   # a still gives the same single-frame result
                wst = None if want is None else ref.awbml_ref(tab, *[x.astype(np.int64) for x in a], p['x0'], p['y0'], p['w'], p['h'], p['stride'],
                                                              p['v24'], p['e30'], p['mode'], still_s=s68_6e(mem, s_off))
                if gs != wst:
                    print(f'STILL MISMATCH {tag} lib={name} C={gs} ref={wst} live={got} params={p}')
                    stats['bad'] = stats.get('bad', 0) + 1
                    return
                if fail_alloc:
                    assert na == 1, na            # tried once, got nothing, left obj alone
                if got != want:
                    print(f'MISMATCH {tag} lib={name} C={got} ref={want} params={p}')
                    stats['bad'] = stats.get('bad', 0) + 1
                    return
            stats[tag] = stats.get(tag, [0, 0])
            stats[tag][0] += 1
            stats[tag][1] += want is None
        seq_state = {}
        t0 = time.time()
        cube, _ = scenes.load_cube()
        for sc in cube:
            a = scenes.scene_args(sc['s'], sc['ev'])
            check('cube', [a[k] for k in ('R', 'Gr', 'Gb', 'B', 'cnt')], {k: a[k] for k in ('x0', 'y0', 'w', 'h', 'stride', 'v24', 'e30', 'mode')})
        print('cube done', round(time.time() - t0, 1), 's', flush=True)
        for tag, lst in (('gallery', scenes.load_gallery()), ('studio', scenes.load_studio())):
            for sc in lst:
                a = scenes.scene_args(sc['s'], sc['ev'])
                check(tag, [a[k] for k in ('R', 'Gr', 'Gb', 'B', 'cnt')], {k: a[k] for k in ('x0', 'y0', 'w', 'h', 'stride', 'v24', 'e30', 'mode')})
        # the cube scenes again with the other flavours: no exposure data, extreme e30, failing alloc, mode byte
        for sc in cube[:60]:
            a = scenes.scene_args(sc['s'], sc['ev'])
            base = [a[k] for k in ('R', 'Gr', 'Gb', 'B', 'cnt')]
            p = {k: a[k] for k in ('x0', 'y0', 'w', 'h', 'stride', 'v24', 'e30', 'mode')}
            check('cube-v24', base, dict(p, v24=-0x880))
            check('cube-e30', base, dict(p, e30=int(rng.choice([2 ** 31 - 1, -2 ** 31, 5000, -5000]))))
            check('cube-mode', base, dict(p, mode=1))
            check('cube-failalloc', base, p, fail_alloc=True)
        for i in range(NCASE_RANDOM):
            arrs, p = gen_random(rng)
            check('random', arrs, p)
        # sequences with the build's period (4) and others: mixed scenes and modes against the state machine of ref.AwbmlSeq,
        # with the build's filter parameters and with other parameter sets in the KF table (the reset path needs a larger R_conf)
        pool = [scenes.scene_args(cube[i]['s'], cube[i]['ev']) for i in rng.integers(0, len(cube), 40)]
        def sequences(tab_x, runners_x, n, tag):
            for sq in range(n):
                period = int(rng.choice([ref.PERIOD] * 4 + [1, 2]))
                af89 = int(rng.random() < 0.7)
                lv_exp = int(rng.choice([0, 1, 2, 2, 2]))
                lv_scale = int(rng.random() < 0.75)
                unity = lv_scale and rng.random() < 0.25      # all S words 0x2000: the C code (lv_scale on) must equal the unscaled model (lv_scale off, as final3)
                seq = ref.AwbmlSeq(tab_x, period, lv_exp, 0 if unity else lv_scale)
                shadow = ref.AwbmlSeq(tab_x, period, lv_exp, 0 if unity else lv_scale)          # the same live view calls without the stills
                still_p = float(rng.choice([0.0, 0.3, 0.3, 0.6]))
                last = None
                steps = []
                any_fail = False
                for step in range(int(rng.integers(10, 40))):
                    if last is not None and rng.random() < 0.55:
                        arrs, p = last[0], dict(last[1])          # the same scene again: the filter converges
                    elif rng.random() < 0.6:
                        a = pool[int(rng.integers(0, len(pool)))]
                        arrs = [a[k] for k in ('R', 'Gr', 'Gb', 'B', 'cnt')]
                        p = {k: a[k] for k in ('x0', 'y0', 'w', 'h', 'stride', 'v24', 'e30', 'mode')}
                    else:
                        arrs, p = gen_random(rng)
                    last = (arrs, dict(p))
                    p['mode'] = int(rng.choice([0] * 9 + [1, 2]))
                    still = int(rng.random() < still_p)
                    fail = step < 2 and rng.random() < 0.2 and not seq.buf
                    any_fail |= fail
                    rec, tears, info, s70 = None, [], None, 2
                    if lv_exp == 2 and rng.random() < 0.8:
                        lab, rec, info = lv_store(rng)
                        if rng.random() < 0.06:
                            s70 = 4                                    # movie: P[0x719EF] == 1
                        if rng.random() < 0.12:                        # a word changes between the two reads: one, or two (so the retry fails as well)
                            cand = [info['X'], info['X'] + 4] + [info['a'] + 0x4D8 + 4 * k for k in range(3)] + [info['b'] + 0x4D8]
                            for _ in range(int(rng.choice([1, 1, 2]))):
                                tears.append((int(rng.integers(4, 24)), int(rng.choice(cand)), int(rng.choice([0, info['b'], info['a'], int(rng.integers(0, 2 ** 32)), f32bits(4.0), f32bits(7.0)]))))
                    mem, s_off, obj, a_ = pack_case(*arrs, p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], rng, rec=rec, s70=s70)
                    ia = [x.astype(np.int64) for x in a_]
                    pa = (p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'])
                    if unity:
                        mem = bytearray(mem); struct.pack_into('<H', mem, s_off + 0x68, 0x2000)
                        struct.pack_into('<H', mem, s_off + 0x6E, 0x2000); mem = bytes(mem)
                    sm = s68_6e(mem, s_off)
                    lv_ev = ref.lv_exposure(make_rd(mem, tears), s70, CFG)
                    stats.setdefault('lv exposure usable', [0, 0])
                    if not still and lv_exp == 2:
                        stats['lv exposure usable'][0] += 1
                        stats['lv exposure usable'][1] += lv_ev is None
                    want = seq.call(*ia, *pa, alloc_ok=not fail, still=bool(still), still_s=sm, lv_ev=lv_ev)
                    if still:       # (a) a still equals the single-call reference on its own stats, whatever came before
                        assert want == (None if fail else ref.awbml_ref(tab_x, *ia, *pa, still_s=sm))
                    else:           # (b) live view is unaffected by the stills
                        wsh = shadow.call(*ia, *pa, alloc_ok=not fail, lv_ev=lv_ev, still_s=sm)
                        assert fail or wsh == want, (sq, step, wsh, want)
                    steps.append((mem, s_off, obj, fail, still, want, step, tears))
                    for name, r in runners_x.items():
                        got, na = r.run(mem, s_off, obj, int(fail), period=period, reset=int(step == 0), still=still, af89=af89, lv_exp=lv_exp, lv_scale=lv_scale, tears=tears)
                        if got != want:
                            print(f'SEQ MISMATCH seq {sq} step {step} still {still} lib={name} C={got} ref={want} {p}')
                            stats['bad'] = stats.get('bad', 0) + 1
                            break
                    stats.setdefault(tag, [0, 0])
                    stats[tag][0] += 1
                    stats[tag][1] += want is None
                    stats.setdefault('stills in ' + tag, [0, 0])
                    if still:
                        stats['stills in ' + tag][0] += 1
                        stats['stills in ' + tag][1] += want is None
                if sq % 3 == 0 and not any_fail and still_p > 0:
                    # the C live view outputs are identical with the stills removed from the sequence
                    live_steps = [x for x in steps if not x[4]]
                    for name, r in runners_x.items():
                        for k, (mem, s_off, obj, fail, still, want, step, tears_) in enumerate(live_steps):
                            got, na = r.run(mem, s_off, obj, 0, period=period, reset=int(k == 0), still=0, af89=af89, lv_exp=lv_exp, lv_scale=lv_scale, tears=tears_)
                            if got != want:
                                print(f'LIVE-ONLY MISMATCH seq {sq} live step {k} lib={name} C={got} with stills={want}')
                                stats['bad'] = stats.get('bad', 0) + 1
                                break
                    stats.setdefault('live-only replays', [0, 0])
                    stats['live-only replays'][0] += 1

        sequences(tab, runners, NSEQ, 'sequence-calls')
        for k, kf in enumerate([dict(rconf=0.13, flags=0), dict(rmin=0.02, rmax=0.12, q=0.005, rconf=0.15, gate=4, flags=1, knot_scale=3.0),
                              dict(rmin=0.001, rmax=0.3, q=0.03, rconf=0.09, gate=16, flags=3, rbase=0.002, knot_scale=0.5), dict(rconf=0.2, gate=1, flags=2, knot_scale=0.3)]):
            tab2, blob2 = with_kf(tab, blob, offs, **kf)
            runners2 = {nm: Runner(rn.lib, blob2, offs) for nm, rn in runners.items()}
            sequences(tab2, runners2, NSEQ // 2, f'sequence-calls KF set {k + 1}')
        print('all done', round(time.time() - t0, 1), 's')
    print('filter coverage in the sequences:', ref.AwbmlSeq.counts)
    bad = stats.pop('bad', 0) + qbad
    for k, (n, fb) in stats.items():
        print(f'{k:16s} cases {n:5d}  fallback (None) {fb:5d}')
    print('total', sum(v[0] for v in stats.values()), 'mismatches', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
