# Auto white balance: stock pipeline and the learned module

Firmware 1.11. Tags: `[E]` emulated bit-exact, `[C]` read from code, `[I]` inferred, `[?]` unknown. The stock estimator was transcribed to `tools/re/awb_ref.py`
and checked against the real functions by `tools/re/awb_emu_check.py` (3502/3502 trials bit-exact at seed 1, 12 472/12 472 at seed 7 scale 4;
random inputs; the weight-map generator 0x5393808C is bypassed).

## 1. Corrections to earlier claims (old -> new)

| old claim | new | source |
|---|---|---|
| 0x53938F00..0x53939174 (estimate) and entry 0x5393931C are Auto | they belong to `CWhiteBalanceCte` (vtable 0x5421B670) | awb_spec §0 [E] |
| which child's output is final per menu WB mode: unresolved | resolved by the jump tables, see 2.8 | awbmgr Follow-up 4 [C][E] |
| temporal smoothing: none known; manager helpers not analysed | 0x53932914 is the live view boxcar average, 20-entry ring, see 2.6 | awbmgr [E] |
| 0x0405's first u16 block is encrypted/scrambled | it is the shadow core's Y-block array, `low16(((stat - ped) * g) >> 13)` | drange NOTES2 [E] (see dng-tags.md) |
| Follow-up 5, item 1: "no G-scale mismatch", no AWB-side cause of green stills found | the cause is the capture gain words S+0x68/0x6E (follow-up 5b); the G scale was never wrong | awbmgr 5b [C][E] |
| Follow-up 3/6: live view e30 = float at P+0x38D30 or the property words +0x38D20 (Av/Tv/Sv) | those words are the user's dial settings, not the live exposure; the live exposure is the AE's (exposure.md) | lvexp, final3 |
| README: stats ≈ (raw-64)/4 * vignetting gain * (0.916, 1, 0.973) | code constants use (0.920, 1.0, 0.974) "from the WhitePoint relation" (`STAT_F` in the scene generator, `KR`/`KB` in ref.py) | later value preferred |

## 2. Stock pipeline

### 2.1 Objects and call graph

- `WhiteBalanceService` singleton `0x553A1370` (vtable `0x542FE568`; init `0x5393CEAC`; getter `0x5393CF84`; GetWrapper `0x5393CFF4`) [E].
  - `svc+4` = wrapper "WhiteBalanceStill" (type 2 -> calc `0x53934398`); `svc+8` = wrapper "WhiteBalanceLv_Video" (type 1 -> calc `0x539362F8`) [E].
  - Wrapper slot 5 is `0x5393CDD8`. `wrapper+8` = the CWhiteBalance manager (ctor `0x539319D8`, 0x54 bytes).
  - Manager children: `+0x28` Auto, `+0x2C` SemiAuto, `+0x30` LightSourceDetector (OnePush family), `+0x34` ColorTemperature, `+0x38` Cte, `+0x3C` Multi, `+0x40` = S (settings block) [E].
    Child vtables: Auto `0x5421B510` (slot 2 `0x53938B28`), SemiAuto `0x542FD5E8` (`0x5393B02C`), LSD `0x542FD670` (`0x5393B7B4`), ColorTemperature `0x542FD620` (`0x5393B704`),
    Cte `0x5421B670` (`0x53938E78`), Multi `0x5421F1C0` (`0x5393AB38`).
  - **Two complete, separate sets**: still and live view each have their own manager, Auto child, S and accumulators [E].
- Live view caller: `LiveViewWhiteBalance::Execute` `0x53649F20` (vtable `0x53EB1A48` slot 4), runs when msg[+0xC] == 0x500001, copies the LV record into `this+0x40`,
  then `wrapper->slot5(wrapper, rec, this+0x38)` at `0x5364ACD8`. No counter or gating [C].
- Still caller: `WbCalcProcess` (module 0x84) Execute `0x5370D9B4`; helpers `0x5370D5D0` / `0x5370D6F8` copy the message's AWB statistics into the still record P
  (arrays at P+0x14BD0.., dims P[0xBB8], P[0xBBA]); then wrapper(kind 2)->slot5(P) at `0x5370DA58` [C].
- Auto-estimate call sites (vtable slot 2): still calc `0x539344D4` (Auto, r2 = P) when WB mode S34 > 3, `0x5393464C` (Cte, r2 = 0), `0x539347E8` (selected child, r2 = P), `0x53934A84`;
  LV calc `0x539363B0` (Auto, r2 = 0), `0x53936420` (selected child, r2 = 0). So the Auto estimate's third argument is P (non-zero) for a still and 0 for live view; the estimate keeps it in r7 up to
  `0x53938E2C` [C][E]. **This is how our hook tells the two paths apart.**

### 2.2 Estimators

Frame/row structure: 33 frames (light-source regions) x 24 brightness rows (EV -5 .. 18). Each frame has 24 rows of accumulators (f8, fC, f10, f14).

- `0x5393C4D4` frame accumulate [E]: `pos` is 8.8 EV; fl = pos>>8, ce = (pos+255)>>8, both clamped to [-5,18]; +5 = row index. w1 = u16((ce<<8) - pos) to the floor row, w2 = 256 - w1 to the
  ceil row. f8, fC, f10 += (val*w + 0x200) >> 10 (arithmetic); f14 += (d*w + 0x80) >> 8.
