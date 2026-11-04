/* SPDX-License-Identifier: GPL-2.0-only
 *
 * GR Mod (experimental): a learned auto white balance for the Ricoh GR IV (firmware 1.11), plain Auto only.
 *
 * FFCC-style (Barron & Tsai 2017) inference on the camera's own AWB statistics (the 64 x 62 block means R, G, B
 * and valid-pixel counts): two log-chroma histograms (block colours; local colour contrast) on a 64 x 64 torus,
 * circularly convolved with two learned filters by a fixed-point 64 x 64 FFT, plus a learned bias map that depends
 * on the scene brightness; softmax and circular mean give the illuminant; a two-point calibration (daylight / warm
 * low light, measured on real GR IV shots) corrects the estimate; the result is written as the camera's own R and B
 * gains (obj + 4 and obj + 0xA, 1.13 fixed point).
 *
 * Called from the AWB with (ctx, obj, S, is_still): `obj` the AWB object, `S` the settings block the stats come through
 * (+0x00..+0x10 pointers to the per-block u32 arrays R, Gr, Gb, B, count; +0x14 u16 stride; +0x1C u16 x0, +0x1E y0,
 * +0x20 w, +0x22 h; +0x24 s32 v24 (-0x880: no exposure data); +0x30 s32 scene brightness Av+Tv-Sv, 8.8 EV).
 * Nothing is written unless obj[0xAF88] == 0 (plain Auto), w, h in 1..64, the scratch buffer exists and at least
 * 5 % of the blocks' pixels are valid; the camera's own result then stays.
 *
 * Integer only (no float, no division by variables, no 64-bit division or variable 64-bit shifts), position
 * independent, no global data: every table comes through the context. tools/awbml/ref.py is the bit-exact
 * reference and builds the tables (layout there); stack use is a few hundred bytes, the scratch buffer is
 * allocated once (two regions of AWBML_SCRATCH_BYTES: live view and stills).
 *
 * Temporal filter (FFCC): the calibrated estimate is an observation whose variance is the spread of the softmax
 * marginals mapped through a measured table (R_eff); a Kalman filter per axis (parameters in the KF table) smooths it over
 * the computing calls and restarts when two confident frames in a row disagree with the state in the same direction.
 *
 * Stills (is_still != 0, the Auto estimate's third argument) always compute fresh from their own statistics: no throttle, no
 * filter, no access to the live view's state. Live view keeps the throttle and the filter, and (ctx->lv_exp) treats the
 * exposure data in S as missing, since its S carries none (v24 = 0, e30 from a record word nothing writes).
 *
 * Throttling: the AWB runs on every live-view frame, so only the first call and then every `ctx->period`-th call
 * compute; the calls in between repeat the last result (or, if the last computation fell back, write nothing). A call
 * with the mode byte not 0 forgets the result, so the next plain-Auto call computes.
 */
#include "awbml_const.h"

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int i32;
typedef short i16;
typedef unsigned long long u64;
typedef long long i64;

/* Context, built by the caller (all pointers 32 bit in the camera). */
struct awbml_ctx {
  u32 magic;                    /* AWBML_MAGIC */
  void *(*alloc)(u32 bytes);    /* the firmware's operator new; called once */
  void **slot;                  /* where the scratch buffer pointer is kept (initially 0) */
  const i32 *log;               /* [4096] */
  const i16 *bias;              /* [3][4096] */
  const i32 *fspec;             /* [2][33][64][2] */
  const i32 *tw;                /* [2][64] cos, sin Q30 */
  const u32 *atan;              /* [24] */
  const u32 *expa;              /* [AWBML_NEXPA] */
  const u32 *expb;              /* [256] */
  const i16 *tanh;              /* [(HI - LO) / 16 + 2] */
  const u32 *gexp;              /* [2][AWBML_NG] */
  const u32 *recip;             /* [9] */
  const i32 *cal;               /* [10] */
  const u32 *kf;                /* [8] Kalman filter parameters */
  const u32 *ln;                /* [257] */
  u32 period;                   /* live view: compute on every period-th call (1: always) */
  u32 af89;                     /* nonzero: a gain override also clears Auto+0xAF89 (the camera's all-zero-sums hold flag) */
  u32 lv_exp;                   /* live view only: 1 = the exposure data (S+0x24 / S+0x30) is not usable and is treated as missing, 0 = use it */
};

