"""Python reference of the RICOH GR IV (fw 1.11) auto white balance front end + estimators.

Everything here was transcribed from the ARM32 code of RTOS.bin (see awb_spec.md); awb_emu_check.py runs the real
firmware functions in unicorn and compares.  Integer semantics follow the ARM code (32 bit wrap, asr/lsr, trunc division).
"""
import struct, os

# The stock RTOS.bin (decoded RTOS section of the official fw 1.11; never committed) is found through $GRIV_RTOS.
RTOS_PATH = os.environ.get('GRIV_RTOS') or os.environ.get('RTOS_BIN') or 'RTOS.bin'
BASE = 0x53000000
RAM_SRC, RAM_DST, RAM_LEN = 0x5437B640, 0x55000000, 0x57480
_RT = None

def rt():
    global _RT
    if _RT is None:
        _RT = open(RTOS_PATH, 'rb').read()
    return _RT

def off(a):
    if RAM_DST <= a < RAM_DST + RAM_LEN:
        return RAM_SRC - BASE + (a - RAM_DST)
    if BASE <= a < BASE + len(rt()):
        return a - BASE
    raise ValueError(hex(a))

def rd(a, n): o = off(a); return rt()[o:o + n]
def rd32(a): return struct.unpack('<I', rd(a, 4))[0]
def rdarr(a, n, fmt='<I'): return list(struct.unpack('<%d%s' % (n, fmt[-1]), rd(a, n * struct.calcsize(fmt))))

def u32(x): return x & 0xffffffff
def s32(x):
    x &= 0xffffffff
    return x - (1 << 32) if x & 0x80000000 else x
def u16(x): return x & 0xffff
def sdiv(a, b):
    """ARM sdiv via helper 0x53153864 (b == 0 saturates)."""
    a = s32(a); b = s32(b)
    if b == 0:
        return 0x7fffffff if a > 0 else (-0x80000000 if a < 0 else 0)
    q = abs(a) // abs(b)
    return s32(q if (a < 0) == (b < 0) else -q)
def udiv(a, b):
    a = u32(a); b = u32(b)
    if b == 0:
        return 0xffffffff if a else 0
    return a // b

# ---------------------------------------------------------------- addresses
ADDR = dict(
    FRAME0=0x6A70, FRAME_STRIDE=0x218, NFRAMES=33,
    MASK_TAB=0x541DB508,          # 512 x 128 u32 frame-membership bit masks (Auto)
    BITS_TAB=0x5421B548,          # 1,2,4,...  (table walked by Auto slot 5)
    ATAN_TAB=0x5421B6B0, COS_TAB=0x5421B734,
    MATRIX=0x541DB4E4,
    LOG_TAB=0x53FD8E08,
    CAL_SINGLETON=0x553A130C,     # 5393cd00() returns this
)
TUNING = {   # mode -> (T2, T3 kind, T4, T5) table addresses (24 rows x 33 columns; T3 is [col*24+row])
    0: (0x55053E04, 0x55053AEC, 0x55054434, 0x5505411C),   # Standard
    1: (0x55053E04, 0x55053AEC, 0x55055094, 0x550553AC),   # Atmosphere (warmth)
    2: (0x55054A64, 0x55053AEC, 0x5505474C, 0x55054D7C),   # White
    3: (0x550556C4, 0x55053AEC, 0x550559DC, 0x55055CF4),   # CTE
}

def tuning_column(mode, col):
    """The 24 x (T2, T4, T5, T3) bytes copied into a frame by 0x5393C39C (frame +0x188 + 4*r + {0,1,2,3})."""
    t2, t3, t4, t5 = (rd(a, 24 * 33) for a in TUNING[mode])
    return [(t2[r * 33 + col], t4[r * 33 + col], t5[r * 33 + col], t3[col * 24 + r]) for r in range(24)]

