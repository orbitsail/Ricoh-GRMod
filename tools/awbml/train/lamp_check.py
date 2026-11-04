"""Lamp in the frame: how far does it pull the white balance?  Ricoh (stock / v5 / v6 / White, exact simulator) vs the learned
model trained on converted SimpleCube++ (none of these scenes were in its training data).

Rooms: the DPReview GR IV daylight scenes and FiveK indoor scenes relit to 2700 K / 3000 K (the camera's own Kelvin table), dim
and normal room brightness.  Each room once without and three times with a lamp blob (2-12 % of the frame, light colour or a
warmer shade, sometimes a lit wall around it).  Reported: warmth left in a neutral after WB (log2 R/B; + = orange), the shift a
lamp causes, and the angular error to the room's light."""
import sys, glob, math, inspect, time
sys.path.insert(0, (__import__('os').environ.get('GRIV_WORK', '.') + '/learnawb'))
sys.path.insert(0, (__import__('os').environ.get('GRIV_WORK', '.') + '/grdng'))
import numpy as np, jax.numpy as jnp
import ffcc as M
import fitlib as FL, scenes as SC, fastawb as F, awb_ref as A

t0 = time.time()
rng = np.random.default_rng(7)
FIV = (__import__('os').environ.get('GRIV_WORK', '.') + '/fivek_gr')

V5 = FL.v5_tables(); ST = F.official_tables(0); WH = F.official_tables(2)
z6 = np.load((__import__('os').environ.get('GRIV_WORK', '.') + '/grdng/v6_tables.npz')); V6 = (z6['T2'], z6['T4'], z6['T5'])
orig = F._scalar_stage
s2 = inspect.getsource(F._scalar_stage).replace("        if special or pid != 15:\n            n20 = u16(n20 + w)", "        if True:\n            n20 = u16(n20 + w)")
assert s2 != inspect.getsource(F._scalar_stage)
ns = dict(F.__dict__); exec(s2.replace('def _scalar_stage', 'def _f1'), ns); F1 = ns['_f1']
RICOH = (('Ricoh stock Auto', ST, False), ('Ricoh v5 Auto', V5, False), ('Ricoh v6 Auto', V6, True), ('Ricoh White Priority', WH, False))

z = np.load('ffcc_cube_meta.npz'); P = dict(F=jnp.asarray(z['F']), B=jnp.asarray(z['B']))


def ricoh(sc, tabs, f1):
    a, m = F.accumulate(SC.settings(sc, A))
    F._scalar_stage = F1 if f1 else orig
    try:
        g = F.estimate(a, m, None, *tabs)
    finally:
        F._scalar_stage = orig
    gR, gB = g[0] / 8192 / FL.KR, g[3] / 8192 / FL.KB
    return np.array([M.STAT_F[0] / gR, 1.0, M.STAT_F[2] / gB])


def learned(sc):
    s = np.stack([sc['R'], sc['G'], sc['B'], sc['D']]).astype(np.int64)
    h = jnp.asarray(M.histograms(s))[None]
    f = M.meta_features(jnp.asarray([sc['e30'] / 256.0]))
    u, v = M.predict(P, h, f)
    return np.asarray(M.uv_to_rgb(u, v))[0]


def truth(sc):
    rn, bn = sc['light']
    return np.array([M.STAT_F[0] * rn, 1.0, M.STAT_F[2] * bn])


def warmth(est, tru):
    return math.log2((tru[0] / est[0]) / (tru[2] / est[2]))


def ang(a, b):
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
    return float(np.degrees(np.arccos(np.clip(a @ b, -1, 1))))


def lamp(sc):
    return SC.add_lamp(sc, rng=rng, frac=float(rng.choice([0.03, 0.06, 0.12])), dEV=float(rng.uniform(2.0, 4.0)),
                       tint=float(rng.choice([1.0, 1.1, 1.2])), wash=float(rng.choice([0.0, 0.0, 1.0, 2.0])))


rooms = []
for rid in SC.DAYLIT:
    for T in (2700, 3000):
        for ev in (4, 6, 8):
            rooms.append(SC.relit_scene(rid, T, ev))
paths = sorted(glob.glob(f'{FIV}/*.npz')); rng.shuffle(paths)
paths = [p for p in paths if (np.load(p)['s'][3][1:63] > 0).mean() >= 0.6][:120]
for p in paths:
    rooms.append(SC.fivek_relit(p, float(rng.choice([2700, 3000])), int(rng.choice([4, 6, 8]))))
print(f'{len(rooms)} rooms ({len(SC.DAYLIT)} GR IV scenes x 6, {len(paths)} FiveK)', flush=True)

names = [n for n, _, _ in RICOH] + ['learned + exposure']
res = {n: dict(w0=[], w1=[], d=[], e0=[], e1=[], src=[]) for n in names}
for sc in rooms:
    tru = truth(sc)
    lamps = [lamp(sc) for _ in range(3)]
    for n, tabs, f1 in RICOH + (('learned + exposure', None, None),):
        est0 = learned(sc) if tabs is None else ricoh(sc, tabs, f1)
        w0 = warmth(est0, tru); e0 = ang(est0, tru)
        for sl in lamps:
            est1 = learned(sl) if tabs is None else ricoh(sl, tabs, f1)
            w1 = warmth(est1, tru)
            r = res[n]
            r['w0'].append(w0); r['w1'].append(w1); r['d'].append(w1 - w0); r['e0'].append(e0); r['e1'].append(ang(est1, tru))
            r['src'].append(sc['src'])
print(f'done in {time.time() - t0:.0f}s\n', flush=True)

print('warmth = log2 R/B left in a neutral after WB (+ = orange; 0.1 is about 7 %); shift = with lamp minus without')
for subset in ('all', 'relit', 'fivek'):
    print(f'\n== {subset}')
    for n in names:
        r = {k: np.array(v) for k, v in res[n].items()}
        m = np.ones(len(r['d']), bool) if subset == 'all' else np.array([s.startswith(subset) for s in r['src']])
        d = r['d'][m]
        print(f'  {n:22s} warmth no lamp {np.median(r["w0"][m]):+.2f}  with lamp {np.median(r["w1"][m]):+.2f}  '
              f'shift median {np.median(d):+.3f}  mean |.| {np.abs(d).mean():.3f}  p90 |.| {np.percentile(np.abs(d), 90):.3f}  '
              f'>0.15 warmer {100 * (d > 0.15).mean():4.1f}%  |  error deg no lamp {np.median(r["e0"][m]):.2f} with {np.median(r["e1"][m]):.2f}')
np.savez('lamp_check.npz', **{n.replace(' ', '_') + '_' + k: np.array(v) for n in names for k, v in res[n].items() if k != 'src'},
         src=np.array(res[names[0]]['src']))
