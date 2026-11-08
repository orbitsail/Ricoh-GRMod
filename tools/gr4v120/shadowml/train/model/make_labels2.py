"""B (v2). Labels with exposure augmentation.  Per scene: exposure offsets OFFS (stops around the simulated AE) x (iso, hl) variants x all available experts.
Shared renders per (variant, offset), pixels subsampled 2x2 (labels agree with the full-pixel v1 labels, see check_v1.py). Re-runnable: per-image cache, only new/changed npz are processed.
usage: python3 -B make_labels2.py [--force]"""
import sys, os, json, glob, hashlib, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import sim
from multiprocessing import Pool
SGRID = np.arange(0, 1025, 16)
OFFS = [-0.5, -0.25, 0.0, 0.25, 0.5]
P = dict(xfloor=12.0, xclip=3900.0, cap=0.8, efloor=2.0 ** -12)
CACHE = sim.MODEL + '/cache2'; os.makedirs(CACHE, exist_ok=True)
PH = hashlib.md5((json.dumps(P, sort_keys=True) + str(OFFS) + open(sim.MODEL + '/sim.py').read() + open(__file__).read()).encode()).hexdigest()[:8]
def best(cost): return int(SGRID[int(np.argmin(cost))])

def do_image(path):
    d = sim.fk_load.load(path); m = d['meta']
    kst, ev = sim.scene_info(d)
    out = dict(name=m['name'], camera=(m.get('make', '') + ' ' + (m.get('model') or m.get('unique_camera_model') or '')).strip(), iso_shot=m.get('iso'),
               kst=float(kst), ev_scene=float(ev), cats=m.get('categories'), variants=[])
    # pixel sets per expert (subsampled 2x2); the raw side is shared unless an expert is a 'crop'
    ex = {}
    for l, e in d['experts'].items():
        flag = e.get('align_flag')
        if flag not in ('ok', 'orient_fixed'): continue      # 'poor' and 'crop' experts are excluded
        Y = e['raw_y'] if flag == 'crop' and 'raw_y' in e else d['raw_y']
        if Y.shape != e['y'].shape: continue
        ex[l] = (Y[::2, ::2].astype(np.float64), e['y'][::2, ::2].astype(np.float64), flag)
    # all non-crop experts share the same Y: group them so renders are shared
    groups = {}
    for l, (Y, E, flag) in ex.items(): groups.setdefault((flag == 'crop', l if flag == 'crop' else ''), []).append(l)
    for iso, hl in sim.variants(ev):
        for off in OFFS:
            F = sim.feats(d, kst + off, hl, iso)
            if F is None: continue
            (R_, G_, B_, C_), _ = sim.planes(d, kst + off, hl)
            s_stock, _, info = sim.SR.strength(G_, 0, hl, sim.iso_index(iso)); stock_t = int(info.get('r3', 0))
            var = dict(off=off, iso=iso, hl=hl, F=F, stock_t=stock_t, labels={})
            for gk, ls in groups.items():
                Y = ex[ls[0]][0]
                xd = 4095.0 * Y * 2 ** (kst + off) / 2 ** hl
                v = (xd >= P['xfloor']) & (xd <= P['xclip'])
                for l in ls: v &= ex[l][1] > P['efloor']
                if v.sum() < 500: continue
                x = xd[v]; dark = x <= np.median(x)
                eds = {}
                for l in ls:
                    e = np.log(ex[l][1][v]); e -= np.median(e); eds[l] = e[dark]
                costs = {l: np.empty(len(SGRID)) for l in ls}
                for i, s in enumerate(SGRID):
                    gr = np.log(np.maximum(sim.render(x, int(s), hl), 1e-9)); gr -= np.median(gr); gd = gr[dark]
                    for l in ls:
                        dd = eds[l] - gd; costs[l][i] = np.minimum(dd * dd, P['cap'] ** 2).mean()
                for l in ls:
                    c = costs[l]; var['labels'][l] = dict(s=best(c), cost=[round(float(a), 5) for a in c], n=int(dark.sum()))
            out_v = var; out['variants'].append(out_v)
    return out

def work(f):
    st = os.stat(f); key = f'{os.path.basename(f)[:-4]}.{st.st_size}.{int(st.st_mtime)}.{PH}.json'; cf = CACHE + '/' + key
    if os.path.exists(cf): return json.load(open(cf)), False
    try: r = do_image(f)
    except Exception as ex_:
        return dict(name=os.path.basename(f)[:-4], error=repr(ex_)), False
    for old in glob.glob(CACHE + '/' + os.path.basename(f)[:-4] + '.*.json'): os.remove(old)
    json.dump(r, open(cf, 'w')); return r, True
if __name__ == '__main__':
    if '--force' in sys.argv:
        for f in glob.glob(CACHE + '/*.json'): os.remove(f)
    files = sorted(glob.glob(sim.SP + '/shadowml/fivek/*.npz')); t0 = time.time(); res = []; new = 0; bad = []
    with Pool(2) as pool:
        for i, (r, isnew) in enumerate(pool.imap(work, files, chunksize=2)):
            if 'error' in r: bad.append(r)
            else: res.append(r)
            new += isnew
            if isnew and new % 25 == 0: print(new, 'new', round(time.time() - t0), 's', flush=True)
    json.dump(res, open(sim.MODEL + '/labels2.json', 'w')); json.dump(bad, open(sim.MODEL + '/labels2_failed.json', 'w'))
    print('images', len(res), 'failed', len(bad), 'new', new, 'files', len(files), 'time', round(time.time() - t0))
