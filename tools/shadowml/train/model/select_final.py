"""3-5. Robust training + selection without optimism.
Candidates: features {full, relative-only} x exposure augmentation {off, on (-.5,-.25,0,+.25,+.5 stop, labels recomputed)} x target {M5: median of five on five-expert images,
M5C: M5 plus C-only images (target = s*_C) at weight 0.3} x depth {2, 3}.
Selection: 5-fold camera-grouped CV on the DEV set (80 % of images; ~20 % held out by camera hash, untouched), CV regret5 AND sensitivity on the 35 DPReview planes.
Rule: among candidates within TOL of the best CV regret5, take the least sensitive.  Final numbers: dev-fit model on the HOLDOUT, plus baselines.  Shipped blob: chosen config refit on ALL data."""
import sys, os, json
sys.dont_write_bytecode = True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common2 import *
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from scipy.stats import spearmanr
TOL = 0.0010   # ~4 % of regret5; paired-bootstrap CIs of differences between candidates are about +-0.003, so smaller gaps are not resolved
LSCALE = 16
def cfg_of(c):
    return dict(n=100, d=c['depth'], lr=0.05, leaf=20 * (5 if c['aug'] else 1), loss='huber')
def train_rows(rows, c):
    rr = [r for r in rows if (c['aug'] or r['off'] == 0.0)]
    X, y, w = [], [], []
    idx = FULL if c['feat'] == 'full' else REL
    for r in rr:
        if r['nexp'] == 5: tg, wt = r['sM'], 1.0
        elif c['tgt'] == 'M5C': tg, wt = r['s']['c'], 0.3
        else: continue
        X.append([r['F'][i] for i in idx]); y.append(2 * tg); w.append(wt)
    return np.array(X, float), np.array(y), np.array(w)
def fit(rows, c):
    X, y, w = train_rows(rows, c); g = cfg_of(c)
    return GradientBoostingRegressor(n_estimators=g['n'], max_depth=g['d'], learning_rate=g['lr'], min_samples_leaf=g['leaf'], subsample=0.7, loss='huber', random_state=0).fit(X, y, sample_weight=w)
def predict(m, c, Fs):
    idx = FULL if c['feat'] == 'full' else REL
    return np.clip(m.predict(np.array([[F[i] for i in idx] for F in Fs], float)), 0, 2048)
def eval_rows(rows): return [r for r in rows if r['off'] == 0.0 and r['nexp'] == 5]
def regrets(rows, t):
    sp = np.array([cap_s(tt, r['F'][NAMES.index('idx')]) for tt, r in zip(t, rows)])
    r5 = np.array([np.mean([cost_at(cc, s) for cc in r['costs'].values()]) - np.mean([cc.min() for cc in r['costs'].values()]) for s, r in zip(sp, rows)])
    rC = np.array([cost_at(r['costC'], s) - r['costC'].min() for s, r in zip(sp, rows)])
    return sp, r5, rC
def sensitivity(m, c, RP):
    t0 = predict(m, c, [real_feats(p) for p in RP]); res = {'t0': t0}
    d = {}
    for dl in (-2 / 3, -1 / 3, 1 / 3, 2 / 3):
        t = predict(m, c, [real_feats(p, scale_stops=dl) for p in RP]); d[dl] = np.abs(t - t0)
    res['exp_mean_abs'] = float(np.mean([v.mean() for v in d.values()])); res['exp_third_mean'] = float(np.mean([d[-1 / 3].mean(), d[1 / 3].mean()])); res['exp_max'] = float(max(v.max() for v in d.values()))
    cl = {}
    for cap in (4095, 7683, 8100):
        t = predict(m, c, [real_feats(p, cap=cap) for p in RP]); cl[cap] = np.abs(t - t0)
    res['clip_mean_abs'] = float(np.mean([v.mean() for v in cl.values()])); res['clip_max'] = float(max(v.max() for v in cl.values()))
    res['t_sd'] = float(t0.std())
    res['sens'] = res['exp_mean_abs'] / max(res['t_sd'], 1.0)      # mean |dt| per +-1/3..2/3 stop, relative to the spread of t over the 35 images
    return res
