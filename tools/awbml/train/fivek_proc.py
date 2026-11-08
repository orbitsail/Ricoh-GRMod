"""Process one FiveK DNG -> GR IV AWB block stats. usage: proc.py <dng> <name> <meta_json_str> <outdir>
Prints a single JSON line: {"ok":true,"rec":{...}} or {"ok":false,"reason":...}"""
import sys, json, math
import numpy as np
sys.path.insert(0, (__import__('os').environ.get('GRIV_WORK', '.') + '/grdng'))
import tiff
import rawpy
from PIL import Image

GR_CM1 = np.array([0.699066162109375, -0.2872467041015625, -0.031890869140625, -0.3809967041015625, 0.997039794921875, 0.44677734375, -0.01129150390625, 0.035491943359375, 0.7245635986328125]).reshape(3, 3)
GR_CM2 = np.array([0.64276123046875, -0.1484832763671875, -0.0814361572265625, -0.461395263671875, 1.2727813720703125, 0.20654296875, -0.066680908203125, 0.1488800048828125, 0.5924224853515625]).reshape(3, 3)
GR_T1, GR_T2 = 2856.0, 6504.0
ILL = {1: 5500, 2: 4200, 3: 2850, 4: 5500, 9: 5500, 10: 6500, 11: 7500, 12: 6430, 13: 5000, 14: 4200, 15: 3450,
       17: 2856, 18: 4874, 19: 6774, 20: 5503, 21: 6504, 22: 7504, 23: 5003, 24: 3200, 16: 2856}
D50xy = (0.3457, 0.3585)


def planck_uv(T):
    u = (0.860117757 + 1.54118254e-4 * T + 1.28641212e-7 * T * T) / (1 + 8.42420235e-4 * T + 7.08145163e-7 * T * T)
    v = (0.317398726 + 4.22806245e-5 * T + 4.20481691e-8 * T * T) / (1 - 2.89741816e-5 * T + 1.61456053e-7 * T * T)
    return u, v

_Tg = np.concatenate([np.linspace(1500, 3000, 301), np.linspace(3000, 15000, 2401)[1:]])
_uvg = np.array([planck_uv(t) for t in _Tg])

def xy_to_cct(x, y):
    d = 12 * 0 + (-2 * x + 12 * y + 3)
    u, v = 4 * x / d, 6 * y / d
    i = int(np.argmin((_uvg[:, 0] - u) ** 2 + (_uvg[:, 1] - v) ** 2))
    return float(_Tg[i])


def interp_cm(T, cm1, cm2, t1, t2):
    if cm2 is None:
        return cm1
    if t1 > t2:
        cm1, cm2, t1, t2 = cm2, cm1, t2, t1
    if T <= t1:
        return cm1
    if T >= t2:
        return cm2
    w = (1 / T - 1 / t2) / (1 / t1 - 1 / t2)
    return w * cm1 + (1 - w) * cm2


def xyz_xy(X):
    s = X.sum()
    return X[0] / s, X[1] / s


def xy_to_xyz(x, y):
    return np.array([x / y, 1.0, (1 - x - y) / y])


