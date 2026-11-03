/* SPDX-License-Identifier: GPL-2.0-only
 *
 * Host test harness for awbml.c (x86, gcc): awbml.c is compiled in (-DAWBML_HOST) together with this file into a
 * shared library that test_host.py calls through ctypes. The stats arrays, S, obj, the blob and the scratch buffer
 * are all exact-size malloc blocks, so a sanitizer sees any overrun.
 */
#include <stdlib.h>
#include <string.h>
#include "awbml.c"

const unsigned char *awbml_host_base;

static void *g_slot;
static int g_fail_alloc, g_allocs;

static void *host_alloc(u32 bytes) {
  void *p;
  g_allocs++;
  if (g_fail_alloc) return 0;
  p = malloc(bytes);
  if (p) memset(p, 0xA5, bytes);   /* the camera's scratch is not zeroed */
  return p;
}

#define OBJ_SIZE 0xAF90u

/* mem: stats arrays and S (pointers inside S are offsets into mem); returns the number of times alloc was called. */
int host_run(const unsigned char *mem, unsigned memlen, unsigned s_off, const unsigned char *objin, unsigned char *objout,
             const unsigned char *blob, unsigned bloblen, const unsigned *offs, int fail_alloc, int reset_slot, unsigned period, unsigned af89, unsigned is_still, unsigned lv_exp) {
  unsigned char *m = malloc(memlen), *obj = malloc(OBJ_SIZE), *bl = malloc(bloblen);
  struct awbml_ctx c;
  memcpy(m, mem, memlen); memcpy(obj, objin, OBJ_SIZE); memcpy(bl, blob, bloblen);
  if (reset_slot) { free(g_slot); g_slot = 0; }
  g_fail_alloc = fail_alloc; g_allocs = 0;
  c.magic = AWBML_MAGIC; c.alloc = host_alloc; c.slot = &g_slot;
  c.log = (const i32 *)(bl + offs[0]); c.bias = (const i16 *)(bl + offs[1]); c.fspec = (const i32 *)(bl + offs[2]);
  c.tw = (const i32 *)(bl + offs[3]); c.atan = (const u32 *)(bl + offs[4]); c.expa = (const u32 *)(bl + offs[5]);
  c.expb = (const u32 *)(bl + offs[6]); c.tanh = (const i16 *)(bl + offs[7]); c.gexp = (const u32 *)(bl + offs[8]);
  c.recip = (const u32 *)(bl + offs[9]); c.cal = (const i32 *)(bl + offs[10]);
  c.kf = (const u32 *)(bl + offs[11]); c.ln = (const u32 *)(bl + offs[12]);
  c.period = period; c.af89 = af89; c.lv_exp = lv_exp;
  awbml_host_base = m;
  awbml(&c, obj, m + s_off, is_still);
  memcpy(objout, obj, OBJ_SIZE);
  free(m); free(obj); free(bl);
  return g_allocs;
}

#ifdef AWBML_FUZZ
/* Adversarial scratch: at each hook point, with probability g_fuzz_permille / 1000, overwrite a random span of the scratch
 * with random bytes or a fill (0, 0xFF, 0x7F, 0x80) */
static unsigned long long g_fz = 88172645463325252ull;
static unsigned g_fuzz_permille;
static unsigned fz(void) { g_fz ^= g_fz << 13; g_fz ^= g_fz >> 7; g_fz ^= g_fz << 17; return (unsigned)(g_fz >> 11); }
void host_fuzz(unsigned long long seed, unsigned permille) { g_fz = seed * 2862933555777941757ull + 3037000493ull; g_fuzz_permille = permille; }
void awbml_fuzz(void *p, int point) {
  unsigned char *b = p;
  unsigned n, off, len, kind;
  (void)point;
  if (!g_fuzz_permille || fz() % 1000 >= g_fuzz_permille) return;
  n = sizeof(struct scratch);
  kind = fz() % 6;
  off = kind == 5 ? 0 : fz() % n;
  len = kind == 5 ? n : 1 + fz() % (n - off < 4096 ? n - off : 4096);
  if (kind == 4) { unsigned st = (unsigned)__builtin_offsetof(struct scratch, valid); off = st + (fz() % ((n - st) / 4)) * 4; len = 4 + fz() % 64; if (off + len > n) len = n - off; }
  for (unsigned i = 0; i < len; i++) b[off + i] = kind == 0 ? 0 : kind == 1 ? 0xFF : kind == 2 ? (fz() & 1 ? 0x7F : 0x80) : (unsigned char)fz();
}
#endif