- Block loop `0x539376A8` [E], called from both estimators, calls vtable slot 5 per valid block: `slot5(this, Y, u, v, [sp]=pos, [sp+4]=d, [sp+8]=flag)`.
  - setup: `this+0x14 = e30 + 0x500`; `this+0x18 = (v24 == -0x880)`; `this+0x1C = S18*w*h`.
  - dark threshold: 0x20 if S70 in {2,4}; else 0 if v2c < 0xB00; 0x20 if v2c > 0x1000; else `((v2c-0xB00)<<5)*0x66666667 >> 32 >> 9`. A block is valid iff thr < v <= 0xF6D for all four channels.
  - `V0 = ((m0*0x3718*R)/S68 + 0x1000) >> 13`; `V3 = ((m3*0x632D*B)/S6E + 0x1000) >> 13`; `V1 = (m1*Gr + 0x1000) >> 13`; `V2 = (m2*Gb + 0x1000) >> 13`; `G = (V1+V2) >> 1`.
  - `Y = (0x450*V0 + 0x9CE*G + 0x1E2*V3 + 0x800) >> 12`; reject if Y <= 31.
  - `pos`: if `f18` then 0x800; else `x = ((Y+8)>>4)+1` (cap 0x200 when Y >= 0x2000), `pos = (e14-0x500) + log2_8_8(x)` (`0x538D3298`). If S50: `pos = pos*(255-fb)/255 + (fb<<11)/255`
    with the weight byte fb; if S51: `pos += 0x100` (the highlight-correction +1 EV).
  - `u = (150G - 1760V0 + 1610V3 + 0x800) >> 12`, `v = (-2263G + 935V0 + 1328V3 + 0x800) >> 12`.
  - Note: the division by S68/S6E means the stock estimator **does** depend on the capture gain words (the final output is proportional, see 2.9).
- Per-block entries. Auto slot 5 `0x53936E1C` [E]: `x = u16(sdiv(216u, Y) + 256)` (zero if >= 0x200); `y = u16(sdiv(216v, Y) + 0x50)` (zero if > 0x7F); `mask = table[x + (y<<9)]` (u32 512x128 mask table at
  `0x541DB508`; bit k-1 = frame k); mask 0 -> frame 0; frame k accumulates for each set bit; if flag == 0 and kind(row5) == 0xF, accumulate only if `mask & ~0x780000 == 0`. Returns mask.
  Cte slot 5 `0x5393931C` [E]: returns 0 if flag != 0; angle/magnitude via `0x5393926C` (atan table `0x5421B6B0`, cos*256 table `0x5421B734`); frame = trunc((angle-12)/24)+1, or 0 if mag == 0; chroma scaled (256-mag)/256, zero if mag > 256; frames 0..15.
- Row weights `h` (`0x53937BFC`) [E]: `v = ((f14*T2 + 0x80)*0x80808081 >> 32) >> 7` per row; M = max over all frames and rows; `h = v*256/M`.
  Frame sums: `Y = sum((f8*h + 0x80) >> 8)`; `c1 = sum((fC*(((T4-128)*h + 0x40) >> 7) + 0x80) >> 8)`; `c2` the same with f10 and T5; `w = sum f14*T2/255` (no rounding).
- Tables (built by `0x5393C39C`; mode 0..3 vtables Standard `0x542FE768`, Atmosphere `0x542FE848`, White `0x542FE7C8`, CTE `0x542FE868`). T2/T4/T5 are indexed `[row*33+col]`, T3 `[col*24+row]` (shared).

  | mode | T2 | T3 | T4 | T5 |
  |---|---|---|---|---|
  | 0 | 0x55053E04 | 0x55053AEC | 0x55054434 | 0x5505411C |
  | 1 | 0x55053E04 | 0x55053AEC | 0x55055094 | 0x550553AC |
  | 2 | 0x55054A64 | 0x55053AEC | 0x5505474C | 0x55054D7C |
  | 3 | 0x550556C4 | 0x55053AEC | 0x550559DC | 0x55055CF4 |

  T3 holds each frame's kind: 0, or 1..16 = its parent id. T2 = weight, T4/T5 = how much to correct towards white (128 = no correction). Menu mapping of modes to tables: see 2.8 (mode 1 = Warmth, 2 = White priority, 0 = plain Auto [I]).
  The tables are in the init-data copy, so a build can swap them (`awbblend.ts`: plain Auto half way to White Priority; `awbfit.ts`: frame 20 corrected 73 % up to EV 11).
