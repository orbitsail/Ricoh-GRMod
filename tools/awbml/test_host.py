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
                             ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    return lib


def pack_case(R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, mode, rng):
    arrs = [np.asarray(a).astype('<u4') for a in (R, Gr, Gb, B, cnt)]
    n = len(arrs[0])
    mem = bytearray()
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
    mem += sb
    obj = bytearray(rng.integers(0, 256, OBJ_SIZE, dtype=np.uint8).tobytes())
    obj[4:6] = b'\0\0'; obj[0xA:0xC] = b'\0\0'; obj[0xAF88] = mode
    return bytes(mem), s_off, bytes(obj), arrs


class Runner:
    def __init__(self, lib, blob, offs):
        self.lib, self.blob = lib, blob
        self.offs = (ctypes.c_uint * 11)(*[offs[n] for n in ref.TABLE_ORDER])
        self.first = True

    def run(self, mem, s_off, obj, fail_alloc=0, period=1, reset=None):
        out = ctypes.create_string_buffer(OBJ_SIZE)
        na = self.lib.host_run(mem, len(mem), s_off, obj, out, self.blob, len(self.blob), self.offs, fail_alloc, fail_alloc if reset is None else reset, period)
        assert na <= 1
        o = out.raw
        if o == obj:
            return None, na
        changed = [i for i in range(OBJ_SIZE) if o[i] != obj[i]]
        assert set(changed) <= {4, 5, 0xA, 0xB}, changed
        return (struct.unpack_from('<H', o, 4)[0], struct.unpack_from('<H', o, 0xA)[0]), na


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


def main():
    tab, blob, offs = ref.build_tables()
    rng = np.random.default_rng(12345)
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
                got, na = r.run(mem, s_off, obj, int(fail_alloc))
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
        # sequences with the build's period (4): mixed scenes and modes against the state machine of ref.AwbmlSeq
        pool = [scenes.scene_args(cube[i]['s'], cube[i]['ev']) for i in rng.integers(0, len(cube), 40)]
        for sq in range(NSEQ):
            seq = ref.AwbmlSeq(tab, ref.PERIOD)
            ok_calls = 0
            for step in range(int(rng.integers(8, 30))):
                if rng.random() < 0.6:
                    a = pool[int(rng.integers(0, len(pool)))]
                    arrs = [a[k] for k in ('R', 'Gr', 'Gb', 'B', 'cnt')]
                    p = {k: a[k] for k in ('x0', 'y0', 'w', 'h', 'stride', 'v24', 'e30', 'mode')}
                else:
                    arrs, p = gen_random(rng)
                p['mode'] = int(rng.choice([0] * 6 + [1, 2]))
                fail = step < 2 and rng.random() < 0.2 and not seq.buf
                mem, s_off, obj, a_ = pack_case(*arrs, p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], rng)
                want = seq.call(*[x.astype(np.int64) for x in a_], p['x0'], p['y0'], p['w'], p['h'], p['stride'], p['v24'], p['e30'], p['mode'], alloc_ok=not fail)
                for name, r in runners.items():
                    if name not in seq_state:
                        seq_state[name] = None
                    got, na = r.run(mem, s_off, obj, int(fail), period=ref.PERIOD, reset=int(step == 0))
                    if got != want:
                        print(f'SEQ MISMATCH seq {sq} step {step} lib={name} C={got} ref={want} {p}')
                        stats['bad'] = stats.get('bad', 0) + 1
                        break
                stats.setdefault('sequence-calls', [0, 0])
                stats['sequence-calls'][0] += 1
                stats['sequence-calls'][1] += want is None
        print('all done', round(time.time() - t0, 1), 's')
    bad = stats.pop('bad', 0)
    for k, (n, fb) in stats.items():
        print(f'{k:16s} cases {n:5d}  fallback (None) {fb:5d}')
    print('total', sum(v[0] for v in stats.values()), 'mismatches', bad)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
