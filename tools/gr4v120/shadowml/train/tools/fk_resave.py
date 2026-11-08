"""Re-save 512-long-side npz files at 384 (no re-download). Atomic, idempotent. usage: python3 -I fk_resave.py"""
import os, sys, json, numpy as np, cv2
R = (__import__('os').environ.get('GRIV_WORK', '.') + '/shadowml')
sys.path.insert(0, R + '/tools'); import fk_common as C
cv2.setNumThreads(1); LONG = 384
d = R + '/fivek'; n = 0; before = after = 0
def shrink(code):
    y = C.dec_logy(code); h, w = y.shape
    s = LONG / max(h, w); nw, nh = (LONG, max(1, round(h * s))) if w >= h else (max(1, round(w * s)), LONG)
    return C.enc_logy(cv2.resize(y, (nw, nh), interpolation=cv2.INTER_AREA)), [nh, nw]
for f in sorted(os.listdir(d)):
    if not f.endswith('.npz') or f.startswith('.'): continue
    p = f'{d}/{f}'
    try:
        z = np.load(p, allow_pickle=False); m = json.loads(str(z['meta_json']))
        if max(m['raw_side']['shape_hw']) <= LONG: continue
        arrs = {k: z[k] for k in z.files}
        shp = None
        for k in list(arrs):
            if k == 'raw_y' or k.startswith('exp_') or k.startswith('rawcut_'):
                arrs[k], shp_k = shrink(arrs[k])
                if k == 'raw_y': m['raw_side']['shape_hw'] = shp_k
                if k.startswith('exp_'): m['experts'][k[4:]]['shape'] = shp_k
        m['raw_side']['resaved_from_long_side'] = 512
        arrs['meta_json'] = np.array(json.dumps(m))
        tmp = f'{d}/.{f[:-4]}.rs.npz'; np.savez_compressed(tmp, **arrs)
        before += os.path.getsize(p); after += os.path.getsize(tmp); os.replace(tmp, p); n += 1
    except Exception as e:
        print('ERR', f, repr(e))
print('resaved', n, 'before MB %.1f after MB %.1f' % (before / 1e6, after / 1e6))
