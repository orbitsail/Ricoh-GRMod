# SPDX-License-Identifier: GPL-2.0-only
"""Fits the two-point calibration (daylight / warm low light) on the four real GR IV studio shots and writes cal.json.

The integer pipeline is run WITHOUT calibration on each shot; truth in the model's units is
u_t = ln(1/(0.920 R/G)), v_t = ln(1/(0.974 B/G)) from the measured raw neutral. Per lighting (day100 + day200; low100 +
low200) the mean estimate P and the mean correction D = truth - estimate; any estimate P is then corrected by
P' = P + D_d + s (D_t - D_d), s = clamp(((P - P_d).(P_t - P_d)) / |P_t - P_d|^2, 0, 1)."""
import json
import math

import numpy as np

import ref
import scenes


def uncalibrated(T, sc):
    a = scenes.scene_args(sc['s'], sc['ev'])
    return ref.estimate_uv(T, a['R'], a['Gr'], a['Gb'], a['B'], a['cnt'], a['x0'], a['y0'], a['w'], a['h'], a['stride'], a['v24'], a['e30'])


def truth_q16(sc):
    rg, bg = sc['raw'][0], sc['raw'][2]
    return (round(-math.log(0.920 * rg) * 65536), round(-math.log(0.974 * bg) * 65536))


def fit():
    T, _, _ = ref.build_tables(ref.default_cal())
    shots = {sc['name']: sc for sc in scenes.load_studio()}
    est = {k: np.array(uncalibrated(T, sc), dtype=float) for k, sc in shots.items()}
    tru = {k: np.array(truth_q16(sc), dtype=float) for k, sc in shots.items()}
    grp = {'day': ['day100', 'day200'], 'warm': ['low100', 'low200']}
    P = {g: sum(est[k] for k in ks) / len(ks) for g, ks in grp.items()}
    D = {g: sum(tru[k] - est[k] for k in ks) / len(ks) for g, ks in grp.items()}
    r = lambda a: [int(round(x)) for x in a]
    Pd, Pt, Dd, Dt = r(P['day']), r(P['warm']), r(D['day']), r(D['warm'])
    cal = ref.make_cal(Pd, Pt, Dd, Dt)
    return cal, dict(est={k: est[k].tolist() for k in est}, truth={k: tru[k].tolist() for k in tru}, Pd=Pd, Pt=Pt, Dd=Dd, Dt=Dt)


if __name__ == '__main__':
    cal, info = fit()
    json.dump(dict(cal=cal, fit=info), open(ref.CAL_JSON, 'w'), indent=1)
    print(json.dumps(info, indent=1))
    print('cal', cal)
