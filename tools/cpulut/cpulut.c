/* SPDX-License-Identifier: GPL-2.0-only
 *
 * GR Mod (experimental): an added look's own .cube, applied by the camera's CPU to the finished
 * pictures (Ricoh GR IV, firmware 1.11).
 *
 * The image hardware renders an added slot with its matrix, hue sectors, curves and post-curve
 * matrix, which can only come close to a 3D LUT. This module takes the rest of the way: called at
 * the start of JpegEncodeMacroProcess::Execute with the process configuration (as the halation and
 * date imprint modules), it maps every pixel of the YCbCr 4:2:2 pictures the encoder is about to
 * compress (main picture, screennail, thumbnail) through the look's correction table: what the
 * hardware gave -> what the .cube gives. GR Mod makes the table from its model of the slot.
 *
 * Table: 17 nodes over Y (node i at 16 i, the last at 256) x 33 over Cb and over Cr (node j at
 * 8 j, the last at 256); node (b, r, y) at index (b * 33 + r) * 17 + y, two words each:
 * Y' | Cb' << 16 and Cr', every value with 4 fraction bits (0..4095; results above 255 are
 * clipped). Tetrahedral interpolation with weights of 1/16. The two pixels of a pair share Cb and
 * Cr: each is looked up with its own Y, Y' goes to each pixel and the mean of the two Cb' (Cr')
 * to the pair. The context has each table's sum of words: a table that does not add up (not in
 * memory as it was built) is not used, and the pictures stay as the hardware made them.
 *
 * Which look (lookstash.ts; bits 0..7 the style, bit 16 valid): `frame`, the look at the start of
 * the exposure (or of the RAW file being developed), so that a look chosen while the picture is
 * still being processed does not change it; else `stash`, the look the development step last ran
 * with. Looks without a table are left alone.
 *
 * Position-independent: no global data, every address comes in through `struct ctx`. No division.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;

struct picture {
  u8 format;          /* 1: YCbCr 4:2:2, Cb/Cr interleaved in their own plane */
  u8 pad[3];
  u8 *y;
  u8 *c;
  u32 size;
  u16 width, height, stride, c_height;
  u16 x, y_off;
  u8 tail[4];
};

struct ctx {
  void *(*cache)(void);                              /* 0x538f0448 */
  void (*invalidate)(void *cache, u32 addr, u32 n);  /* 0x538f04d8 */
  void (*clean)(void *cache, u32 addr, u32 n);       /* 0x538f04c4 */
  const volatile u32 *frame;  /* FRAME_LOOK */
  const volatile u32 *stash;  /* LOOK_STASH */
  const u32 *tables;  /* `count` tables of NODES * 2 words */
  u32 count;
  u32 magic;          /* 'CLT2' */
  u8 look_map[64];    /* style -> table + 1, 0: none */
  u32 sum[64];        /* per table: the sum of its words; a table that does not add up is not used */
};

#define NY 17u
#define NC 33u
#define NODES (NY * NC * NC)
#define MAGIC 0x32544c43u /* 'CLT2' */
#define STASH_VALID 0x10000u
static int ram(const void *p) {
  u32 a = (u32)p;
  return a >= 0x40000000u && a < 0xc0000000u && (a & 3) == 0;
}

/* `n` bytes from `a` lie in memory a picture can be in: RAM below the firmware's image
 * (0x53000000..0x55000000, read-only), above it up to 0x80000000, or 0xA0000000..0xC0000000
 * (0x80000000..0xA0000000 has no access in the start-up translation table). */
static int span_ok(u32 a, u32 n) {
  u32 end;
  if (a >= 0x40000000u && a < 0x53000000u) end = 0x53000000u;
  else if (a >= 0x55000000u && a < 0x80000000u) end = 0x80000000u;
  else if (a >= 0xa0000000u && a < 0xc0000000u) end = 0xc0000000u;
  else return 0;
  return n <= end - a;
}

static int picture_ok(const struct picture *p) {
  u32 w = p->width, h = p->height, n;
  /* (an even stride keeps every pair's Cb, Cr halfword aligned for the assembly's ldrh) */
  if (p->format != 1 || w < 64 || h < 48 || w > 12000 || h > 12000 || p->stride < w || (p->stride & 1) || p->c_height < h) return 0;
  if (((u32)p->y & 3) || ((u32)p->c & 3)) return 0;
  /* every row of both planes, as far as the cache maintenance reaches (64-byte lines) */
  n = h * p->stride + 63;
  return span_ok((u32)p->y, n) && span_ok((u32)p->c, n);
}

/* Sum of a table's words: catches a table that is not in memory as it was built. */
static u32 table_sum(const u32 *t) {
  u32 s = 0, i;
  for (i = 0; i < NODES * 2; i++) s += t[i];
  return s;
}

