"""Pipeline self-test on synthetic scenes with known lights (relit GR IV + FiveK scenes)."""
import sys, glob, math, time
sys.path.insert(0, (__import__('os').environ.get('GRIV_WORK', '.') + '/learnawb'))
sys.path.insert(0, (__import__('os').environ.get('GRIV_WORK', '.') + '/grdng'))
import numpy as np, jax.numpy as jnp
import ffcc as M
import scenes as SC
rng = np.random.default_rng(0)
paths = sorted(glob.glob((__import__('os').environ.get('GRIV_WORK', '.') + '/fivek_gr/*.npz')))
items = []
t0 = time.time()
for i, p in enumerate(paths):
    T = float(np.exp(rng.uniform(np.log(2300), np.log(7500)))); ev = float(rng.uniform(1, 13))
    sc = SC.fivek_relit(p, T, ev)
    s = np.stack([sc['R'], sc['G'], sc['B'], sc['D']]).astype(np.int64)
    rn, bn = sc['light']
    u, v = M.chroma_to_uv(M.STAT_F[0] * rn, M.STAT_F[2] * bn)
    items.append((M.histograms(s), (sc['e30'] / 256 + 1.0), u, v, i % 5 == 0))
print('built', len(items), 'in', round(time.time() - t0, 1), 's')
H_ = jnp.asarray(np.stack([x[0] for x in items])); E = np.array([x[1] for x in items])
U_ = jnp.asarray(np.array([x[2] for x in items])); V_ = jnp.asarray(np.array([x[3] for x in items]))
te = np.array([x[4] for x in items]); tr = ~te
M_ = M.meta_features(jnp.asarray(E))
for use_meta in (False, True):
    p, Mtr = M.train2(H_[tr], M_[tr], U_[tr], V_[tr], use_meta=use_meta, log=print)
    Mte = M_[te] if use_meta else M_[te].at[:, 1:].set(0.0)
    u, v = M.predict(p, H_[te], Mte)
    err = np.asarray(M.angular_error_deg(M.uv_to_rgb(u, v), M.uv_to_rgb(U_[te], V_[te])))
    print(f'meta={use_meta}: test angular error mean {err.mean():.2f} median {np.median(err):.2f} worst25% {np.mean(np.sort(err)[-len(err)//4:]):.2f}')
gw = []
for h, e, u0, v0, t in items:
    pass
