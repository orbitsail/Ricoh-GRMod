"""1. Domain shift: every feature, simulated FiveK planes (exposure offset 0, all variants) vs the 35 real DPReview planes."""
import sys, os
sys.dont_write_bytecode = True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common2 import *
from scipy.stats import ks_2samp
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
rows = [r for r in load_rows() if r['off'] == 0.0]
seen = set(); tr = []
for r in rows: tr.append(r['F'])            # one row per (image, variant): the training distribution
TR = np.array(tr, float); RP = real_planes(); RE = np.array([real_feats(p) for p in RP], float)
print('train rows %d (images %d), real %d' % (len(TR), len({r['name'] for r in rows}), len(RE)))
print('%-9s %9s %9s %9s | %9s %9s %9s | %5s %7s  %s' % ('feature', 'sim p5', 'sim p50', 'sim p95', 'real p5', 'real p50', 'real p95', 'KS', 'p', 'real outside sim [min,max] / [p1,p99]'))
out = []; flags = []
for i, n in enumerate(NAMES):
    if n in ('mode',): continue
    a, b = TR[:, i], RE[:, i]
    sc = 256.0 if n not in ('in1', 'in2', 'in3', 'in4', 'in5', 'nearclip', 'valid', 'idx', 'hl') else (4096.0 if n != 'idx' and n != 'hl' else 1.0)
    ks = ks_2samp(a, b); lo, hi = a.min(), a.max(); p1, p99 = np.percentile(a, [1, 99])
    o1 = int(((b < lo) | (b > hi)).sum()); o2 = int(((b < p1) | (b > p99)).sum())
    q = lambda v, p: np.percentile(v, p) / sc
    print('%-9s %9.2f %9.2f %9.2f | %9.2f %9.2f %9.2f | %5.2f %7.3f  %d / %d   %s' % (n, q(a, 5), q(a, 50), q(a, 95), q(b, 5), q(b, 50), q(b, 95), ks.statistic, ks.pvalue, o1, o2, '*USED*' if n not in EXCL else ''))
    out.append((n, ks.statistic, o1, o2))
print('\nunits: q*, meanlog, d*, u99, cvb, rg, bg in stops (Q8/256); in*, nearclip, valid in fraction (Q12/4096); idx, hl raw.')
used = [o for o in out if o[0] not in EXCL]
print('\nUSED features with KS >= 0.35 or real values outside the sim [p1,p99] for >= 5 of 35 images:')
for n, k, o1, o2 in used:
    if k >= 0.35 or o2 >= 5: print('  %-9s KS %.2f  outside-range %d  outside-p1..p99 %d' % (n, k, o1, o2))
# hl-matched comparison (real set is 80 % HC)
for hl in (0, 1):
    a = TR[TR[:, NAMES.index('hl')] == hl]; b = RE[RE[:, NAMES.index('hl')] == hl]
    ks = {NAMES[i]: ks_2samp(a[:, i], b[:, i]).statistic for i in FULL if NAMES[i] not in ('hl',)}
    top = sorted(ks.items(), key=lambda t: -t[1])[:6]; print('hl=%d: n_sim %d n_real %d  largest KS:' % (hl, len(a), len(b)), [(k, round(v, 2)) for k, v in top])
fig, axs = plt.subplots(3, 5, figsize=(20, 10))
for ax, n in zip(axs.ravel(), ['q01', 'q05', 'q25', 'q50', 'q75', 'q99', 'meanlog', 'd01', 'd05', 'd10', 'u99', 'in3', 'nearclip', 'cvb', 'idx']):
    i = NAMES.index(n); ax.hist(TR[:, i], bins=30, density=True, alpha=.55, label='sim FiveK'); ax.hist(RE[:, i], bins=15, density=True, alpha=.55, label='real DPReview'); ax.set_title(n)
axs[0, 0].legend(); plt.tight_layout(); plt.savefig('domain_shift.png', dpi=70)