D01 = NAMES.index('d01')
def c5_matrix(rows):
    return np.array([[np.mean([cost_at(cc, SG[k]) for cc in r['costs'].values()]) - np.mean([cc.min() for cc in r['costs'].values()]) for k in range(len(SG))] for r in rows])
def tune_rule(rows, c5=None):
    """best (threshold on d01 in Q8 stops, level t=32k) for the rule t = level if d01 > thr else 0, by mean 5-expert regret on these rows"""
    c5 = c5_matrix(rows) if c5 is None else c5; d = np.array([r['F'][D01] for r in rows]); best = None
    for thr in range(128, 2200, 16):
        on = d > thr
        for k in range(1, len(SG)):
            v = np.where(on, c5[:, k], c5[:, 0]).mean()
            if best is None or v < best[0]: best = (v, thr, 2 * int(SG[k]))
    return best[1], best[2], best[0]
def rule_t(rows, thr, lev): return np.array([lev if r['F'][D01] > thr else 0 for r in rows], float)
def to_trees(m, idxs):
    off = int(round(float(m.init_.predict(np.zeros((1, len(idxs))))[0]))); lr = m.learning_rate; trees = []
    for est in m.estimators_[:, 0]:
        t = est.tree_
        def rec(n):
            if t.children_left[n] == -1: return ('leaf', int(round(lr * float(t.value[n, 0, 0]) * LSCALE)))
            return ('split', idxs[t.feature[n]], int(np.floor(t.threshold[n])), rec(t.children_left[n]), rec(t.children_right[n]))
        trees.append(rec(0))
    return off, trees
