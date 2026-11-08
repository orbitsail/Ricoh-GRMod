# SPDX-License-Identifier: GPL-2.0-only
"""Calibrates the observation variance: gathers (z, R_post, truth) for full frames and reframed views of the cube,
gallery and studio scenes, bins err^2 against R_post, and fits the monotone R_eff = f(R_post) table (17 knots)."""
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

import ref
import scenes
from calib import truth_q16

CACHE = Path(tempfile.gettempdir()) / 'awbml_calib_r.npz'


def windows(rng, n):
    out = []
    for _ in range(n):
        w = int(rng.integers(round(64 * .55), round(64 * .95) + 1)); h = int(rng.integers(round(62 * .55), round(62 * .95) + 1))
        out.append((int(rng.integers(0, 64 - w + 1)), int(rng.integers(1, 63 - h + 1)), w, h))
    return out


def gather(T, seed=1):
    rng = np.random.default_rng(seed)
    cube, _ = scenes.load_cube(); gal = scenes.load_gallery(); stu = scenes.load_studio()
    rows = []
    for kind, lst, nwin in (('cube', cube, 4), ('gallery', gal, 16), ('studio', stu, 16)):
        for i, sc in enumerate(lst):
            a = scenes.scene_args(sc['s'], sc['ev'])
            if kind == 'cube':
                tr = (-math.log(sc['gt'][0]) * 65536, -math.log(sc['gt'][2]) * 65536)
            elif kind == 'studio':
                tr = truth_q16(sc)
            else:
                tr = None
            for j, wn in enumerate([None] + windows(rng, nwin)):
                b = dict(a)
                if wn:
                    b.update(x0=wn[0], y0=wn[1], w=wn[2], h=wn[3])
                o = ref.observe(T, **b)
                if o is None:
                    continue
                rows.append((kind, i, j, o[0], o[1], o[2], o[3], tr[0] if tr else np.nan, tr[1] if tr else np.nan))
    return rows


def load(T):
    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=True)
        return {k: z[k] for k in z.files}
    r = gather(T)
    d = dict(kind=np.array([x[0] for x in r]), scene=np.array([x[1] for x in r]), win=np.array([x[2] for x in r]),
             z=np.array([[x[3], x[4]] for x in r], float), R=np.array([[x[5], x[6]] for x in r], float),
             tr=np.array([[x[7], x[8]] for x in r], float))
    CACHE.parent.mkdir(exist_ok=True)
    np.savez(CACHE, **d)
    return d


def bins(R, e2, nb=16):
    """Quantile bins over R (pooled axes)."""
    o = np.argsort(R); out = []
    for ch in np.array_split(o, nb):
        out.append((len(ch), float(np.median(R[ch])), float(e2[ch].mean()), float(np.percentile(e2[ch], 90))))
    return out


def main():
    T, _, _ = ref.build_tables(ref.load_cal())
    d = load(T)
    q = 2.0 ** 32
    ok = ~np.isnan(d['tr'][:, 0])
    err2 = ((d['z'] - d['tr']) / 65536.0) ** 2
    Rl = d['R'] / q
    print('rows', len(d['kind']), {k: int((d['kind'] == k).sum()) for k in ('cube', 'gallery', 'studio')})
    # cross-scene error (truth known): cube + studio, full frames and views
    for label, m in (('cube full', ok & (d['kind'] == 'cube') & (d['win'] == 0)), ('cube views', ok & (d['kind'] == 'cube') & (d['win'] > 0)),
                     ('studio', ok & (d['kind'] == 'studio')), ('cube+studio all', ok)):
        R = Rl[m].ravel(); e = err2[m].ravel()
        print(f'\n{label}: n={m.sum()} axes pooled; sd(post)={np.sqrt(np.median(R)):.3f} rms err={np.sqrt(e.mean()):.3f}')
        print('   n   med R_post(sd)  mean err2(sd)  p90 err2(sd)')
        for n, r, mean, p90 in bins(R, e):
            print(f'{n:5d}   {r:.5f} ({math.sqrt(r):.3f})   {mean:.5f} ({math.sqrt(mean):.3f})   {p90:.5f} ({math.sqrt(p90):.3f})')
    # frame-to-frame variability: deviation of each view from its scene's mean z, per R
    dev = np.full_like(Rl, np.nan)
    for kind in ('cube', 'gallery', 'studio'):
        for s in np.unique(d['scene'][d['kind'] == kind]):
            m = (d['kind'] == kind) & (d['scene'] == s)
            if m.sum() < 3:
                continue
            zz = d['z'][m]; dev[m] = ((zz - zz.mean(0)) / 65536.0) ** 2 * m.sum() / (m.sum() - 1)
    m = ~np.isnan(dev[:, 0]) & (d['win'] > 0)
    R = Rl[m].ravel(); e = dev[m].ravel()
    print(f'\nreframed views, deviation from the scene mean (frame-to-frame): n={m.sum()}')
    for n, r, mean, p90 in bins(R, e):
        print(f'{n:5d}   {r:.5f} ({math.sqrt(r):.3f})   {mean:.5f} ({math.sqrt(mean):.3f})   {p90:.5f} ({math.sqrt(p90):.3f})')




