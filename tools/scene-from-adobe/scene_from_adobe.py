#!/usr/bin/env python3
"""Recover scene-referred (colorimetric) colours of GR Mod's 1026 calibration colours
by undoing Lightroom's "Adobe Standard" rendering with Adobe's own camera profile (a DCP).

    python3 scene_from_adobe.py "RICOH GR IV HDF Adobe Standard.dcp" [--out out/cal_scene.json]

The DCP is read from the path given; none of its data is stored in the repo or in the output.
The tone-curve inverse is GR Mod's own (core/src/color/look.ts, class Tone, with TONE_PARAMS):
it is run through node via bridge.ts (bundled by esbuild), so it is exactly the same math.

Chain modelled (DNG spec 1.6, chapter 6 "Mapping Camera Color Space to CIE XYZ Space"):
  camera -> ColorMatrix/ForwardMatrix -> linear ProPhoto (D50)
         -> ProfileHueSatMap  -> ProfileLookTable -> base tone curve (hue preserving) -> sRGB display
This tool inverts everything after the forward matrix.
"""
import argparse, json, os, struct, subprocess, sys, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))

# ----------------------------------------------------------------------------------------------
# 1. DCP reader (TIFF-like; magic 'IIRC' little endian / 'MMCR' big endian)
# ----------------------------------------------------------------------------------------------
TAGS = {
    50708: 'UniqueCameraModel', 50721: 'ColorMatrix1', 50722: 'ColorMatrix2',
    50778: 'CalibrationIlluminant1', 50779: 'CalibrationIlluminant2',
    50936: 'ProfileName', 50937: 'ProfileHueSatMapDims', 50938: 'ProfileHueSatMapData1',
    50939: 'ProfileHueSatMapData2', 50940: 'ProfileToneCurve', 50941: 'ProfileEmbedPolicy',
    50932: 'ProfileCalibrationSignature', 50942: 'ProfileCopyright', 50964: 'ForwardMatrix1', 50965: 'ForwardMatrix2',
    50981: 'ProfileLookTableDims', 50982: 'ProfileLookTableData',
    51107: 'ProfileHueSatMapEncoding', 51108: 'ProfileLookTableEncoding',
    51109: 'BaselineExposureOffset', 51110: 'DefaultBlackRender',
}
TYPE_FMT = {1: ('B', 1), 2: ('c', 1), 3: ('H', 2), 4: ('I', 4), 6: ('b', 1), 7: ('B', 1),
            8: ('h', 2), 9: ('i', 4), 11: ('f', 4), 12: ('d', 8)}
ILLUM = {0: 'unknown', 1: 'daylight', 2: 'fluorescent', 3: 'tungsten', 4: 'flash', 9: 'fine weather',
         10: 'cloudy', 11: 'shade', 12: 'D-fluorescent (D5700)', 13: 'N-fluorescent (D4600)',
         14: 'W-fluorescent (D3500)', 15: 'WW-fluorescent', 17: 'standard A', 18: 'standard B',
         19: 'standard C', 20: 'D55', 21: 'D65', 22: 'D75', 23: 'D50', 24: 'ISO studio tungsten'}


