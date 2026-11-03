# SPDX-License-Identifier: GPL-2.0-only
"""Filter design simulation (task: calibrated observation variance + reset rule). Observations come from the integer
reference (ref.observe); the filter variants run in floating point over them. Prints one metrics table and per-call outputs."""
import importlib.util
import math
import pickle
import sys

import numpy as np

import calib_r
import ref
import scenes

SP = ref.SP
CACHE = SP / 'awbml_work' / 'sim2_obs2.pkl'
_spec = importlib.util.spec_from_file_location('grscenes', SP / 'grdng' / 'scenes.py')
g = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(g)
Q16 = 65536.0
NS = 32          # computing calls per static run


def rand_windows(rng, n):
    return calib_r.windows(rng, n)


def views(T, args, wins):
    out = []
    for wn in wins:
        b = dict(args)
        if wn:
            b.update(x0=wn[0], y0=wn[1], w=wn[2], h=wn[3])
        o = ref.observe(T, **b)
        out.append(None if o is None else (o[0] / Q16, o[1] / Q16, o[2] / 2 ** 32, o[3] / 2 ** 32))
    return out


def build_obs(T):
    rng = np.random.default_rng(7)
    d = {}
    cube, _ = scenes.load_cube()
    # confidence of the full frame, to find the least-confident quarter
    full = []
    for sc in cube:
        o = ref.observe(T, **scenes.scene_args(sc['s'], sc['ev']))
        full.append(1.0 if o is None else (o[2] + o[3]) / 2 ** 33)
    order = np.argsort(full)
    quarter = order[-len(cube) // 4:]
    pick = lambda idx, n: [int(i) for i in rng.choice(idx, n, replace=False)]
    d['cube'] = []
    for i in pick(np.arange(len(cube)), 120):
        sc = cube[i]
        a = scenes.scene_args(sc['s'], sc['ev'])
        v = [x for x in views(T, a, rand_windows(rng, NS)) if x]
        d['cube'].append(dict(name=sc['name'], obs=v, tr=(-math.log(sc['gt'][0]), -math.log(sc['gt'][2]))))
    d['amb'] = []
    for i in pick(quarter, 120):
        sc = cube[i]
        a = scenes.scene_args(sc['s'], sc['ev'])
        v = [x for x in views(T, a, rand_windows(rng, NS)) if x]
        d['amb'].append(dict(name=sc['name'], obs=v, tr=(-math.log(sc['gt'][0]), -math.log(sc['gt'][2]))))
    d['gal'] = []
    for sc in scenes.load_gallery() + scenes.load_studio():
        a = scenes.scene_args(sc['s'], sc['ev'])
        v = [x for x in views(T, a, rand_windows(rng, NS)) if x]
        d['gal'].append(dict(name=sc['name'], obs=v, tr=None))
    d['studio'] = {}
    for sc in scenes.load_studio():
        a = scenes.scene_args(sc['s'], sc['ev'])
        d['studio'][sc['name']] = [x for x in views(T, a, [None] + rand_windows(rng, 40)) if x]
    lights = {'day': (5500, 10), 'warm28': (2800, 6), 'warm30': (3000, 6), 'shade': (7500, 9), 'cool4': (4000, 7), 'near': (5000, 10)}
    d['relit'] = {}
    for rid in g.DAYLIT:
        for nm, (Tk, ev) in lights.items():
            sc = g.relit_scene(rid, Tk, ev)
            s = np.stack([sc['R'], sc['G'], sc['B'], sc['D']])
            a = scenes.scene_args(s, sc['e30'] / 256)
            v = [x for x in views(T, a, rand_windows(rng, 40)) if x]
            d['relit'][(rid, nm)] = v
    return d


def load_obs(T):
    if CACHE.exists():
        return pickle.load(open(CACHE, 'rb'))
    d = build_obs(T)
    pickle.dump(d, open(CACHE, 'wb'))
    return d


# ---- filter variants ----
class Cand:
    def __init__(self, name, rule='single', q=0.015, k=3.0, rconf_sd=0.03, scale=1.0, floor_sd=0.005, reset_to='new', table=None):
        self.name, self.rule, self.q2, self.k2, self.rc = name, rule, q * q, k * k, rconf_sd ** 2
        self.scale, self.floor, self.reset_to, self.table = scale, floor_sd ** 2, reset_to, table

    def reff(self, rp):
        if self.table is None:
            return rp
        x = (math.log(max(rp, 1e-9)) - math.log(calib_r.RBASE)) / calib_r.STEP
        x = min(max(x, 0.0), calib_r.NK - 1.0001)
        i = int(x); f = x - i
        v = self.table[i] * (1 - f) + self.table[i + 1] * f
        return max(v * self.scale, self.floor)


def run(c, obs):
    """-> (outputs (n,2), resets list of call indices)"""
    mu = None; sg = None; out = []; resets = []; cand = None
    for n, (u, v, ru, rv) in enumerate(obs):
        z = np.array([u, v]); r = np.array([c.reff(ru), c.reff(rv)])
        if mu is None:
            mu = z.copy(); sg = r.copy()
        else:
            sgp = sg + c.q2
            conf = r.max() < c.rc
            d = z - mu
            ex = d * d > c.k2 * (sgp + r)
            sign = np.where(ex, np.sign(d), 0)
            if c.rule != 'none' and conf and ex.any():
                if c.rule == 'single':
                    mu = z.copy(); sg = r.copy(); resets.append(n); out.append(mu.copy()); continue
                if cand is not None and ((cand[1] * sign) > 0).any():
                    mu = z.copy() if c.reset_to == 'new' else (cand[0] + z) / 2
                    sg = r.copy(); cand = None; resets.append(n); out.append(mu.copy()); continue
                cand = (z.copy(), sign); sg = sgp; out.append(mu.copy()); continue
            cand = None
            k = sgp / (sgp + r)
            mu = mu + k * d; sg = sgp - k * sgp
        out.append(mu.copy())
    return np.array(out), resets


def raw(obs):
    return np.array([[o[0], o[1]] for o in obs])


def ang(u, v, tu, tv):
    a = np.stack([np.exp(-u), np.ones_like(u), np.exp(-v)], -1); b = np.stack([np.exp(-tu), 1, np.exp(-tv)])
    a = a / np.linalg.norm(a, axis=-1, keepdims=True); b = b / np.linalg.norm(b)
    return np.degrees(np.arccos(np.clip(a @ b, -1, 1)))


def static_metrics(c, runs):
    err, steps, resets, calls, nseq_reset = [], [], 0, 0, 0
    for r in runs:
        o = raw(r['obs']) if c is None else run(c, r['obs'])[0]
        if c is not None:
            rs = run(c, r['obs'])[1]
            resets += len(rs); nseq_reset += bool(rs)
        calls += len(o)
        steps.append(np.linalg.norm(np.diff(o[2:], axis=0), axis=1))
        if r['tr'] is not None:
            err.append(ang(o[-16:, 0], o[-16:, 1], *r['tr']).mean())
    st = np.concatenate(steps)
    return dict(err_mean=np.mean(err) if err else np.nan, err_p90=np.percentile(err, 90) if err else np.nan,
                jit_std=st.std(), jit_p99=np.percentile(st, 99), resets=resets / calls, seqs=nseq_reset / len(runs))


SWITCHES = {'day>warm28': ('day', 'warm28'), 'warm28>day': ('warm28', 'day'), 'day>warm30': ('day', 'warm30'),
            'warm30>day': ('warm30', 'day'), 'day>shade': ('day', 'shade'), 'day>cool4': ('day', 'cool4'), 'small day>near': ('day', 'near')}
NA, NB = 12, 24


STUDIO_SW = {'studio day>low': ('day100', 'low100'), 'studio low>day': ('low100', 'day100'),
             'studio day>low200': ('day200', 'low200'), 'studio low200>day': ('low200', 'day200')}
CONF_MAX = 0.0125     # a light counts as confident when the views' mean R_post is below this (sd 0.11)


def mean_r(v):
    return float(np.mean([(x[2] + x[3]) / 2 for x in v]))


def switch_runs(d, name, nrep=3, seed=3, conf=True):
    rng = np.random.default_rng(seed)
    runs = []
    if name.startswith('shift'):          # synthetic: confident static views, the estimate moves by that many log units (u up, v down)
        off = float(name.split()[1]) / math.sqrt(2)
        for r in d['cube'] + d['gal']:
            if len(r['obs']) < 20 or mean_r(r['obs']) > CONF_MAX:
                continue
            for _ in range(2):
                ia = rng.integers(0, len(r['obs']), NA + NB)
                run_ = [r['obs'][i] for i in ia]
                runs.append(run_[:NA] + [(o[0] + off, o[1] - off, o[2], o[3]) for o in run_[NA:]])
        return runs
    if name in STUDIO_SW:
        a, b = STUDIO_SW[name]
        va, vb = d['studio'][a], d['studio'][b]
        for _ in range(30):
            ia = rng.permutation(len(va))[:NA]; ib = rng.permutation(len(vb))[:NB]
            runs.append([va[i] for i in ia] + [vb[i] for i in ib])
        return runs
    a, b = SWITCHES[name]
    for rid in g.DAYLIT:
        va, vb = d['relit'][(rid, a)], d['relit'][(rid, b)]
        if len(va) < 20 or len(vb) < 20 or (conf and (mean_r(va) > CONF_MAX or mean_r(vb) > CONF_MAX)):
            continue
        for _ in range(nrep * 3):
            ia = rng.permutation(len(va))[:NA]; ib = rng.permutation(len(vb))[:NB]
            runs.append([va[i] for i in ia] + [vb[i] for i in ib])
    return runs


def lag_of(o, final, tol=0.02):
    """Computing calls after the switch (1 = the first) until the output is within tol (log units) of the new steady state."""
    dist = np.linalg.norm(o[NA:] - final, axis=1)
    hit = np.nonzero(dist < tol)[0]
    return int(hit[0]) + 1 if len(hit) else NB + 1


def switch_metrics(c, runs, tol=0.02):
    lags, conf_lags = [], []
    for r in runs:
        o = raw(r) if c is None else run(c, r)[0]
        final = raw(r[-8:]).mean(0)           # the new light's own steady state: mean of the last observations
        lag = lag_of(o, final, tol)
        lags.append(lag)
        conf_lags.append(lag)
    lags = np.array(lags); cl = np.array(conf_lags) if conf_lags else np.array([np.nan])
    return dict(n=len(lags), med=float(np.median(lags)), p90=float(np.percentile(lags, 90)), le2=float((lags <= 2).mean()),
                cn=len(conf_lags), cmed=float(np.median(cl)), cle2=float((cl <= 2).mean()), cp90=float(np.percentile(cl, 90)))


SWL = ['studio day>low', 'studio low>day', 'studio day>low200', 'studio low200>day', 'day>shade', 'shift 0.05', 'shift 0.10']
UNC = {'day>warm28': ('day', 'warm28'), 'day>cool4': ('day', 'cool4')}


def candidates(tab):
    cands = [None, Cand('none (Kalman only)', 'none', 0.015, 3, 0.03, 4.0, 0.01, 'new', tab),
             Cand('v8 (R_post, single, q.015 k3 c.03)', 'single', 0.015, 3, 0.03, 1, 0.0, 'new', None)]
    for rule, rt in (('single', 'new'), ('persist', 'new'), ('persist', 'mean')):
        for sc_ in (2.0, 4.0):
            for q in (0.01, 0.015):
                for k in (3, 4):
                    for rc in (0.03,):
                        cands.append(Cand(f'{rule[:1]}/{rt[:1]} s{sc_:g} q{q} k{k} c{rc}', rule, q, k, rc, sc_, 0.01, rt, tab))
    return cands


def evaluate(cands, d):
    sw = {n: switch_runs(d, n) for n in SWL}
    unc = {n: switch_runs(d, n, conf=False) if False else None for n in UNC}
    rows = []
    for c in cands:
        s1 = static_metrics(c, d['cube'] + d['gal']); s2 = static_metrics(c, d['amb'])
        sws = [switch_metrics(c, sw[n]) for n in SWL]
        rows.append((c, s1, s2, sws))
    return rows, sw


def fmt(rows, sw):
    print('static: cube+gallery+studio views (err = angular error of the last 16 calls vs truth, cube only); ambiguous = least-confident quarter of the cube')
    print('switch cells: median lag (calls to stay within 0.02 log of the new steady state) / share <= 2 calls; n runs: ' + ', '.join(f'{n} {len(sw[n])}' for n in SWL))
    print(f'{"candidate":34s}|err mean p90 | jit std  p99  resets | amb jit std  p99  resets| ' + '|'.join(f'{n[:10]:>10s}' for n in SWL))
    for c, s1, s2, sws in rows:
        nm = 'v7 (single frame)' if c is None else c.name
        print(f'{nm:34s}|{s1["err_mean"]:5.2f} {s1["err_p90"]:5.2f}|{s1["jit_std"]:.4f} {s1["jit_p99"]:.4f} {s1["resets"]:.4f}|{s2["jit_std"]:.4f} {s2["jit_p99"]:.4f} {s2["resets"]:.4f}|' +
              '|'.join(f'{x["med"]:3.0f} {x["le2"]:.2f}'.rjust(10) for x in sws))


def run_int(T, obs):
    """The chosen filter through the integer reference (ref.reff / ref.kalman); -> outputs (n, 2) in log units and reset flags."""
    st = None; out = []; fl = []
    for u, v, ru, rv in obs:
        z = [round(u * Q16), round(v * Q16)]
        r = [ref.reff(T, round(ru * 2 ** 32)), ref.reff(T, round(rv * 2 ** 32))]
        st = ref.kalman(T, st, z, r)
        out.append([st['mu'][0] / Q16, st['mu'][1] / Q16]); fl.append('R' if st.get('reset') else ('h' if st.get('held') else ''))
    return np.array(out), fl, r


def show(T, d, tab):
    v8 = Cand('v8', 'single', 0.015, 3, 0.03, 1, 0.0, 'new', None)
    pick = {}
    cu = [r for r in d['cube'] if r['tr']]
    pick['static (cube scene, reframed views)'] = (d['cube'][3]['obs'][:20], d['cube'][3]['tr'], 0)
    pick['ambiguous (least-confident quarter)'] = (d['amb'][5]['obs'][:20], d['amb'][5]['tr'], 0)
    for title, runs, lo in (('studio day100 > low100 (real 2700-3000 K), switch after call 12', switch_runs(d, 'studio day>low'), 8),
                            ('5500 K > 7500 K shade (relit), switch after call 12', switch_runs(d, 'day>shade'), 8),
                            ('synthetic shift of 0.05 log (u up, v down) after call 12', switch_runs(d, 'shift 0.05'), 8)):
        pick[title] = (runs[0][lo:lo + 12], None, lo)
    for title, (obs, tr, lo) in pick.items():
        full = obs
        if lo:
            # keep the filter history: rerun from the start of the run
            pass
        print(f'\n{title}')
        print(' call |   z (u, v)      R_eff sd |   v7 (u, v)   |   v8 (u, v)   |  v8b (u, v)  ev')
        if lo:
            runs = {'studio': 'studio day>low', 'shade': 'day>shade', 'synthetic': 'shift 0.05'}
            key = [k for k in runs if title.startswith(k) or k in title][0]
            obs_full = switch_runs(d, runs[key])[0]
        else:
            obs_full = obs
        o8, _ = run(v8, obs_full); ob, fl, _ = run_int(T, obs_full)
        z = raw(obs_full)
        rng_ = range(lo, lo + 12) if lo else range(0, 16)
        for n in rng_:
            ro = [ref.reff(T, round(obs_full[n][2] * 2 ** 32)), ref.reff(T, round(obs_full[n][3] * 2 ** 32))]
            print(f'{n + 1:5d} | {z[n][0]:6.3f} {z[n][1]:6.3f} {math.sqrt(ro[0] / 2 ** 32):.3f}/{math.sqrt(ro[1] / 2 ** 32):.3f} | {z[n][0]:6.3f} {z[n][1]:6.3f} | {o8[n][0]:6.3f} {o8[n][1]:6.3f} | {ob[n][0]:6.3f} {ob[n][1]:6.3f}  {fl[n]}')
        if tr:
            print(f'      truth (u, v) = ({tr[0]:.3f}, {tr[1]:.3f})')


def main():
    T, _, _ = ref.build_tables(ref.load_cal())
    d = load_obs(T)
    tab, _, _ = calib_r.fit_table(calib_r.load(T))
    rows, sw = evaluate(candidates(tab), d)
    fmt(rows, sw)
    show(T, d, tab)
    return rows


if __name__ == '__main__':
    main()
