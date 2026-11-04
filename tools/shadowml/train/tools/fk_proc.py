"""Process one FiveK image.  usage: python3 -I fk_proc.py <dng> <name> <meta_json_str> <outdir> <letter>=<tif> ...
Writes <outdir>/<name>.npz (atomic) and prints one JSON line {"ok":..., ...}.  Never executes anything from inputs."""
import sys, os, json, math, time, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np, cv2
import tiff_min as tiff
import fk_common as C
import rawpy, tifffile
from scipy.stats import rankdata
cv2.setNumThreads(1)
LONG = 384

def rs(a, w, h):
    return cv2.resize(np.ascontiguousarray(a, dtype=np.float32), (int(w), int(h)), interpolation=cv2.INTER_AREA)

def spearman(a, b):
    return float(np.corrcoef(rankdata(a.ravel()), rankdata(b.ravel()))[0, 1])

def logY(y, fl=-12):
    return np.log2(np.maximum(y, 2.0 ** fl))

def read_dng_tags(path):
    data, t, out = tiff.read_all(path)
    ifds = {n: r for n, o, r in out['_ifds']}
    ifd0 = ifds['ifd0']; exif = ifds.get('ifd0.exif', {})
    sub = None
    for n, r in ifds.items():
        if 'ActiveArea' in r or ('WhiteLevel' in r and 'CFAPattern' in r):
            sub = r
    if sub is None: sub = ifd0
    return ifd0, exif, sub

def color_model(ifd0, T=None):
    """returns dict with Y weights for (R,G,B) unbalanced camera values relative to white level"""
    cm1 = np.array(ifd0['ColorMatrix1'], float).reshape(3, 3)
    cm2 = np.array(ifd0['ColorMatrix2'], float).reshape(3, 3) if ifd0.get('ColorMatrix2') is not None else None
    ci1, ci2 = ifd0.get('CalibrationIlluminant1'), ifd0.get('CalibrationIlluminant2')
    t1 = float(ILL_.get(ci1, 2856)); t2 = float(ILL_.get(ci2, 6504)) if cm2 is not None else t1
    if cm2 is None: cm2 = cm1
    if t1 > t2:
        cm1, cm2, t1, t2 = cm2, cm1, t2, t1
        swap = True
    else: swap = False
    fm1 = ifd0.get('ForwardMatrix1'); fm2 = ifd0.get('ForwardMatrix2')
    has_fm = fm1 is not None
    fm1 = np.array(fm1, float).reshape(3, 3) if has_fm else None
    fm2 = np.array(fm2, float).reshape(3, 3) if (has_fm and fm2 is not None) else fm1
    cc1 = ifd0.get('CameraCalibration1'); cc2 = ifd0.get('CameraCalibration2')
    cc1 = np.array(cc1, float).reshape(3, 3) if cc1 is not None else np.eye(3)
    cc2 = np.array(cc2, float).reshape(3, 3) if cc2 is not None else cc1
    ab = ifd0.get('AnalogBalance'); ab = np.diag(np.array(ab, float)) if ab is not None else np.eye(3)
    if swap:  # keep FM/CC consistent with swapped CM ordering
        if has_fm: fm1, fm2 = fm2, fm1
        cc1, cc2 = cc2, cc1
    # (illuminant 1 is always the lower colour temperature after the swap)
    n = ifd0.get('AsShotNeutral')
    wxy = ifd0.get('AsShotWhiteXY')
    def mats(T):
        w = C.interp_w(T, t1, t2)
        cm = w * cm1 + (1 - w) * cm2
        cc = w * cc1 + (1 - w) * cc2
        fm = (w * fm1 + (1 - w) * fm2) if has_fm else None
        return cm, cc, fm
    if n is not None:
        n = np.array(n, float)
        T = 5000.0
        for _ in range(60):
            cm, cc, fm = mats(T)
            XYZ = np.linalg.solve(ab @ cc @ cm, n)
            Tn = C.xy_to_cct(XYZ[0] / XYZ.sum(), XYZ[1] / XYZ.sum())
            if abs(Tn - T) < 1: T = Tn; break
            T = Tn
        cct = T
    elif wxy is not None:
        cct = C.xy_to_cct(*wxy)
        cm, cc, fm = mats(cct)
        xyz = np.array([wxy[0] / wxy[1], 1.0, (1 - wxy[0] - wxy[1]) / wxy[1]])
        n = ab @ cc @ cm @ xyz; n = n / n[1]
    else:
        raise RuntimeError('no AsShotNeutral/AsShotWhiteXY')
    cm, cc, fm = mats(cct)
    abcc = ab @ cc
    if has_fm:
        refn = np.linalg.solve(abcc, n)           # reference neutral
        M = fm @ np.diag(1.0 / refn) @ np.linalg.inv(abcc)   # cam -> XYZ(D50)
        which = 'ForwardMatrix'
    else:
        M = np.linalg.inv(abcc @ cm)                            # cam -> XYZ (scene illuminant)
        which = 'ColorMatrix(inverse)'
    return dict(wY=M[1].astype(np.float64), which=which, cct=float(cct), neutral=n, wb_mult=(n[1] / n).tolist(), M=M)