struct scratch {
  i32 re[4096];
  i32 im[4096];
  u32 pu[64];
  u32 pv[64];
  u8 rowflag[64];                 /* histogram rows in use: bit 0 channel 1, bit 1 channel 2 */
  /* rolling 3 rows of the masked block values (0 where the block is invalid) and their column sums (index x + 1,
   * zero padded on both sides) for the local contrast */
  u32 rrg[3][64], rbc[3][64];      /* r | g << 16 and b | valid << 16 */
  u32 crg[66], cbc[66];            /* column sums of those (the lanes cannot overflow: 9 * 3949 < 65536) */
  /* throttling state: the result of the last full computation */
  u32 valid, left, fb, g0, g3;
  /* temporal filter: state valid, mean (Q16 log units) and variance (Q32) per axis */
  u32 have;
  i32 mu[2];
  u32 sg[2];
  /* a held-back scene change candidate: set, its observation and the direction it was far from the state per axis */
  u32 cand;
  i32 cz[2];
  i32 cs[2];
};

struct stats {
  const u32 *r, *gr, *gb, *b, *c;
  u32 stride, x0, y0;
};

#ifdef AWBML_HOST
extern const unsigned char *awbml_host_base; /* host tests: the stats pointers are offsets into this */
#define S_PTR(v) ((const u32 *)(awbml_host_base + (v)))
#else
#define S_PTR(v) ((const u32 *)(v))
#endif

void awbml(const struct awbml_ctx *ctx, unsigned char *obj, const unsigned char *S, u32 is_still);

static u32 rd16(const u8 *p) { return (u32)p[0] | ((u32)p[1] << 8); }
static u32 rd32(const u8 *p) { return rd16(p) | (rd16(p + 2) << 16); }
static void wr16(u8 *p, u32 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); }

#ifdef AWBML_PROFILE
#define STAGE static __attribute__((noinline))
#else
#define STAGE static
#endif

typedef char awbml_scratch_size_check[sizeof(struct scratch) == AWBML_SCRATCH_BYTES ? 1 : -1];

/* Test hook (host fuzzing only): lets the test corrupt the scratch between and inside the stages, as a second task using the
 * same memory would. Every index below must stay in bounds whatever the scratch holds. */
#ifdef AWBML_FUZZ
extern void awbml_fuzz(void *sc, int point);
#define FUZZ(sc, p) awbml_fuzz(sc, p)
#else
#define FUZZ(sc, p) ((void)0)
#endif

/* x is at most 0xF6D for the block values; the clamp only matters if the scratch was corrupted */
static i32 ilog(const struct awbml_ctx *k, u32 x) { return k->log[x > 4095 ? 4095 : x]; }

static u32 gmean(u32 gr, u32 gb) { return (gr >> 1) + (gb >> 1) + ((gr | gb) & 1); }

/* floor(2^50 / d) by shift and subtract. */
static u64 div50(u32 d) {
  u64 r = 0, q = 0;
  int i;
  for (i = 50; i >= 0; i--) {
    r = (r << 1) | (u64)(i == 50);
    q <<= 1;
    if (r >= d) { r -= d; q |= 1; }
  }
  return q;
}

static u32 rev6(u32 i) {
#ifdef __clang__
  return __builtin_bitreverse32(i) >> 26;
#else
  u32 r = 0, n;
  for (n = 0; n < 6; n++) { r = (r << 1) | (i & 1); i >>= 1; }
  return r;
#endif
}

/*
 * FFTs of 64 points in place on the lines listed: element k of line l at k * es + l * ls, so that the twiddle of a
 * butterfly is shared by all the lines. Forward: e^-i, no scaling. Inverse: e^+i, every stage halves (rounded).
 * Twiddles Q30, product rounded (x + 2^29) >> 30; the twiddles 1 and -+i (exact in Q30) are done without
 * multiplications, with the same results.
 */
