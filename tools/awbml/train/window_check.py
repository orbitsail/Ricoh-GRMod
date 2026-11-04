"""Where do illuminants live on the 64x64 chroma torus, and how much softmax mass falls outside a window?"""
import sys, json, glob, math
sys.path.insert(0, '.')
import numpy as np, jax, jax.numpy as jnp
import ffcc as M
D = '../cubepp_gr'
z = np.load('cube_eval_preds.npz'); gt = z['gt']; names = z['names']; tr = z['tr']
U = np.log(1 / gt[:, 0]); V = np.log(1 / gt[:, 2])
iu = (U - M.U0) / M.H - 0.5; iv = (V - M.V0) / M.H - 0.5
print('GT bins (all 2234): iu %.1f..%.1f  iv %.1f..%.1f' % (iu.min(), iu.max(), iv.min(), iv.max()))
# GR IV kelvin table points, stats space
sys.path.insert(0, '../grdng'); import scenes as SC
for T in (1800, 2000, 2500, 3000, 5000, 6500, 10000, 15000):
    rn, bn = SC.kelvin_neutral(T); u = math.log(1 / (rn * M.STAT_F[0])); v = math.log(1 / (bn * M.STAT_F[2]))
    print(f'  {T} K -> bin u {(u - M.U0) / M.H - 0.5:5.1f} v {(v - M.V0) / M.H - 0.5:5.1f}')
for nm, rg, bg in [('studio day', 0.3401, 0.6688), ('studio tungsten', 0.6647, 0.3217)]:
    u = math.log(1 / (rg * M.STAT_F[0])); v = math.log(1 / (bg * M.STAT_F[2]))
    print(f'  {nm} -> bin u {(u - M.U0) / M.H - 0.5:5.1f} v {(v - M.V0) / M.H - 0.5:5.1f}')
p = np.load('ffcc_cube_meta.npz'); P = dict(F=jnp.asarray(p['F']), B=jnp.asarray(p['B']))
print('F range', float(p['F'].min()), float(p['F'].max()), 'B range', float(p['B'].min()), float(p['B'].max()))
idx = json.load(open(f'{D}/index.json')); idx = idx if isinstance(idx, list) else list(idx.values())
te = np.where(~tr)[0]
Hs, Ms = [], []
for i in te:
    zz = np.load(f"{D}/{names[i]}.npz", allow_pickle=True)
    Hs.append(M.histograms(zz['s'].astype(np.int64)))
    Ms.append(float(zz['Av']) + float(zz['Tv']) - float(zz['Sv']))
Hs = jnp.asarray(np.stack(Hs)); F = M.meta_features(jnp.asarray(np.array(Ms)))
S = jax.vmap(lambda h, f: M.score_map(P, h, f))(Hs, F)
Pm = jax.nn.softmax(S.reshape(len(te), -1), -1).reshape(len(te), 64, 64)
Pm = np.asarray(Pm)
peak = np.array([np.unravel_index(np.argmax(x), x.shape) for x in Pm])
print('test peaks: iu %d..%d iv %d..%d' % (peak[:, 0].min(), peak[:, 0].max(), peak[:, 1].min(), peak[:, 1].max()))
for (u0, u1, v0, v1) in [(0, 63, 0, 63), (8, 47, 8, 47), (12, 43, 10, 41), (14, 41, 12, 39), (16, 39, 14, 37)]:
    out = 1 - Pm[:, u0:u1 + 1, v0:v1 + 1].sum((1, 2))
    print(f'window u {u0}-{u1} v {v0}-{v1} ({u1 - u0 + 1}x{v1 - v0 + 1}): mass outside max {out.max():.2e} mean {out.mean():.2e}')
np.save('test_P.npy', Pm)