RBASE = 0.001           # R_post at knot 0
STEP = 0.25             # ln step between knots
NK = 17


def fit_table(d, floor=2.5e-5):
    """Monotone R_eff knots (float variance) from the frame-to-frame variability of reframed views, per R_post bin."""
    q = 2.0 ** 32
    Rl = d['R'] / q
    dev = np.full_like(Rl, np.nan)
    for kind in ('cube', 'gallery', 'studio'):
        for s in np.unique(d['scene'][d['kind'] == kind]):
            m = (d['kind'] == kind) & (d['scene'] == s) & (d['win'] > 0)
            if m.sum() < 3:
                continue
            zz = d['z'][m]; dev[m] = ((zz - zz.mean(0)) / 65536.0) ** 2 * m.sum() / (m.sum() - 1)
    ok = ~np.isnan(dev[:, 0])
    R = Rl[ok].ravel(); e = dev[ok].ravel()
    k = np.clip(np.rint((np.log(R) - math.log(RBASE)) / STEP), 0, NK - 1).astype(int)
    out = np.zeros(NK); cnt = np.zeros(NK, int); p90 = np.zeros(NK)
    for i in range(NK):
        m = k == i
        cnt[i] = m.sum()
        if m.sum() >= 30:
            out[i] = e[m].mean(); p90[i] = np.percentile(e[m], 90)
        else:
            out[i] = np.nan
    idx = np.arange(NK); good = ~np.isnan(out)
    out = np.interp(idx, idx[good], out[good])
    out = np.maximum.accumulate(np.maximum(out, floor))
    return out, cnt, p90


def write_table(scale=4.0, floor_sd=0.01):
    """R_eff knots (Q32) = max(scale * frame-to-frame variance, floor), monotone; written to reff.json for ref.build_tables."""
    import json
    T, _, _ = ref.build_tables(ref.load_cal())
    t, _, _ = fit_table(load(T))
    k = np.maximum.accumulate(np.maximum(t * scale, floor_sd ** 2))
    knots = [int(round(x * 2 ** 32)) for x in k]
    (ref.HERE / 'reff.json').write_text(json.dumps(dict(scale=scale, floor_sd=floor_sd, rbase=RBASE, knots=knots), indent=1))
    return knots


def report_table():
    T, _, _ = ref.build_tables(ref.load_cal())
    d = load(T)
    t, cnt, p90 = fit_table(d)
    print('knot  R_post(sd)      count  p90 f2f(sd)   R_eff(sd)')
    for i in range(NK):
        r = RBASE * math.exp(STEP * i)
        print(f'{i:3d}  {r:.5f} ({math.sqrt(r):.3f})  {cnt[i]:6d}  {math.sqrt(p90[i]):.4f}      {t[i]:.6f} ({math.sqrt(t[i]):.4f})')
    return t


if __name__ == '__main__':
    if '--bins' in sys.argv:
        main()
    report_table()
    if '--write' in sys.argv:
        print(write_table())
