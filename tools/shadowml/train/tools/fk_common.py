"""Shared helpers for the FiveK shadow dataset (encode/decode, orientation, ICC, colour math)."""
import struct, math
import numpy as np

# ---- log-Y code (stored as uint16): Y = 2**(code/STEPS - OFFS) ; code 0 means "<= floor"
STEPS = 32.0
OFFS = 20.0

def enc_logy(Y):
    """linear Y -> int16 array holding the 2nd-order finite difference (cols, then rows) of the log2 code
    code = round((log2(Y)+20)*32), floored at 0 (Y<=2**-20)."""
    c = np.clip(np.rint((np.log2(np.maximum(Y, 2.0 ** -OFFS)) + OFFS) * STEPS), 0, 30000).astype(np.int32)
    d = np.diff(c, axis=1, prepend=0)
    d = np.diff(d, axis=0, prepend=0)
    return d.astype(np.int16)

def dec_logy(d):
    c = np.cumsum(np.cumsum(d.astype(np.int32), axis=0), axis=1)
    return np.exp2(c.astype(np.float32) / STEPS - OFFS)

def trunc_f32(a, drop=12):
    """zero the low mantissa bits of float32 (helps deflate; keeps ~11 bits = 0.05%)"""
    u = np.ascontiguousarray(a, np.float32).view(np.uint32) & np.uint32((0xFFFFFFFF << drop) & 0xFFFFFFFF)
    return u.view(np.float32)

# ---- EXIF orientation -> display
def orient(a, o):
    o = int(o)
    if o == 2: return a[:, ::-1]
    if o == 3: return a[::-1, ::-1]
    if o == 4: return a[::-1]
    if o == 5: return a.T
    if o == 6: return a.T[:, ::-1]
    if o == 7: return a.T[::-1, ::-1]
    if o == 8: return a.T[::-1]
    return a

# ---- colour-temperature helpers (as in earlier pipeline)
ILL = {1: 5500, 2: 4200, 3: 2850, 4: 5500, 9: 5500, 10: 6500, 11: 7500, 12: 6430, 13: 5000, 14: 4200, 15: 3450,
       17: 2856, 18: 4874, 19: 6774, 20: 5503, 21: 6504, 22: 7504, 23: 5003, 24: 3200, 16: 2856}

def _planck_uv(T):
    u = (0.860117757 + 1.54118254e-4 * T + 1.28641212e-7 * T * T) / (1 + 8.42420235e-4 * T + 7.08145163e-7 * T * T)
    v = (0.317398726 + 4.22806245e-5 * T + 4.20481691e-8 * T * T) / (1 - 2.89741816e-5 * T + 1.61456053e-7 * T * T)
    return u, v
_Tg = np.concatenate([np.linspace(1500, 3000, 301), np.linspace(3000, 15000, 2401)[1:]])
_uvg = np.array([_planck_uv(t) for t in _Tg])

def xy_to_cct(x, y):
    d = -2 * x + 12 * y + 3
    u, v = 4 * x / d, 6 * y / d
    i = int(np.argmin((_uvg[:, 0] - u) ** 2 + (_uvg[:, 1] - v) ** 2))
    return float(_Tg[i])

def interp_w(T, t1, t2):
    """weight of matrix 1 (spec: linear in 1/T, clamped)"""
    if t1 > t2: raise ValueError
    if T <= t1: return 1.0
    if T >= t2: return 0.0
    return (1 / T - 1 / t2) / (1 / t1 - 1 / t2)

# ---- ICC parsing (just what we need)
def parse_icc(b):
    b = bytes(b)
    out = dict(desc=None, gamma=None, curve_n=None, primaries_Y=None, rXYZ=None, ok=False)
    try:
        n = struct.unpack_from('>I', b, 128)[0]
        tags = {}
        for i in range(n):
            sig, off, sz = struct.unpack_from('>4sII', b, 132 + 12 * i)
            tags[sig.decode('latin1')] = (off, sz)
        if 'desc' in tags:
            off, sz = tags['desc']
            if b[off:off + 4] == b'desc':
                ln = struct.unpack_from('>I', b, off + 8)[0]
                out['desc'] = b[off + 12:off + 12 + max(ln - 1, 0)].decode('latin1')
            elif b[off:off + 4] == b'mluc':
                out['desc'] = b[off + 28:off + sz].decode('utf-16-be', 'ignore')
        Y = []
        for k in ('rXYZ', 'gXYZ', 'bXYZ'):
            off, sz = tags[k]
            X, Yv, Z = [v / 65536.0 for v in struct.unpack_from('>iii', b, off + 8)]
            Y.append(Yv)
            if k == 'rXYZ': out['rXYZ'] = [X, Yv, Z]
        out['primaries_Y'] = Y
        off, sz = tags['rTRC']
        if b[off:off + 4] == b'curv':
            cnt = struct.unpack_from('>I', b, off + 8)[0]
            out['curve_n'] = cnt
            if cnt == 1:
                out['gamma'] = struct.unpack_from('>H', b, off + 12)[0] / 256.0
            elif cnt > 1:
                out['table'] = np.frombuffer(b, '>u2', cnt, off + 12).astype(np.float64) / 65535.0
        out['ok'] = True
    except Exception as e:
        out['err'] = repr(e)
    return out

PROPHOTO_Y = np.array([0.2880402, 0.7118741, 0.0000857])

def romm_decode_lut(n=65536):
    """ROMM RGB (ProPhoto) 16-bit code -> linear, with the linear toe (Et = 1/512)"""
    v = np.arange(n, dtype=np.float64) / (n - 1)
    return np.where(v < 16.0 / 512.0, v / 16.0, v ** 1.8).astype(np.float32)

def gamma_lut(g, n=65536):
    v = np.arange(n, dtype=np.float64) / (n - 1)
    return (v ** g).astype(np.float32)

def table_lut(tab, n=65536):
    x = np.linspace(0, 1, len(tab))
    return np.interp(np.arange(n) / (n - 1), x, tab).astype(np.float32)
