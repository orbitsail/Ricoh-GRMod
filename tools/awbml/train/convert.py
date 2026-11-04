import sys, os, json, csv, math, time
import numpy as np, cv2
from multiprocessing import Pool
RAW, OUT = sys.argv[1], sys.argv[2]
CMC = {'Canon EOS 550D': np.array([6941,-1164,-857,-3825,11597,2534,-416,1540,6039])/10000.,
       'Canon EOS 600D': np.array([6461,-907,-882,-4300,12184,2378,-819,1944,5931])/10000.}
CMG = np.array([0.64276123046875,-0.1484832763671875,-0.0814361572265625,-0.461395263671875,1.2727813720703125,0.20654296875,-0.066680908203125,0.1488800048828125,0.5924224853515625]).reshape(3,3)
WL = {'Canon EOS 550D': 15831, 'Canon EOS 600D': 13584}
MAT = {k: CMG @ np.linalg.inv(v.reshape(3,3)) for k, v in CMC.items()}
SC = np.array([0.920,1.0,0.974])

def load_csv(p):
    return {r['image']: r for r in csv.DictReader(open(p))}
def ffloat(x):
    try: return float(x)
    except: return float('nan')

def proc(a):
    iid, path, split, lab, gt, ex = a
    try:
        im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if im is None or im.ndim != 3 or im.dtype != np.uint16: return iid, 'bad image %s' % (None if im is None else (im.shape, im.dtype)), None
        rgb = im[:, :, ::-1].astype(np.float64)
        H, W, _ = rgb.shape
        model = ex.get('EXIF:Model')
        flag = ''
        if model not in MAT: model = 'Canon EOS 550D'; flag = 'unknown_camera_used_550D'
        m = rgb.max()
        masked = (rgb.max(2) == 0)
        valid = (~masked) & (rgb.max(2) < m - 50)
        bs = np.clip(rgb - 2048, 0, None)
        ye = np.round(np.linspace(0, H, 63)).astype(int); xe = np.round(np.linspace(0, W, 65)).astype(int)
        v = valid.astype(np.float64)
        def red(x):
            return np.add.reduceat(np.add.reduceat(x, ye[:-1], axis=0), xe[:-1], axis=1)
        cnt = red(v); npix = np.outer(np.diff(ye), np.diff(xe)).astype(np.float64)
        sums = np.stack([red(bs[:, :, c] * v) for c in range(3)], -1)
        ok = cnt > 0
        mean = np.where(ok[..., None], sums / np.maximum(cnt, 1)[..., None], 0)
        norm = mean / (WL[model] - 2048)
        g = norm @ MAT[model].T
        st = np.clip(np.round(g * 4063 * SC), 0, 4095)
        D = np.round(cnt / npix * 1584)
        st[~ok] = 0; D[~ok] = 0
        s = np.zeros((4, 64, 64), np.uint32)
        for c in range(3): s[c, 1:63, :] = st[:, :, c]
        s[3, 1:63, :] = D
        gtv = MAT[model] @ np.array(gt)
        gtgr = np.array([gtv[0]/gtv[1], gtv[2]/gtv[1]])
        N = ffloat(ex.get('EXIF:FNumber')); t = ffloat(ex.get('EXIF:ExposureTime')); iso = ffloat(ex.get('EXIF:ISO'))
        Av = 2*math.log2(N) if N > 0 else float('nan'); Tv = -math.log2(t) if t > 0 else float('nan'); Sv = math.log2(iso/3.125) if iso > 0 else float('nan')
        labs = {k: lab.get(k, '') for k in ['daytime','place','illumination','light_objects','shadows','is_sharp','richness','has_known_objects']}
        np.savez_compressed(os.path.join(OUT, iid + '.npz'), s=s, gt_gr=gtgr, Av=Av, Tv=Tv, Sv=Sv, camera=model, split=split, **labs)
        ent = dict(image=iid, split=split, camera=model, camera_flag=flag, gt_gr=gtgr.tolist(), gt_raw=list(gt), Av=Av, Tv=Tv, Sv=Sv,
                   N=N, t=t, iso=iso, max_val=float(m), valid_frac=float(v.mean()), size=[int(H), int(W)], **labs)
        return iid, None, ent
    except Exception as e:
        return iid, 'exception %r' % e, None

if __name__ == '__main__':
    t0 = time.time()
    ex_all = json.load(open(sys.argv[3]))
    items = []; skipped = []
    mk = load_csv(os.path.join(RAW, 'markup', 'Cube++', 'properties.csv'))
    for split in ['train', 'test']:
        d = os.path.join(RAW, 'SimpleCube++', split)
        gts = load_csv(os.path.join(d, 'gt.csv')); lab = load_csv(os.path.join(RAW, 'SimpleCube++', 'auxiliary', split + '_properties.csv'))
        pngs = sorted(f for f in os.listdir(os.path.join(d, 'PNG')) if f.endswith('.png'))
        for f in pngs:
            iid = f[:-4]
            if iid not in gts: skipped.append((iid, 'no gt')); continue
            g = gts[iid]
            items.append((iid, os.path.join(d, 'PNG', f), split, {**mk.get(iid, {}), **lab.get(iid, {})}, [float(g['mean_r']), float(g['mean_g']), float(g['mean_b'])], ex_all.get(iid, {})))
    print(len(items), 'images', flush=True)
    index = []
    with Pool(2) as p:
        for k, (iid, err, ent) in enumerate(p.imap_unordered(proc, items, chunksize=8)):
            if err: skipped.append((iid, err))
            else: index.append(ent)
            if k % 200 == 0: print(k, time.time() - t0, flush=True)
    index.sort(key=lambda e: e['image'])
    json.dump(index, open(os.path.join(OUT, 'index.json'), 'w'))
    json.dump([{'image': a, 'reason': b} for a, b in skipped], open(os.path.join(OUT, 'skipped.json'), 'w'), indent=1)
    print('done', len(index), len(skipped), time.time() - t0)