def main():
    rows = load_rows(); RP = real_planes()
    hold = [r for r in rows if is_holdout(r['cam'])]; dev = [r for r in rows if not is_holdout(r['cam'])]
    ni = lambda rs: len({r['name'] for r in rs})
    ne = lambda rs: len({r['name'] for r in rs if r['nexp'] == 5})
    print('images total %d (five-expert %d) | dev %d (%d) | holdout %d (%d); holdout cameras: %s' % (ni(rows), ne(rows), ni(dev), ne(dev), ni(hold), ne(hold), sorted({r['cam'] for r in hold})))
    cands = [dict(feat=f, aug=a, tgt=t, depth=d) for f in ('full', 'rel') for a in (False, True) for t in ('M5', 'M5C') for d in (2, 3)]
    ev = eval_rows(dev); camg = np.array([r['cam'] for r in dev]); table = []
    cams = sorted({r['cam'] for r in dev}); gkf = GroupKFold(5)
    cam_arr = np.array(cams); folds = [(set(cam_arr[a]), set(cam_arr[b])) for a, b in gkf.split(cam_arr, groups=cam_arr)]
    # camera-level folds (balanced by number of rows) so every candidate sees the same split
    from sklearn.model_selection import GroupKFold as G2
    gi = np.array([r['cam'] for r in dev]); fold_of = {}
    for k, (a, b) in enumerate(G2(5).split(np.zeros(len(dev)), groups=gi)):
        for c_ in set(gi[b]): fold_of[c_] = k
    for c in cands:
        t_oof = np.zeros(len(ev)); evcam = np.array([fold_of[r['cam']] for r in ev]); fd = np.array([fold_of[r['cam']] for r in dev])
        for k in range(5):
            m = fit([r for r, f in zip(dev, fd) if f != k], c)
            sel = np.nonzero(evcam == k)[0]
            if len(sel): t_oof[sel] = predict(m, c, [ev[i]['F'] for i in sel])
        sp, r5, rC = regrets(ev, t_oof)
        m = fit(dev, c); sn = sensitivity(m, c, RP)
        row = dict(c=c, regret5=float(r5.mean()), regretC=float(rC.mean()), mean_s=float(sp.mean()), **{k: v for k, v in sn.items() if k != 't0'})
        table.append(row)
        print('%-4s aug=%d %-4s d%d | CV regret5 %.4f regretC %.4f meanS %3.0f | sens: exposure mean|dt| %5.1f (+-1/3 stop %5.1f, max %4.0f)  clip mean|dt| %5.1f max %4.0f  t_sd %4.0f  sens/sd %.3f' % (
            c['feat'], c['aug'], c['tgt'], c['depth'], row['regret5'], row['regretC'], row['mean_s'], row['exp_mean_abs'], row['exp_third_mean'], row['exp_max'], row['clip_mean_abs'], row['clip_max'], row['t_sd'], row['sens']), flush=True)
    best5 = min(r['regret5'] for r in table)
    ok = [r for r in table if r['regret5'] <= best5 + TOL]; pick = min(ok, key=lambda r: (r['sens'] + 0.0 * r['regret5']))
    print('\nbest CV regret5 %.4f; tolerance %.4f -> %d candidates; chosen (least sensitive):' % (best5, TOL, len(ok)), pick['c'], 'regret5 %.4f sens/sd %.3f' % (pick['regret5'], pick['sens']))
    c = pick['c']
    # tuned simple rule: CV on the same camera folds
    c5ev = c5_matrix(ev); evcam_f = np.array([fold_of[r['cam']] for r in ev]); t_rule = np.zeros(len(ev)); chosen_rules = []
    for k in range(5):
        tr = np.nonzero(evcam_f != k)[0]; te = np.nonzero(evcam_f == k)[0]
        thr, lev, _ = tune_rule([ev[i] for i in tr], c5ev[tr]); chosen_rules.append((thr / 256., lev)); t_rule[te] = rule_t([ev[i] for i in te], thr, lev)
    sp_, r5_, rC_ = regrets(ev, t_rule)
    print('TUNED SIMPLE RULE (t = level if d01 > thr else 0), 5-fold CV regret5 %.4f regretC %.4f meanS %.0f; per-fold (thr stops, level t): %s' % (r5_.mean(), rC_.mean(), sp_.mean(), [(round(a, 2), b) for a, b in chosen_rules]))
    thr_d, lev_d, _ = tune_rule(ev, c5ev); print('  tuned on all dev: thr %.2f stops, level t=%d (s=%d)' % (thr_d / 256., lev_d, lev_d // 2))
    # ---- holdout
    mh = fit(dev, c); evh = eval_rows(hold)
    if len(evh) == 0: print('no holdout rows'); return
    th = predict(mh, c, [r['F'] for r in evh])
    # dev-derived constants
    evd = eval_rows(dev); cc = sum(np.mean([cc_ for cc_ in r['costs'].values()], 0) for r in evd); const_s = SG[int(np.argmin(cc))]; mean_t = float(np.mean([2 * r['sM'] for r in evd]))
    base = {'model (dev fit)': th, 'zero (no correction)': np.zeros(len(evh)), 'placeholder (d01>4 stops -> Low)': np.array([512 if r['F'][NAMES.index('d01')] > 4 * 256 else 0 for r in evh], float),
            'tuned simple rule (dev-tuned: d01>%.2f stops -> t=%d)' % (thr_d / 256., lev_d): rule_t(evh, thr_d, lev_d), 'stock rule, G plane': np.array([min(r['stock_t'], 2048) for r in evh], float), 'constant, best dev cost (s=%d)' % const_s: np.full(len(evh), 2.0 * const_s), 'constant, dev mean t (%.0f)' % mean_t: np.full(len(evh), mean_t)}
    names = np.array([r['name'] for r in evh]); un = np.unique(names); rng = np.random.default_rng(0); ix = {u: np.nonzero(names == u)[0] for u in un}
    boots = [np.concatenate([ix[u] for u in rng.choice(un, len(un))]) for _ in range(500)]
    PR = {k: regrets(evh, v) for k, v in base.items()}; hold_tbl = {}
    print('\nHOLDOUT (%d five-expert images, %d rows, %d cameras), expert-C regret and 5-expert regret:' % (len(un), len(evh), len({r['cam'] for r in evh})))
    for k, v in base.items():
        sp, r5, rC = PR[k]; row = dict(regret5=float(r5.mean()), regretC=float(rC.mean()), mean_s=float(sp.mean()), spearman=float(spearmanr(v, [2 * r['sM'] for r in evh]).statistic) if v.std() > 0 else None)
        if k != 'model (dev fit)':
            d5 = [(PR['model (dev fit)'][1][b] - r5[b]).mean() for b in boots]; dC = [(PR['model (dev fit)'][2][b] - rC[b]).mean() for b in boots]
            row['model_minus_regret5'] = [float(np.mean(d5)), float(np.percentile(d5, 2.5)), float(np.percentile(d5, 97.5))]; row['model_minus_regretC'] = [float(np.mean(dC)), float(np.percentile(dC, 2.5)), float(np.percentile(dC, 97.5))]
        hold_tbl[k] = row
        ex = '  model-this: regret5 %+.4f [%+.4f,%+.4f]  regretC %+.4f [%+.4f,%+.4f]' % (*row['model_minus_regret5'], *row['model_minus_regretC']) if 'model_minus_regret5' in row else ''
        print('  %-34s regret5 %.4f regretC %.4f meanS %4.0f rho(t,M5 label) %5.2f%s' % (k, row['regret5'], row['regretC'], row['mean_s'], row['spearman'] or 0, ex))
    orc = float(np.mean([np.mean([cost_at(cc_, SG[int(np.argmin(sum(r['costs'].values())))]) for cc_ in r['costs'].values()]) - np.mean([cc_.min() for cc_ in r['costs'].values()]) for r in evh]))
    print('  per-image best-single-s oracle regret5 on holdout: %.4f' % orc)
    # ---- ship: refit on all
    mall = fit(rows, c); idxs = FULL if c['feat'] == 'full' else REL
    off, trees = to_trees(mall, idxs)
    blob = ref.build_blob(trees, mul=65536 // LSCALE, off=off, lo=0, hi=ref.T_MAX)
    open(sim.MODEL + '/model_final.bin', 'wb').write(blob)
    json.dump(dict(off=off, mul=65536 // LSCALE, lo=0, hi=ref.T_MAX, trees=trees, features=NAMES, used=[NAMES[i] for i in idxs], choice=c), open(sim.MODEL + '/model_final_trees.json', 'w'))
    Fall = [r['F'] for r in evh]; fl = predict(mall, c, Fall); it = np.array([ref.eval_model(blob, F) for F in Fall]); pm = ref.parse_blob(blob)
    print('\nSHIPPED model (chosen config, fit on all %d images): %d bytes, %d trees, %d nodes; float vs integer: max |diff| %.2f, mean %.3f (t units)' % (ni(rows), len(blob), pm[0], pm[1], np.abs(fl - it).max(), np.abs(fl - it).mean()))
    t_real = np.array([ref.eval_model(blob, real_feats(p)) for p in RP]); print('  35 DPReview t: min %d median %d max %d' % (t_real.min(), np.median(t_real), t_real.max()))
    json.dump(dict(simple_rule=dict(cv_regret5=float(r5_.mean()), thr_stops=thr_d / 256., level_t=lev_d, per_fold=chosen_rules), table=table, chosen=pick, holdout=hold_tbl, oracle_hold=orc, n_images=ni(rows), n_five=ne(rows), n_hold=len(un)), open(sim.MODEL + '/select_final.json', 'w'), indent=1, default=float)
if __name__ == '__main__': main()
