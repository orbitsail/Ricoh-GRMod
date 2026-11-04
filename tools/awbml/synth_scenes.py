"""Scene generator for the AWB table fit: GR IV block stats (R, G, B, D on the 64x62 grid in a 64x64 array, rows 1..62),
plus the exposure term e30 (8.8 EV, before the b51 +1).

Sources
  - day:   the 35 DPReview GR IV scenes as shot (real AWB stats from the makernote).
  - relit: 32 daylight DPReview scenes relit to an indoor light (camera's own Kelvin WB table) at a room brightness.
  - fivek: FiveK raws converted to GR IV stats (fivek_gr/*.npz), when available.
Augmentations
  - lamp:  a bright blob with the light's colour (optionally tinted by a shade), core partly clipped (D reduced),
           optional wall wash (room blocks around it brighter, same chroma).
  - spec:  small specular highlights of the light colour.
"""
import json, math, struct, os, glob
import numpy as np

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 're'))
import griv_env

EXT = str(griv_env.data('grdng', 'ext'))          # $GRIV_DATA/grdng/ext: the DPReview statistics + summary.json
FIVEK = str(griv_env.data('fivek_gr'))
ROWS = {r['id']: r for r in json.load(open(f'{EXT}/summary.json'))}
STAT_F = np.array([0.920, 1.0, 0.974])        # GR IV stats space vs raw space (R, G, B), from the WhitePoint relation

_kb = np.load(f'{EXT}/4024978768.npz')['kelvin'].tobytes()
KT = []
for _i in range(1, 17):
    _code, _, _rg, _bg = struct.unpack('<HHHH', _kb[2 + 8 * _i:10 + 8 * _i])
    KT.append((20000 - (_code & 0x7fff), _rg / 8192, _bg / 8192))
KT = np.array(KT)


def kelvin_neutral(T, gm=1.0):
    """Raw-space neutral (R/G, B/G) of a T kelvin light from the camera's Kelvin WB table; gm > 1 = greener light."""
    m = 1e6 / KT[:, 0]; o = np.argsort(m); mt = 1e6 / T
    rg = float(np.interp(mt, m[o], KT[o, 1])); bg = float(np.interp(mt, m[o], KT[o, 2]))
    return 1 / rg / gm, 1 / bg / gm


def _ev_terms(r):
    Av = 2 * math.log2(r['N']); Tv = -math.log2(r['t']); Sv = math.log2(r['iso'] / 3.125)
    return Av, Tv, Sv


def day_scene(rid):
    r = ROWS[rid]; s = np.load(f'{EXT}/{rid}.npz')['s'].astype(np.int64)
    Av, Tv, Sv = _ev_terms(r)
    return dict(R=s[0].copy(), G=s[1].copy(), B=s[2].copy(), D=s[3].copy(), e30=round((Av + Tv - Sv) * 256),
                Av=Av, Sv=Sv, src='day', id=rid, light=(8192 / r['wp'][0], 8192 / r['wp'][3]))


DAYLIT = [rid for rid in sorted(ROWS) if ROWS[rid]['wp'][0] > 19000 and ROWS[rid]['wp'][3] < 15500]


def clean(sc):
    """Drop garbage blocks (any channel above 0xF6D with tiny G, as seen at the right edge of some frames)."""
    bad = (sc['R'] > 0xFFFF) | (sc['G'] > 0xFFFF) | (sc['B'] > 0xFFFF)
    for k in 'RGBD':
        sc[k][bad] = 0
    return sc


def relit_scene(rid, T, ev_room, gm=1.0, Sv=7.0):
    """Daylight DPReview scene rid relit to a T kelvin light, median block at ev_room on the AWB's EV scale."""
    base = clean(day_scene(rid))
    r0, b0 = base['light']
    r1, b1 = kelvin_neutral(T, gm)
    R = base['R'] * (r1 / r0); B = base['B'] * (b1 / b0); G = base['G'].astype(float)
    mx = max(R[1:63].max(), G[1:63].max(), B[1:63].max())
    k = 3900 / mx if mx > 3900 else 1.0
    sc = dict(R=np.round(R * k).astype(np.int64), G=np.round(G * k).astype(np.int64), B=np.round(B * k).astype(np.int64),
              D=base['D'].copy(), src='relit', id=f'{rid}@{T}K{"g%.2f" % gm if gm != 1 else ""}EV{ev_room}', base=rid,
              light=(r1, b1), T=T, gm=gm, ev_room=ev_room)
    return set_room_ev(sc, ev_room, Sv)


def set_room_ev(sc, ev_room, Sv=7.0):
    v = sc['G'][1:63][sc['D'][1:63] > 0]
    ymed = float(np.median(v)) if v.size else 100.0
    sc['e30'] = round((ev_room - 1 - math.log2(ymed / 16 + 1.5)) * 256)
    sc['Sv'] = Sv; sc['Av'] = 3.0
    sc['Ymed'] = ymed
    return sc


def fivek_scene(path, ev_shift=0.0):
    z = np.load(path, allow_pickle=True)
    s = z['s'].astype(np.int64)
    Av, Tv, Sv = float(z['Av']), float(z['Tv']), float(z['Sv'])
    rn, bn = (float(x) for x in z['neutral_gr'])
    sc = dict(R=s[0].copy(), G=s[1].copy(), B=s[2].copy(), D=s[3].copy(), e30=round((Av + Tv - Sv + ev_shift) * 256),
              Av=Av, Sv=Sv, src='fivek', id=os.path.basename(path)[:-4], light=(rn, bn))
    v = sc['G'][1:63][sc['D'][1:63] > 0]
    sc['Ymed'] = float(np.median(v)) if v.size else 100.0
    return sc


