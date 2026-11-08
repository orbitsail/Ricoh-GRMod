# SPDX-License-Identifier: GPL-2.0-only
"""Loads the evaluation scenes (SimpleCube++ in GR IV stats space, GR IV gallery scenes, studio shots)."""
import json
import math

import numpy as np

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 're'))
import griv_env

STAT_F = np.array([0.920, 1.0, 0.974])
STUDIO = {  # name: (raw R/G, raw B/G, N, t, ISO)
    'day100': (0.3401, 0.6688, 5.6, 1 / 40, 100), 'day200': (0.3391, 0.6692, 5.6, 1 / 80, 200),
    'low100': (0.6647, 0.3217, 5.6, 3.0, 100), 'low200': (0.6648, 0.3212, 5.6, 1.6, 200)}


def ev_of(N, t, iso):
    return 2 * math.log2(N) - math.log2(t) - math.log2(iso / 3.125)


def scene_args(s, ev):
    """Normal still: 64 x 62 grid at y0 = 1, stride 64; G taken as Gr = Gb."""
    s = np.asarray(s).astype(np.int64)
    flat = [s[k].ravel() for k in range(4)]
    return dict(R=flat[0], Gr=flat[1], Gb=flat[1], B=flat[2], cnt=flat[3], x0=0, y0=1, w=64, h=62, stride=64,
                v24=0, e30=int(round(ev * 256)), mode=0)


def load_cube():
    pr = np.load(griv_env.data('learnawb', 'cube_eval_preds.npz'), allow_pickle=True)
    names = [str(n) for n in pr['names']]
    out = []
    for nm in names:
        z = np.load(griv_env.data('cubepp_gr', f'{nm}.npz'), allow_pickle=True)
        rn, bn = (float(x) for x in z['gt_gr'])
        ev = float(z['Av']) + float(z['Tv']) - float(z['Sv'])
        out.append(dict(name=nm, s=z['s'], gt=np.array([STAT_F[0] * rn, 1.0, STAT_F[2] * bn]), ev=ev, Av=float(z['Av']), Sv=float(z['Sv'])))
    return out, pr


def load_gallery():
    summ = json.load(open(griv_env.data('grdng', 'ext', 'summary.json')))
    out = []
    for r in summ:
        z = np.load(griv_env.data('grdng', 'ext', f"{r['id']}.npz"))
        out.append(dict(name=r['id'], s=z['s'], ev=ev_of(r['N'], r['t'], r['iso']), wp=r['wp'], Av=2 * math.log2(r['N']), Sv=math.log2(r['iso'] / 3.125)))
    return out


def load_studio():
    out = []
    for nm, (rg, bg, N, t, iso) in STUDIO.items():
        z = np.load(griv_env.data('studio', f'{nm}.npz'))
        out.append(dict(name=nm, s=z['s'], ev=ev_of(N, t, iso), Av=2 * math.log2(N), Sv=math.log2(iso / 3.125), raw=np.array([rg, 1.0, bg]),
                        gt=np.array([STAT_F[0] * rg, 1.0, STAT_F[2] * bg])))
    return out