- CTE estimate `0x53938E78` [E]: reset -> multipliers -> block loop -> h -> sums -> tail. Multipliers come from the calibration singleton `0x553A130C` (guard `0x553A136C`; +0x30, +0x34 -> u16[4]; +0x5C used by Auto when S70 == 3):
  `m0 = (sdiv(c34[0]*S68, c30[0]) * S64) >> 13`; `m1 = sdiv(c34[1]*S6A, c30[1])`; `m2 = sdiv(c34[2]*S6C, c30[2])`; `m3 = (sdiv(c34[3]*S6E, c30[3]) * S66) >> 13` (obj+0xC, 0xE, 0x10, 0x12).
  The calibration constructor `0x5393CBC4` only stores ROM pointers: c30 = `0x542FD750` {2000,2000,2000,2000}, c34 = `0x542FDD74` {3352,2000,2000,1241}, so with S64..6E = 0x2000: m0 = 0x3352, m3 = 0x1241 [E]; m0 and m3 are linear in S68 and S6E.
  If S54: frames 5..9 use the raw f8 sum for Y, trunc(-6*sumC/10) for c1, -trunc(f10sum/10) for c2; then c1, c2 negated.
  Tail: matrix words at `0x541DB4E4` (256, -295, 264/256, 68, -175/256, 323, 305); Rq, Bq = (sum+0x80)>>8; G256 = (G+0x80)&~0xFF; gR = u16(G256/Rq), gB = u16(G256/Bq) (0x100 if the divisor is 0);
  clamp to [Rmin 0x80, Rmax 0x400] etc. (obj+0x6A68..6E; constructor defaults, runtime writers not checked [?]); `R = (gR*m0 + 0x80) >> 8`, `B = (gB*m3 + 0x80) >> 8` saturated to 0xFFFF;
  obj+4 = R, +6 = +8 = 0x2000, +0xA = B (1.13 fixed point, G = 0x2000).
- Auto estimate `0x53938B28` [E]: mode byte `this+0xAF88` = S34 if 1 or 2 else 0; reset (slot 4 `0x53936FEC`); parent weights 0x100; multipliers (S70 == 3 uses cal+0x5C); block loop; weight stage;
  h; parent slot 6 (`0x53936748`) for 16 parents (`this+0x4028+0x2A4*k`, id k+1, each 33 frames; weights wy, wc1, wc2 at +0x21A/21C/21E); final stage `0x53938970`.
  - Parents count only rows whose kind == id. Parent Y = (sum((f8*h+0x80)>>8) * wy + 0x80) >> 8; c1, c2 use the unrounded (T-128)*h>>7 times f, +0x80>>8, then the weight; ids 6, 11, 15 use a matrix/ratio path with 64-bit divides.
  - Weight stages: `0x53938508` (S50 == 0), `0x53937EF4` (S50 != 0; constants P1=0x80, P2=0x10, P3=8, P5=4, P6=8, P7=0x10, P8=8, P9=8, P10=8, P11=4, P12=4, P13=4, P14=0, P15=8), `0x53937CB0` driven by parent 5's share.
    The `f18` branch zeroes parents 1..3 only when S50 == 0. Parent 13 is scaled by the S2c factor (0xC00..0xE00 maps 0x100 -> 0x40). The weight-map generator `0x5393808C` (S50 != 0) is not reimplemented [?].
  - Slot 6: `share = ((cnt>>4)*1000)/(n1c>>4)`; thresholds depend on e14 (0x300, 0x500); ramp w 0..256; `n20` accumulates w for all parents except id 15 (awbFit counts parent 15 too: the one code word).
  - Final stage `0x53938970`: `wt = min(256, n20*256/thr)`; `gR = (256-wt) + Gq*wt/Rq`, gB likewise; the matrix is not negated; same clamps and multipliers; strh result, no 0xFFFF saturation.
    It writes **+6 = +8 = 0x2000 always** (strh r7 at 0x53938AC0/CC), so R and B are on a G = 0x2000 scale [C]. It also sets `Auto+0xAF89 = (sum0|sum1|sum2 == 0)` (see 2.7).
  - The Auto estimate runs the full estimate for every WB mode (it is called regardless of the routing in 2.8).

### 2.3 Settings block S

Built from the record by the S builders (still `0x53933D88`.., LV `0x53935F84`). Layout [C layout, E for use]:

| offset | meaning |
|---|---|
| +0x00..+0x10 | five u32 pointers to the stat arrays: R, Gr, Gb, B, d (valid-pixel count); 12-bit values; channel order inferred [I] |
| +0x14 | u16 stride (blocks per row of the array) |
| +0x18 | u32 multiplier m18 (= (w*h)/4 of the block descriptor in a still; 1584 = 48x33 2x2 groups in the DNG stats) |
| +0x1C / +0x1E | u16 x0, y0 |
| +0x20 / +0x22 | u16 w, h |
| +0x24 | s32 v24 = 256 * Av (8.8 EV); -0x880 means "no exposure" |
| +0x28 | s32 v28 = 256 * Tv |
| +0x2C | s32 v2c = 256 * Sv |
| +0x30 | s32 e30 = v24 + v28 - v2c (= 256 * Bv) |
| +0x34 | u32 WB mode (see 2.8) |
| +0x50 / +0x51 / +0x54 / +0x5C | flag bytes: S50 weight-map on, S51 highlight correction applied (+1 EV in pos), S54 (= P[0x79C] == 0x17), S5C |
| +0x60 | int |
| +0x64 / +0x66 | u16 gain words (always 0x2000) |
| +0x68 / +0x6A / +0x6C / +0x6E | u16 R, G1, G2, B gain words: 0x2000 normally; **per-unit factor at capture** (2.9) |
| +0x70 | u32 mode: still 0; live view 4 if P[0x719EF] == 1 (movie / full grid) else 2; 3 selects the alternative calibration table |
| +0x74.. | per-block flag bytes |

