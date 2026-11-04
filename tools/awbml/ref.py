# SPDX-License-Identifier: GPL-2.0-only
"""Bit-exact Python reference of tools/awbml/awbml.c (integer FFCC-style auto white balance) and the table builder.

Everything below is integer arithmetic (numpy int64 / Python int) that mirrors the C code operation by operation.

Data blob layout (little endian, every table 4-byte aligned, built by build_tables(); offsets are in TABLE_ORDER and
are written to core/src/fw/aspect/awbml-data.ts by gen.py):

  LOG    i32[4096]        round(32*65536*ln(x+1))
  BIAS   i16[3][4096]     bias maps B0, B1, B2 in Q12, cell index iu*64+iv
  FSPEC  i32[2][64][33][2]  FFT2 of the two filters, columns kx = 0..32 (the rest follows by conjugate symmetry),
                          [filter][ky][kx][re, im], Q16 (FQ)
  TW     i32[2][64]       cos(2*pi*j/64), sin(2*pi*j/64) in Q30 (FFT twiddles and circular-mean weights)
  ATAN   u32[24]          atan(2^-i)/(2*pi) * 2^32 (CORDIC)
  EXPA   u32[272]         exp(-a/16) in Q24 (a = d >> 8, d the score gap in Q12)
  EXPB   u32[256]         exp(-b/4096) in Q30 (b = d & 255)
  TANH   i16[NTANH]       tanh(2e), e = (e30 - 1024)/1024, at e30 = E30_LO + 16 j, Q12
  GEXP   u32[2][NG]       16 * 8192 * K * exp(j/16 - 1), K = 0.6313*0.920 (R) and 0.3313*0.974 (B)
  RECIP  u32[9]           ceil(2^24 / (2 n)), n = 1..8: round(a / n) = ((2a + n) * RECIP[n]) >> 24
  KF     u32[32]          Kalman filter (variances in log units^2, Q32): [0] R_min, [1] R_max (clamps of the posterior
                          variance R_post), [2] Q (per computing call), [3] R_conf (a frame is confident when its R_eff
                          is below it), [4] gate (a frame is far from the state when (z - mu)^2 > gate * (Sigma + R_eff)),
                          [5] R_base (R_post at knot 0), [6] flags (bit 0: a scene change needs two confident far frames
                          in the same direction, else one; bit 1: the restart value is the mean of the two frames, else
                          the newer one), [7] 0, [8..24] R_eff at the 17 knots R_post = R_base exp(k / 4) (monotone,
                          linear in between: the variance of the frame-to-frame estimate that the filter uses instead of
                          the posterior variance), [25..31] 0
  LN     u32[257]         round(2^24 ln(1 + i/256))
  CAL    i32[10]          calibration: Pd_u, Pd_v, Dd_u, Dd_v, dU, dV (= Pt - Pd), DDu, DDv (= Dt - Dd), INV (u32 =
                          floor(2^48 / (dU^2 + dV^2))), 0   (all Q16 log units)
"""
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SP = Path('/tmp/claude-0/-home-claude/4982966f-5cf0-5c25-b5a9-c2b6bab6cd69/scratchpad')
PARAMS = Path(os.environ.get('AWBML_PARAMS', SP / 'learnawb' / 'ffcc_cube_meta.npz'))
CAL_JSON = HERE / 'cal.json'