static inline __attribute__((always_inline)) void fft_lines_t(i32 *re, i32 *im, u32 es, u32 ls, const u8 *lines, u32 nl, const i32 *tw, const int inv) {
  u32 i, j, n, len, half, base, ts, o, hes;
  u16 lo[64];
  const i32 sh = inv ? 1 : 0, rnd = inv ? 1 : 0;
  for (n = 0; n < nl; n++) lo[n] = (u16)(lines[n] * ls);
  for (i = 0; i < 64; i++) {
    j = rev6(i);
    if (j > i) {
      for (n = 0; n < nl; n++) {
        u32 pa = i * es + lo[n], pb = j * es + lo[n];
        i32 t = re[pa]; re[pa] = re[pb]; re[pb] = t;
        t = im[pa]; im[pa] = im[pb]; im[pb] = t;
      }
    }
  }
  for (len = 2, ts = 32; len <= 64; len <<= 1, ts >>= 1) {
    half = len >> 1; hes = half * es;
    for (j = 0; j < half; j++) {
      i32 wr = tw[j * ts], wi = inv ? tw[64 + j * ts] : -tw[64 + j * ts], nwi = -wi;
      for (base = 0; base < 64; base += len) {
        o = (base + j) * es;
        if (j == 0) {                                  /* w = 1 */
          for (n = 0; n < nl; n++) {
            u32 a = o + lo[n], b = a + hes;
            i32 ar = re[a], ai = im[a], br = re[b], bi = im[b];
            re[a] = (ar + br + rnd) >> sh; re[b] = (ar - br + rnd) >> sh;
            im[a] = (ai + bi + rnd) >> sh; im[b] = (ai - bi + rnd) >> sh;
          }
        } else if (j * 4 == len) {                     /* w = -+i */
          for (n = 0; n < nl; n++) {
            u32 a = o + lo[n], b = a + hes;
            i32 ar = re[a], ai = im[a], br = re[b], bi = im[b], tr = inv ? -bi : bi, ti = inv ? br : -br;
            re[a] = (ar + tr + rnd) >> sh; re[b] = (ar - tr + rnd) >> sh;
            im[a] = (ai + ti + rnd) >> sh; im[b] = (ai - ti + rnd) >> sh;
          }
        } else {
          for (n = 0; n < nl; n++) {
            u32 a = o + lo[n], b = a + hes;
            i32 ar = re[a], ai = im[a], br = re[b], bi = im[b];
            i64 acr = 1 << 29, aci = 1 << 29;
            i32 tr, ti;
            acr += (i64)wr * br; acr += (i64)nwi * bi;
            aci += (i64)wr * bi; aci += (i64)wi * br;
            tr = (i32)(acr >> 30); ti = (i32)(aci >> 30);
            re[a] = (ar + tr + rnd) >> sh; re[b] = (ar - tr + rnd) >> sh;
            im[a] = (ai + ti + rnd) >> sh; im[b] = (ai - ti + rnd) >> sh;
          }
        }
      }
    }
  }
}

STAGE void fft_fwd(i32 *re, i32 *im, u32 es, u32 ls, const u8 *lines, u32 nl, const i32 *tw) { fft_lines_t(re, im, es, ls, lines, nl, tw, 0); }
STAGE void fft_inv(i32 *re, i32 *im, u32 es, u32 ls, const u8 *lines, u32 nl, const i32 *tw) { fft_lines_t(re, im, es, ls, lines, nl, tw, 1); }

/* Scales the rows in use (flag bit `bit`) of a histogram to a total of 2^20. */
STAGE void normalise(const u8 *rowflag, u32 bit, i32 *a, u32 tot) {
  u64 q;
  u32 i, x;
  if (!tot) return;
  q = div50(tot);
  for (i = 0; i < 64; i++) {
    if (!(rowflag[i] & bit)) continue;
    for (x = 0; x < 64; x++) a[i * 64 + x] = (i32)((((u64)(u32)a[i * 64 + x] * q) + (1u << 29)) >> 30);
  }
}

/* Angle of (x, y) as a u32 fraction of a turn (CORDIC). */
static u32 atan2_turn(i64 x, i64 y, const u32 *at) {
  u32 z = 0;
  i32 xi, yi, t;
  int i;
  if (x < 0) { x = -x; y = -y; z = 0x80000000u; }
  while (x >= (1 << 29) || x <= -(1 << 29) || y >= (1 << 29) || y <= -(1 << 29)) { x >>= 1; y >>= 1; }
  xi = (i32)x; yi = (i32)y;
  for (i = 0; i < 24; i++) {
    if (yi >= 0) { t = xi + (yi >> i); yi = yi - (xi >> i); xi = t; z += at[i]; }
    else { t = xi - (yi >> i); yi = yi + (xi >> i); xi = t; z -= at[i]; }
  }
  return z;
}

/* ln(v) in Q24, v >= 1: v reduced to 32 bits, table of 256 steps with linear interpolation */
static i32 lnq(const struct awbml_ctx *k, u64 v) {
  u32 sh = 0, w, c, m, f, rest;
  i32 a, b;
  while (v >> 32) { v >>= 1; sh++; }
  w = (u32)v;
  c = (u32)__builtin_clz(w);
  m = w << c;
  f = (m >> 23) & 255; rest = (m >> 15) & 255;
  a = (i32)k->ln[f]; b = (i32)k->ln[f + 1];
  return (i32)(31 - c + sh) * AWBML_LN2Q + a + (((b - a) * (i32)rest) >> 8);
}