Provenance (still builder `0x53933D88`) [C]: arrays at P+0x14BD0, +0x18BD0, +0x1CBD0, +0x20BD0, +0x26BD0; stride/w = P[0xBB8], h = P[0xBBA]; S34 = P[0x78D]; S50 = P[0x71B08]; S51 = P[0xBB7]; S54 = (P[0x79C] == 0x17);
S68..6E from the manager halfwords. For the exposure fields see exposure.md.

### 2.4 Live view vs still (same estimator, different S) [C]

| | still | live view |
|---|---|---|
| planes | P+0x14BD0 / 18BD0 / 1CBD0 / 20BD0, count +0x26BD0 | P+0x4D2C0 / 512C0 / 552C0 / 592C0, count +0x5F2C0 (same layout, 0x4000 each, count 0x6000 later) |
| stride / rows | P[0xBB8] / P[0xBBA] | u16[P+0x392A8] / u16[P+0x392AA] (data, not constants; the 64 x 62 grid cannot be proven statically) |
| x0, y0, w, h | 0, 0, P[0xBB8], P[0xBBA] (crop code skipped when P[0x770] in {9,10}) | crop from P+0x672D4/D6, P+0x38D80..86 and the grid; full grid if P[0x719EF] == 1 |
| S+0x18 | P[0xBC0] | u32[P+0x392B0] |
| S+0x34 mode | P[0x78D] | P[0x71A0D] |
| S+0x70 | 0 | 4 if P[0x719EF] == 1 else 2 |
| v24 / v28 / v2c | P[0xB98]*256 / P[0xB9C]*256 / P[0xBA0]*256 (floats; P[0x770] in {9,10}: v28 from the exposure time) | **never written by the builder**: stay 0 (emulated init 0), so v24 = 0 (not -0x880: f18 = 0), v2c = 0; S+0x30 comes from the float at P+0x38D30 which nothing writes (see exposure.md) |
| S+0x51 | P[0xBB7] | byte P+0x38D34 |
| S68..6E | manager halfwords; at capture P+0x2EC40..46 | always the manager halfwords |
| consequences | dark threshold is a ramp by v2c | dark threshold fixed 0x20; parent-13 scale by v2c always full |

The LV S builder `0x53935F84` stores S[0] = P+0x4D2C0 unconditionally (`0x5393603C..84`), so `P_lv = S[0] - 0x4D2C0` for every LV S [C]; it reads P+0x38D20 itself (`0x53935FA4`, Av for `0x538F75FC`).
There is a single caller of the LV calc (`0x53936324`), before both estimate calls.

### 2.5 Still calc `0x53934398`

- P[0x7BB] in {3,5} sets `mgr+0x49 = 1` (set in the S builder `0x53933F20`). P[0xB11] != 0 marks a capture exposure (set 1 for kinds 9/0xA/0xD by `0x537111C8`).
- Normal case: estimate on this frame's statistics, then `0x5393236C` (headroom; limiter only in the reuse path).
- P[0xB11] != 0 and `mgr+0x49` != 0 (continuous / bracket capture): after the estimate, the Auto child's +4..+0xA are **overwritten** with P[0x2EC60..66] (or the `mgr+0x1E..0x24` copy) [C]. We found that after a normal still
  those stashes hold exactly the gains our hook wrote [E], so the capture path reproduces our gains.
- P[0x7BB] == 3, P[0xB11] == 0, P[0xB1A] > 1: no estimate; results restored from `mgr+8..0x1C` (reuse path `0x53934514`). 7BB == 5 the same with an NV store (3, 0x16); `mgr+0x26` is never set non-zero [C].
- `0x5393236C` with B11 set writes P+0x2EBF0..F6 = gain*scale >> 13, scale ~ 1/min(min(R,0x100),G1,G2,B) / P+0x38AE8, clipped at 0x7FF; ratios are kept except clipping; all four clip to 2047 (no WB) when P+0x38AE8 <= ~0x400 [E].

### 2.6 Live view post-processing `0x539362F8` and smoothing

- child +4/+6/+8/+0xA >> 5 -> P+0x672D8/DA/DC/DE (8.8) -> user shift (tables A..D, 2.8) -> `0x53932914` moving average on R (P+0x672D8) and B (P+0x672DE) -> `0x53932680` headroom/clip normalisation (no step limit, flag 0)
  -> `0x53932310` copies calibration words.
- `0x53932914`: ring buffers of 20 x u16, R at `0x553A12A8`, B at `0x553A12D4`, index at `0x553A12D0`; saved mode `0x55053ABC`, saved shift `0x553A12FC` / `0x553A1300`.
  `N = clamp(K / (6 * u32[P+0x38D70] * (u16[P+0x38D74] + 1)) + 1, 4, 20)`, K = 1 000 000 (S+0x70 != 4) or 2 000 000 (S+0x70 == 4). Boxcar mean of the last N samples [E].
  P+0x38D70 is a u32 from vtable slot 0x1C of the object at [lvobj+4] (units not determined; if it is the frame period in µs the window is ~0.167 s/(m+1), 0.333 s for movie) [I]; P+0x38D74 = u16 [lvobj+0x5338].
  So the **camera's own smoothing still follows our gains in live view**.
