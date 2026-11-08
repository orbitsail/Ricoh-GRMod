"""Learned model (trained on converted SimpleCube++) on the 35 real GR IV scenes: does it agree with the camera on daylight?"""
import sys, json, math
sys.path.insert(0, (__import__('os').environ.get('GRIV_WORK', '.') + '/learnawb'))
import numpy as np, jax.numpy as jnp
import ffcc as M
EXT = (__import__('os').environ.get('GRIV_WORK', '.') + '/grdng/ext')
rows = json.load(open(f'{EXT}/summary.json'))
for tag in ('nometa', 'meta'):
    z = np.load(f'ffcc_cube_{tag}.npz'); p = dict(F=jnp.asarray(z['F']), B=jnp.asarray(z['B']))
    errs = []; lines = []
    for r in rows:
        s = np.load(f"{EXT}/{r['id']}.npz")['s'].astype(np.int64)
        s[(s > 0xFFFF)] = 0
        h = jnp.asarray(M.histograms(s))[None]
        ev = 2 * math.log2(r['N']) - math.log2(r['t']) - math.log2(r['iso'] / 3.125)          # Av + Tv - Sv, as in training
        f = M.meta_features(jnp.asarray([ev]))
        if tag == 'nometa': f = f.at[:, 1:].set(0.0)
        u, v = M.predict(p, h, f)
        est = np.asarray(M.uv_to_rgb(u, v))[0]
        cam = np.array([M.STAT_F[0] * 8192 / r['wp'][0], 1.0, M.STAT_F[2] * 8192 / r['wp'][3]])
        e = float(np.degrees(np.arccos(np.clip(np.dot(est / np.linalg.norm(est), cam / np.linalg.norm(cam)), -1, 1))))
        errs.append(e); lines.append((r['id'], e, r['wp'][0], r['wp'][3]))
    errs = np.array(errs)
    print(f'{tag}: learned vs the camera\'s own white balance on 35 GR IV scenes: mean {errs.mean():.2f} deg, median {np.median(errs):.2f}, max {errs.max():.2f}')
    for nm, e, wr, wb in sorted(lines, key=lambda x: -x[1])[:5]:
        print(f'   {nm} {e:5.2f} deg  (camera WP R {wr} B {wb})')