ILL_ = C.ILL

def prophoto_luts(icc):
    note = dict(icc_present=icc is not None)
    if icc is not None and icc.get('ok'):
        note.update(icc_desc=icc.get('desc'), icc_curve_n=icc.get('curve_n'), icc_gamma=icc.get('gamma'),
                    icc_primaries_Y=icc.get('primaries_Y'))
        pY = np.array(icc['primaries_Y'])
        note['icc_is_prophoto_primaries'] = bool(np.abs(pY - C.PROPHOTO_Y).max() < 2e-3)
        if icc.get('curve_n') == 1 and icc.get('gamma'):
            g = 1.8 if abs(icc['gamma'] - 1.8) < 0.01 else icc['gamma']; lut = C.gamma_lut(g); note['trc'] = 'icc_pure_gamma_%.3f' % g
        elif icc.get('curve_n', 0) > 1:
            lut = C.table_lut(icc['table']); note['trc'] = 'icc_table'
        else:
            lut = C.romm_decode_lut(); note['trc'] = 'romm_toe(fallback)'
    else:
        lut = C.romm_decode_lut(); note['trc'] = 'romm_toe(no_icc)'
    return lut, note

def expert_Y(tifpath):
    with tifffile.TiffFile(tifpath) as f:
        pg = f.pages[0]
        icc_t = pg.tags.get('InterColorProfile')
        icc = C.parse_icc(icc_t.value) if icc_t is not None else None
        a = pg.asarray()
    if a.ndim != 3 or a.shape[2] < 3: raise RuntimeError('unexpected tiff shape %s' % (a.shape,))
    if a.dtype != np.uint16: raise RuntimeError('tiff dtype %s' % a.dtype)
    lut, note = prophoto_luts(icc)
    H, W = a.shape[:2]
    Y = np.empty((H, W), np.float32)
    for y0 in range(0, H, 256):
        s = a[y0:y0 + 256, :, :3]
        Y[y0:y0 + 256] = (C.PROPHOTO_Y[0] * lut[s[..., 0]] + C.PROPHOTO_Y[1] * lut[s[..., 1]] + C.PROPHOTO_Y[2] * lut[s[..., 2]])
    return Y, note

def out_size(cw, ch, o):
    if o in (5, 6, 7, 8): cw, ch = ch, cw
    s = LONG / max(cw, ch)
    if cw >= ch: return LONG, max(1, int(round(ch * s)))
    return max(1, int(round(cw * s))), LONG

def crop_search(frame, ey):
    """frame: raw-side log image (Hf,Wf) at ~LONG; ey: expert Y (He,We).  Find crop box (fractions) of frame."""
    Hf, Wf = frame.shape
    s = 160.0 / max(Wf, Hf)
    fw, fh = max(8, int(Wf * s)), max(8, int(Hf * s))
    fr = cv2.GaussianBlur(rs(frame, fw, fh), (0, 0), 1.0)
    ea = ey.shape[1] / ey.shape[0]
    best = (-2, None)
    for frac in np.linspace(1.0, 0.2, 61):
        ww = frac * fw; hh = ww / ea
        if hh > fh + 0.5: 
            hh = fh; ww = hh * ea
        ww = int(round(ww)); hh = int(round(hh))
        if ww < 8 or hh < 8 or ww > fw or hh > fh: continue
        t = cv2.GaussianBlur(rs(logY(ey), ww, hh), (0, 0), 1.0)
        if ww == fw and hh == fh:
            r = np.array([[np.corrcoef(t.ravel(), fr.ravel())[0, 1]]]); loc = (0, 0)
        else:
            r = cv2.matchTemplate(fr, t, cv2.TM_CCOEFF_NORMED)
        mv = float(r.max())
        if mv > best[0]:
            iy, ix = np.unravel_index(int(np.argmax(r)), r.shape)
            best = (mv, (ix / fw, iy / fh, (ix + ww) / fw, (iy + hh) / fh))
    return best