- Reset (ring refilled with the current sample): WB mode byte P[0x71A0D] differs from the saved one, modes 0xD/0xE/0xF on every call, user shift changed, first call after boot [E].
- Hold: in modes 0 and 3 with `Auto+0xAF89 != 0` the new sample is replaced by the previous ring entry [E].

### 2.7 Auto+0xAF89 (the hold flag)

Writers: final stage `0x539389A0` (every call that reaches it: `(sum0|sum1|sum2) == 0`), Auto constructor `0x539371E4` (`0x5393749C` / `0x539374A4` clear +0xAF88/+0xAF89). The only reader is `0x53932AEC` inside the LV moving average
(path for mode byte P[0x71A0D] in {0,3}). The still calc, Cte, Multi and the manager never read it (movw/ldrb scan of #0xF89 / #0xAF89 over the whole image; the other hits at 0x5327..0x532F are getters on
shooting-record bytes). The mode byte +0xAF88 is read only by reset `0x5393701C`. Writing 0 after a valid override is correct and safe: the only effect is that the LV average takes our gains instead of holding [C][E].

### 2.8 WB mode routing (S+0x34) and the user shift

Mode byte: still S+0x34 = P[0x78D] (`0x53933F7C`); P[0x79C] == 9 and P[0x78D] == 0 -> 4 (`0x5393430C..1C`); `mgr+0x49` and P[0x78D] == 3 -> 0 (`0x539341AC..C4`).
LV S+0x34 = P[0x71A0D]; P[0x71A1C] == 9 and P[0x71A0D] == 0 -> 4 (`0x539362DC..EC`) [C].

Routing by jump tables (still `0x53934668`, LV `0x539363CC`, index mode-4, 16 entries) [C][E]:

| S+0x34 | chosen child (final gains come from) |
|---|---|
| 0, 1, 2 | Auto |
| 3 | Auto (+ Multi in a still) |
| 4..12 | SemiAuto |
| 13..15 | LightSourceDetector |
| 16..18 | ColorTemperature |
| 19 (0x13) | Cte |
| >= 20 | Auto (default `0x53934A34` / `0x539365CC`) |

Which estimates run: still, mode <= 3: Cte (r2 = 0) then Auto (r2 = P); mode 4..18: Auto (r2 = P) (`0x539344C4..D4`), Cte (r2 = 0) (`0x5393463C..4C`), child (r2 = P) (`0x539347D8..E8`); mode 19: Auto (r2 = P), Cte (r2 = P); mode 3 also Multi (r2 = P).
Live view (r2 = 0 always): mode <= 3: Auto once; mode 4..19: Auto (`0x539363A0`) then the child (`0x5393641C`); >= 20: Auto twice [E].
Final gains: still, chosen child +4/+6/+8/+0xA >> 5 -> P+0x2EBE8/EA/EC/EE (`0x539349F0..30`); LV -> P+0x672D8/DA/DC/DE (`0x53936544..88`) then shift / smoothing / headroom. Mode 3 only: R and B are recomputed from the Auto child (+4, +0xA) x user shift >> 18 (still `0x53934944..68`, LV `0x539365E4..0C`), G1/G2 from Multi in a still.
**The Auto child's output reaches nothing else in modes 4..19** [E]: with real SemiAuto / LSD / CT / Cte code and three different Auto outputs, all child objects and every P byte were identical except the stash P+0x2EC60..66 (still only).
Hence the module skip rule: our override is applied only when `this+0xAF88 == 0` (the plain Auto). Mode byte values 1 and 2 (`AF88 == S34` only for these) are White Priority / Warmth Priority; menu mapping 0 = standard Auto, 1 = Warmth, 2 = White priority, 3 = Multi
(from recorded makernote code 18 ~ stock mode 1 gains, and mode 2 ~ White priority gains) [I]; the writer of makernote tag 0x0019 was not found [?].
User shift: a = P[0x78E], b = P[0x78F] (0..28, 14 neutral); mulB = (tabA[a] * tabB[b]) >> 13, mulR = (tabD[a] * tabC[b]) >> 13; u16 tables A `0x542FE420`, B `0x542FD758`, C `0x542FE464`, D `0x542FE398`; Rg = R*mulR >> 13, Bg = B*mulB >> 13. LV uses P[0x71A0E] / P[0x71A0F]. Not emulated [?].

### 2.9 Capture gain words S+0x64..S+0x6E (the 8.0 green stills)

