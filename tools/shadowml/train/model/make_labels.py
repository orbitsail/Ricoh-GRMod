"""B. Labels.  Re-runnable: per-image results are cached in cache/*.json (keyed on npz size+mtime and the label parameters); only new files are processed.
usage: python3 -B make_labels.py [--force]"""
import sys, os, json, glob, hashlib, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import sim
SGRID = np.arange(0, 1025, 16)
P = dict(xfloor=12.0, xclip=3900.0, cap=0.8, efloor=2.0 ** -12)          # noisiest-black cut (12-bit x), clip cut, residual cap (ln units), expert floor
ALTS = {'cap0.5': dict(cap=0.5), 'cap1.2': dict(cap=1.2), 'floor30': dict(xfloor=30.0), 'floor6': dict(xfloor=6.0)}
CACHE = sim.MODEL + '/cache'; os.makedirs(CACHE, exist_ok=True)
PH = hashlib.md5((json.dumps(P, sort_keys=True) + json.dumps(ALTS, sort_keys=True) + open(sim.MODEL + '/sim.py').read() + open(__file__).read()).encode()).hexdigest()[:8]

def prep(Y, kst, hl, p):
    xd = 4095.0 * Y.astype(np.float64) * 2 ** kst / 2 ** hl
    valid = (xd >= p['xfloor']) & (xd <= p['xclip'])
    return xd, valid
def label_costs(xd, valid, E, hl, p):
    """cost[s] for every s in SGRID.  E and x on the same pixels."""
    v = valid & (E > p['efloor'])
    x = xd[v]; e = np.log(E[v].astype(np.float64)); e -= np.median(e)
    dark = x <= np.median(x)
    ed = e[dark]
    cost = np.empty(len(SGRID))
    for i, s in enumerate(SGRID):
        gr = np.log(np.maximum(sim.render(x, int(s), hl), 1e-9)); gr -= np.median(gr)
        d = ed - gr[dark]
        cost[i] = np.minimum(d * d, p['cap'] ** 2).mean()
    return cost, int(dark.sum())
def best(cost):
    # tie -> smallest s; parabola refinement not used (grid step 16 per spec)
    return int(SGRID[int(np.argmin(cost))])

def do_image(path):
    d = sim.fk_load.load(path); m = d['meta']
    kst, ev = sim.scene_info(d)
    out = dict(name=m['name'], camera=(m.get('make', '') + ' ' + (m.get('model') or m.get('unique_camera_model') or '')).strip(), iso_shot=m.get('iso'),
               kst=float(kst), ev_scene=float(ev), cats=m.get('categories'), variants=[])
    for iso, hl in sim.variants(ev):
        F = sim.feats(d, kst, hl, iso)
        if F is None: continue
        var = dict(iso=iso, hl=hl, F=F, labels={})
        for l, e in d['experts'].items():
            flag = e.get('align_flag')
            if flag not in ('ok', 'orient_fixed', 'crop'): continue
            Y = e['raw_y'] if flag == 'crop' and 'raw_y' in e else d['raw_y']
            if Y.shape != e['y'].shape: continue
            xd, valid = prep(Y, kst, hl, P)
            if valid.sum() < 2000: continue
            cost, nd = label_costs(xd, valid, e['y'], hl, P)
            L = dict(s=best(cost), c0=float(cost[0]), cmin=float(cost.min()), c1024=float(cost[-1]), n=nd, flag=flag, cost=[round(float(c), 5) for c in cost])
            if l == 'c':
                L['alt'] = {}
                for an, ov in ALTS.items():
                    p2 = dict(P, **ov); xd2, v2 = prep(Y, kst, hl, p2); c2, _ = label_costs(xd2, v2, e['y'], hl, p2); L['alt'][an] = best(c2)
            var['labels'][l] = L
        out['variants'].append(var)
    return out

if __name__ == '__main__':
    force = '--force' in sys.argv
    files = sorted(glob.glob(sim.SP + '/shadowml/fivek/*.npz')); t0 = time.time(); new = 0; res = []
    for f in files:
        st = os.stat(f); key = f'{os.path.basename(f)[:-4]}.{st.st_size}.{int(st.st_mtime)}.{PH}.json'
        cf = CACHE + '/' + key
        if os.path.exists(cf) and not force: res.append(json.load(open(cf))); continue
        try: r = do_image(f)
        except Exception as ex:
            print('FAIL', f, repr(ex)); continue
        for old in glob.glob(CACHE + '/' + os.path.basename(f)[:-4] + '.*.json'): os.remove(old)
        json.dump(r, open(cf, 'w')); res.append(r); new += 1
        if new % 20 == 0: print(new, 'done', round(time.time() - t0), 's', flush=True)
    json.dump(res, open(sim.MODEL + '/labels.json', 'w'))
    print('images', len(res), 'new', new, 'files', len(files), 'time', round(time.time() - t0))