def main():
    dng, name, meta_s, outdir = sys.argv[1:5]
    experts = dict(a.split('=', 1) for a in sys.argv[5:])
    meta_in = json.loads(meta_s)
    t0 = time.time()
    ifd0, exif, sub = read_dng_tags(dng)
    if ifd0.get('ColorMatrix1') is None: return dict(ok=False, reason='no ColorMatrix1')
    cmod = color_model(ifd0)
    ISO = exif.get('ISO'); ISO = ISO[0] if isinstance(ISO, list) else ISO
    orient_tag = int(ifd0.get('Orientation', 1) or 1)
    raw = rawpy.imread(dng)
    with raw:
        if raw.raw_type != rawpy.RawType.Flat: return dict(ok=False, reason='raw_type %s' % raw.raw_type)
        desc = raw.color_desc.decode()
        if raw.num_colors != 3 or sorted(desc[:3]) != ['B', 'G', 'R']: return dict(ok=False, reason='not RGB CFA %s' % desc)
        img = raw.raw_image_visible.astype(np.float32)
        cols = np.array(raw.raw_colors_visible)
        white = float(raw.white_level); bl = np.array(raw.black_level_per_channel, float)
        sz = raw.sizes
        raw_dims = [int(sz.raw_width), int(sz.raw_height)]
    H0, W0 = img.shape
    aa = sub.get('ActiveArea')
    aa_ok = (aa is None) or ((aa[2] - aa[0], aa[3] - aa[1]) == (H0, W0))
    # clipped mask on the full-res mosaic (samples at or above 98% of the way to white)
    thr = (bl[cols] + 0.98 * (white - bl[cols]))
    clipmask = (img >= thr).astype(np.float32)
    blocks_clip = cv2.resize(clipmask, (64, 62), interpolation=cv2.INTER_AREA)
    del clipmask, thr
    H2, W2 = H0 // 2, W0 // 2
    val = (img[:H2 * 2, :W2 * 2] - bl[cols[:H2 * 2, :W2 * 2]]) / (white - bl[cols[:H2 * 2, :W2 * 2]])
    cc = cols[:2, :2]; pos = {'R': [], 'G': [], 'B': []}
    for dy in range(2):
        for dx in range(2): pos[desc[cc[dy, dx]]].append((dy, dx))
    if not (len(pos['R']) == 1 and len(pos['B']) == 1 and len(pos['G']) == 2): return dict(ok=False, reason='odd CFA layout')
    q = lambda p: val[p[0]::2, p[1]::2]
    R = q(pos['R'][0]); B = q(pos['B'][0]); G = 0.5 * (q(pos['G'][0]) + q(pos['G'][1]))
    w = cmod['wY']
    Yh = (w[0] * R + w[1] * G + w[2] * B).astype(np.float32)   # half-res linear Y (relative to white level)
    del val, img, R, G, B
    blocks_y = cv2.resize(Yh, (64, 62), interpolation=cv2.INTER_AREA)
    # default crop (relative to active area), in full-res coords -> half-res slice
    dco = ifd0.get('DefaultCropOrigin') or sub.get('DefaultCropOrigin') or [0, 0]
    dcs = ifd0.get('DefaultCropSize') or sub.get('DefaultCropSize') or [W0, H0]
    dco = sub.get('DefaultCropOrigin', dco); dcs = sub.get('DefaultCropSize', dcs)
    cx0, cy0, cw, ch = float(dco[0]), float(dco[1]), float(dcs[0]), float(dcs[1])
    xs, xe = int(round(cx0 / 2)), int(round((cx0 + cw) / 2)); ys, ye = int(round(cy0 / 2)), int(round((cy0 + ch) / 2))
    xe = min(xe, W2); ye = min(ye, H2)
    Yc = Yh[ys:ye, xs:xe]
    # experts
    ex_y = {}; ex_note = {}
    for l, p in sorted(experts.items()):
        ex_y[l], ex_note[l] = expert_Y(p)
    res = {}
    def make_raw(o, w_, h_, box=None):
        Yo = C.orient(Yc, o)
        if box is not None:
            hh, ww = Yo.shape
            x0, y0, x1, y1 = box
            Yo = Yo[int(round(y0 * hh)):max(int(round(y1 * hh)), int(round(y0 * hh)) + 1), int(round(x0 * ww)):max(int(round(x1 * ww)), int(round(x0 * ww)) + 1)]
        return rs(Yo, w_, h_)
    W_, H_ = out_size(Yc.shape[1] * 2, Yc.shape[0] * 2, orient_tag)
    raw_y = make_raw(orient_tag, W_, H_)
    rawcut = {}; out_exp = {}; exp_arrays = {}
    for l in sorted(ex_y):
        ey = ex_y[l]; He, We = ey.shape
        info = dict(tif_size=[We, He], trc=ex_note[l], orient_used=orient_tag, flag_notes=[])
        size_match = abs(We - round(cw if orient_tag < 5 else ch)) <= 2 and abs(He - round(ch if orient_tag < 5 else cw)) <= 2
        info['size_match_default_crop'] = bool(size_match)
        def evaluate(o, ey_small=None):
            wcoarse = 128 if We >= He else max(8, int(128 * We / He)); hcoarse = 128 if He >= We else max(8, int(128 * He / We))
            a = make_raw(o, wcoarse, hcoarse); b = rs(ey, wcoarse, hcoarse)
            return spearman(logY(a), logY(b))
        o_use = orient_tag
        if size_match:
            rho_c = evaluate(orient_tag)
            if rho_c < 0.8:
                cands = {}
                for o in range(1, 9):
                    ow, oh = out_size(Yc.shape[1] * 2, Yc.shape[0] * 2, o)
                    if abs(ow / oh - We / He) < 0.02: cands[o] = evaluate(o)
                if cands:
                    ob = max(cands, key=cands.get)
                    if ob != orient_tag and cands[ob] > rho_c + 0.1:
                        o_use = ob; info['flag_notes'].append('orient_override %d->%d (rho %.2f->%.2f)' % (orient_tag, ob, rho_c, cands[ob]))
        else:
            # maybe orientation (transposed dims)?
            sw = abs(We - round(ch if orient_tag < 5 else cw)) <= 2 and abs(He - round(cw if orient_tag < 5 else ch)) <= 2
            if sw:
                for o in range(1, 9):
                    ow, oh = out_size(Yc.shape[1] * 2, Yc.shape[0] * 2, o)
                    if abs(ow / oh - We / He) < 0.02:
                        pass
                cands = {}
                for o in range(1, 9):
                    ow, oh = out_size(Yc.shape[1] * 2, Yc.shape[0] * 2, o)
                    if abs(ow / oh - We / He) < 0.02: cands[o] = evaluate(o)
                if cands:
                    ob = max(cands, key=cands.get); o_use = ob
                    info['flag_notes'].append('orient_by_search %d->%d (rho %.2f)' % (orient_tag, ob, cands[ob])); size_match = True
        info['orient_used'] = int(o_use)
        W1, H1 = out_size(Yc.shape[1] * 2, Yc.shape[0] * 2, o_use)
        if size_match:
            ra = make_raw(o_use, W1, H1)
            ea = rs(ey, W1, H1)
            box = None
        else:
            # crop / different geometry: locate expert inside the raw frame
            frame = logY(make_raw(o_use, W1, H1))
            sc, box = crop_search(frame, ey)
            info['crop_search_score'] = sc; info['crop_box_frac'] = [round(v, 4) for v in box] if box else None
            Wn, Hn = (LONG, max(1, int(round(LONG * He / We)))) if We >= He else (max(1, int(round(LONG * We / He))), LONG)
            ea = rs(ey, Wn, Hn)
            ra = make_raw(o_use, Wn, Hn, box) if box else rs(Yc[:Hn, :Wn], Wn, Hn)
            rawcut[l] = ra
        la, lb = logY(ra), logY(ea)
        rho = spearman(la, lb); pr = float(np.corrcoef(la.ravel(), lb.ravel())[0, 1])
        try:
            win = cv2.createHanningWindow((la.shape[1], la.shape[0]), cv2.CV_32F)
            ga = cv2.Laplacian(cv2.GaussianBlur(la, (0, 0), 1.0), cv2.CV_32F); gb = cv2.Laplacian(cv2.GaussianBlur(lb, (0, 0), 1.0), cv2.CV_32F)
            (sx, sy), resp = cv2.phaseCorrelate(ga, gb, win)
        except Exception:
            sx = sy = float('nan'); resp = float('nan')
        info.update(rho=rho, pearson_logY=pr, shift_px=[float(sx), float(sy)], shift_resp=float(resp), shape=list(ea.shape))
        if size_match:
            flag = 'ok' if (rho >= 0.8 and abs(sx) <= 4 and abs(sy) <= 4) else 'poor'
            if flag == 'ok' and o_use != orient_tag: flag = 'orient_fixed'
        else:
            flag = 'crop' if (info.get('crop_search_score', 0) >= 0.85 and rho >= 0.8) else 'poor'
        info['align_flag'] = flag
        out_exp[l] = info; exp_arrays[l] = ea
        if l == sorted(ex_y)[0] and flag in ('ok', 'orient_fixed'):
            pass
    # raw_y for the canonical orientation = the one used by the (first ok) expert; if experts disagree keep tag-based one
    used = [i['orient_used'] for i in out_exp.values() if i['align_flag'] in ('ok', 'orient_fixed')]
    if used and used[0] != orient_tag:
        W_, H_ = out_size(Yc.shape[1] * 2, Yc.shape[0] * 2, used[0]); raw_y = make_raw(used[0], W_, H_)
    cam = meta_in['camera']
    meta = dict(
        name=name, make=cam['make'], model=cam['model'], dng_make=ifd0.get('Make'), dng_model=ifd0.get('Model'),
        unique_camera_model=ifd0.get('UniqueCameraModel'),
        iso=ISO, exposure_time=exif.get('ExposureTime'), f_number=exif.get('FNumber'),
        baseline_exposure=ifd0.get('BaselineExposure'), orientation_tag=orient_tag,
        raw_dims_wh=raw_dims, active_area_tlbr=aa, active_area_visible_hw=[H0, W0], active_area_matches_libraw=bool(aa_ok),
        default_crop_origin=[cx0, cy0], default_crop_size=[cw, ch], default_crop_half_slice=[ys, ye, xs, xe],
        categories=meta_in['categories'], dng_id=meta_in.get('id'),
        black_level=bl.tolist(), white_level=white,
        as_shot_neutral=[float(x) for x in cmod['neutral']], wb_mult_rgb=[float(x) for x in cmod['wb_mult']],
        cct_k=cmod['cct'], y_matrix_source=cmod['which'], y_weights_rgb=[float(x) for x in cmod['wY']],
        raw_side=dict(shape_hw=list(raw_y.shape), demosaic='half-resolution 2x2 CFA binning (G averaged), then area-downsample',
                      orient_used=int(used[0]) if used else orient_tag, y_log_code='int16 2nd diff of round((log2Y+20)*32); Y=2**(code/32-20)',
                      grid='62 rows x 64 cols over full visible active area, sensor orientation'),
        experts=out_exp, proc_seconds=time.time() - t0)
    arrs = dict(meta_json=np.array(json.dumps(meta, default=float)), raw_y=C.enc_logy(raw_y),
                blocks_y=C.trunc_f32(blocks_y), blocks_clip=blocks_clip.astype(np.float16))
    for l, ea in exp_arrays.items(): arrs['exp_' + l] = C.enc_logy(ea)
    for l, ra in rawcut.items(): arrs['rawcut_' + l] = C.enc_logy(ra)
    tmp = os.path.join(outdir, '.' + name + '.tmp.npz'); fin = os.path.join(outdir, name + '.npz')
    np.savez_compressed(tmp, **arrs)
    os.replace(tmp, fin)
    return dict(ok=True, name=name, bytes=os.path.getsize(fin), flags={l: i['align_flag'] for l, i in out_exp.items()},
                rho={l: round(i['rho'], 3) for l, i in out_exp.items()}, secs=round(time.time() - t0, 1), notes={l: i['flag_notes'] for l, i in out_exp.items() if i['flag_notes']})

if __name__ == '__main__':
    try:
        r = main()
    except Exception as e:
        r = dict(ok=False, reason='exception: ' + repr(e) + ' | ' + traceback.format_exc()[-400:])
    print(json.dumps(r, default=float))