static void sync(const struct ctx *k, void *cache, const struct picture *p, int clean) {
  u32 a, b;
  a = (u32)p->y & ~63u; b = ((u32)p->y + (u32)p->height * p->stride + 63) & ~63u;
  if (clean) k->clean(cache, a, b - a); else k->invalidate(cache, a, b - a);
  a = (u32)p->c & ~63u; b = ((u32)p->c + (u32)p->height * p->stride + 63) & ~63u;
  if (clean) k->clean(cache, a, b - a); else k->invalidate(cache, a, b - a);
}

/*
 * One row: the pairs of pixels from yr / cr up to cr_end (cr_end - cr even, > 0). In assembly
 * (the compiler's version needs about twice the instructions). Byte offsets in the table: Y step
 * 8, Cr step 136, Cb step 4488; the cell's far corner 4632.
 *
 * Per pair: base = node (cb >> 3, cr >> 3, 0); b = (cb & 7) * 2, c = (cr & 7) * 2 (sixteenths);
 * fhi >= flo the larger and smaller of b, c, dhi the step of fhi's axis. Per pixel: a = Y & 15,
 * v = base + (Y >> 4) * 8; tetrahedral interpolation along the axes in order of falling fraction:
 *   a >= fhi:        nodes 0, Y, Y+hi, all   weights 16-a,   a-fhi,   fhi-flo, flo
 *   flo <= a < fhi:  nodes 0, hi, hi+Y, all  weights 16-fhi, fhi-a,   a-flo,   flo
 *   a < flo:         nodes 0, hi, hi+lo, all weights 16-fhi, fhi-flo, flo-a,   a
 * lo = sum w * (Y' | Cb' << 16), hi = sum w * Cr' (16-bit lanes do not carry: 4095 * 16 < 65536).
 * Registers: r0 yr, r1 cr, r3 table, r6 base, r7 fhi, r8 flo, r9 dhi (saved: static base),
 * lr a, r12 v, r4/r5 node, r2 weight, r10/r11 sums; [sp] Cb sum of the first pixel, [sp, #4] its
 * Cr sum, [sp, #8] the last pair's Cb | Cr << 8 (its set-up is kept when the next pair has the
 * same), [sp, #16] cr_end, [sp, #20] the caller's r9.
 */
#define PIXEL(J) \
  "and   r12, lr, #0xf0\n" \
  "and   lr, lr, #15\n" \
  "add   r12, r6, r12, lsr #1\n" \
  "ldrd  r4, r5, [r12]\n" \
  "cmp   lr, r7\n" \
  "bhs   " #J "1f\n" \
  "cmp   lr, r8\n" \
  "blo   " #J "3f\n" \
  /* flo <= a < fhi */ \
  "rsb   r2, r7, #16\n" \
  "mul   r10, r4, r2\n" \
  "mul   r11, r5, r2\n" \
  "ldrd  r4, r5, [r12, r9]\n" \
  "sub   r2, r7, lr\n" \
  "mla   r10, r4, r2, r10\n" \
  "mla   r11, r5, r2, r11\n" \
  "add   r4, r12, r9\n" \
  "ldrd  r4, r5, [r4, #8]\n" \
  "sub   r2, lr, r8\n" \
  "mla   r10, r4, r2, r10\n" \
  "mla   r11, r5, r2, r11\n" \
  "mov   r2, r8\n" \
  "b     " #J "4f\n" \
  /* a >= fhi */ \
  #J "1:\n" \
  "rsb   r2, lr, #16\n" \
  "mul   r10, r4, r2\n" \
  "mul   r11, r5, r2\n" \
  "ldrd  r4, r5, [r12, #8]\n" \
  "sub   r2, lr, r7\n" \
  "mla   r10, r4, r2, r10\n" \
  "mla   r11, r5, r2, r11\n" \
  "add   r4, r12, r9\n" \
  "ldrd  r4, r5, [r4, #8]\n" \
  "sub   r2, r7, r8\n" \
  "mla   r10, r4, r2, r10\n" \
  "mla   r11, r5, r2, r11\n" \
  "mov   r2, r8\n" \
  "b     " #J "4f\n" \
  /* a < flo */ \
  #J "3:\n" \
  "rsb   r2, r7, #16\n" \
  "mul   r10, r4, r2\n" \
  "mul   r11, r5, r2\n" \
  "ldrd  r4, r5, [r12, r9]\n" \
  "sub   r2, r7, r8\n" \
  "mla   r10, r4, r2, r10\n" \
  "mla   r11, r5, r2, r11\n" \
  "add   r4, r12, #4608\n" \
  "ldrd  r4, r5, [r4, #16]\n" \
  "sub   r2, r8, lr\n" \
  "mla   r10, r4, r2, r10\n" \
  "mla   r11, r5, r2, r11\n" \
  "mov   r2, lr\n" \
  /* the far corner, weight in r2 */ \
  #J "4:\n" \
  "add   r4, r12, #4608\n" \
  "ldrd  r4, r5, [r4, #24]\n" \
  "mla   r10, r4, r2, r10\n" \
  "mla   r11, r5, r2, r11\n"