def read_dcp(path):
    b = open(path, 'rb').read()
    if b[:2] == b'II': e = '<'
    elif b[:2] == b'MM': e = '>'
    else: raise ValueError('not a TIFF/DCP file')
    magic = b[2:4]
    if magic not in (b'RC', b'CR', b'\x2a\x00', b'\x00\x2a'):
        raise ValueError('unexpected magic %r' % b[:4])
    ifd, = struct.unpack(e + 'I', b[4:8])
    n, = struct.unpack(e + 'H', b[ifd:ifd + 2])
    tags = {}
    for i in range(n):
        tag, typ, cnt, val = struct.unpack(e + 'HHI4s', b[ifd + 2 + 12 * i: ifd + 14 + 12 * i])
        if typ in (5, 10):              # RATIONAL / SRATIONAL: two LONG / SLONG
            size = 8 * cnt
        elif typ in TYPE_FMT:
            size = TYPE_FMT[typ][1] * cnt
        else:
            raise ValueError('tag %d: unsupported type %d' % (tag, typ))
        raw = val[:size] if size <= 4 else b[struct.unpack(e + 'I', val)[0]:][:size]
        if typ == 2:
            v = raw.rstrip(b'\0').decode('latin-1')
        elif typ in (5, 10):            # SRATIONAL (type 10) = numerator/denominator, signed 32 bit
            f = struct.unpack(e + ('%di' if typ == 10 else '%dI') % (2 * cnt), raw)
            v = [(f[2 * k] / f[2 * k + 1]) if f[2 * k + 1] else 0.0 for k in range(cnt)]
        else:
            v = list(struct.unpack(e + '%d%s' % (cnt, TYPE_FMT[typ][0]), raw))
        tags[tag] = v
    d = {TAGS.get(t, 'tag%d' % t): v for t, v in tags.items()}
    return d


class Table:
    """HueSatMap / LookTable: dims (hue, sat, val), data[val][hue][sat] = (hue shift deg, sat scale, val scale)."""
    def __init__(self, dims, data, encoding=0):
        self.hd, self.sd, self.vd = [int(x) for x in dims]
        self.data = np.asarray(data, np.float64).reshape(self.vd, self.hd, self.sd, 3)
        self.encoding = encoding  # 0 linear, 1 sRGB (DNG 1.4 ProfileLookTableEncoding)


# ----------------------------------------------------------------------------------------------
# 2. Forward model of the profile tables (DNG spec 1.6 ch.6 "Applying the Hue/Saturation Map"
#    and the DNG SDK dng_hue_sat_map / RefBaselineHueSatMap)
# ----------------------------------------------------------------------------------------------
def srgb_enc(v):
    v = np.clip(v, 0, 1)
    return np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)


def srgb_dec(v):
    v = np.clip(v, 0, 1)
    return np.where(v <= 0.04045, v / 12.92, np.power((v + 0.055) / 1.055, 2.4))


def rgb_to_hsv(rgb):
    """h in 0..6 (DNG SDK convention), s, v in 0..1."""
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    mx = rgb.max(1); mn = rgb.min(1); c = mx - mn
    cs = np.where(c > 1e-12, c, 1.0)
    h = np.where(mx == r, np.mod((g - b) / cs, 6), np.where(mx == g, (b - r) / cs + 2, (r - g) / cs + 4))
    h = np.where(c > 1e-12, h, 0.0)
    s = np.where(mx > 1e-12, c / np.where(mx > 1e-12, mx, 1.0), 0.0)
    return h, s, mx


def hsv_to_rgb(h, s, v):
    h = np.mod(h, 6.0)
    fl = np.floor(h); f = h - fl; sec = fl.astype(int) % 6
    p = v * (1 - s); q = v * (1 - s * f); t = v * (1 - s * (1 - f))
    r = np.choose(sec, [v, q, p, p, t, v])
    g = np.choose(sec, [t, v, v, q, p, p])
    b = np.choose(sec, [p, p, t, v, v, q])
    return np.stack([r, g, b], 1)