- S64 = S66 = 0x2000 always (still `0x539341D0/D4`, LV `0x53936260/64`). S68..6E: LV always the manager halfwords mgr[0..6] (`0x5393626C..90`). Still: B11 == 0 or `0x538D0B8C() != 0` -> mgr[0..6]; else P+0x2EC40..46 (`0x539342D8..304`).
- mgr[0..6] are initialised 0x2000 (ctor `0x539319D8`) and set by `0x53936614` (via `0x5393CE40`) from the results of `0x5393D0A4` (callers `0x5393D2E4` / `0x5393D320` for the still / LV wrappers, `0x5364ACA4`, `0x5370DD50`).
  `0x5393D0A4`: if `0x538D0B8C() != 0` (board id 2 or 7 via `0x538D094C`) -> all 0x2000; else gains from the per-unit adjustment object (`0x5372B620` -> [+8] -> [+0x20]): mode arg 1 -> fields +0xC, +0xE, +0x10, +0x12; 2 -> +4..+0xA;
  else product of fields +8..+0x14 with the current value >> 13. The LV wrapper calls with r1 = 1; the still wrapper uses the caller's argument. **These values are runtime / per-unit: not emulable** [C].
- P+0x2EC40..46 comes from `0x53931D40` (stores `0x539320AC/B0`) = a copy of CAL+0x54 table `0x542FE410` {2000 x 4}: unity in the emulator [E]. (Table layout P+0x2EC30 + 8j: j0..j6 = CAL+0x4C, 0x50, 0x54, 0x58, (0), Cte stash, Auto stash.)
- Effect: the stock final-stage output equals the 0x2000-words result times (S68/0x2000) for R and (S6E/0x2000) for B (m0 and m3 are linear in them) [E]. On the real camera at capture the factors are about **1.563 (R) and 3.019 (B)** (awbmgr 5b says
  these match the old fixed simulation-to-camera ratio K: the DNG comparison had R 0.6313 and B 0.3313, whose inverses are 1.584 and 3.018 by simple arithmetic here: B matches closely, R is 1.3 % apart; "about" is the honest wording).
- The learned module's gains are in the units of the 0x2000 words (calibrated that way), so 8.0 wrote them unscaled and stills came out green. 8.1: `out = (g * S[0x68] + 0x1000) >> 13` for R, B with `S[0x6E]`, at most 0xFFFF, for stills; 8.2 does the same for live view with
  the call's own words (ctx `lv_scale`). A zero word leaves the gain alone. Output is scaled at write time only: the cached live-view gains and the filter state stay in model units.
- Still-path check by emulation: unity words = previous build bit for bit; (0x30D4, 0x607B) = round(old * word / 0x2000) = ref.py; the camera's own gains read at the stub scale by the same factor (module/camera ratio constant to 7e-5) [E] (review final2).

### 2.10 Estimate statistics and accuracy of the model

The emulated stock Auto, fed the statistics of 35 public GR IV DNGs with b51 = 1 (EV +1) and m18 = 1584, matches the recorded white balance to a fixed ratio (R 0.6313, B 0.3313), after which R differs by 0.64 % on average, B by 0.83 %, worst 2.3 % [E]
(DNGs from firmware 1.01; awbmgr 5b identifies this fixed ratio with the capture-word factor of 2.9 [I]).

### 2.11 Concurrency

`LiveViewWb` (id 0x2E, pri 80/82, stack 16384) and `WbCalcProcess` (id 0x84, pri 84/84, stack 8192) are separate tasks on an SMP T-Kernel. No lock or semaphore call exists in either Execute, either calc, or the Auto estimate. The two managers
share nothing mutable except the RAM globals of `0x53932914` (live view only) and the read-only calibration singleton. So two Auto estimates can be in flight at once (another core, or live view preempting the still task) [C][I].
Design consequence: **per-path scratch**. Our module has one allocation of two regions, live view first, still second; a still never touches the live view region (throttle counter, cached result, filter). The same rule holds for the shadow hook (shadow-highlight.md).

## 3. The learned module (`tools/awbml/awbml.c`, `core/src/fw/aspect/awbml.ts`)

### 3.1 Hook

`0x53938E2C` is `bl 0x53938970` (the final stage) inside the Auto estimate `0x53938B28`. The hook word becomes a `bl` to a stub:

```
push {r4-r6,lr}; mov r6,r0; bl 0x53938970        ; the camera's own final stage first
movw/movt r0,#ctx; mov r1,r6 (obj); mov r2,r5 (S); mov r3,r7 (is_still); bl module; pop {r4-r6,pc}
```

The installer asserts: `0x53938B54` is `mov r7,r2`, `0x53938B40` is `mov r5,r1`, `0x53938B4C` is `mov r4,r0`, `0x53938E2C-8` is `mov r0,r4`, `0x53938E2C-4` is `sub r1,fp,#0x38`, and the call target is the final stage.
r7 == the entry's r2 at the hook in 18/18 emulated runs, r4 = this, r5 = S [E]. The module overwrites `obj+4` (R) and `obj+0xA` (B) only; G (+6, +8) stay 0x2000. The rest of the Auto estimate and the manager continue unchanged.
The image differs from the same build without awbLearn only in the hook word and the appended bytes (plus the zero-fill literal) [E].

### 3.2 Behaviour