static void row(u8 *yr, u8 *cr, u8 *cr_end, const u32 *t) {
  register u8 *r0 __asm__("r0") = yr;
  register u8 *r1 __asm__("r1") = cr;
  register u8 *r2 __asm__("r2") = cr_end;
  register const u32 *r3 __asm__("r3") = t;
  __asm__ volatile(
    "push  {r2, r9}\n"
    "sub   sp, sp, #16\n"
    "mvn   r4, #0\n"
    "str   r4, [sp, #8]\n"            /* the last pair's Cb | Cr << 8: none yet */
    "5:\n"
    /* the pair's Cb | Cr << 8; the cell set-up is kept when it is the previous pair's */
    "ldrh  r4, [r1]\n"
    "ldr   r5, [sp, #8]\n"
    "cmp   r4, r5\n"
    "beq   8f\n"
    "str   r4, [sp, #8]\n"
    "and   r5, r4, #0xff\n"
    "lsr   r4, r4, #8\n"
    "movw  r9, #4488\n"
    "lsr   r6, r5, #3\n"
    "mla   r6, r6, r9, r3\n"
    "lsr   r7, r4, #3\n"
    "add   r7, r7, r7, lsl #4\n"
    "add   r6, r6, r7, lsl #3\n"
    "and   r5, r5, #7\n"
    "and   r4, r4, #7\n"
    "lsl   r5, r5, #1\n"
    "lsl   r4, r4, #1\n"
    "cmp   r5, r4\n"
    "movhs r7, r5\n"
    "movhs r8, r4\n"
    "movlo r7, r4\n"
    "movlo r8, r5\n"
    "movlo r9, #136\n"
    "8:\n"
    "ldrb  lr, [r0]\n"
    PIXEL(6)
    "uxth  r2, r10\n"
    "add   r2, r2, #128\n"
    "usat  r2, #8, r2, asr #8\n"
    "strb  r2, [r0]\n"
    "lsr   r10, r10, #16\n"
    "str   r10, [sp]\n"
    "str   r11, [sp, #4]\n"
    "ldrb  lr, [r0, #1]\n"
    PIXEL(7)
    "uxth  r2, r10\n"
    "add   r2, r2, #128\n"
    "usat  r2, #8, r2, asr #8\n"
    "strb  r2, [r0, #1]\n"
    "ldr   r2, [sp]\n"
    "add   r2, r2, r10, lsr #16\n"
    "add   r2, r2, #256\n"
    "usat  r2, #8, r2, asr #9\n"
    "strb  r2, [r1]\n"
    "ldr   r2, [sp, #4]\n"
    "add   r2, r2, r11\n"
    "add   r2, r2, #256\n"
    "usat  r2, #8, r2, asr #9\n"
    "strb  r2, [r1, #1]\n"
    "add   r0, r0, #2\n"
    "add   r1, r1, #2\n"
    "ldr   r2, [sp, #16]\n"
    "cmp   r1, r2\n"
    "blo   5b\n"
    "add   sp, sp, #16\n"
    "pop   {r2, r9}\n"
    : "+r"(r0), "+r"(r1), "+r"(r2), "+r"(r3)
    :
    : "r4", "r5", "r6", "r7", "r8", "r10", "r11", "r12", "lr", "cc", "memory");
}

static void correct(const struct ctx *k, void *cache, const struct picture *p, const u32 *t) {
  u32 w = p->width & ~1u, h = p->height, r;
  sync(k, cache, p, 0);
  for (r = 0; r < h; r++) {
    u8 *yr = p->y + r * p->stride, *cr = p->c + r * p->stride;
    row(yr, cr, cr + w, t);
  }
  sync(k, cache, p, 1);
}

/* Entry: k = context, config = JpegEncodeMacroProcess configuration. */
void cpulut(const struct ctx *k, u32 *config) {
  u32 st, style, e, i, j;
  const u32 *t;
  struct picture *seen[4];
  void *cache;
  if (k->magic != MAGIC || !ram((const void *)k->frame) || !ram((const void *)k->stash)) return;
  st = *k->frame;
  if (!(st & STASH_VALID)) st = *k->stash;
  if (!(st & STASH_VALID) || !ram(config) || !ram(k->tables)) return;
  style = st & 0xff;
  if (style >= 64) return;
  e = k->look_map[style];
  if (!e || e > k->count || e > 64) return;
  t = k->tables + (e - 1) * (NODES * 2);
  if (table_sum(t) != k->sum[e - 1]) return;
  cache = k->cache();
  /* One picture per buffer (another entry with the same planes describes the whole sensor). */
  for (i = 0; i < 4; i++) {
    struct picture *p = (struct picture *)config[(0x3c >> 2) + i];
    seen[i] = 0;
    if (!ram(p) || !picture_ok(p)) continue;
    for (j = 0; j < i; j++) if (seen[j] && seen[j]->y == p->y) break;
    if (j == i) seen[i] = p;
  }
  for (i = 0; i < 4; i++) if (seen[i]) correct(k, cache, seen[i], t);
}