# ---------------------------------------------------------------- frame ("light source detector")
class Frame:
    def __init__(self, idx=0, mode=0):
        self.idx = idx
        self.f = [[0, 0, 0, 0] for _ in range(24)]      # per row: f8, fC, f10, f14 (u32 each)
        self.h = [0] * 24
        self.set_mode(mode)
    def set_mode(self, mode):
        self.T = tuning_column(mode, self.idx)          # per row: T2, T4, T5, T3(kind)
    def clear(self):
        self.f = [[0, 0, 0, 0] for _ in range(24)]

    # --- 0x5393C4D4 -----------------------------------------------------------------------------
    def acc(self, pos, a, b, c, d):
        pos = s32(pos)
        fl = pos >> 8
        ce = (pos + 255) >> 8
        lo = min(max(fl, -5), 18) + 5
        hi = min(max(ce, -5), 18) + 5
        w1 = u16((ce << 8) - pos)
        w2 = u16(0x100 - w1)
        for row, w in ((lo, w1), (hi, w2)):
            r = self.f[row]
            r[0] = u32(r[0] + (s32(a * w + 0x200) >> 10))
            r[1] = u32(r[1] + (s32(b * w + 0x200) >> 10))
            r[2] = u32(r[2] + (s32(c * w + 0x200) >> 10))
            r[3] = u32(r[3] + (u32(d * w + 0x80) >> 8))

    # --- vtable slots 0x5393BA34 .. 0x5393BBBC ------------------------------------------------
    def sum_f(self, k): return u32(sum(r[k] for r in self.f))                       # slots +8..+0x14
    def sum_Y(self):                                                                # +0x18
        return u32(sum(s32(s32(r[0]) * self.h[i] + 0x80) >> 8 for i, r in enumerate(self.f)))
    def sum_c1(self):                                                               # +0x1C
        t = 0
        for i, r in enumerate(self.f):
            x = s32(s32((self.T[i][1] - 128) * self.h[i] + 0x40) >> 7)
            t += s32(s32(r[1]) * x + 0x80) >> 8
        return s32(t)
    def sum_c2(self):                                                               # +0x20
        t = 0
        for i, r in enumerate(self.f):
            x = s32(s32((self.T[i][2] - 128) * self.h[i] + 0x40) >> 7)
            t += s32(s32(r[2]) * x + 0x80) >> 8
        return s32(t)
    def sum_w(self):                                                                # +0x24
        t = 0
        for i, r in enumerate(self.f):
            t += (u32(r[3] * self.T[i][0]) * 0x80808081 >> 32) >> 7
        return u32(t)
    def row_weight(self, row):                                                      # 0x5393C354
        return (u32(self.f[row][3] * self.T[row][0] + 0x80) * 0x80808081 >> 32) >> 7