def main():
    path, name, meta, outdir = sys.argv[1:5]
    meta = json.loads(meta)
    data, t, out = tiff.read_all(path)
    ifds = {n: r for n, o, r in out['_ifds']}
    ifd0 = ifds['ifd0']
    exif = ifds.get('ifd0.exif', {})
    cm1 = ifd0.get('ColorMatrix1'); cm2 = ifd0.get('ColorMatrix2')
    if cm1 is None:
        return dict(ok=False, reason='no ColorMatrix1')
    cm1 = np.array(cm1, float).reshape(3, 3)
    cm2 = np.array(cm2, float).reshape(3, 3) if cm2 is not None else None
    ci1 = ifd0.get('CalibrationIlluminant1'); ci2 = ifd0.get('CalibrationIlluminant2')
    t1 = float(ILL.get(ci1, 2856)); t2 = float(ILL.get(ci2, 6504)) if cm2 is not None else t1
    neutral = ifd0.get('AsShotNeutral')
    if neutral is None:
        wxy = ifd0.get('AsShotWhiteXY')
        if wxy is None:
            return dict(ok=False, reason='no AsShotNeutral/AsShotWhiteXY')
        neutral = None
    ET = exif.get('ExposureTime'); FN = exif.get('FNumber')
    ISO = exif.get('ISO')
    if isinstance(ISO, list):
        ISO = ISO[0]
    if not ET or not FN or not ISO:
        return dict(ok=False, reason=f'missing exif exposure (t={ET}, N={FN}, ISO={ISO})')
    orient = ifd0.get('Orientation', 1)

    try:
        raw = rawpy.imread(path)
    except Exception as e:
        return dict(ok=False, reason=f'rawpy open failed: {e}')
    with raw:
        if raw.raw_type != rawpy.RawType.Flat:
            return dict(ok=False, reason=f'raw_type {raw.raw_type}')
        pat = np.array(raw.raw_pattern)
        if pat.shape != (2, 2):
            return dict(ok=False, reason=f'CFA pattern shape {pat.shape}')
        desc = raw.color_desc.decode()
        if raw.num_colors != 3 or sorted(desc[:3]) != ['B', 'G', 'R']:
            return dict(ok=False, reason=f'not 3-colour RGB CFA ({desc}, n={raw.num_colors})')
        img = raw.raw_image_visible.astype(np.float32)
        cols = np.array(raw.raw_colors_visible)
        white = float(raw.white_level)
        bl = np.array(raw.black_level_per_channel, float)
        H, W = img.shape
        H2, W2 = H // 2, W // 2
        img = img[:H2 * 2, :W2 * 2]; cols = cols[:H2 * 2, :W2 * 2]
        # per-pixel black subtraction by raw colour index
        blk = bl[cols]
        sat = img >= 0.98 * white
        val = np.clip(img - blk, 0, None) / (white - blk)
        # quad channel assignment
        cc = cols[:2, :2]
        letter = lambda c: desc[c]
        planes = {'R': [], 'G': [], 'B': []}
        for dy in range(2):
            for dx in range(2):
                planes[letter(cc[dy, dx])].append((dy, dx))
        if not (len(planes['R']) == 1 and len(planes['B']) == 1 and len(planes['G']) == 2):
            return dict(ok=False, reason='unexpected CFA layout')
        def q(a, pos):
            dy, dx = pos
            return a[dy::2, dx::2]
        R = q(val, planes['R'][0]); B = q(val, planes['B'][0])
        G = 0.5 * (q(val, planes['G'][0]) + q(val, planes['G'][1]))
        ok = ~(q(sat, (0, 0)) | q(sat, (0, 1)) | q(sat, (1, 0)) | q(sat, (1, 1)))
        # preview (as-shot WB, half size)
        try:
            rgb8 = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
        except Exception:
            rgb8 = None

    transposed = False
    if H2 > W2:
        R, G, B, ok = R.T, G.T, B.T, ok.T
        transposed = True
    h, w = ok.shape  # long side = w
    ye = np.linspace(0, h, 63).round().astype(int)
    xe = np.linspace(0, w, 65).round().astype(int)

    def bsum(a):
        a = np.add.reduceat(a, xe[:-1], axis=1)
        return np.add.reduceat(a, ye[:-1], axis=0)
    okf = ok.astype(np.float64)
    n_valid = bsum(okf)
    n_all = np.outer(np.diff(ye), np.diff(xe)).astype(np.float64)
    with np.errstate(invalid='ignore', divide='ignore'):
        mr = bsum(R * okf) / n_valid; mg = bsum(G * okf) / n_valid; mb = bsum(B * okf) / n_valid
    empty = n_valid == 0
    rgb_src = np.stack([mr, mg, mb], -1)
    rgb_src[empty] = 0

    # CCT from AsShotNeutral
    def cm_src(T):
        return interp_cm(T, cm1, cm2, t1, t2)
    if neutral is not None:
        n = np.array(neutral, float)
        T = 5000.0
        for _ in range(50):
            XYZ = np.linalg.solve(cm_src(T), n)
            xy = xyz_xy(XYZ)
            Tn = xy_to_cct(*xy)
            if abs(Tn - T) < 1:
                T = Tn
                break
            T = Tn
        Tn = T
        cct = Tn
    else:
        xy = tuple(wxy)
        cct = xy_to_cct(*xy)
        n = cm_src(cct) @ xy_to_xyz(*xy)
        n = n / n.max()
        n = 1.0 / (1.0 / n) if False else n
    Msrc = cm_src(cct)
    Mgr = interp_cm(cct, GR_CM1, GR_CM2, GR_T1, GR_T2)
    conv = Mgr @ np.linalg.inv(Msrc)
    gr = rgb_src @ conv.T
    n_gr = conv @ n
    n_gr = n_gr / n_gr[1]
    scale = 4063.0 * np.array([0.920, 1.0, 0.974])
    stat = np.clip(np.rint(gr * scale), 0, 4095)
    stat[empty] = 0
    D = np.rint(np.clip(n_valid / n_all, 0, 1) * 1584)
    D[empty] = 0
    s = np.zeros((4, 64, 64), np.uint32)
    s[0, 1:63, :] = stat[..., 0]; s[1, 1:63, :] = stat[..., 1]; s[2, 1:63, :] = stat[..., 2]; s[3, 1:63, :] = D

    Av = 2 * math.log2(FN); Tv = -math.log2(ET); Sv = math.log2(ISO / 3.125)
    cam = meta['camera']
    np.savez_compressed(f'{outdir}/{name}.npz', s=s, Av=Av, Tv=Tv, Sv=Sv, cct=cct,
                        neutral_gr=np.array([n_gr[0], n_gr[2]]), camera=f"{cam['make']} {cam['model']}",
                        categories=json.dumps(meta['categories']), transposed=transposed)
    if rgb8 is not None:
        im = Image.fromarray(rgb8)
        im = im.resize((256, max(1, round(256 * im.height / im.width))), Image.BILINEAR)
        im.save(f'{outdir}/prev/{name}.jpg', quality=80)
    live = ~empty
    G12 = s[1, 1:63, :].astype(float)
    rec = dict(name=name, camera=f"{cam['make']} {cam['model']}", categories=meta['categories'],
               Av=Av, Tv=Tv, Sv=Sv, Ev=Av + Tv - Sv, cct=cct, neutral_gr=[float(n_gr[0]), float(n_gr[2])],
               transposed=transposed, orientation=orient, raw_size=[int(W), int(H)], white_level=white,
               black_level=[float(x) for x in bl], mean_G=float(G12.mean()), share_D_lt_1584=float((D < 1584).mean()),
               share_empty=float(empty.mean()), dng_cct_illum=[ci1, ci2], bytes=len(data))
    return dict(ok=True, rec=rec)


try:
    r = main()
except Exception as e:
    import traceback
    r = dict(ok=False, reason='exception: ' + repr(e) + traceback.format_exc()[-300:])
print(json.dumps(r))