/* Variance of one axis (log units^2, Q32) from the resultant (x, y) of its marginal (mass M): sigma^2 = -2 ln(rho)
 * radians^2, rho = |resultant| / (M 2^30), converted to log units and clamped to [R_min, R_max]. */
static u32 axis_variance(const struct awbml_ctx *k, u64 mass, i64 x, i64 y) {
  u32 s = 0;
  u64 s2, r;
  i64 d;
  while (x >= (1 << 29) || x <= -(1 << 29) || y >= (1 << 29) || y <= -(1 << 29)) { x >>= 1; y >>= 1; s++; }
  s2 = (u64)(x * x) + (u64)(y * y);
  if (!s2 || !mass) return k->kf[1];
  d = (i64)lnq(k, mass * mass) + 60 * (i64)AWBML_LN2Q - lnq(k, s2) - 2 * (i64)s * AWBML_LN2Q;
  r = d > 0 ? ((u64)d * AWBML_VARC) >> 8 : 0;
  if (r < k->kf[0]) r = k->kf[0];
  if (r > k->kf[1]) r = k->kf[1];
  return (u32)r;
}

static u32 circ_mean(const struct awbml_ctx *k, const u32 *p, u32 *var) {
  i64 x = 0, y = 0;
  u64 mass = 0;
  u32 i;
  for (i = 0; i < 64; i++) {
    i64 q = (i64)(p[i] >> 6);
    mass += (u64)q;
    x += q * k->tw[i];
    y += q * k->tw[64 + i];
  }
  *var = axis_variance(k, mass, x, y);
  return atan2_turn(x, y, k->atan) >> 10;
}

static u32 exp_gain(const struct awbml_ctx *k, u32 which, i32 x) {
  i32 xo = x + 65536;
  u32 idx, r, p, g;
  if (xo < 0) xo = 0;
  if (xo > 81 * 4096 - 1) xo = 81 * 4096 - 1;
  idx = (u32)xo >> 12; r = (u32)xo & 4095;
  p = 65536 + r + ((r * r) >> 17) + (((((r * r) >> 16) * r >> 16) * 10923) >> 16);
  g = (u32)((((u64)k->gexp[which * AWBML_NG + idx] * p) + (1u << 19)) >> 20);
  if (g < 1024) g = 1024;
  if (g > 65535) g = 65535;
  return g;
}

/* round(d / cn) for the neighbour count cn (1..8) */
static u32 divrnd(const struct awbml_ctx *k, u32 d, u32 cn) {
  if (cn == 8) return (d + 4) >> 3;
  return (u32)((((u64)(2u * d + cn)) * k->recip[cn]) >> 24);
}

/* Block statistics: validity, histogram of block colours, local colour contrast (|block - mean of the valid
 * 8-neighbours inside the grid|) histogram. Returns the sum of the valid blocks' counts; t1, t2 the histograms' totals. */