# ---------------------------------------------------------------- the engine object
class AwbObject:
    """State of CWhiteBalanceAuto / CWhiteBalanceCte relevant for the still-image estimate."""
    def __init__(self, kind='auto', mode=None):
        self.kind = kind
        self.mode = (3 if kind == 'cte' else 0) if mode is None else mode
        self.frames = [Frame(i, self.mode) for i in range(33)]
        self.m = [0x2000] * 4                       # obj+0xC,+0xE,+0x10,+0x12
        self.gains = [0x2000] * 4                   # obj+4 (R), +6, +8, +0xA (B)
        self.lim = [0x400, 0x400, 0x80, 0x80]       # obj+0x6A68..0x6A6E : Rmax, Bmax, Rmin, Bmin
        self.blockres = {}
        self.f18 = 0                                # obj+0x18
        self.e14 = 0                                # obj+0x14  (S+0x30 + 0x500)
        self.n1c = 0                                # obj+0x1c  (S+0x18 * w*h)
    def reset(self):
        for f in self.frames: f.clear(); f.set_mode(self.mode)
    _masktab = None
    def mask_at(self, idx):
        if AwbObject._masktab is None:
            AwbObject._masktab = rdarr(ADDR['MASK_TAB'], 512 * 128)
        return AwbObject._masktab[idx]

    # --- per-block entry for CWhiteBalanceAuto: 0x53936E1C ----------------------------------
    def auto_slot5(self, Y, u, v, pos, d, flag):
        x = u16(sdiv(216 * u, Y) + 0x100)
        y = u16(sdiv(216 * v, Y) + 0x50)
        if x >= 0x200: x = 0
        if y > 0x7f: y = 0
        mask = self.mask_at(x + (y << 9))
        if mask == 0:
            self.frames[0].acc(pos, Y, u, v, d)
            return 0
        for k in range(1, 33):
            bit = 1 << (k - 1)
            if mask & bit != bit: continue
            fr = self.frames[k]
            if flag == 0 and fr.T[5][3] == 0xF:      # 0x5393C388(frame, 0): kind byte of row index 0+5
                if mask & ~0x780000 & 0xffffffff == 0:
                    fr.acc(pos, Y, u, v, d)
            else:
                fr.acc(pos, Y, u, v, d)
        return mask

    # --- 0x5393926C : angle (deg 0..359) and magnitude ---------------------------------------
    _atan = _cos = None
    @staticmethod
    def angle_mag(x, y):
        if AwbObject._atan is None:
            AwbObject._atan = rdarr(ADDR['ATAN_TAB'], 65, '<H')
            AwbObject._cos = rdarr(ADDR['COS_TAB'], 46, '<H')
        ax, ay = abs(s32(x)), abs(s32(y))
        mx, mn = max(ax, ay), min(ax, ay)
        if mx == 0:
            r0 = 0
        else:
            r0 = sdiv(mn << 6, mx)
        a = AwbObject._atan[r0]
        mag = sdiv(mx << 8, AwbObject._cos[a]) >> 2     # asr 2
        if ax < ay: a = 90 - a
        if s32(x) < 0: a = 180 - a
        if s32(y) < 0: a = 360 - a
        return (0 if a == 360 else a), mag

    # --- per-block entry for CWhiteBalanceCte: 0x5393931C ------------------------------------
    def cte_slot5(self, Y, u, v, pos, d, flag):
        if flag != 0:
            return 0
        ang, mag = self.angle_mag(u, v)
        if mag == 0:
            idx = 0
            a2, b2 = u, v                      # weight 256 -> unchanged
        else:
            t = s32(ang - 12)
            hi = (t * 0x2AAAAAAB) >> 32        # smull high word (floor)
            idx = ((hi >> 2) - (t >> 31)) + 1
            if mag > 256:
                a2 = b2 = 0
            else:
                wt = 256 - mag
                a2 = s32(wt * u + 0x80) >> 8
                b2 = s32(wt * v + 0x80) >> 8
        self.frames[idx].acc(pos, Y, a2, b2, d)
        return u32(pos)

    def slot5(self, *a):
        return self.cte_slot5(*a) if self.kind == 'cte' else self.auto_slot5(*a)

    # --- 0x53937BFC ---------------------------------------------------------------------------
    def compute_h(self):
        mx = 0
        for row in range(-5, 19):
            for fr in self.frames:
                mx = max(mx, fr.row_weight(row + 5))
        for row in range(-5, 19):
            for fr in self.frames:
                v = fr.row_weight(row + 5) if mx else 0
                fr.h[row + 5] = u16(udiv(v << 8, mx)) if mx else 0

    # --- block loop 0x539376A8 ----------------------------------------------------------------
    @staticmethod
    def log2_8_8(x):
        """0x538D3298: 8.8 fixed point log2-ish of x (1..0x200)."""
        tab = rdarr(ADDR['LOG_TAB'], 256, '<H')
        e = max(0, x.bit_length() - 8)
        return tab[x >> e] + (e << 8)

    def block_loop(self, S, W, call=None):
        """S: dict with the settings object fields, W: per-block weight bytes (obj+0xAF8C buffer).
        call(Y,u,v,pos,d,flag) defaults to self.slot5.  Returns {idx: return value} (0 for rejected blocks)."""
        call = call or self.slot5
        self.e14 = s32(S['e30'] + 0x500)
        self.f18 = 1 if s32(S['v24']) == -0x880 else 0
        self.n1c = u32(S['m18'] * (S['w'] * S['h']))
        if (S['mode70'] - 2) & ~2 & 0xffffffff == 0:
            thr = 0x20
        else:
            v = s32(S['v2c'])
            if v < 0xb00: thr = 0
            else:
                v16 = v & 0xffff
                if v16 < 0xb00: thr = 0
                elif v16 > 0x1000: thr = 0x20
                else:
                    x = (v16 - 0xb00) << 5
                    thr = (((x * 0x66666667) >> 32) >> 9) & 0xffff
        m0, m1, m2, m3 = self.m
        out = {}
        stride = S['stride']
        for y in range(S['y0'], S['y0'] + S['h']):
            for x in range(S['x0'], S['x0'] + S['w']):
                i = y * stride + x
                p = [S['P'][k][i] for k in range(5)]
                ok = all(thr < s32(p[k]) <= 0xf6d for k in range(4))
                if not ok:
                    out[i] = 0
                    continue
                R, Gr, Gb, B = p[0], p[1], p[2], p[3]
                q0 = (m0 * 0x3718 * R) // S['g68'] if S['g68'] else (1 << 64) - 1
                V0 = ((q0 + 0x1000) >> 13) & 0xffffffff
                q3 = (m3 * 0x632D * B) // S['g6e'] if S['g6e'] else (1 << 64) - 1
                V3 = ((q3 + 0x1000) >> 13) & 0xffffffff
                V1 = ((m1 * Gr + 0x1000) >> 13) & 0xffffffff
                V2 = ((m2 * Gb + 0x1000) >> 13) & 0xffffffff
                G = s32(V1 + V2) >> 1
                Y = s32(s32(0x450 * V0 + 0x9CE * G + 0x1E2 * V3 + 0x800) >> 12)
                if self.f18:
                    pos = 0x800
                else:
                    if Y < 0x2000: xx = (((Y + 8) >> 4) & 0xffff) + 1
                    else: xx = 0x200
                    pos = (self.e14 - 0x500) + self.log2_8_8(xx)
                    if S['b50']:
                        fb = W[i]
                        t1 = pos * (255 - fb)
                        t2 = fb << 11
                        a = int(t1 / 255) if t1 >= 0 else -((-t1) // 255)
                        pos = a + (t2 // 255)
                    if S['b51']:
                        pos += 0x100
                pos = s32(pos)
                flag = S['flags'][i]
                if Y <= 0x1f:
                    out[i] = 0
                    continue
                u = s32(150 * G - 1760 * V0 + 1610 * V3 + 0x800) >> 12
                v = s32(-2263 * G + 935 * V0 + 1328 * V3 + 0x800) >> 12
                out[i] = call(Y, u, v, pos, p[4], flag)
        return out

    # --- parameter-block derived multipliers (Cte 0x53938E78 / Auto 0x53938B28) ---------------
    def set_multipliers(self, S, cal30, cal34):
        """cal30/cal34: the four u16 of the calibration object (obj+0x30 / +0x34 or +0x5c)"""
        q = lambda i, g: sdiv(cal34[i] * S[g], cal30[i])
        self.m[0] = u16(u32(S['g64'] * q(0, 'g68')) >> 13)
        self.m[1] = u16(q(1, 'g6a'))
        self.m[2] = u16(q(2, 'g6c'))
        self.m[3] = u16(u32(S['g66'] * q(3, 'g6e')) >> 13)

    # --- estimate -> gains (shared tail of the CTE estimator, 0x53939028) -------------------------
    def matrix(self):
        return rdarr(ADDR['MATRIX'], 9)

    def gains_from_sums(self, Y, c1, c2, cte_clamp=True):
        """Y,c1,c2 already in the sign convention used by the CTE tail (c1,c2 negated)."""
        M = [s32(x) for x in self.matrix()]
        Bs = s32(M[6] * Y + M[7] * c1 + M[8] * c2)
        Rs = s32(M[0] * Y + M[1] * c1 + M[2] * c2)
        Bq = s32(Bs + 0x80) >> 8
        Rq = s32(Rs + 0x80) >> 8
        if Bq != 0 and Rq != 0:
            Gs = s32(M[4] * c1 + M[3] * Y + M[5] * c2)
            G256 = s32(Gs + 0x80) & ~0xff
            gR = u16(sdiv(G256, Rq))
            gB = u16(sdiv(G256, Bq))
        else:
            gR = gB = 0x100
        return gR, gB

    def clamp_and_scale(self, gR, gB):
        Rmax, Bmax, Rmin, Bmin = self.lim
        if gB < Bmin: gB = Bmin
        if gR < Rmin: gR = Rmin
        if gR >= Rmax: gR = Rmax
        if gB >= Bmax: gB = Bmax
        r = (gR * self.m[0] + 0x80) >> 8
        b = (gB * self.m[3] + 0x80) >> 8
        r = r if r < 0x10000 else 0xffff
        b = b if b < 0x10000 else 0xffff
        self.gains = [r, 0x2000, 0x2000, b]
        return self.gains

    def cte_estimate_sums(self, S54):
        """Loop of 0x53938F44..0x53939028 (S54 = settings byte +0x54 selects the special treatment of frames 5..9)."""
        Y = c1 = c2 = 0
        for i, fr in enumerate(self.frames):
            if S54 and 5 <= i <= 9:
                Y += s32(fr.sum_f(0))
                c1 += tdiv(-6 * s32(fr.sum_f(1)), 10)
                c2 += -tdiv(s32(fr.sum_f(2)), 10)
            else:
                Y += s32(fr.sum_Y()); c1 += fr.sum_c1(); c2 += fr.sum_c2()
        return s32(Y), s32(-c1), s32(-c2)

    def estimate_cte(self, S, W, cal30, cal34, call=None):
        """CWhiteBalanceCte::estimate (0x53938E78): reset -> multipliers -> block loop -> h -> sums -> gains."""
        self.reset()
        self.set_multipliers(S, cal30, cal34)
        self.block_loop(S, W, call)
        self.compute_h()
        Y, c1, c2 = self.cte_estimate_sums(S['b54'])
        gR, gB = self.gains_from_sums(Y, c1, c2)
        self.sums = (Y, c1, c2)
        self.raw_gains = (gR, gB)
        return self.clamp_and_scale(gR, gB)

def tdiv(a, b):
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q


# =============================================================================================
#  CWhiteBalanceAuto (Standard / Atmosphere / White) : parent detectors, weights, final stage
# =============================================================================================
def sdiv64(n, d):
    """__aeabi_ldivmod quotient (0x53153EA4): truncating signed 64 bit division, result low 32 bits as signed."""
    if d == 0:
        return 0
    q = abs(n) // abs(d)
    return s32(-q if (n < 0) != (d < 0) else q)

def interp_ramp(e, a, b):
    """((b*(0x500-e)... ) helper used by several stages: returns ((a*(0x500-e) + b*(e-0x300)) + round-fix) >> 9 & 0xffff"""
    t = a * (0x500 - e) + b * (e - 0x300)
    if t < 0: t += 0x1ff
    return (t >> 9) & 0xffff

def _parent_rows(self, pid):
    for fr in self.frames:
        for r in range(24):
            if fr.T[r][3] == pid:
                yield fr, r

def parent_count(self, pid):                       # 0x5393C7B0 -> 0x5393BD2C : sum of f14 for rows of this kind
    return u32(sum(fr.f[r][3] for fr, r in self.parent_rows(pid)))

def parent_Y(self, pid):                           # 0x5393C808 -> 0x5393BD64
    t = 0
    for fr, r in self.parent_rows(pid):
        t += s32(s32(fr.f[r][0]) * fr.h[r] + 0x80) >> 8
    t = s32(t)
    return s32(t * self.pw[pid - 1][0] + 0x80) >> 8

def _special_row(self, fr, r, which):
    """kinds 6, 11, 15 : 0x5393BDB0 / 0x5393C05C special branch (which = 0 -> chroma 1 (T4), 1 -> chroma 2 (T5))"""
    M = [s32(x) for x in rdarr(ADDR['MATRIX'], 9)]
    M2 = [s32(x) for x in rdarr(0x541DB4B4, 12)]
    a, b, c = (s32(x) for x in fr.f[r][:3])
    Rs = s32(b * M[1] + a * M[0] + c * M[2] + 0x80)
    Gs = s32(M[4] * b + M[3] * a + M[5] * c + 0x80)
    Bs = s32(M[7] * b + M[6] * a + M[8] * c + 0x80)
    Rq, Gq, Bq = Rs >> 8, Gs >> 8, Bs >> 8
    gr = 0 if Rq <= 0 else sdiv64((Rs >> 9) + 1024 * Gq, Rq)
    gb = 0 if Bq <= 0 else sdiv64((Bq >> 1) + 1024 * Gq, Bq)
    T = fr.T[r][1 + which]
    x1 = s32(s32((T - 128) * gr + ((256 - T) << 10) + 0x40) >> 7)
    x2 = s32(s32((T - 128) * gb + ((256 - T) << 10) + 0x40) >> 7)
    g1 = 0 if x1 == 0 else sdiv64(Gq << 10, x1)
    g2 = 0 if x2 == 0 else sdiv64(Gq << 10, x2)
    k = [(v + 8) >> 4 for v in M2[3 + 3 * which: 6 + 3 * which]]      # R, G, B coefficients
    val = s32(k[1] * Gq + k[0] * g1 + k[2] * g2)
    val = s32(val + 0x80) >> 8
    return s32(s32(val * fr.h[r]) + 0x80) >> 8

def parent_C(self, pid, which):                    # 0x5393C870 (which=0) / 0x5393C8D8 (which=1)
    t = 0
    special = (pid == 6) or ((pid & 0xfb) == 0xb)
    for fr, r in self.parent_rows(pid):
        if not special:
            x = s32(s32((fr.T[r][1 + which] - 128) * fr.h[r]) >> 7)
            t += s32(s32(fr.f[r][1 + which]) * x + 0x80) >> 8
        else:
            t += self._special_row(fr, r, which)
    t = s32(t)
    return s32(t * self.pw[pid - 1][1 + which] + 0x80) >> 8

AwbObject.parent_rows = _parent_rows
AwbObject.parent_count = parent_count
AwbObject.parent_Y = parent_Y
AwbObject.parent_C = parent_C
AwbObject._special_row = _special_row

# --- tuning of the parent weights ---------------------------------------------------------------
def _set(self, ids, vals):
    for i in ids: self.pw[i] = list(vals)

def stage_S50_const(self):                         # 0x53937EF4 (used when settings byte +0x50 != 0)
    tab = {1: 0x80, 2: 0x10, 3: 8, 5: 4, 6: 8, 7: 0x10, 8: 8, 9: 8, 10: 8, 11: 4, 12: 4, 13: 4, 14: 0, 15: 8}
    for k, v in tab.items(): self.pw[k] = [v, v, v]

def stage_pct13(self, S):                          # 0x53938508 (settings byte +0x50 == 0)
    cnt = self.parent_count(14)                     # parent #13 (id 14)
    pct = u16(udiv((cnt >> 4) * 1000, self.n1c >> 4))
    e = u16(max(s32(self.e14), 0))
    ramp = lambda p: u16(trunc_div((200 - p) * 256 + p * 128, 200))   # 256 -> 128 over 0..200 per mille
    q = ramp(pct) if pct <= 200 else 0x80
    if (S['mode70'] - 2) & ~2 & 0xffffffff == 0:
        A, B, SL, R2 = q, 0x100, 0x100, q
    elif S['b5c'] == 0:
        A, B, SL, R2 = 0x100, 0x100, 0x100, q
    else:
        d = 0x10e - s32(S['v60'])
        ip = u16(max(d, 0))
        if e < 0x500: q2 = 0x100
        elif e > 0x700: q2 = 0x40
        else: q2 = interp_ramp2(e)
        if ip > 0x64:
            SL, A = 0x100, 0x80
        else:
            t = 0x64 - ip
            SL = u16(trunc_div(q2 * t + (ip << 8), 100))
            A = u16(trunc_div((t << 8) + (ip << 7), 100))
        if d > 0:
            f30, r2b = 0x100, (q if pct <= 200 else 0x80)
        else:
            r2b = q if pct <= 200 else 0x80
            f30 = r2b
        ad = abs(d) & 0xffff
        if ad <= 0x32:
            lr = (0x32 - ad) << 8
            f30 = u16(trunc_div(f30 * ad + lr, 50))
            r2b = u16(trunc_div(r2b * ad + lr, 50))
        B, R2 = f30, r2b
    for k in (6, 7, 8, 9, 10, 15): self.pw[k] = [A, A, A]
    self.pw[13] = [B, R2, R2]
    self.pw[5] = [SL, SL, SL]

def interp_ramp2(e):                               # (0x700-e)*256 + (e-0x500)*64, >>9
    t = ((0x700 - e) << 8) + ((e - 0x500) << 6)
    if t < 0: t += 0x1ff
    return (t >> 9) & 0xffff

def trunc_div(a, b):
    q = abs(a) // abs(b)
    return -q if (a < 0) != (b < 0) else q

def stage_pct4(self):                              # 0x53937CB0
    cnt = self.parent_count(5)
    pct = min(udiv(100 * cnt, self.n1c) & 0xffff, 100)
    if pct <= 10: return
    if pct > 40:
        r1, r3, r2 = 0, 0x10, 0x20
    else:
        ip = (0x28 - pct) << 8
        r0 = pct - 10
        r1 = u16(trunc_div(ip, 30))
        r3 = u16(trunc_div(ip + (r0 << 4), 30))
        r2 = u16(trunc_div(ip + (r0 << 5), 30))
    for k, v in ((0, r2), (1, r3), (2, r1), (3, r3), (4, 0x100), (5, r3), (6, r1), (7, r2), (8, r3), (9, r3), (10, r3),
                 (11, r1), (12, r1), (15, r3)):
        self.pw[k] = [v, v, v]

def stage_S2c(self, S):                            # tail of 0x5393883C
    v = S['v2c'] & 0xffff
    if v < 0xc00: f = 0x100
    elif v > 0xe00: f = 0x40
    else:
        t = ((0xe00 - v) << 8) + ((v - 0xc00) << 6)
        if t < 0: t += 0x1ff
        f = (t >> 9) & 0xffff
        if f == 0: return
    self.pw[13] = [((f * w) >> 8) & 0xffff for w in self.pw[13]]

def stage_5393883c(self, S):
    if S['b50'] == 0:
        self.stage_pct13(S)
        if self.f18:                                # only reached when +0x50 == 0, so the value written is 0
            for k in (1, 2, 3): self.pw[k] = [0, 0, 0]
    else:
        self.stage_S50_const()
    self.stage_pct4()
    self.stage_S2c(S)

def parent_slot6(self, tmp, pid):                  # 0x53936748
    e = u16(max(s32(self.e14), 0))
    cnt = self.parent_count(pid)
    share = u16(udiv((cnt >> 4) * 1000, self.n1c >> 4))
    special = (pid == 6)
    if special:
        if e < 0x300: lo, hi = 0x14, 0x28
        elif e > 0x500: lo, hi = 0xa, 0x14
        else:
            hi = interp_ramp(e, 0x28, 0x14); lo = hi >> 1
    else:
        if e < 0x300: lo, hi = 0x32, 0x64
        elif e > 0x500: lo, hi = 0xa, 0x14
        else:
            hi = interp_ramp(e, 0x64, 0x14); lo = hi >> 1
    span = max(hi - lo, 1) if not (e < 0x300 or e > 0x500) else (hi - lo)
    if share < lo: w = 0
    elif share > hi: w = 256
    else: w = u16(sdiv((share - lo) << 8, span))
    if special or pid != 15:
        self.n20 = u16(self.n20 + w)
    tmp[0] = s32(tmp[0] + (s32(w * self.parent_Y(pid) + 0x80) >> 8))
    tmp[1] = s32(tmp[1] + (s32(w * self.parent_C(pid, 0) + 0x80) >> 8))
    tmp[2] = s32(tmp[2] + (s32(w * self.parent_C(pid, 1) + 0x80) >> 8))

def stage_final(self, tmp):                        # 0x53938970
    Y, c1, c2 = (s32(x) for x in tmp)
    self.flag_zero = 1 if (Y | c1 | c2) == 0 else 0
    e = u16(max(s32(self.e14), 0))
    if e < 0x300: thr = 0x64
    elif e > 0x500: thr = 0x14
    else: thr = interp_ramp(e, 0x64, 0x14)
    w = self.n20
    wt = 0x100 if w > thr else u16(sdiv(w << 8, thr))
    r1 = s32(-295 * c1 + (Y << 8))
    r2 = s32(0x26a * c1 + r1)
    B = s32(r2 + 0x131 * c2)
    R = s32(r1 + 0x108 * c2)
    Rq, Bq = s32(R + 0x80) >> 8, s32(B + 0x80) >> 8
    if Rq == 0 or Bq == 0:
        gR = gB = 0x100
    else:
        G = s32(r2 - 255 * c1 - 175 * c2)
        Gq = s32(G + 0x80) >> 8
        r4 = u16(0x100 - wt)
        t = s32(Gq * wt)
        gR = u16(r4 + sdiv(t, Rq))
        gB = u16(r4 + sdiv(t, Bq))
    self.raw_gains = (gR, gB)
    Rmax, Bmax, Rmin, Bmin = self.lim
    if gB < Bmin: gB = Bmin
    if gR < Rmin: gR = Rmin
    if gR >= Rmax: gR = Rmax
    if gB >= Bmax: gB = Bmax
    self.gains = [u16((gR * self.m[0] + 0x80) >> 8), 0x2000, 0x2000, u16((gB * self.m[3] + 0x80) >> 8)]
    return self.gains

def init_pw(self):
    self.pw = [[0x100, 0x100, 0x100] for _ in range(16)]
    self.n20 = 0

def estimate_auto(self, S, W, cal30, cal34, cal5c, call=None):
    """CWhiteBalanceAuto::estimate (0x53938B28) with the S50 weight-map generator (0x5393808C) left to the caller (W)."""
    self.mode = S['s34'] if S['s34'] in (1, 2) else 0
    self.reset(); self.init_pw()
    self.set_multipliers(S, cal30, cal5c if S['mode70'] == 3 else cal34)
    self.block_loop(S, W, call)
    self.stage_5393883c(S)
    self.compute_h()
    tmp = [0, 0, 0]
    self.n20 = 0
    for pid in range(1, 17):
        self.parent_slot6(tmp, pid)
    self.sums = tuple(tmp)
    return self.stage_final(tmp)

for _n in ('stage_S50_const', 'stage_pct13', 'stage_pct4', 'stage_S2c', 'stage_5393883c', 'parent_slot6', 'stage_final', 'init_pw', 'estimate_auto'):
    setattr(AwbObject, _n, globals()[_n])


# =============================================================================================
#  User white-balance shift (A-B / G-M) applied by the manager 0x53934398 on top of the estimate
#  (READ FROM CODE ONLY, not emulated: 0x53934898..0x53934920)
# =============================================================================================
def wb_shift_multipliers(step_ab, step_gm):
    """step_ab = P[0x78E], step_gm = P[0x78F] (0..28, 14 = neutral).  Returns (mul_for_R_gain, mul_for_B_gain), 1.13 fixed point.
    P+0x2EBE8 (R) *= mulR >> 13 ; P+0x2EBEE (B) *= mulB >> 13   (see awb_spec.md, section 8)"""
    A = rdarr(0x542FE420, 29, '<H'); D = rdarr(0x542FE398, 29, '<H')
    B = rdarr(0x542FD758, 29, '<H'); C = rdarr(0x542FE464, 29, '<H')
    mul_for_B = (A[step_ab] * B[step_gm]) >> 13 & 0xffff       # r2 in the code, multiplies the word at P+0x2EBEE
    mul_for_R = (D[step_ab] * C[step_gm]) >> 13 & 0xffff       # r7 in the code, multiplies the word at P+0x2EBE8
    return mul_for_R, mul_for_B


def default_cal():
    """Calibration arrays returned by 0x5393CD00 after its constructor 0x5393CBC4 (static data in the image):
    (obj+0x30, obj+0x34, obj+0x5C), four u16 each (R, Gr, Gb, B), 1.13 fixed point.  Whether the camera later replaces them with
    per-unit data was not determined."""
    return (rdarr(0x542FD750, 4, '<H'), rdarr(0x542FDD74, 4, '<H'), rdarr(0x542FDD84, 4, '<H'))


def make_settings(P, w, h, stride=None, **kw):
    """Settings block ('S') with the defaults of its constructor 0x5393CAF0 and the values 0x53933D88 writes for a normal still.
    P = [R, Gr, Gb, B, W] lists of per-block values (12 bit stats; W = per-block weight/count)."""
    S = dict(P=P, stride=stride or w, m18=1, x0=0, y0=0, w=w, h=h, v24=0, v2c=0x900, e30=0, b50=0, b51=0, b54=0, b5c=0, v60=0, s34=0,
             g64=0x2000, g66=0x2000, g68=0x2000, g6a=0x2000, g6c=0x2000, g6e=0x2000, mode70=0, flags=[0] * (h * (stride or w) + w + 2))
    S.update(kw)
    return S


if __name__ == '__main__':
    # tiny demo: a grey-world scene lit by an illuminant with R/G = 0.62, B/G = 1.45 (raw counts), default calibration
    import random
    rng = random.Random(1)
    w, h = 32, 24
    P = [[], [], [], [], []]
    for i in range(w * h):
        g = rng.uniform(200, 1500)
        P[0].append(int(g * 0.62)); P[1].append(int(g)); P[2].append(int(g)); P[3].append(int(g * 1.45)); P[4].append(100)
    S = make_settings(P, w, h, v24=0x100, e30=0x200)
    W = bytes(w * h + 4)
    c30, c34, c5c = default_cal()
    for kind in ('auto', 'cte'):
        o = AwbObject(kind)
        g = o.estimate_auto(S, W, c30, c34, c5c) if kind == 'auto' else o.estimate_cte(S, W, c30, c34)
        print(kind, 'R gain %.3f  B gain %.3f  (1.13 fixed: %d %d)' % (g[0] / 8192, g[3] / 8192, g[0], g[3]), 'raw 8.8 pre-multiplier', o.raw_gains)
