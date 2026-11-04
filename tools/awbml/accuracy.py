# SPDX-License-Identifier: GPL-2.0-only
"""Accuracy report: (a) float FFCC model, (b) integer pipeline without calibration, (c) integer pipeline with calibration
(final gains), angular error in GR IV stats space on the SimpleCube++ test split; per-shot errors and warmth / tint
residuals on the four studio shots; the calibration constants baked into the tables."""
import json
import math
import sys

import numpy as np

import ref
import scenes
from calib import truth_q16

sys.path.insert(0, str(ref.HERE / 'train'))      # ffcc.py
STAT = scenes.STAT_F


def ang(a, b):
    a = a / np.linalg.norm(a, axis=-1, keepdims=True); b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(np.arccos(np.clip((a * b).sum(-1), -1, 1)))


def stats_line(e):
    e = np.sort(e)
    return f'mean {e.mean():5.3f}   median {np.median(e):5.3f}   worst25% {e[-max(1, len(e) // 4):].mean():5.3f}'


def uv_to_stats(u, v):
    return np.array([math.exp(-u / 65536), 1.0, math.exp(-v / 65536)])


def gains_to_stats(g0, g3):
    raw = np.array([8192 * 0.6313 / g0, 1.0, 8192 * 0.3313 / g3])
    return raw * STAT


def warm_tint(est_raw, tru_raw):
    r, b = tru_raw[0] / est_raw[0], tru_raw[2] / est_raw[2]
    return math.log2(r / b), math.log2(math.sqrt(r * b))


def float_model():
    try:
        import jax.numpy as jnp
        import ffcc as M
    except Exception:
        return None
    p = np.load(ref.PARAMS)
    P = dict(F=jnp.asarray(p['F']), B=jnp.asarray(p['B']))

    def est(s, ev):
        h = jnp.asarray(M.histograms(np.asarray(s).astype(np.int64)))[None]
        u, v = M.predict(P, h, M.meta_features(jnp.asarray([ev])))
        return np.asarray(M.uv_to_rgb(u, v))[0]
    return est


def main():
    T, blob, offs = ref.build_tables()
    cal = json.load(open(ref.CAL_JSON))
    cube, pr = scenes.load_cube()
    te = ~pr['tr']
    fl = pr['learned_+_exposure']
    gt = np.array([c['gt'] for c in cube])
    ib = np.zeros_like(gt); ic = np.zeros_like(gt)
    for i in np.where(te)[0]:
        a = scenes.scene_args(cube[i]['s'], cube[i]['ev'])
        args = (T, a['R'], a['Gr'], a['Gb'], a['B'], a['cnt'], a['x0'], a['y0'], a['w'], a['h'], a['stride'], a['v24'], a['e30'])
        ib[i] = uv_to_stats(*ref.estimate_uv(*args))
        ic[i] = gains_to_stats(*ref.awbml_ref(*args, a['mode']))
    print(f'SimpleCube++ test split, n = {int(te.sum())}; angular error to the measured illuminant (degrees, stats space)')
    ea, eb, ec = ang(fl[te], gt[te]), ang(ib[te], gt[te]), ang(ic[te], gt[te])
    print(f'  (a) float model                       {stats_line(ea)}')
    print(f'  (b) integer, no calibration           {stats_line(eb)}')
    print(f'  (c) integer, calibrated (final gains) {stats_line(ec)}')
    print(f'  |(b) - (a)| median {np.median(ang(ib[te], fl[te])):.4f}  mean {ang(ib[te], fl[te]).mean():.4f}  max {ang(ib[te], fl[te]).max():.3f} deg;'
          f'  median (b)-(a) error difference {np.median(eb) - np.median(ea):+.4f}')
    print(f'  |(c) - (b)| median {np.median(ang(ic[te], ib[te])):.3f}  mean {ang(ic[te], ib[te]).mean():.3f}  max {ang(ic[te], ib[te]).max():.3f} deg (what the calibration moves)')

    print('\nStudio shots (real GR IV, measured neutral); warmth = log2 R/B of a neutral after white balance (+ orange), tint = log2 sqrt(RB)/G (+ magenta)')
    fm = float_model()
    print(f'  {"shot":8s} {"method":22s} {"R/G":>7s} {"B/G":>7s} {"error":>7s} {"warmth":>8s} {"tint":>8s}')
    for sc in scenes.load_studio():
        a = scenes.scene_args(sc['s'], sc['ev'])
        args = (T, a['R'], a['Gr'], a['Gb'], a['B'], a['cnt'], a['x0'], a['y0'], a['w'], a['h'], a['stride'], a['v24'], a['e30'])
        rows = []
        if fm:
            rows.append(('(a) float', fm(sc['s'], sc['ev'])))
        rows.append(('(b) integer, uncal', uv_to_stats(*ref.estimate_uv(*args))))
        rows.append(('(c) integer, calibrated', gains_to_stats(*ref.awbml_ref(*args, 0))))
        for n, est in rows:
            raw = est / STAT
            wt, tn = warm_tint(raw / raw[1], sc['raw'])
            print(f'  {sc["name"]:8s} {n:22s} {raw[0] / raw[1]:7.4f} {raw[2] / raw[1]:7.4f} {ang(est, sc["gt"]):6.2f}d {wt:+8.3f} {tn:+8.3f}')
        print(f'  {sc["name"]:8s} truth                  {sc["raw"][0]:7.4f} {sc["raw"][2]:7.4f}')

    c = cal['cal']; f = cal['fit']
    print('\nCalibration constants baked in (Q16 log units, u = ln(1/(R/G)), v = ln(1/(B/G)), 65536 = 1.0)')
    print(f'  P_d (daylight mean estimate)   {f["Pd"]}  = ({f["Pd"][0] / 65536:.4f}, {f["Pd"][1] / 65536:.4f})')
    print(f'  P_t (warm low-light estimate)  {f["Pt"]}  = ({f["Pt"][0] / 65536:.4f}, {f["Pt"][1] / 65536:.4f})')
    print(f'  D_d (truth - estimate, day)    {f["Dd"]}  = ({f["Dd"][0] / 65536:+.4f}, {f["Dd"][1] / 65536:+.4f})')
    print(f'  D_t (truth - estimate, warm)   {f["Dt"]}  = ({f["Dt"][0] / 65536:+.4f}, {f["Dt"][1] / 65536:+.4f})')
    print(f'  P_t - P_d {c["dP"]}, D_t - D_d {c["dD"]}, 1/|P_t-P_d|^2 as 2^48/den = {c["inv"]}')
    print(f'  (fitted and checked on the same four shots: the studio numbers above are in-sample for (c))')


if __name__ == '__main__':
    main()