STAGE u64 histograms(const struct awbml_ctx *ctx, struct scratch *sc, const struct stats *st, u32 w, u32 h, u32 *t1p, u32 *t2p) {
  u32 t, x, i, cur = 0, prev = 2, tot1 = 0, tot2 = 0;
  u64 csum = 0;
  for (i = 0; i < 4096; i++) { sc->re[i] = 0; sc->im[i] = 0; }
  for (i = 0; i < 64; i++) sc->rowflag[i] = 0;
  for (i = 0; i < 66; i++) { sc->crg[i] = 0; sc->cbc[i] = 0; }
  for (i = 0; i < 3; i++) for (x = 0; x < 64; x++) { sc->rrg[i][x] = 0; sc->rbc[i][x] = 0; }
  /* step t: row t enters the rolling window (row t - 3 leaves), then row t - 1 (rows t - 2 .. t in the window) is done */
  for (t = 0; t <= h; t++) {
    u32 *nrg = sc->rrg[cur], *nbc = sc->rbc[cur];
    for (x = 0; x < w; x++) {                      /* the row leaving */
      sc->crg[x + 1] -= nrg[x]; sc->cbc[x + 1] -= nbc[x];
      nrg[x] = 0; nbc[x] = 0;
    }
    if (t < h) {                                   /* the row entering */
      u32 j = (st->y0 + t) * st->stride + st->x0;
      for (x = 0; x < w; x++, j++) {
        u32 c = st->c[j], r, g, b, mn, mx;
        if (c < 317 || c > AWBML_MAXCNT) continue;
        r = st->r[j]; g = gmean(st->gr[j], st->gb[j]); b = st->b[j];
        mn = r < g ? r : g; mx = r > g ? r : g;
        if (b < mn) mn = b;
        if (b > mx) mx = b;
        if (mn >= 4 && mx <= 0xF6D) {
          i32 lg = ilog(ctx, g);
          u32 iu = (u32)((lg - ilog(ctx, r)) >> 16) & 63;
          u32 iv = (u32)((lg - ilog(ctx, b) + AWBML_V_OFFSET) >> 16) & 63;
          u32 rg = r | (g << 16), bc = b | 0x10000u;
          sc->rowflag[iu] |= 1;
          nrg[x] = rg; nbc[x] = bc;
          sc->crg[x + 1] += rg; sc->cbc[x + 1] += bc;
          csum += c; tot1 += c;
          ((u32 *)sc->re)[iu * 64 + iv] += c;
        }
      }
    }
    if (t >= 1) {                                  /* row t - 1 */
      const u32 *crg = sc->rrg[prev], *cbc = sc->rbc[prev];
      for (x = 0; x < w; x++) {
        u32 rg = crg[x], bc = cbc[x], srg, sbc, cn, r, g, b, sr, sg, sb, er, eg, eb, wt;
        if (!(bc >> 16)) continue;
        sbc = sc->cbc[x] + sc->cbc[x + 1] + sc->cbc[x + 2] - bc;
        cn = sbc >> 16;
        if (!cn || cn > 8) continue;                 /* 1..8 neighbours (more only if the scratch was corrupted) */
        srg = sc->crg[x] + sc->crg[x + 1] + sc->crg[x + 2] - rg;
        r = rg & 0xffff; g = rg >> 16; b = bc & 0xffff;
        sr = srg & 0xffff; sg = srg >> 16; sb = sbc & 0xffff;
        {
          i32 d = (i32)(cn * r) - (i32)sr; if (d < 0) d = -d; er = divrnd(ctx, (u32)d, cn);
          d = (i32)(cn * g) - (i32)sg; if (d < 0) d = -d; eg = divrnd(ctx, (u32)d, cn);
          d = (i32)(cn * b) - (i32)sb; if (d < 0) d = -d; eb = divrnd(ctx, (u32)d, cn);
        }
        wt = er + eg + eb;
        tot2 += wt;
        {
          i32 lg = ilog(ctx, eg);
          u32 iu = (u32)((lg - ilog(ctx, er)) >> 16) & 63, iv = (u32)((lg - ilog(ctx, eb) + AWBML_V_OFFSET) >> 16) & 63;
          sc->rowflag[iu] |= 2;
          ((u32 *)sc->im)[iu * 64 + iv] += wt;
        }
      }
    }
    FUZZ(sc, 10);
    prev = cur; cur = cur == 2 ? 0 : cur + 1;
  }
  *t1p = tot1; *t2p = tot2;
  return csum;
}

/*
 * Z = H1 + i H2, forward FFT (rows with data only), separate by conjugate symmetry, multiply with the filter spectra for
 * the columns kx = 0..32, inverse FFT of those columns, the other columns by conjugate symmetry; two real output rows
 * (y, y + 32) share one complex row FFT. Result: score of cell (y, x) at re[y * 64 + x] for y < 32 and at
 * im[(y - 32) * 64 + x] for y >= 32.
 */