- Only the plain Auto: `obj[0xAF88] == 0`. White Priority and Warmth Priority and all other modes keep the camera's result. For a live view call with `AF88 != 0` the cached result and filter are forgotten.
- Fallback (camera result kept): bad magic/ctx, `w` or `h` outside 1..64, allocation failure, fewer than 5 % of the pixels usable (valid-pixel sum x 20 < w*h*1584). A valid block has count in [317, 65535], min channel >= 4, max channel <= 0xF6D.
- `ctx->af89` (on in 8.x): a valid override also writes 0 to `obj[0xAF89]` (also for a repeated LV result; never on fallback or in another mode), so the LV average takes our gains instead of holding.
- **Stills**: always compute fresh from their own statistics, no throttle, no repeat, no filter, never read or write the live view region. Gains are scaled by S+0x68 / S+0x6E (2.9).
- **Live view**: full estimate on the first call and then every `ctx->period` = 4th call (about 2.2 M instructions per full estimate; the camera's own Auto is about 2.9 M); the calls in between repeat the last result (a fallback result repeats as "write nothing").
  The exposure for the scene prior: `ctx->lv_exp` (default 2): 0 use S, 1 treat as missing (`v24 = -0x880` in the module's copy), 2 read the AE's current Tv/Av/Sv (exposure.md), falling back to 1 on any failure and in movie live view (S+0x70 == 4).
  The exposure is read only on computing calls. Output scaled by this call's words when `ctx->lv_scale` (default 1).
- Measured cost: +5.7 k instructions per computing call for the filter (commit message); average about +20 % over the camera's Auto at period 4 (v7 README).

### 3.3 Algorithm (FFCC-style, Barron & Tsai 2017; `ref.py` is the bit-exact reference)

1. Per block: Gr/Gb are merged `g = (gr>>1) + (gb>>1) + ((gr|gb)&1)`. Log chroma `iu = ((lg(g) - lg(r)) >> 16) & 63`, `iv = ((lg(g) - lg(b) + V_OFFSET) >> 16) & 63` on a 64 x 64 torus, `LOG[x] = round(32*65536*ln(x+1))`, V_OFFSET = 419430.
2. Two histograms: block colours weighted by count, and local colour contrast (8-neighbourhood mean abs difference per channel, reciprocal table `RECIP[n]` for the division, exact over the used range).
3. Each is normalised and circularly convolved with a learned 64 x 64 filter by a fixed-point 64 x 64 FFT (`FSPEC` holds the filters' spectra, columns 0..32, Q16; `TW` twiddles Q30), the two results are added.
4. Score map `s = conv + B0 + e*B1 + t*B2` (Q12), where `B0..B2 = BIAS[0..2]` are learned bias maps, `e = (e30c - 1024) * 4` is linear in the scene brightness (`e30c` = e30 clamped to [-1536, 3328], i.e. EV -6 .. 13) and
   `t` is `TANH` interpolated at `e30c` (tanh(2 (e30c - 1024)/1024), Q12). When `v24 == -0x880` (no exposure) `e = t = 0`.
5. Softmax without float: `d = max(s) - s`, weight `exp(-d/4096)` from the `EXPA` (high part) and `EXPB` (low 8 bits) tables. The weights are summed to the two marginals (`pu` over rows, `pv` over columns); a circular mean on each axis
   (twiddle table `TW`, angle by CORDIC from the `ATAN` table) gives the illuminant (u, v) in Q16 log units; the posterior variance per axis comes from the mean resultant length (`LN`, `VARC`).
6. Two-point calibration (`CAL`: daylight and warm low light, measured on real GR IV studio raws): the correction moves along the line Pd -> Pt, interpolating between the daylight offset Dd and the warm offset Dt
   (parameter s clamped to [0, 1], `INV` = 2^48/|Pt-Pd|²). Gains: `exp_gain` interpolates `GEXP[2][81]` = `16*8192*K*exp(j/16 - 1)` with K = 0.6313 * 0.920 (R) and 0.3313 * 0.974 (B), result clamped to [1024, 65535].
   So the output is in the camera's R/B 1.13 units **for S68 = S6E = 0x2000**, which is why stills need the capture scaling (2.9).
7. Training/calibration data (not in the repository): 2234 SimpleCube++ scenes converted to GR IV statistics, FiveK indoor scenes for lamp tests, DPReview studio raws (daylight and warm) for the calibration (testing.md, "external inputs").
   Accuracy [E in the simulator]: studio daylight 0.02° from the grey card (v6: 2.6°), studio warm 0.01° (v6: 4.2°); SimpleCube++ test median 0.56° with exposure vs 3.51° stock Auto. Both studio numbers are in-sample (the calibration used those four shots).

### 3.4 Temporal filter (live view only)

Per axis (log-chroma u and v) on the computing calls. Observation = the calibrated estimate; its variance is the softmax-marginal spread mapped through a measured 17-knot monotone table (`R_eff`, fitted on reframed views of cube, gallery and studio scenes;
posterior sd 0.05-0.12 against a frame-to-frame sd of 0.003-0.02, which is why the raw posterior variance was useless). Kalman: first observation sets (mu, Sigma); then `Sigma += Q` (Q = 0.01² per computing call), `K = Sigma/(Sigma+R)`,
`mu += K (z - mu)`, `Sigma *= 1 - K`. Scene change: two confident frames in a row (R_eff < 0.03² on both axes) that are both far from the state in the same direction (far = (z - mu)² > 9 (Sigma + R_eff), i.e. 3 sigma; KF gate word) restart the filter at the
mean of the two; the first is held back (`cand`). A fallback call leaves the state; leaving plain Auto clears it; cached calls repeat the last output. All parameters are data in the `KF` table (flags: bit 0 two-frame rule, bit 1 restart at the mean).
Integer only: `ln` by a 257-entry table with interpolation, K by 16 shift-subtract steps.

### 3.5 Scratch layout (`struct scratch`, 35 468 = 0x8A8C bytes per region; offsets derived here from the struct, [C])

| offset | field |
|---|---|
| 0x0000 | `i32 re[4096]` |
| 0x4000 | `i32 im[4096]` |
| 0x8000 | `u32 pu[64]`, 0x8100 `u32 pv[64]` (marginals) |
| 0x8200 | `u8 rowflag[64]` (histogram rows in use) |
| 0x8240 | `u32 rrg[3][64]`, 0x8540 `u32 rbc[3][64]` (rolling 3 rows of masked block values: r|g<<16, b|valid<<16) |
| 0x8840 | `u32 crg[66]`, 0x8948 `u32 cbc[66]` (column sums, zero padded; lanes cannot overflow: 9 * 3949 < 65536) |
| 0x8A50 | `valid, left, fb, g0, g3` (throttle: result of the last full computation; `fb` = fallback) |
| 0x8A64 | `have` (filter state valid) |
| 0x8A68 | `i32 mu[2]`; 0x8A70 `u32 sg[2]` |
| 0x8A78 | `cand`; 0x8A7C `i32 cz[2]`; 0x8A84 `i32 cs[2]` (held-back scene-change candidate and its direction) |

The allocation is `2 * AWBML_SCRATCH_BYTES`: region 0 = live view (also holds the throttle and filter state), region 1 = stills (working arrays only; its state fields are unused). The pointer is kept in `0x558372DC`.
Every index into the scratch is bounds-safe whatever it contains (found by a review: the neighbour count and a log-table index used to come from scratch contents; fixed in 4c1c356 and covered by `test_fuzz.py`).

### 3.6 ctx fields (`struct awbml_ctx`, 20 words = 0x50 bytes, built by `installAwbLearn`)

| offset | field | value / meaning |
|---|---|---|
| 0x00 | `magic` | `AWBML_MAGIC` 0x4D425741 ('AWBM') |
| 0x04 | `alloc` | `operator new` 0x538E09B0 |
| 0x08 | `slot` | RAM word 0x558372DC (scratch pointer) |
| 0x0C | `log` | i32[4096] |
| 0x10 | `bias` | i16[3][4096] |
| 0x14 | `fspec` | i32[2][33][64][2] (ref.py documents it as [2][64][33][2], columns kx = 0..32) |
| 0x18 | `tw` | i32[2][64] cos, sin Q30 |
| 0x1C | `atan` | u32[24] |
| 0x20 | `expa` | u32[272] (AWBML_NEXPA) |
| 0x24 | `expb` | u32[256] |
| 0x28 | `tanh` | i16[(HI-LO)/16 + 2] |
| 0x2C | `gexp` | u32[2][81] (AWBML_NG) |
| 0x30 | `recip` | u32[9] |
| 0x34 | `cal` | i32[10] |
| 0x38 | `kf` | u32[32] Kalman parameters (the C comment says [8]; ref.py defines 32 words: R_min, R_max, Q, R_conf, gate, R_base, flags, 0, 17 knots, zeros) |
| 0x3C | `ln` | u32[257] |
| 0x40 | `period` | 4 (PERIOD) |
| 0x44 | `af89` | 1 (clear Auto+0xAF89 on override) |
| 0x48 | `lv_exp` | 2 (live view exposure source; 0, 1, 2 as in 3.2) |
| 0x4C | `lv_scale` | 1 (scale live view output by its own S words) |

Table order in the data blob (`TABLE_ORDER` in ref.py and awbml.ts): LOG, BIAS, FSPEC, TW, ATAN, EXPA, EXPB, TANH, GEXP, RECIP, CAL, KF, LN (79 KB total). Constants shared with the C code are in the generated `awbml_const.h`
(AWBML_SCRATCH_BYTES 35468, E30_LO -1536, E30_HI 3328, NEXPA 272, NG 81, V_OFFSET 419430, VARC 6640, ...). Do not edit generated files; run `tools/awbml/gen.py`.
The trained parameters (filters F[2][64][64], biases B[3][64][64]) are the input of `build_tables`; they are not in the repository (testing.md).

## 4. Open items

- Weight-map generator `0x5393808C` not reimplemented [?]; Multi class not analysed [?]; user WB shift not emulated [?]; runtime writers of the Rmin/Rmax clamps not checked [?].
- Per-unit values of S+0x68..6E: only a camera log gives them (log them from the hook; both paths).
- Whether the LV smoothing window formula's inputs are the frame period (units of P+0x38D70) [I].
- Exposure questions: exposure.md.