def apply_table(pp, tab):
    """Spec 1.6 ch.6: convert linear ProPhoto RGB to HSV, look up (hue shift deg, sat scale, val scale) by
    trilinear interpolation (hue wraps, sat and val clamp at the table ends; val is skipped when there is a
    single val division), then h += shift/60, s = min(1, s*sscale), v = min(1, v*vscale), HSV -> RGB.
    Input is clamped to 0..1 like RefBaselineHueSatMap does. For a table with sRGB encoding the val index
    is taken on the gamma-encoded V (ProfileLookTableEncoding = 1)."""
    pp = np.clip(pp, 0, 1)
    h, s, v = rgb_to_hsv(pp)
    ve = srgb_enc(v) if tab.encoding == 1 else v
    hd, sd, vd = tab.hd, tab.sd, tab.vd
    hi = h / 6.0 * hd
    hf = np.floor(hi); fh = hi - hf
    h0 = hf.astype(int) % hd; h1 = (h0 + 1) % hd
    si = s * (sd - 1)
    s0 = np.clip(np.floor(si).astype(int), 0, sd - 2); fs = si - s0
    if vd > 1:
        vi = ve * (vd - 1)
        v0 = np.clip(np.floor(vi).astype(int), 0, vd - 2); fv = vi - v0; v1 = v0 + 1
    else:
        v0 = v1 = np.zeros_like(h0); fv = np.zeros_like(h)
    D = tab.data
    acc = 0
    for va, wa in ((v0, 1 - fv), (v1, fv)):
        for hb, wb in ((h0, 1 - fh), (h1, fh)):
            for sc, wc in ((s0, 1 - fs), (s0 + 1, fs)):
                acc = acc + (wa * wb * wc)[:, None] * D[va, hb, sc]
    h2 = np.mod(h + acc[:, 0] / 60.0, 6.0)
    s2 = np.clip(s * acc[:, 1], 0, 1)
    v2 = np.clip(v * acc[:, 2], 0, 1)
    return hsv_to_rgb(h2, s2, v2)


# ----------------------------------------------------------------------------------------------
# Colour maths (same definitions as core/src/color/math.ts: Lab D65 with sRGB white, CIEDE2000)
# ----------------------------------------------------------------------------------------------
S2X = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.072175], [0.0193339, 0.119192, 0.9503041]])
WHITE = S2X.sum(1)
P2S = np.array([2.0340763610012553, -0.7273343315490479, -0.30674170521474897,
                -0.228813409595274, 1.231730168456554, -0.0029169042747250254,
                -0.008569763411926157, -0.15328659684761936, 1.1618564158615476]).reshape(3, 3)