STAGE void convolve(const struct awbml_ctx *ctx, struct scratch *sc) {
  u8 lines[64];
  u32 i, n = 0, ky, kx, kmax, y, x;
  for (i = 0; i < 64; i++) if (sc->rowflag[i]) lines[n++] = (u8)i;
  fft_fwd(sc->re, sc->im, 1, 64, lines, n, ctx->tw);
  for (i = 0; i < 64; i++) lines[i] = (u8)i;
  FUZZ(sc, 11);
  fft_fwd(sc->re, sc->im, 64, 1, lines, 64, ctx->tw);
  FUZZ(sc, 12);
  for (kx = 0; kx <= 32; kx++) {
    int both = kx == 0 || kx == 32;
    kmax = both ? 32 : 63;
    for (ky = 0; ky <= kmax; ky++) {
      u32 k1 = ky * 64 + kx, k2 = ((64 - ky) & 63) * 64 + ((64 - kx) & 63);
      i32 ar = sc->re[k1], ai = sc->im[k1], br = sc->re[k2], bi = sc->im[k2];
      i32 x1r = ar + br, x1i = ai - bi, x2r = ai + bi, x2i = -(ar - br);
      const i32 *f1 = ctx->fspec + (ky * 33 + kx) * 2, *f2 = f1 + 64 * 33 * 2;
      i64 accr = (i64)x1r * f1[0] - (i64)x1i * f1[1] + (i64)x2r * f2[0] - (i64)x2i * f2[1];
      i64 acci = (i64)x1r * f1[1] + (i64)x1i * f1[0] + (i64)x2r * f2[1] + (i64)x2i * f2[0];
      i32 pr = (i32)((accr + (1 << (AWBML_PSHIFT - 1))) >> AWBML_PSHIFT);
      i32 pi = (i32)((acci + (1 << (AWBML_PSHIFT - 1))) >> AWBML_PSHIFT);
      sc->re[k1] = pr; sc->im[k1] = pi;
      if (both) { sc->re[k2] = pr; sc->im[k2] = -pi; }
    }
  }
  FUZZ(sc, 13);
  for (i = 0; i < 33; i++) lines[i] = (u8)i;
  fft_inv(sc->re, sc->im, 64, 1, lines, 33, ctx->tw);
  for (y = 0; y < 32; y++) {
    i32 *r1 = sc->re + y * 64, *i1 = sc->im + y * 64, *r2 = sc->re + (y + 32) * 64, *i2 = sc->im + (y + 32) * 64;
    for (x = 63; x > 32; x--) {                    /* columns 33..63: conjugates of 31..1 */
      i32 a1r = r1[64 - x], a1i = -i1[64 - x], a2r = r2[64 - x], a2i = -i2[64 - x];
      r1[x] = a1r - a2i; i1[x] = a1i + a2r;
    }
    for (x = 0; x <= 32; x++) {
      i32 a1r = r1[x], a1i = i1[x], a2r = r2[x], a2i = i2[x];
      r1[x] = a1r - a2i; i1[x] = a1i + a2r;
    }
  }
  FUZZ(sc, 14);
  for (i = 0; i < 32; i++) lines[i] = (u8)i;
  fft_inv(sc->re, sc->im, 1, 64, lines, 32, ctx->tw);
}

/* score = convolution + bias (scene-brightness dependent); softmax marginals; circular means. Returns u, v (Q16). */
STAGE void scores(const struct awbml_ctx *ctx, struct scratch *sc, i32 v24, i32 e30, i32 *pu_, i32 *pv_, u32 *ru, u32 *rv) {
  i32 e, tq, smax = -0x7fffffff - 1, ou, ov;
  u32 i, h;
  if (v24 == -0x880) {
    e = 0; tq = 0;
  } else {
    i32 ec = e30 < AWBML_E30_LO ? AWBML_E30_LO : (e30 > AWBML_E30_HI ? AWBML_E30_HI : e30);
    i32 j = (ec - AWBML_E30_LO) >> 4, f = (ec - AWBML_E30_LO) & 15;
    e = (ec - 1024) * 4;
    tq = ctx->tanh[j] + ((((i32)ctx->tanh[j + 1] - (i32)ctx->tanh[j]) * f + 8) >> 4);
  }
  for (h = 0; h < 2; h++) {                       /* cells 0..2047 live in re, 2048..4095 in im */
    i32 *cell = h ? sc->im : sc->re;
    const i16 *b0 = ctx->bias + h * 2048, *b1 = b0 + 4096, *b2 = b1 + 4096;
    for (i = 0; i < 2048; i++) {
      i32 s = cell[i] + b0[i] + ((e * (i32)b1[i]) >> 12) + ((tq * (i32)b2[i]) >> 12);
      cell[i] = s;
      if (s > smax) smax = s;
    }
  }
  for (i = 0; i < 64; i++) { sc->pu[i] = 0; sc->pv[i] = 0; }
  FUZZ(sc, 15);
  for (h = 0; h < 2; h++) {
    const i32 *cell = h ? sc->im : sc->re;
    u32 *pu = sc->pu + h * 32;
    for (i = 0; i < 2048; i++) {
      u32 d = (u32)(smax - cell[i]), a = d >> 8;
      if (a < AWBML_NEXPA) {
        u32 wgt = (u32)((((u64)ctx->expa[a] * ctx->expb[d & 255]) + (1u << 29)) >> 30);
        pu[i >> 6] += wgt;
        sc->pv[i & 63] += wgt;
      }
    }
  }
  FUZZ(sc, 16);
  ou = (i32)circ_mean(ctx, sc->pu, ru);
  ov = (i32)circ_mean(ctx, sc->pv, rv);
  *pu_ = AWBML_U0Q + ((ou + 32768 + 16) >> 5);
  *pv_ = AWBML_V0Q + ((ov + 32768 + 16) >> 5);
}

