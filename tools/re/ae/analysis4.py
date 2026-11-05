# SPDX-License-Identifier: GPL-2.0-only
"""Robustness for the reviewer's points: (A) experts are anchored to the DSLR's as-shot exposure -> add the as-shot level as a
feature and let the GR's own level in; (B) de-duplicate repeated scenes; (C) HC split of the clipping comparison."""
import json, sys, numpy as np, warnings
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import _paths
warnings.filterwarnings('ignore')
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import KFold
fk = [r for r in json.load(open('fk_table.json')) if 'error' not in r and len(r['experts']) == 5 and r['ev100'] is not None]
gr = json.load(open('gr_table.json'))
green = _paths.EXCLUDE
sel = [i for i, r in enumerate(gr) if r['ec'] == 0 and r['name'] not in green]
G = [gr[i] for i in sel]
gg = json.load(open('gap_by_expert.json'))
assert [r['name'] for r in G] == gg['names']
slope = np.array(gg['slope'])
SHAPE = ['s_q2','s_q10','s_q25','s_q50','s_q75','s_q90','s_q98','s_std','s_rng','s_top_minus_bottom','s_centre_minus_all','s_cell_std','s_cell_max_minus_mean']
def be_of(r): return float(r.get('be') or 0.0)
variants = {
  'none':        lambda r: [],
  'lvl':         lambda r: [r['lvl_mean']],
  'lvl+BE':      lambda r: [r['lvl_mean'] + be_of(r)],
}
Ljpg = np.array([r['disp']['L_p50'] for r in G])
print('FiveK n=%d  GR n=%d' % (len(fk), len(G)))
print('FiveK BaselineExposure: median %.2f  p10 %.2f p90 %.2f ; None count %d' % (np.median([be_of(r) for r in fk]), np.percentile([be_of(r) for r in fk], 10), np.percentile([be_of(r) for r in fk], 90), sum(1 for r in fk if r.get('be') is None)))
print('GR as-shot rendered level lvl_mean+BE: median %.2f ; FiveK: median %.2f' % (np.median([r['lvl_mean']+be_of(r) for r in G]), np.median([r['lvl_mean']+be_of(r) for r in fk])))
out = {}
for vn, vf in variants.items():
    Xf = np.array([[r[f] for f in SHAPE] + [r['ev100']] + vf(r) for r in fk], float)
    Xg = np.array([[r[f] for f in SHAPE] + [r['ev100']] + vf(r) for r in G], float)
    line = {}
    for tag, letters in [('consensus', 'abcde')] + [(l, l) for l in 'abcde']:
        y = np.array([np.mean([r['experts'][l]['L_p50'] for l in letters]) for r in fk])
        ps = []
        for s in range(5):
            idx = np.random.RandomState(s).choice(len(fk), int(.85 * len(fk)), replace=False)
            ps.append(HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=250, min_samples_leaf=20, random_state=s).fit(Xf[idx], y[idx]).predict(Xg))
        p = np.mean(ps, 0); gap = p - Ljpg; st = gap / np.maximum(slope, 6.0)
        line[tag] = st
        if tag == 'consensus':
            # CV rmse (image folds)
            pr = np.zeros(len(fk))
            for tr, te in KFold(5, shuffle=True, random_state=0).split(Xf):
                pr[te] = HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=250, min_samples_leaf=20, random_state=0).fit(Xf[tr], y[tr]).predict(Xf[te])
            cv = float(np.sqrt(np.mean((pr - y) ** 2)))
    out[vn] = line
    print('%-7s CV RMSE(consensus p50) %.2f L* | stops (+ = GR darker than experts): ' % (vn, cv) + '  '.join('%s %+.2f' % (k, v.mean()) for k, v in line.items()))
# (B) de-duplicate: the three shots of the same rock scene -> one
names = [r['name'] for r in G]
dup = [names.index(n) for n in ('77497572', '36480343', '59402554') if n in names]
print('dup idx', dup, [names[i] for i in dup])
for vn in variants:
    st = out[vn]['consensus']
    keep = [i for i in range(len(st)) if i not in dup]
    sc = np.append(st[keep], st[dup].mean())
    rng = np.random.RandomState(3)
    bs = [rng.choice(sc, len(sc)).mean() for _ in range(5000)]
    print('%-7s dedup n=%d mean %+.3f  90%% scene-bootstrap [%+.3f, %+.3f]  sd %.2f' % (vn, len(sc), sc.mean(), *np.percentile(bs, [5, 95]), sc.std(ddof=1)))
json.dump({v: {k: list(map(float, a)) for k, a in d.items()} for v, d in out.items()}, open('anchor_variants.json', 'w'))
