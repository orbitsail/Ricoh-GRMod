# SPDX-License-Identifier: GPL-2.0-only
"""GR IV DNG -> per-image npz for the AE accuracy study.
For each DNG: EXIF/makernote basics, raw luminance map (same recipe as the FiveK set: linear Y relative to the
sensor white level, as-shot WB, default crop, EXIF orientation applied, long side 384), the camera's own full-size
JPEG preview (sub-IFD 1) as linear display Y at the same size, plus a small sRGB thumbnail.
usage: python3 -I gr_extract.py OUTDIR file1.dng file2.dng ..."""
import sys, os, io, json, time
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import _paths
import numpy as np, cv2
import tiff_min as tiff
import fk_common as C
import fk_proc as P
import rawpy
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
cv2.setNumThreads(2)
LONG = 384
OVR = _paths.PRIV['wb_override']

def srgb_to_lin(u8):
    v = u8.astype(np.float32) / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4).astype(np.float32)

def one(path, outdir):
    t0 = time.time()
    data, t, out = tiff.read_all(path)
    ifds = {n: r for n, o, r in out['_ifds']}
    ifd0 = ifds['ifd0']; exif = ifds.get('ifd0.exif', {})
    sub0 = ifds['ifd0.sub0']; sub1 = ifds['ifd0.sub1']
    name = os.path.splitext(os.path.basename(path))[0]
    name = name.split('_')[-1] if name.startswith('1793') else name
    if name in OVR: ifd0['AsShotNeutral'] = OVR[name]
    cmod = P.color_model(ifd0)
    orient = int(ifd0.get('Orientation', 1) or 1)
    raw = rawpy.imread(path)
    with raw:
        desc = raw.color_desc.decode()
        img = raw.raw_image_visible.astype(np.float32)
        cols = np.array(raw.raw_colors_visible)
        white = float(raw.white_level); bl = np.array(raw.black_level_per_channel, float)
    H0, W0 = img.shape
    thr = bl[cols] + 0.98 * (white - bl[cols])
    clipmask = (img >= thr).astype(np.float32)
    blocks_clip = cv2.resize(clipmask, (64, 62), interpolation=cv2.INTER_AREA)
    H2, W2 = H0 // 2, W0 // 2
    c2 = cols[:H2 * 2, :W2 * 2]
    val = (img[:H2 * 2, :W2 * 2] - bl[c2]) / (white - bl[c2])
    cc = cols[:2, :2]; pos = {'R': [], 'G': [], 'B': []}
    for dy in range(2):
        for dx in range(2): pos[desc[cc[dy, dx]]].append((dy, dx))
    q = lambda p: val[p[0]::2, p[1]::2]
    R = q(pos['R'][0]); B = q(pos['B'][0]); G = 0.5 * (q(pos['G'][0]) + q(pos['G'][1]))
    w = cmod['wY']
    Yh = (w[0] * R + w[1] * G + w[2] * B).astype(np.float32)
    # per-channel maxima of the half-res planes (for headroom stats)
    dco = sub0.get('DefaultCropOrigin', [0, 0]); dcs = sub0.get('DefaultCropSize', [W0, H0])
    cx0, cy0, cw, ch = float(dco[0]), float(dco[1]), float(dcs[0]), float(dcs[1])
    xs, xe = int(round(cx0 / 2)), int(round((cx0 + cw) / 2)); ys, ye = int(round(cy0 / 2)), int(round((cy0 + ch) / 2))
    Yc = Yh[ys:ye, xs:xe]
    Rc, Gc, Bc = R[ys:ye, xs:xe], G[ys:ye, xs:xe], B[ys:ye, xs:xe]
    W_, H_ = P.out_size(Yc.shape[1] * 2, Yc.shape[0] * 2, orient)
    def mk(a):
        return P.rs(C.orient(a, orient), W_, H_)
    raw_y = mk(Yc)
    raw_r, raw_g, raw_b = mk(Rc), mk(Gc), mk(Bc)
    # camera JPEG preview
    off = sub1['StripOffsets']; cnt = sub1['StripByteCounts']
    off = off[0] if isinstance(off, (list, tuple)) else off; cnt = cnt[0] if isinstance(cnt, (list, tuple)) else cnt
    jb = bytes(data[off:off + cnt])
    im = Image.open(io.BytesIO(jb)); jw, jh = im.size
    im.draft('RGB', (jw // 2, jh // 2)); im = im.convert('RGB')
    a = np.asarray(im)
    lin = srgb_to_lin(a)
    jy = (0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]).astype(np.float32)
    jY = P.rs(C.orient(jy, orient), W_, H_)
    thumb = cv2.resize(np.ascontiguousarray(np.stack([C.orient(a[..., k], orient) for k in range(3)], axis=-1)), (W_, H_), interpolation=cv2.INTER_AREA)
    # makernote bytes of interest (HC flag etc.) are read by the caller if needed
    info = dict(name=name, path=os.path.basename(path), model=ifd0.get('Model'), software=ifd0.get('Software'),
                date=exif.get('DateTimeOriginal'), t=exif.get('ExposureTime'), N=exif.get('FNumber'), iso=exif.get('ISO'),
                ec=exif.get('ExposureCompensation'), prog=exif.get('ExposureProgram'), metering=exif.get('MeteringMode'),
                expmode=exif.get('ExposureMode'), wbmode=exif.get('WhiteBalance'), flash=exif.get('Flash'),
                focal=exif.get('FocalLength'), baseline_exposure=ifd0.get('BaselineExposure'),
                black=bl.tolist(), white=white, orient=orient, jpeg_size=[jw, jh], raw_size=[W0, H0],
                asn=[float(x) for x in cmod['neutral']], cct=cmod['cct'], wY=[float(x) for x in w],
                cm_source=cmod['which'], jpeg_bytes=cnt)
    np.savez_compressed(os.path.join(outdir, name + '.npz'), meta_json=np.array(json.dumps(info, default=float)),
                        raw_y=raw_y, raw_r=raw_r, raw_g=raw_g, raw_b=raw_b, jpg_y=jY, thumb=thumb,
                        blocks_clip=blocks_clip.astype(np.float16))
    return name, round(time.time() - t0, 1)

if __name__ == '__main__':
    outdir = sys.argv[1]; os.makedirs(outdir, exist_ok=True)
    for p in sys.argv[2:]:
        try:
            print(*one(p, outdir), flush=True)
        except Exception as e:
            import traceback; print('FAIL', p, repr(e), traceback.format_exc()[-300:], flush=True)