/* two-point calibration: P' = P + Dd + s (Dt - Dd), s = clamp(((P - Pd).(Pt - Pd)) / |Pt - Pd|^2, 0, 1) */
static void calibrate(const i32 *cal, i32 *pu, i32 *pv) {
  i64 dot = (i64)(*pu - cal[0]) * cal[4] + (i64)(*pv - cal[1]) * cal[5];
  i64 den = (i64)cal[4] * cal[4] + (i64)cal[5] * cal[5];
  i64 s;
  if (dot <= 0) s = 0;
  else if (dot >= den) s = 65536;
  else s = (i64)((((u64)dot * (u32)cal[8]) + (1u << 31)) >> 32);
  *pu = *pu + cal[2] + (i32)((s * cal[6] + 32768) >> 16);
  *pv = *pv + cal[3] + (i32)((s * cal[7] + 32768) >> 16);
}

/* floor(n * 65536 / d) for n < d, by shift and subtract */
static u32 divq16(u32 n, u32 d) {
  u64 r = n;
  u32 q = 0;
  int i;
  for (i = 0; i < 16; i++) {
    r <<= 1; q <<= 1;
    if (r >= d) { r -= d; q |= 1; }
  }
  return q;
}

/* R_eff (Q32) from the posterior variance rp: linear in between the 17 knots at ln(rp / R_base) = j / 4 */
static u32 reff(const struct awbml_ctx *k, u32 rp) {
  i32 x = lnq(k, rp) - lnq(k, k->kf[5]);
  u32 i, f;
  if (x < 0) x = 0;
  if (x > 16 * (1 << 22) - 1) x = 16 * (1 << 22) - 1;
  i = (u32)x >> 22; f = (u32)x & ((1u << 22) - 1);
  return k->kf[8 + i] + (u32)(((u64)(k->kf[9 + i] - k->kf[8 + i]) * f) >> 22);
}

/* Temporal filter over the illuminant (Kalman, per axis): observation z with variance r (R_eff); the output is sc->mu.
 * A confident frame far from the state restarts it (flags bit 0 clear) or becomes a held-back candidate that the next confident
 * frame, far in the same direction, confirms (bit 0 set); the restart is at that frame, or at the mean of the two (bit 1). */
static void kalman(struct scratch *sc, const u32 *kf, const i32 *z, const u32 *r) {
  int a;
  i32 sign[2] = {0, 0};
  if (!sc->have) {
    sc->have = 1; sc->cand = 0;
    for (a = 0; a < 2; a++) { sc->mu[a] = z[a]; sc->sg[a] = r[a]; }
    return;
  }
  for (a = 0; a < 2; a++) sc->sg[a] += kf[2];
  if (r[0] < kf[3] && r[1] < kf[3]) {
    for (a = 0; a < 2; a++) {
      i64 d = (i64)z[a] - sc->mu[a];
      if ((u64)(d * d) > (u64)kf[4] * ((u64)sc->sg[a] + r[a])) sign[a] = d > 0 ? 1 : -1;
    }
    if (sign[0] || sign[1]) {
      if (!(kf[6] & 1) || (sc->cand && (sc->cs[0] * sign[0] > 0 || sc->cs[1] * sign[1] > 0))) {
        for (a = 0; a < 2; a++) {
          sc->mu[a] = (kf[6] & 2) && (kf[6] & 1) ? (sc->cz[a] + z[a]) >> 1 : z[a];
          sc->sg[a] = r[a];
        }
        sc->cand = 0;
      } else {
        sc->cand = 1;
        for (a = 0; a < 2; a++) { sc->cz[a] = z[a]; sc->cs[a] = sign[a]; }
      }
      return;
    }
  }
  sc->cand = 0;
  for (a = 0; a < 2; a++) {
    u32 k = divq16(sc->sg[a], sc->sg[a] + r[a]);
    sc->mu[a] += (i32)((((i64)k * ((i64)z[a] - sc->mu[a])) + 32768) >> 16);
    sc->sg[a] -= (u32)((((u64)k * sc->sg[a]) + 32768) >> 16);
  }
}

/* The gains are in the units of the camera's final stage under the settings the model was calibrated with (S+0x68 and
 * S+0x6E = 0x2000, the R and B gain words); at capture those words carry the camera's per-unit factor: out = (g * s + 0x1000)
 * >> 13, at most 0xFFFF (a zero word is left alone). */
static u32 scale_gain(u32 g, u32 s) {
  u32 o;
  if (!s) return g;
  o = (u32)(((u64)g * s + 0x1000) >> 13);
  return o > 0xFFFF ? 0xFFFF : o;
}