def copy(sc):
    return {k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in sc.items()}


def add_lamp(sc, frac, dEV, tint=1.0, yel=1.0, center=None, wash=0.0, rng=None, tag=''):
    """A lamp blob covering ~frac of the frame, peak dEV above the median block, light colour (x tint: R*tint, B/tint;
    yel: G boost), core partly clipped. wash > 0 brightens the room around it by up to wash EV (same chroma)."""
    rng = rng or np.random.default_rng(0)
    sc = copy(sc)
    rn, bn = sc['light']
    col = STAT_F * np.array([rn * tint, yel, bn / tint]); col = col / col[1]
    H, W = 62, 64
    rad = math.sqrt(frac * H * W / math.pi)
    if center is None:
        center = (rng.uniform(rad, H - rad), rng.uniform(rad, W - rad))
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.hypot(yy + 0.5 - center[0], xx + 0.5 - center[1]) / max(rad, 0.5)
    inside = d <= 1.0
    if wash > 0:
        ring = (d > 1.0) & (d < 3.0)
        f = 2 ** (wash * (1 - (d[ring] - 1) / 2))
        for k in 'RGB':
            a = sc[k][1:63].astype(float); a[ring] = np.minimum(a[ring] * f, 3900); sc[k][1:63] = np.round(a).astype(np.int64)
    ev = dEV * (1 - 0.5 * d[inside] ** 2)                    # peak at centre, -dEV/2 at the edge
    g_true = sc['Ymed'] * 2 ** ev
    unclipped = np.clip(2.2 - g_true / 1800.0, 0.0, 1.0)     # share of pixels below saturation
    g_seen = np.minimum(g_true, 3500.0)
    for k, c in zip('RGB', col):
        a = sc[k][1:63].astype(float)
        a[inside] = np.minimum(g_seen * c, 3940.0)
        sc[k][1:63] = np.round(a).astype(np.int64)
    Dd = sc['D'][1:63].astype(float); Dd[inside] = np.round(1584 * unclipped); sc['D'][1:63] = Dd.astype(np.int64)
    for k in 'RGB':
        a = sc[k][1:63]; a[(sc['D'][1:63] == 0)] = 0
    sc['src'] = sc['src'] + '+lamp'; sc['aug'] = dict(frac=frac, dEV=dEV, tint=tint, yel=yel, wash=wash, tag=tag)
    return sc


def add_specular(sc, n, dEV, rng=None):
    rng = rng or np.random.default_rng(1)
    sc = copy(sc)
    rn, bn = sc['light']; col = STAT_F * np.array([rn, 1.0, bn]); col = col / col[1]
    g = min(sc['Ymed'] * 2 ** dEV, 3500.0)
    ys = rng.integers(1, 63, n); xs = rng.integers(0, 64, n)
    for k, c in zip('RGB', col):
        sc[k][ys, xs] = int(min(g * c, 3940))
    sc['src'] = sc['src'] + '+spec'; sc['aug'] = dict(n=int(n), dEV=dEV)
    return sc


def settings(sc, A):
    """awb_ref settings dict for a scene (b51 = 1, m18 = 1584, flags 0), as verified against the camera."""
    P = [sc['R'].ravel().tolist(), sc['G'].ravel().tolist(), sc['G'].ravel().tolist(), sc['B'].ravel().tolist(),
         sc['D'].ravel().tolist()]
    S = A.make_settings(P, 64, 62, stride=64, y0=1, x0=0, v24=round(sc['Av'] * 256), v2c=round(sc['Sv'] * 256),
                        e30=int(sc['e30']), m18=1584, b51=1)
    S['flags'] = [0] * (64 * 64 + 4)
    return S


def fivek_relit(path, T, ev_room, gm=1.0, Sv=7.0):
    """FiveK scene relit to a T kelvin light: block stats divided by the as-shot neutral (in GR IV raw terms), times the new
    light's neutral; median block at ev_room on the AWB's EV scale."""
    z = np.load(path, allow_pickle=True)
    s = z['s'].astype(np.int64)
    r0, b0 = (float(x) for x in z['neutral_gr'])
    r1, b1 = kelvin_neutral(T, gm)
    R = s[0] * (r1 / r0); B = s[2] * (b1 / b0); G = s[1].astype(float)
    sc = dict(R=R, G=G, B=B, D=s[3].copy())
    v = G[1:63][s[3][1:63] > 0]
    gmed = float(np.median(v)) if v.size else 100.0
    k = 300.0 / max(gmed, 1.0)                                    # put the median block at a typical level
    mx = max(R[1:63].max(), G[1:63].max(), B[1:63].max()) * k
    if mx > 3900:
        k *= 3900 / mx
    for ch in 'RGB':
        sc[ch] = np.round(sc[ch] * k).astype(np.int64)
    sc.update(src='fivek_relit', id=f'{os.path.basename(path)[:-4]}@{T}K', light=(r1, b1), T=T, gm=gm, ev_room=ev_room)
    return set_room_ev(sc, ev_room, Sv)