N = 64
FQ = 16                      # filter spectrum fraction bits
PSHIFT = 9 + FQ              # (acc + round) >> PSHIFT gives the product spectrum scaled for a /4096 inverse FFT in Q12
E30_LO, E30_HI = -1536, 3328  # exposure clamp (8.8 EV): EV -6 .. 13
NTANH = (E30_HI - E30_LO) // 16 + 2
NEXPA, NG = 272, 81
U0Q, V0Q = 0, -13107          # window corner in Q16 log units
V_OFFSET = 419430             # round(0.2 * 32 * 65536)
KR, KB = 0.6313 * 0.920, 0.3313 * 0.974
# Kalman filter parameters (log units; variances are squares), tunable through the KF table without code changes
KF_RMIN, KF_RMAX, KF_Q, KF_RCONF, KF_GATE = 0.004 ** 2, 0.2 ** 2, 0.01 ** 2, 0.03 ** 2, 9
KF_RBASE, KF_FLAGS, KF_NK, KF_STEP = 0.001, 3, 17, 1 << 22        # knot spacing: ln step 1/4 (Q24 2^22)
KF_WORDS = 32
REFF_JSON = HERE / 'reff.json'     # R_eff knots (Q32 integers), written by calib_r.py --write
LN2Q = 11629080               # round(2^24 ln 2)
VARC = 6640                   # round(2^16 ((64 / 2 pi) / 32)^2): radians^2 of the circular spread -> log units^2
MAGIC = 0x4d425741            # 'AWBM'
MAXCNT = 0xFFFF
PERIOD = 4                    # build value of ctx->period
SCRATCH_BYTES = 4096 * 4 * 2 + 64 * 4 * 2 + 2 * 3 * 64 * 4 + 2 * 66 * 4 + 5 * 4 + 64 + 5 * 4 + 5 * 4   # struct scratch in awbml.c
TABLE_ORDER = ['LOG', 'BIAS', 'FSPEC', 'TW', 'ATAN', 'EXPA', 'EXPB', 'TANH', 'GEXP', 'RECIP', 'CAL', 'KF', 'LN']
DTYPES = dict(LOG='<i4', BIAS='<i2', FSPEC='<i4', TW='<i4', ATAN='<u4', EXPA='<u4', EXPB='<u4', TANH='<i2', GEXP='<u4',
              RECIP='<u4', CAL='<i4', KF='<u4', LN='<u4')


def rnd(x):
    return int(math.floor(x + 0.5))


def bitrev6(i):
    r = 0
    for _ in range(6):
        r = (r << 1) | (i & 1)
        i >>= 1
    return r


BITREV = np.array([bitrev6(i) for i in range(64)])


def default_cal():
    return dict(Pd=[0, 0], Dd=[0, 0], dP=[0, 0], dD=[0, 0], inv=0)


def load_cal():
    if CAL_JSON.exists():
        return json.loads(CAL_JSON.read_text())['cal']
    return default_cal()