def lab_from_linear_srgb(lin):
    xyz = (lin @ S2X.T) / WHITE
    e = 216 / 24389; k = 24389 / 27
    f = np.where(xyz > e, np.cbrt(xyz), (k * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def lab_from_srgb(rgb):
    return lab_from_linear_srgb(srgb_dec(rgb))


def pp_to_lin_srgb(pp):
    return pp @ P2S.T


def lab_from_pp(pp):
    """Unclipped (out-of-sRGB-gamut colours keep their true Lab)."""
    return lab_from_linear_srgb(pp_to_lin_srgb(pp))


def pp_to_srgb_display(pp):
    """Colorimetric display: linear ProPhoto -> linear sRGB -> clip -> sRGB encoding. No tone curve."""
    return srgb_enc(np.clip(pp_to_lin_srgb(pp), 0, 1))


def de2000(l1, l2):
    L1, a1, b1 = l1.T; L2, a2, b2 = l2.T
    C1 = np.hypot(a1, b1); C2 = np.hypot(a2, b2); Cb7 = ((C1 + C2) / 2) ** 7
    G = 0.5 * (1 - np.sqrt(Cb7 / (Cb7 + 25.0 ** 7)))
    a1p = (1 + G) * a1; a2p = (1 + G) * a2
    C1p = np.hypot(a1p, b1); C2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360; h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dL = L2 - L1; dC = C2p - C1p
    dh = h2p - h1p; dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dH = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lb = (L1 + L2) / 2; Cb = (C1p + C2p) / 2
    hs = h1p + h2p
    hb = np.where(C1p * C2p == 0, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2,
                  np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    T = (1 - 0.17 * np.cos(np.radians(hb - 30)) + 0.24 * np.cos(np.radians(2 * hb))
         + 0.32 * np.cos(np.radians(3 * hb + 6)) - 0.2 * np.cos(np.radians(4 * hb - 63)))
    dth = 30 * np.exp(-(((hb - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lb - 50) ** 2 / np.sqrt(20 + (Lb - 50) ** 2)
    Sc = 1 + 0.045 * Cb; Sh = 1 + 0.015 * Cb * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh))


# ----------------------------------------------------------------------------------------------
# Bridge to GR Mod's TypeScript (the exact Tone inverse / forward)
# ----------------------------------------------------------------------------------------------
class Bridge:
    def __init__(self):
        esb = os.path.join(REPO, 'node_modules', '.bin', 'esbuild')
        self.tmp = tempfile.mkdtemp(prefix='scene_bridge_')
        self.js = os.path.join(self.tmp, 'bridge.mjs')
        subprocess.run([esb, os.path.join(HERE, 'bridge.ts'), '--bundle', '--platform=node', '--format=esm',
                        '--outfile=' + self.js, '--log-level=error'], check=True)

    def call(self, **req):
        r = subprocess.run(['node', self.js], input=json.dumps(req), capture_output=True, text=True, check=True)
        return json.loads(r.stdout)

    def data(self):
        d = self.call(op='data')
        return np.array(d['adobe']).reshape(-1, 3), np.array(d['cam']).reshape(-1, 3)

    def to_pre(self, rgb):
        return np.array(self.call(op='toPre', rgb=rgb.ravel().tolist())['out']).reshape(-1, 3)

    def to_display(self, pre):
        return np.array(self.call(op='toDisplay', pre=pre.ravel().tolist())['out']).reshape(-1, 3)


# ----------------------------------------------------------------------------------------------
# 3. Numerical inversion of a table stage: damped Gauss-Newton (Levenberg-Marquardt) per colour
# ----------------------------------------------------------------------------------------------
def invert_stage(fn, target, iters=200, eps=1e-6):
    n = len(target)
    x = np.clip(target.copy(), 0, 1)
    lam = np.full(n, 1e-3)
    r = fn(x) - target
    err = np.abs(r).max(1)
    for _ in range(iters):
        if err.max() < 1e-11: break
        J = np.zeros((n, 3, 3))
        for k in range(3):
            d = np.zeros(3); d[k] = eps
            J[:, :, k] = (fn(np.clip(x + d, 0, 1)) - fn(np.clip(x - d, 0, 1))) / (2 * eps)
        JT = np.transpose(J, (0, 2, 1))
        A = JT @ J + lam[:, None, None] * np.eye(3)
        step = np.linalg.solve(A, (JT @ r[:, :, None]))[:, :, 0]
        xn = np.clip(x - step, 0, 1)
        rn = fn(xn) - target
        en = np.abs(rn).max(1)
        ok = en < err
        x = np.where(ok[:, None], xn, x); r = np.where(ok[:, None], rn, r); err = np.where(ok, en, err)
        lam = np.where(ok, np.maximum(lam / 3, 1e-9), np.minimum(lam * 4, 1e6))
    return x, err


# ----------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dcp', help='path to the Adobe Standard DCP of the camera (read only)')
    ap.add_argument('--out', default=os.path.join(HERE, 'out', 'cal_scene.json'))
    a = ap.parse_args()

    d = read_dcp(a.dcp)
    print('DCP: %s  (%s)' % (d.get('ProfileName'), d.get('UniqueCameraModel')))
    print('tags:', ', '.join(sorted(d)))
    i1 = d.get('CalibrationIlluminant1', [None])[0]; i2 = d.get('CalibrationIlluminant2', [None])[0]
    print('CalibrationIlluminant1 = %s (%s); CalibrationIlluminant2 = %s (%s)'
          % (i1, ILLUM.get(i1, '?'), i2, ILLUM.get(i2, '?')))
    # Spec 1.6 ch.6: tables are interpolated between the two illuminants by colour temperature of the white
    # balance; for the daylight (D65) shot we take the table whose illuminant is D65.
    if i2 == 21: which = 2
    elif i1 == 21: which = 1
    else:
        which = 2
        print('WARNING: neither illuminant is D65; falling back to HueSatMapData2')
    print('using ProfileHueSatMapData%d for D65' % which)
    hdims = d['ProfileHueSatMapDims']; ldims = d['ProfileLookTableDims']
    print('HueSatMap dims (hue,sat,val) =', hdims, ' LookTable dims =', ldims)
    henc = d.get('ProfileHueSatMapEncoding', [0])[0]; lenc = d.get('ProfileLookTableEncoding', [0])[0]
    print('encodings: HueSatMap %d, LookTable %d (0 = linear, 1 = sRGB); ProfileToneCurve present: %s'
          % (henc, lenc, 'ProfileToneCurve' in d))
    hsm = Table(hdims, d['ProfileHueSatMapData%d' % which], henc)
    lut = Table(ldims, d['ProfileLookTableData'], lenc)
    # sanity: at saturation 0 the maps are nearly neutral-preserving (sat scale irrelevant); report ranges
    for nm, t in (('HueSatMap', hsm), ('LookTable', lut)):
        D = t.data
        print('  %s: hue shift %.2f..%.2f deg, sat scale %.3f..%.3f, val scale %.3f..%.3f'
              % (nm, D[..., 0].min(), D[..., 0].max(), D[..., 1].min(), D[..., 1].max(), D[..., 2].min(), D[..., 2].max()))

    br = Bridge()
    adobe, cam = br.data()
    print('calibration colours:', len(adobe))

    # --- inverse tone curve: GR Mod's Tone.toPre (display -> linear ProPhoto after the LookTable)
    pre = br.to_pre(adobe)
    print('pre-tone linear ProPhoto: max channel %.4f, %d colours with a channel > 1 (clipped by the tables)'
          % (pre.max(), int((pre.max(1) > 1).sum())))
    target = np.clip(pre, 0, 1)

    # --- invert LookTable, then HueSatMap
    after_hsm, e_lut = invert_stage(lambda x: apply_table(x, lut), target)
    scene, e_hsm = invert_stage(lambda x: apply_table(x, hsm), after_hsm)
    bad_stage = (e_lut > 1e-6) | (e_hsm > 1e-6)
    print('stage inversion: LookTable max resid %.2e, HueSatMap max resid %.2e; %d colours above 1e-6'
          % (e_lut.max(), e_hsm.max(), bad_stage.sum()))

    # --- verification: forward model on the recovered scene colours
    fwd_lut = apply_table(apply_table(scene, hsm), lut)
    fwd = br.to_display(fwd_lut)
    lab_adobe = lab_from_srgb(adobe)
    rt = de2000(lab_from_srgb(fwd), lab_adobe)
    print('\nround trip vs CAL_ADOBE (CIEDE2000): mean %.5f, median %.5f, max %.5f; > 0.05: %d, > 0.5: %d'
          % (rt.mean(), np.median(rt), rt.max(), (rt > 0.05).sum(), (rt > 0.5).sum()))
    if (rt > 0.05).any():
        idx = np.argsort(-rt)[:8]
        print('  worst:', ', '.join('#%d dE=%.3f pre_max=%.3f hsv_s=%.3f' % (i, rt[i], pre[i].max(),
              rgb_to_hsv(np.clip(pre[i:i + 1], 0, 1))[1][0]) for i in idx))
        why = []
        for i in np.where(rt > 0.05)[0]:
            tags = []
            if pre[i].max() > 1: tags.append('pre-tone > 1 (clipped)')
            if min(adobe[i]) <= 1e-4 or max(adobe[i]) >= 1 - 1e-4: tags.append('display value at 0/1 (clipped)')
            if not tags: tags.append('no convergence / non-invertible table region')
            why.append(', '.join(tags))
        from collections import Counter
        print('  reasons:', dict(Counter(why)))

    # --- outputs
    colori = pp_to_srgb_display(scene)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    out = {
        'description': 'Scene-referred colours of the 1026 GR Mod calibration colours, recovered by inverting '
                       'Lightroom Adobe Standard (inverse base tone curve, ProfileLookTable, ProfileHueSatMap D65). '
                       'Derived numbers only.',
        'scene_linear_prophoto_d50': np.round(scene, 8).tolist(),
        'colorimetric_srgb': np.round(colori, 6).tolist(),
        'colorimetric_srgb_note': 'linear ProPhoto D50 -> linear sRGB (Bradford) -> clip -> sRGB encoding; no tone curve',
        'roundtrip_ciede2000': {'mean': float(rt.mean()), 'max': float(rt.max())},
    }
    json.dump(out, open(a.out, 'w'))
    print('wrote', a.out)

    # --- statistics
    lab_cam = lab_from_srgb(cam)
    lab_col = lab_from_srgb(colori)
    print('\n(a) mean CIEDE2000 colorimetric sRGB vs CAL_ADOBE: %.3f' % de2000(lab_col, lab_adobe).mean())
    print('(b) mean CIEDE2000 colorimetric sRGB vs CAL_CAM  : %.3f' % de2000(lab_col, lab_cam).mean())
    print('    (for reference CAL_ADOBE vs CAL_CAM: %.3f)' % de2000(lab_adobe, lab_cam).mean())

    def sectors(lab_ref, lab_new, title):
        Cr = np.hypot(lab_ref[:, 1], lab_ref[:, 2]); Cn = np.hypot(lab_new[:, 1], lab_new[:, 2])
        hr = np.degrees(np.arctan2(lab_ref[:, 2], lab_ref[:, 1])) % 360
        hn = np.degrees(np.arctan2(lab_new[:, 2], lab_new[:, 1])) % 360
        dh = (hn - hr + 180) % 360 - 180
        m = Cr > 15
        print('\n%s  (reference chroma > 15: %d colours)' % (title, m.sum()))
        print(' sector(deg)   n  median C ratio  median hue shift(deg)')
        for k in range(12):
            s = m & (hr >= 30 * k) & (hr < 30 * k + 30)
            if s.sum() == 0:
                print(' %3d-%3d   %4d       -              -' % (30 * k, 30 * k + 30, 0)); continue
            print(' %3d-%3d   %4d      %.3f          %+.1f' % (30 * k, 30 * k + 30, s.sum(),
                  np.median(Cn[s] / Cr[s]), np.median(dh[s])))
        print(' all          %4d      %.3f          %+.1f' % (m.sum(), np.median(Cn[m] / Cr[m]), np.median(dh[m])))

    # Adobe Standard relative to colorimetric (includes the tone curve; Lab chroma depends on lightness)
    sectors(lab_from_pp(scene), lab_adobe, 'Adobe Standard (CAL_ADOBE) relative to colorimetric scene (unclipped Lab)')
    # HueSatMap + LookTable alone, same linear exposure, no tone curve
    sectors(lab_from_pp(scene), lab_from_pp(fwd_lut), 'HueSatMap + LookTable alone (no tone curve) relative to scene')
    mid = (lab_from_pp(scene)[:, 0] > 20)
    c0 = np.hypot(*lab_from_pp(scene)[:, 1:].T); c1 = np.hypot(*lab_from_pp(fwd_lut)[:, 1:].T)
    print('\nHSM+LUT alone: median chroma ratio over all colours with C>15: %.3f; mean dE2000 scene vs after tables: %.3f'
          % (np.median((c1 / np.where(c0 > 0, c0, 1))[c0 > 15]), de2000(lab_from_pp(scene), lab_from_pp(fwd_lut)).mean()))


if __name__ == '__main__':
    main()
