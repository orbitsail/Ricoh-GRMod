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
             const unsigned char *blob, unsigned bloblen, const unsigned *offs, int fail_alloc, int reset_slot, unsigned period) {
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
  c.period = period;
  awbml_host_base = m;
  awbml(&c, obj, m + s_off);
  memcpy(objout, obj, OBJ_SIZE);
  free(m); free(obj); free(bl);
  return g_allocs;
}