def build_tables(cal=None, params=None):
    """Returns (tables: dict name -> numpy array (storage dtype), blob bytes, offsets dict)."""
    cal = cal if cal is not None else load_cal()
    z = np.load(params or PARAMS)
    Fp, Bp = z['F'], z['B']
    t = {}
    t['LOG'] = np.array([rnd(32 * 65536 * math.log(x + 1)) for x in range(4096)])
    t['BIAS'] = np.array([[[rnd(4096 * v) for v in row] for row in b] for b in Bp]).reshape(3, 4096)
    assert abs(t['BIAS']).max() < 32768
    fs = np.zeros((2, 64, 33, 2), dtype=np.int64)
    for k in range(2):
        fh = np.fft.fft2(Fp[k])[:, :33]
        fs[k, :, :, 0] = np.floor(fh.real * (1 << FQ) + 0.5)
        fs[k, :, :, 1] = np.floor(fh.imag * (1 << FQ) + 0.5)
    assert abs(fs).max() < 2 ** 31
    t['FSPEC'] = fs
    ang = 2 * math.pi * np.arange(64) / 64
    t['TW'] = np.stack([np.floor(np.cos(ang) * 2 ** 30 + 0.5), np.floor(np.sin(ang) * 2 ** 30 + 0.5)]).astype(np.int64)
    t['ATAN'] = np.array([rnd(math.atan(2.0 ** -i) / (2 * math.pi) * 2 ** 32) for i in range(24)])
    t['EXPA'] = np.array([rnd(2 ** 24 * math.exp(-a / 16)) for a in range(NEXPA)])
    t['EXPB'] = np.array([rnd(2 ** 30 * math.exp(-b / 4096)) for b in range(256)])
    t['TANH'] = np.array([rnd(4096 * math.tanh(2 * ((E30_LO + 16 * j) - 1024) / 1024)) for j in range(NTANH)])
    t['GEXP'] = np.array([[rnd(16 * 8192 * K * math.exp(j / 16 - 1)) for j in range(NG)] for K in (KR, KB)])
    t['RECIP'] = np.array([0] + [-((-(1 << 24)) // (2 * n)) for n in range(1, 9)])
    for n in range(1, 9):                       # the reciprocal division is exact over the whole range used
        a = np.arange(0, 2 * 8 * 0xF6D + 1)
        assert np.array_equal(((2 * a + n) * int(t['RECIP'][n])) >> 24, (2 * a + n) // (2 * n))
    c = cal
    knots = json.loads(REFF_JSON.read_text())['knots'] if REFF_JSON.exists() else [rnd(KF_RMAX * 2 ** 32)] * KF_NK
    assert len(knots) == KF_NK and all(a <= b for a, b in zip(knots, knots[1:]))
    t['KF'] = np.array([rnd(KF_RMIN * 2 ** 32), rnd(KF_RMAX * 2 ** 32), rnd(KF_Q * 2 ** 32), rnd(KF_RCONF * 2 ** 32), KF_GATE,
                        rnd(KF_RBASE * 2 ** 32), KF_FLAGS, 0] + list(knots) + [0] * (KF_WORDS - 8 - KF_NK))
    t['LN'] = np.array([rnd(2 ** 24 * math.log(1 + i / 256)) for i in range(257)])
    t['CAL'] = np.array(list(c['Pd']) + list(c['Dd']) + list(c['dP']) + list(c['dD']) + [c['inv'], 0])
    blob = bytearray()
    offs = {}
    for name in TABLE_ORDER:
        while len(blob) % 4:
            blob.append(0)
        offs[name] = len(blob)
        arr = t[name]
        blob += arr.astype(DTYPES[name]).tobytes()
    while len(blob) % 4:
        blob.append(0)
    # work arrays for the reference (int64)
    tab = {k: v.astype(np.int64) for k, v in t.items()}
    return tab, bytes(blob), offs


def make_cal(Pd, Pt, Dd, Dt):
    """Pd, Pt: mean estimates (u, v) in Q16 ints for daylight / warm low light; Dd, Dt: mean (truth - estimate), Q16 ints."""
    dP = [Pt[0] - Pd[0], Pt[1] - Pd[1]]
    den = dP[0] ** 2 + dP[1] ** 2
    inv = (1 << 48) // den
    assert 0 < inv < 2 ** 32
    return dict(Pd=list(Pd), Dd=list(Dd), dP=dP, dD=[Dt[0] - Dd[0], Dt[1] - Dd[1]], inv=inv)


# ------------------------------------------------------------------------------------------------ pipeline pieces
def grid_arrays(R, Gr, Gb, B, cnt, x0, y0, w, h, stride):
    idx = (y0 + np.arange(h))[:, None] * stride + x0 + np.arange(w)[None, :]
    r = np.asarray(R)[idx].astype(np.int64)
    gr = np.asarray(Gr)[idx].astype(np.int64)
    gb = np.asarray(Gb)[idx].astype(np.int64)
    b = np.asarray(B)[idx].astype(np.int64)
    c = np.asarray(cnt)[idx].astype(np.int64)
    g = (gr >> 1) + (gb >> 1) + ((gr | gb) & 1)
    return r, g, b, c


def histograms(T, r, g, b, c):
    """Returns (h1, h2 raw u32-style int64 (4096,), tot1, tot2, valid-count sum)."""
    h, w = r.shape
    mn = np.minimum(np.minimum(r, g), b)
    mx = np.maximum(np.maximum(r, g), b)
    ok = (c >= 317) & (c <= MAXCNT) & (mn >= 4) & (mx <= 0xF6D)
    LOG = T['LOG']
    csum = int(c[ok].sum())
    lg = lambda x: LOG[np.minimum(x, 4095)]       # invalid blocks are masked out below; only keep the lookup in range
    iu = ((lg(g) - lg(r)) >> 16) & 63
    iv = ((lg(g) - lg(b) + V_OFFSET) >> 16) & 63
    h1 = np.bincount((iu * 64 + iv)[ok], weights=c[ok].astype(np.float64), minlength=4096).astype(np.int64)
    # local contrast
    vp = np.zeros((h + 2, w + 2), np.int64); vp[1:-1, 1:-1] = ok
    pl = []
    for ch in (r, g, b):
        p = np.zeros((h + 2, w + 2), np.int64); p[1:-1, 1:-1] = np.where(ok, ch, 0); pl.append(p)
    cn = np.zeros((h, w), np.int64)
    sm = [np.zeros((h, w), np.int64) for _ in range(3)]
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            sl = (slice(1 + dy, 1 + dy + h), slice(1 + dx, 1 + dx + w))
            cn += vp[sl]
            for q in range(3):
                sm[q] += pl[q][sl]
    sel = ok & (cn > 0)
    rc = T['RECIP'][cn]
    e = []
    for q, ch in enumerate((r, g, b)):
        num = np.abs(cn * np.where(ok, ch, 0) - sm[q])
        e.append(((2 * num + cn) * rc) >> 24)
    wt = e[0] + e[1] + e[2]
    iu2 = ((lg(e[1]) - lg(e[0])) >> 16) & 63
    iv2 = ((lg(e[1]) - lg(e[2]) + V_OFFSET) >> 16) & 63
    h2 = np.bincount((iu2 * 64 + iv2)[sel], weights=wt[sel].astype(np.float64), minlength=4096).astype(np.int64)
    return h1, h2, int(h1.sum()), int(h2.sum()), csum


def normalise(hist, tot):
    if tot == 0:
        return np.zeros(4096, np.int64)
    q = (1 << 50) // tot
    return (hist * q + (1 << 29)) >> 30


def fft_last(re, im, TW, inverse):
    re = re[..., BITREV]; im = im[..., BITREV]
    cosT, sinT = TW[0], TW[1]
    for ln in (2, 4, 8, 16, 32, 64):
        half = ln // 2
        j = np.arange(half) * (64 // ln)
        wr = cosT[j]; wi = sinT[j] if inverse else -sinT[j]
        shp = re.shape[:-1] + (64 // ln, ln)
        r = re.reshape(shp); i_ = im.reshape(shp)
        ar, ai, br, bi = r[..., :half], i_[..., :half], r[..., half:], i_[..., half:]
        tr = (wr * br - wi * bi + (1 << 29)) >> 30
        ti = (wr * bi + wi * br + (1 << 29)) >> 30
        if inverse:
            nr = np.concatenate([(ar + tr + 1) >> 1, (ar - tr + 1) >> 1], -1)
            ni = np.concatenate([(ai + ti + 1) >> 1, (ai - ti + 1) >> 1], -1)
        else:
            nr = np.concatenate([ar + tr, ar - tr], -1)
            ni = np.concatenate([ai + ti, ai - ti], -1)
        re = nr.reshape(re.shape); im = ni.reshape(im.shape)
    return re, im


def fft2d(re, im, TW, inverse):
    """re, im: (64, 64) int64; rows (along the last axis) first, then columns."""
    re, im = fft_last(re, im, TW, inverse)
    re, im = fft_last(re.T, im.T, TW, inverse)
    return re.T.copy(), im.T.copy()


_ky = []
_kx = []
_both = []
for kx in range(33):
    both = kx in (0, 32)
    for ky in range(33 if both else 64):
        _ky.append(ky); _kx.append(kx); _both.append(both)
KY = np.array(_ky); KX = np.array(_kx); BOTH = np.array(_both)
K1 = KY * 64 + KX
K2 = ((64 - KY) & 63) * 64 + ((64 - KX) & 63)


def conv_scores(T, hn1, hn2):
    """Circular convolution of both normalised histograms with their filters, Q12, (4096,) int64 (indexed iu*64+iv).

    Forward FFT of Z = H1 + i H2; products for the columns kx = 0..32 (the other columns follow by conjugate symmetry);
    inverse FFT of those columns, the missing ones filled by conjugation; the real output rows y and y + 32 share one
    complex row FFT (row y: real part, row y + 32: imaginary part)."""
    re, im = fft2d(hn1.reshape(64, 64).copy(), hn2.reshape(64, 64).copy(), T['TW'], False)
    zr, zi = re.ravel(), im.ravel()
    ar, ai, br, bi = zr[K1], zi[K1], zr[K2], zi[K2]
    x1r, x1i = ar + br, ai - bi
    x2r, x2i = ai + bi, -(ar - br)
    fs = T['FSPEC']
    f1 = fs[0, KY, KX]; f2 = fs[1, KY, KX]
    accr = x1r * f1[:, 0] - x1i * f1[:, 1] + x2r * f2[:, 0] - x2i * f2[:, 1]
    acci = x1r * f1[:, 1] + x1i * f1[:, 0] + x2r * f2[:, 1] + x2i * f2[:, 0]
    pr = (accr + (1 << (PSHIFT - 1))) >> PSHIFT
    pi = (acci + (1 << (PSHIFT - 1))) >> PSHIFT
    orr = np.zeros(4096, np.int64); oi = np.zeros(4096, np.int64)
    orr[K1] = pr; oi[K1] = pi
    orr[K2[BOTH]] = pr[BOTH]; oi[K2[BOTH]] = -pi[BOTH]
    pr_, pi_ = orr.reshape(64, 64), oi.reshape(64, 64)
    # columns 0..32 along ky
    cr, ci = fft_last(pr_[:, :33].T.copy(), pi_[:, :33].T.copy(), T['TW'], True)      # (33, 64): [kx][y]
    cr, ci = cr.T, ci.T                                                               # (64 y, 33 kx)
    xs = np.arange(64)
    src = np.where(xs <= 32, xs, 64 - xs)
    sgn = np.where(xs <= 32, 1, -1)
    ar_, ai_ = cr[:, src], ci[:, src] * sgn                                           # full Hermitian rows
    zr_ = ar_[:32] - ai_[32:]
    zi_ = ai_[:32] + ar_[32:]
    o_r, o_i = fft_last(zr_, zi_, T['TW'], True)
    return np.concatenate([o_r.ravel(), o_i.ravel()])


def tanh_q12(T, e30c):
    j = (e30c - E30_LO) >> 4
    f = (e30c - E30_LO) & 15
    tt = T['TANH']
    return int(tt[j]) + ((((int(tt[j + 1]) - int(tt[j])) * f) + 8) >> 4)


def atan2_turn(x, y, T):
    """CORDIC; x, y Python ints. Returns the angle as a u32 fraction of a full turn."""
    z = 0
    if x < 0:
        x, y = -x, -y
        z = 1 << 31
    while max(abs(x), abs(y)) >= (1 << 29):
        x >>= 1; y >>= 1
    AT = T['ATAN']
    for i in range(24):
        if y >= 0:
            x, y = x + (y >> i), y - (x >> i)
            z += int(AT[i])
        else:
            x, y = x - (y >> i), y + (x >> i)
            z -= int(AT[i])
    return z & 0xFFFFFFFF


def lnq(T, v):
    """ln(v) in Q24 for an integer v >= 1 (as the C code: v reduced to 32 bits, 8-bit table with linear interpolation)."""
    sh = 0
    while v >> 32:
        v >>= 1; sh += 1
    n = v.bit_length() - 1
    m = (v << (31 - n)) & 0xFFFFFFFF
    f, rest = (m >> 23) & 255, (m >> 15) & 255
    ln = T['LN']
    return (n + sh) * LN2Q + int(ln[f]) + (((int(ln[f + 1]) - int(ln[f])) * rest) >> 8)


def axis_variance(T, M, sx, sy):
    """Variance (log units^2, Q32) of one axis from the resultant (sx, sy) of its marginal and the marginal's mass M:
    sigma^2 = -2 ln(rho) radians^2, rho = |resultant| / (M 2^30), in log units, clamped to [R_min, R_max]."""
    kf = [int(x) for x in T['KF']]
    s = 0
    xn, yn = sx, sy
    while max(abs(xn), abs(yn)) >= (1 << 29):
        xn >>= 1; yn >>= 1; s += 1
    s2 = xn * xn + yn * yn
    if s2 == 0 or M == 0:
        return kf[1]
    d = lnq(T, M * M) + 60 * LN2Q - lnq(T, s2) - 2 * s * LN2Q
    r = ((d * VARC) >> 8) if d > 0 else 0
    return min(max(r, kf[0]), kf[1])


def estimate_uv(T, R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, want_debug=False, want_var=False):
    """Uncalibrated estimate (u, v) in Q16 log units, or None (fallback); with want_var (u, v, R_u, R_v)."""
    r, g, b, c = grid_arrays(R, Gr, Gb, B, cnt, x0, y0, w, h, stride)
    h1, h2, t1, t2, csum = histograms(T, r, g, b, c)
    if csum * 20 < w * h * 1584:
        return None
    hn1 = normalise(h1, t1); hn2 = normalise(h2, t2)
    sc = conv_scores(T, hn1, hn2)
    if v24 == -0x880:
        e = t = 0
    else:
        e30c = min(max(e30, E30_LO), E30_HI)
        e = (e30c - 1024) * 4
        t = tanh_q12(T, e30c)
    bm = T['BIAS']
    s = sc + bm[0] + ((e * bm[1]) >> 12) + ((t * bm[2]) >> 12)
    d = s.max() - s
    a = d >> 8; bb = d & 255
    wgt = np.where(a < NEXPA, (T['EXPA'][np.minimum(a, NEXPA - 1)] * T['EXPB'][bb] + (1 << 29)) >> 30, 0)
    wm = wgt.reshape(64, 64)
    pu = wm.sum(1); pv = wm.sum(0)
    TW = T['TW']
    out = []
    var = []
    for p in (pu, pv):
        q = p >> 6
        sx = int((q * TW[0]).sum()); sy = int((q * TW[1]).sum())
        z = atan2_turn(sx, sy, T)
        out.append(z >> 10)
        var.append(axis_variance(T, int(q.sum()), sx, sy))
    u = U0Q + ((out[0] + 32768 + 16) >> 5)
    v = V0Q + ((out[1] + 32768 + 16) >> 5)
    if want_debug:
        return (u, v), dict(hn1=hn1, hn2=hn2, sc=s, wgt=wgt, var=var)
    if want_var:
        return u, v, var[0], var[1]
    return u, v


def calibrate(T, u, v):
    c = [int(x) for x in T['CAL']]
    pdu, pdv, ddu, ddv, du, dv, dduu, ddvv, inv, _ = c
    dot = (u - pdu) * du + (v - pdv) * dv
    den = du * du + dv * dv
    if dot <= 0:
        s = 0
    elif dot >= den:
        s = 65536
    else:
        s = (dot * inv + (1 << 31)) >> 32
    return u + ddu + ((s * dduu + 32768) >> 16), v + ddv + ((s * ddvv + 32768) >> 16)


def exp_gain(T, which, x):
    xo = min(max(x + 65536, 0), 81 * 4096 - 1)
    idx = xo >> 12
    r = xo & 4095
    p = 65536 + r + ((r * r) >> 17) + ((((r * r) >> 16) * r >> 16) * 10923 >> 16)
    g = (int(T['GEXP'][which][idx]) * p + (1 << 19)) >> 20
    return min(max(g, 1024), 65535)


def reff(T, rp):
    """R_eff (Q32) from the posterior variance rp (Q32): piecewise linear over ln(rp / R_base) in steps of 1/4 (as the C code)."""
    kf = [int(x) for x in T['KF']]
    x = min(max(lnq(T, rp) - lnq(T, kf[5]), 0), 16 * KF_STEP - 1)
    i, f = x >> 22, x & (KF_STEP - 1)
    return kf[8 + i] + (((kf[9 + i] - kf[8 + i]) * f) >> 22)


def kalman(T, state, z, r):
    """One computing call's observation z = (u', v') (Q16) with variances r = R_eff (Q32). state: None or dict(mu, sg, cand,
    cz, cs); returns the new state (the filter output is its mu). Mirrors kalman() in awbml.c.

    A confident frame (both R_eff < R_conf) that is far from the state (d^2 > gate (Sigma + R) on an axis) restarts the filter
    (flags bit 0 clear), or, with bit 0 set, is held back as a candidate (the state only grows by Q) until the next frame is
    also confident and far in the same direction on an axis; then the filter restarts at that frame (bit 1 clear) or at the mean
    of the two (bit 1 set), with Sigma = R_eff. Any other frame drops the candidate and takes the ordinary update."""
    kf = [int(x) for x in T['KF']]
    if state is None:
        return dict(mu=list(z), sg=list(r), cand=0, cz=[0, 0], cs=[0, 0])
    mu, sg = list(state['mu']), [x + kf[2] for x in state['sg']]
    cand, cz, cs = state['cand'], list(state['cz']), list(state['cs'])
    if r[0] < kf[3] and r[1] < kf[3]:
        sign = [0, 0]
        for a in range(2):
            d = z[a] - mu[a]
            if d * d > kf[4] * (sg[a] + r[a]):
                sign[a] = 1 if d > 0 else -1
        if sign[0] or sign[1]:
            if not kf[6] & 1 or (cand and (cs[0] * sign[0] > 0 or cs[1] * sign[1] > 0)):
                m = [(cz[a] + z[a]) >> 1 for a in range(2)] if kf[6] & 2 and kf[6] & 1 else list(z)
                return dict(mu=m, sg=list(r), cand=0, cz=[0, 0], cs=[0, 0], reset=1)
            return dict(mu=mu, sg=sg, cand=1, cz=list(z), cs=sign, held=1)
    for a in range(2):
        den = sg[a] + r[a]
        k = (sg[a] << 16) // den                      # the C code: 16 shift-subtract steps
        mu[a] += (k * (z[a] - mu[a]) + 32768) >> 16
        sg[a] -= (k * sg[a] + 32768) >> 16
    return dict(mu=mu, sg=sg, cand=0, cz=[0, 0], cs=[0, 0])


def observe(T, R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, mode):
    """(u', v', R_u, R_v): the calibrated estimate and its variances, or None (the camera's own result stays)."""
    if mode != 0 or not (1 <= w <= 64 and 1 <= h <= 64):
        return None
    if (y0 + h - 1) * stride + x0 + w > (1 << 24):
        return None
    o = estimate_uv(T, R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, want_var=True)
    if o is None:
        return None
    u, v = calibrate(T, o[0], o[1])
    return u, v, o[2], o[3]


FW_CFG = dict(guard=0x55379608, eslot=0x55379610, lo=0x55000000, hi=0x80000000, lo2=0x40000000, hi2=0x53000000)
VTABLE = 0x53F8EDE8


def fl8(b, base):
    """trunc(fl32(base + 8 x)) for the float bits b as the camera's vmla / vnmls + vcvt.s32.f32 (see awbml.c fl8), or None (NaN, inf, |x| >= 16, sum <= 0)."""
    e, m = (b >> 23) & 255, b & 0x7FFFFF
    if e == 255 or e > 130:
        return None
    if e:
        m |= 0x800000
    else:
        e = 1
    st = 0
    if e >= 123:
        M = m << (e - 123)
    elif e > 100:
        r_ = 123 - e
        M, st = m >> r_, int(m & ((1 << r_) - 1) != 0)
    else:
        M, st = 0, int(m != 0)
    vv = base * 0x1000000 + (-M - st if b >> 31 else M)
    if vv <= 0:
        return None
    v = vv
    L = v.bit_length()
    if L > 24:
        r_ = L - 24
        rem, half = v & ((1 << r_) - 1), 1 << (r_ - 1)
        v >>= r_
        if rem > half or (rem == half and (st or v & 1)):
            v += 1
        v <<= r_
    return v >> 24


def lv_exposure(rd32, s70=2, cfg=None):
    """The live view's exposure from the property store as awbml.c lv_exposure reads it (same order of reads; rd32(addr) is the memory):
    (v24, e30), or None when it is not usable (the exposure is then treated as missing)."""
    c = cfg or FW_CFG
    lo, hi, lo2, hi2 = c['lo'], c['hi'], c['lo2'], c['hi2']
    if s70 == 4 or not rd32(c['guard']) & 1:
        return None
    E = rd32(c['eslot'])
    if not E or E & 3 or E < lo or E >= hi - 0x520 or rd32(E) != VTABLE:
        return None
    X = rd32(E + 0x518)
    if not X or X & 3 or X < lo or X >= hi - 0x10:
        return None
    ok = lambda p: lo <= p <= hi - 0x1090 or lo2 <= p <= hi2 - 0x1090
    for t in range(2):
        a, b = rd32(X), rd32(X + 4)
        if not a or not b or a & 3 or b & 3 or (a - b) & 0xFFFFFFFF != 0x1090 and (b - a) & 0xFFFFFFFF != 0x1090 or not ok(a) or not ok(b):
            return None
        w = [rd32(a + 0x4D8 + 4 * k) for k in range(3)]
        a2, b2 = rd32(X), rd32(X + 4)
        w2 = [rd32(a + 0x4D8 + 4 * k) for k in range(3)]
        if (a2, b2, w2) == (a, b, w):
            break
    else:
        return None
    if not any(w):
        return None
    na, nt, ns = fl8(w[1], 68), fl8(w[0], 68), fl8(w[2], -8)
    if None in (na, nt, ns):
        return None
    na, nt, ns = na - 68, nt - 68, ns + 8
    if not (8 <= na <= 80 and -40 <= nt <= 120 and 24 <= ns <= 120):
        return None
    e = 32 * (na + nt - ns)
    return (32 * na, e) if -1800 <= e <= 3100 else None


def scale_gain(g, s):
    """At capture the R and B gain words S+0x68 / S+0x6E carry the camera's per-unit factor: (g * s + 0x1000) >> 13, at most 0xFFFF
    (a zero word is left alone), as the C code."""
    return g if not s else min((g * s + 0x1000) >> 13, 0xFFFF)


def awbml_ref(T, R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, mode, calibrated=True, still_s=None):
    """still_s: (u16 S+0x68, u16 S+0x6E) of a still call (the gains are scaled by them), None for live view and single frames."""
    """-> (g0, g3) or None (the camera's own result stays). Arrays: flat, indexable at (y0+y)*stride+x0+x."""
    if mode != 0 or not (1 <= w <= 64 and 1 <= h <= 64):
        return None
    if (y0 + h - 1) * stride + x0 + w > (1 << 24):
        return None
    uv = estimate_uv(T, R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30)
    if uv is None:
        return None
    u, v = calibrate(T, *uv) if calibrated else uv
    g = exp_gain(T, 0, u), exp_gain(T, 1, v)
    if still_s is not None:
        g = scale_gain(g[0], still_s[0]), scale_gain(g[1], still_s[1])
    return g


def file_sha256(b):
    return hashlib.sha256(b).hexdigest()


def const_header():
    """Text of awbml_const.h: the constants awbml.c shares with this reference."""
    return (
        '/* GENERATED by tools/awbml/gen.py from tools/awbml/ref.py -- do not edit. */\n'
        f'#define AWBML_MAGIC 0x{MAGIC:08x}u /* \'AWBM\' */\n'
        f'#define AWBML_SCRATCH_BYTES {SCRATCH_BYTES}u\n'
        f'#define AWBML_MAXCNT {MAXCNT}u\n'
        f'#define AWBML_E30_LO ({E30_LO})\n'
        f'#define AWBML_E30_HI ({E30_HI})\n'
        f'#define AWBML_NEXPA {NEXPA}u\n'
        f'#define AWBML_NG {NG}u\n'
        f'#define AWBML_U0Q ({U0Q})\n'
        f'#define AWBML_V0Q ({V0Q})\n'
        f'#define AWBML_V_OFFSET {V_OFFSET}\n'
        f'#define AWBML_PSHIFT {PSHIFT}\n'
        f'#define AWBML_LN2Q {LN2Q}\n'
        f'#define AWBML_VARC {VARC}u\n')


class AwbmlSeq:
    """The throttled entry as a state machine (the scratch buffer's state): one object per camera session.

    call() == the C entry: a full computation on the first call and then on every `period`-th call that is plain Auto with a
    usable grid; the calls between repeat the cached (g0, g3) or, if the computation fell back, return None; a call with
    mode != 0 forgets the cache (if the buffer exists). alloc_ok=False models a failing operator new."""

    counts = dict.fromkeys(['observations', 'first', 'scene resets', 'candidate frames held', 'R_post clamped at R_max (either axis)', 'confident (both axes R_eff below R_conf)'], 0)

    def __init__(self, T, period=PERIOD, lv_exp=2, lv_scale=1):
        self.T, self.period, self.lv_exp, self.lv_scale = T, period, lv_exp, lv_scale
        self.buf = False
        self.valid = False
        self.left = 0
        self.fb = True
        self.g = None
        self.allocs = 0
        self.state = None

    def out(self, s):
        """The cached model-unit gains as a live view call outputs them: scaled by the call's S words when lv_scale is on."""
        return (scale_gain(self.g[0], s[0]), scale_gain(self.g[1], s[1])) if self.lv_scale and s is not None else self.g

    def call(self, R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, mode, alloc_ok=True, still=False, still_s=None, lv_ev=None):
        """still: the estimate's third argument is non-zero: a fresh single-frame estimate that touches no live view state
        (it may create the buffer, as the C code does)."""
        if mode != 0:
            if self.buf and not still:
                self.valid = False
                self.state = None
            return None
        if not (1 <= w <= 64 and 1 <= h <= 64) or (y0 + h - 1) * stride + x0 + w > (1 << 24):
            return None
        if not self.buf:
            self.allocs += 1
            if not alloc_ok:
                return None
            self.buf, self.valid, self.state = True, False, None
        if still:
            return awbml_ref(self.T, R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, mode, still_s=still_s)
        if self.valid and self.left:
            self.left -= 1
            return None if self.fb else self.out(still_s)
        self.valid, self.fb, self.left = True, True, self.period - 1 if self.period > 1 else 0
        if self.lv_exp == 2 and lv_ev is not None:
            v24, e30 = lv_ev                          # live view: the exposure from the record (lv_exposure())
        elif self.lv_exp:
            v24 = -0x880                              # live view: the exposure data is treated as missing
        o = observe(self.T, R, Gr, Gb, B, cnt, x0, y0, w, h, stride, v24, e30, mode)
        if o is None:
            return None
        prev = self.state
        rr = [reff(self.T, o[2]), reff(self.T, o[3])]
        self.state = kalman(self.T, self.state, o[:2], rr)
        AwbmlSeq.counts['observations'] += 1
        AwbmlSeq.counts['first'] += prev is None
        AwbmlSeq.counts['scene resets'] += bool(self.state.get('reset'))
        AwbmlSeq.counts['candidate frames held'] += bool(self.state.get('held'))
        AwbmlSeq.counts['R_post clamped at R_max (either axis)'] += max(o[2:]) >= int(self.T['KF'][1])
        AwbmlSeq.counts['confident (both axes R_eff below R_conf)'] += max(rr) < int(self.T['KF'][3])
        self.fb, self.g = False, (exp_gain(self.T, 0, self.state['mu'][0]), exp_gain(self.T, 1, self.state['mu'][1]))
        return self.out(still_s)
