// SPDX-License-Identifier: GPL-2.0-only
/* Exhaustive check of awbml.c fl8() (the integer emulation of the camera's float quantisation) over ALL 2^32 float bit patterns, against the strict
 * float32 operations of the camera (vmla / vnmls: a product by 8 and a rounded sum, no fusing; vcvt.s32.f32 toward zero), done with C float on SSE
 * (-ffp-contract=off). Build and run: gcc -O2 -DAWBML_HOST -ffp-contract=off -o test_fl8 test_fl8.c && ./test_fl8 */
#include <stdio.h>
#include <string.h>
#include "awbml.c"
const unsigned char *awbml_host_base;
u32 awbml_host_rd32(u32 a) { (void)a; return 0; }
static int ref_int(float x, int base68, int *ok) {
  volatile float p = x * 8.0f, y;
  y = base68 ? 68.0f + p : p - 8.0f;
  if (y != y || y >= 2147483520.0f || y <= -2147483520.0f) { *ok = 0; return 0; }
  *ok = 1;
  return (int)y;
}
int main(void) {
  unsigned long long bad = 0, accepted = 0, n = 0;
  for (u64 k = 0; k < (1ull << 32); k++) {
    u32 b = (u32)k; float x; int ok, base;
    memcpy(&x, &b, 4);
    if (x != x) continue;                                  /* NaN: rejected by exponent 255 */
    for (base = 0; base < 2; base++) {
      i32 got = 0; int rj = fl8(b, base ? 68 : -8, &got), want = ref_int(x, base, &ok);
      n++;
      if (!rj) {
        accepted++;
        if (!ok || got != want) { if (bad++ < 10) printf("MISMATCH bits %08x base %d got %d want %d\n", b, base ? 68 : -8, got, want); }
      } else if (ok) {                                     /* a rejection must be out of every accepted range: na/nt in [-40,120] (+68), ns in [24,120] (-8 + 8) */
        int lo = base ? 68 - 40 : 16, hi = base ? 68 + 120 : 112;
        if (want >= lo && want <= hi) { if (bad++ < 10) printf("WRONG REJECT bits %08x base %d want %d\n", b, base ? 68 : -8, want); }
      }
    }
  }
  printf("fl8: %llu pattern/base pairs, %llu accepted, mismatches %llu\n", n, accepted, bad);
  return bad != 0;
}
