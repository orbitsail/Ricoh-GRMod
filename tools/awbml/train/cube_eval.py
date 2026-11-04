"""SimpleCube++ (converted to GR IV AWB stats): Ricoh's AWB (stock / v5 / v6 / White, exact simulator) vs simple baselines
vs an FFCC-style learned model, angular error to the measured illuminant (GR IV stats space)."""
import sys, json, glob, math, time, inspect
sys.path.insert(0, (__import__('os').environ.get('GRIV_WORK', '.') + '/learnawb'))
sys.path.insert(0, (__import__('os').environ.get('GRIV_WORK', '.') + '/grdng'))
import numpy as np, jax.numpy as jnp
import ffcc as M
import fitlib as FL, scenes as SC, fastawb as F, awb_ref as A
D = (__import__('os').environ.get('GRIV_WORK', '.') + '/cubepp_gr')
idx = json.load(open(f'{D}/index.json'))
idx = idx if isinstance(idx, list) else list(idx.values())
t0 = time.time()
recs = []
for r in idx:
    nm = r.get('id') or r.get('image') or r.get('name')
    z = np.load(f'{D}/{nm}.npz', allow_pickle=True)
    s = z['s'].astype(np.int64)
    rn, bn = (float(x) for x in z['gt_gr'])
    ev = float(z['Av']) + float(z['Tv']) - float(z['Sv'])
    lab = {k: str(z[k]) for k in ('daytime', 'place', 'illumination', 'light_objects') if k in z.files}
    recs.append(dict(name=nm, s=s, rn=rn, bn=bn, ev=ev, Av=float(z['Av']), Sv=float(z['Sv']), split=str(z['split']), **lab))
print('loaded', len(recs), round(time.time() - t0, 1), 's', flush=True)
gt = np.array([[M.STAT_F[0] * r['rn'], 1.0, M.STAT_F[2] * r['bn']] for r in recs])

def ang(est, ref):
    a = est / np.linalg.norm(est, axis=1, keepdims=True); b = ref / np.linalg.norm(ref, axis=1, keepdims=True)
    return np.degrees(np.arccos(np.clip((a * b).sum(1), -1, 1)))

# ---------------- baselines on the blocks
def baselines(s):
    rgb, w = M.block_arrays(s)
    m = w > 0
    c = rgb[m]; ww = w[m][:, None]
    gw = (c * ww).sum(0)
    wp = np.percentile(c, 99, axis=0)
    sog = ((c ** 4 * ww).sum(0)) ** 0.25
    return gw, wp, sog
B = np.array([baselines(r['s']) for r in recs])          # (n, 3 methods, 3)

# ---------------- Ricoh variants (exact simulator)
V5 = FL.v5_tables(); ST = F.official_tables(0); WH = F.official_tables(2)
z6 = np.load((__import__('os').environ.get('GRIV_WORK', '.') + '/grdng/v6_tables.npz')); V6 = (z6['T2'], z6['T4'], z6['T5'])
orig = F._scalar_stage
s2 = inspect.getsource(F._scalar_stage).replace("        if special or pid != 15:\n            n20 = u16(n20 + w)", "        if True:\n            n20 = u16(n20 + w)")
ns = dict(F.__dict__); exec(s2.replace('def _scalar_stage', 'def _f1'), ns); F1 = ns['_f1']
def ricoh_illum(r, tabs, f1=False):
    sc = dict(R=r['s'][0], G=r['s'][1], B=r['s'][2], D=r['s'][3], e30=round(r['ev'] * 256), Av=r['Av'], Sv=r['Sv'])
    a, m = F.accumulate(SC.settings(sc, A))
    F._scalar_stage = F1 if f1 else orig
    g = F.estimate(a, m, None, *tabs); F._scalar_stage = orig
    gR, gB = g[0] / 8192 / FL.KR, g[3] / 8192 / FL.KB          # camera-equivalent raw gains
    return np.array([M.STAT_F[0] / gR, 1.0, M.STAT_F[2] / gB])  # what it corrects to, stats space
R_ = {}
for name, tabs, f1 in (('Ricoh stock Auto', ST, False), ('Ricoh v5 Auto', V5, False), ('Ricoh v6 Auto', V6, True), ('Ricoh White Priority', WH, False)):
    R_[name] = np.array([ricoh_illum(r, tabs, f1) for r in recs])
print('ricoh done', round(time.time() - t0, 1), 's', flush=True)

# ---------------- learned (FFCC-style), the dataset's own train/test split
Hs = jnp.asarray(np.stack([M.histograms(r['s']) for r in recs]))
E = jnp.asarray(np.array([r['ev'] for r in recs])); Mf = M.meta_features(E)
U = jnp.asarray(np.log(1 / gt[:, 0])); V = jnp.asarray(np.log(1 / gt[:, 2]))
tr = np.array([r['split'] == 'train' for r in recs]); te = ~tr
L_ = {}
for use_meta in (False, True):
    p, _ = M.train2(Hs[tr], Mf[tr], U[tr], V[tr], use_meta=use_meta, log=lambda s: print(s, flush=True))
    Mte = Mf if use_meta else Mf.at[:, 1:].set(0.0)
    u, v = M.predict(p, Hs, Mte)
    L_['learned' + (' + exposure' if use_meta else '')] = np.asarray(M.uv_to_rgb(u, v))
    np.savez(f'ffcc_cube_{"meta" if use_meta else "nometa"}.npz', F=np.asarray(p['F']), B=np.asarray(p['B']))
print('learned done', round(time.time() - t0, 1), 's', flush=True)

def stats(e):
    e = np.sort(e); n = len(e)
    q1, q2, q3 = np.percentile(e, [25, 50, 75])
    return f'mean {e.mean():5.2f}  median {q2:5.2f}  trimean {(q1 + 2 * q2 + q3) / 4:5.2f}  best25% {e[:max(1, n // 4)].mean():5.2f}  worst25% {e[-max(1, n // 4):].mean():5.2f}'
groups = {'all test': te,
          'test, natural light': te & np.array([r.get('illumination') == 'natural' for r in recs]),
          'test, artificial/mixed': te & np.array([r.get('illumination') in ('artificial', 'mixed') for r in recs]),
          'test, indoor': te & np.array([r.get('place') == 'indoor' for r in recs]),
          'ALL artificial/mixed (incl. train; Ricoh & baselines only)': np.array([r.get('illumination') in ('artificial', 'mixed') for r in recs]),
          'ALL with a lamp in frame (Ricoh & baselines only)': np.array(['lamp' in str(r.get('light_objects')) for r in recs])}
methods = {'gray world': B[:, 0], 'white patch (99%)': B[:, 1], 'shades of gray p4': B[:, 2], **R_, **L_}
out = {}
for gname, gm in groups.items():
    print(f'\n== {gname}: n = {int(gm.sum())}')
    for mname, est in methods.items():
        if mname.startswith('learned') and gname.startswith('ALL'):
            continue
        e = ang(est[gm], gt[gm]); out[(gname, mname)] = e
        print(f'  {mname:24s} {stats(e)}')
np.savez('cube_eval_preds.npz', gt=gt, names=np.array([r['name'] for r in recs]), tr=tr, **{k.replace(' ', '_').replace('/', '_'): v for k, v in methods.items()})
