"""2. Sensitivity of the shipped model (model_final.bin): AE uncertainty (planes scaled by +-1/3, +-2/3 stop) and clip assumption (real planes capped at 4095 / 7683 / 8100; FiveK sim rebuilt with those caps)."""
import sys, os, glob
from scipy.stats import spearmanr
sys.dont_write_bytecode = True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common2 import *
blob = open(sim.MODEL + '/model_final.bin', 'rb').read(); RP = real_planes()
ev = lambda F: ref.eval_model(blob, F)
t0 = np.array([ev(real_feats(p)) for p in RP], float)
print('35 DPReview, shipped model: t0 min %d median %d max %d sd %.0f' % (t0.min(), np.median(t0), t0.max(), t0.std()))
print('AE uncertainty (all planes x 2^delta):')
for dl in (-2 / 3, -1 / 3, 1 / 3, 2 / 3):
    t = np.array([ev(real_feats(p, scale_stops=dl)) for p in RP], float); d = t - t0
    print('  %+.2f stop: mean dt %+6.1f  mean|dt| %5.1f  p90|dt| %5.1f  max|dt| %4.0f (image %s)  rank corr with t0 %.2f' % (dl, d.mean(), np.abs(d).mean(), np.percentile(np.abs(d), 90), np.abs(d).max(), RP[int(np.argmax(np.abs(d)))]['id'], float(spearmanr(t, t0).statistic)))
print('clip cap on the real planes (pre-HC plane values capped):')
for cap in (4095, 7683, 8100):
    t = np.array([ev(real_feats(p, cap=cap)) for p in RP], float); d = t - t0
    print('  cap %5d: mean|dt| %.1f  max|dt| %.0f  images changed %d' % (cap, np.abs(d).mean(), np.abs(d).max(), int((d != 0).sum())))
print('clip assumption inside the FiveK simulation (features recomputed at offset 0, cap 4095 / 7683 vs the 8100 used in training):')
fs = sorted(glob.glob(sim.SP + '/shadowml/fivek/*.npz'))[::4][:150]; base = {}; res = {c: [] for c in (4095, 7683)}
for f in fs:
    try:
        d = sim.fk_load.load(f); kst, evs = sim.scene_info(d); iso, hl = sim.variants(evs)[-1]
    except Exception: continue
    for cap in (8100, 4095, 7683):
        sim.PLANE_CAP = cap; F = sim.feats(d, kst, hl, iso)
        if F is None: break
        if cap == 8100: b = ev(F)
        else: res[cap].append(ev(F) - b)
for cap, v in res.items():
    v = np.abs(np.array(v)); print('  cap %d: %d scenes, mean|dt| %.1f  p95 %.0f  max %.0f  scenes with |dt|>50: %d' % (cap, len(v), v.mean(), np.percentile(v, 95), v.max(), int((v > 50).sum())))