static void put_gains(const struct awbml_ctx *ctx, unsigned char *obj, u32 g0, u32 g3, const unsigned char *S) {
  if (S) {                                        /* a still; live view is left as it is */
    g0 = scale_gain(g0, rd16(S + 0x68));
    g3 = scale_gain(g3, rd16(S + 0x6E));
  }
  wr16(obj + 4, g0);
  wr16(obj + 0xA, g3);
  if (ctx->af89) obj[0xAF89] = 0;
}

/* Entry (first function in .text). is_still: 0 = live view, else a still (the estimate's third argument).
 * The scratch allocation holds two regions of AWBML_SCRATCH_BYTES: [0] live view (also the throttle and the filter state),
 * [1] stills (working arrays only; a still always computes fresh and never reads or changes the live view's state). */
void awbml(const struct awbml_ctx *ctx, unsigned char *obj, const unsigned char *S, u32 is_still) {
  struct stats st;
  struct scratch *sc, *live;
  u32 w, h, stride, x0, y0, t1, t2, fresh = 0;
  i32 v24, e30, pu, pv, z[2];
  u32 rr[2];
  if (ctx->magic != AWBML_MAGIC || !ctx->alloc || !ctx->slot) return;
  if (obj[0xAF88] != 0) {                         /* not plain Auto: a live view call forgets the last result */
    if (!is_still && *ctx->slot) { ((struct scratch *)*ctx->slot)->valid = 0; ((struct scratch *)*ctx->slot)->have = 0; }
    return;
  }
  stride = rd16(S + 0x14); x0 = rd16(S + 0x1c); y0 = rd16(S + 0x1e); w = rd16(S + 0x20); h = rd16(S + 0x22);
  v24 = (i32)rd32(S + 0x24); e30 = (i32)rd32(S + 0x30);
  if (!is_still && ctx->lv_exp) v24 = -0x880;     /* live view: no usable exposure data */
  if (w < 1 || w > 64 || h < 1 || h > 64) return;
  if ((u64)(y0 + h - 1) * stride + x0 + w > (1u << 24)) return;
  if (!*ctx->slot) { *ctx->slot = ctx->alloc(2 * AWBML_SCRATCH_BYTES); fresh = 1; }
  if (!*ctx->slot) return;
  live = (struct scratch *)*ctx->slot;
  if (fresh) { live->valid = 0; live->have = 0; }
  FUZZ(live, 20);
  if (is_still) {
    sc = (struct scratch *)((u8 *)live + AWBML_SCRATCH_BYTES);
  } else {
    sc = live;
    if (sc->valid && sc->left) {                  /* between two computations: repeat the last result */
      sc->left--;
      if (!sc->fb) put_gains(ctx, obj, sc->g0, sc->g3, 0);
      return;
    }
  }
  FUZZ(sc, 0);
  st.r = S_PTR(rd32(S + 0)); st.gr = S_PTR(rd32(S + 4)); st.gb = S_PTR(rd32(S + 8));
  st.b = S_PTR(rd32(S + 12)); st.c = S_PTR(rd32(S + 16));
  st.stride = stride; st.x0 = x0; st.y0 = y0;
  if (!is_still) { sc->valid = 1; sc->fb = 1; sc->left = ctx->period > 1 ? ctx->period - 1 : 0; }
  if (histograms(ctx, sc, &st, w, h, &t1, &t2) * 20 < (u64)w * h * 1584) return;
  FUZZ(sc, 1);
  normalise(sc->rowflag, 1, sc->re, t1);
  normalise(sc->rowflag, 2, sc->im, t2);
  FUZZ(sc, 2);
  convolve(ctx, sc);
  FUZZ(sc, 3);
  scores(ctx, sc, v24, e30, &pu, &pv, &rr[0], &rr[1]);
  FUZZ(sc, 4);
  calibrate(ctx->cal, &pu, &pv);
  if (is_still) {                                 /* no filter: the single-frame estimate */
    put_gains(ctx, obj, exp_gain(ctx, 0, pu), exp_gain(ctx, 1, pv), S);
    return;
  }
  z[0] = pu; z[1] = pv;
  rr[0] = reff(ctx, rr[0]); rr[1] = reff(ctx, rr[1]);
  FUZZ(sc, 5);
  kalman(sc, ctx->kf, z, rr);
  FUZZ(sc, 6);
  sc->g0 = exp_gain(ctx, 0, sc->mu[0]); sc->g3 = exp_gain(ctx, 1, sc->mu[1]); sc->fb = 0;
  put_gains(ctx, obj, sc->g0, sc->g3, 0);
}
