# Shadow and highlight correction (GR IV fw 1.11)

Tags: `[E]` emulated bit-exact, `[C]` read from code, `[I]` inferred. Python model: `tools/re/shadow_ref.py`; unicorn harness for the real core: `tools/re/shadow_emu.py`; check: `tools/re/shadow_check.py`
(400 random cases, firmware strength / level / gain table vs the model: **0 mismatches**, re-run when these notes were written) [E].

## 1. Settings and records

- Shadow setting `P[0x7E5]` (core: `sb[0x54]`): 0 = Auto, 1 = Low, 2 = Medium, 3 = High, 4 = Off.
- Highlight correction `P[0x7E4]`: 0 = Auto, 1 = On, 2 = Off. `P[0xBB7]` = highlight correction applied (this is also AWB's S+0x51, +1 EV in the AWB position, and the makernote byte 0x0069 byte 0, see dng-tags.md).
- Core entry `0x5391F230` (ToneControlTuning, `src/R2Y/ToneControlTuning.cpp`: `m_ShadowAdjustmentTone[ForTag]`, `WaveDetectCorrect`). Related: curve builder `0x5391F084`, fixed byte LUT copy `0x5391F1BC`, wrapper `0x5391F888`, HW program `0x5391EE80`.
  The module list at the context (this+0x154 .. 0x18C) are `ImageTuning` members; 0x180 is the ToneControlTuning. Look struct `0x54080AB8`: +9..+0xB = 77, 150, 29 (luma weights), +0x14 = 0x0FFF, +0x16 = 0 [C].
- Harness call (shadow_emu.py): `core(THIS, THIS+0x14, OUTB, SB, LVL)`, `sb+0x130` = P pointer, `sb+0x53` = hl, `sb+0x54` = setting, `sb+0x44` = ISO index (u16), `sb+0x8D` = mode (0 still / RAW development, 1 and 2 live view / movie, 3),
  `sb+0x8A` / `sb+0x8B` = forced-zero bytes. Results: `this+0x822` strength (u16), `this+0x821` recomputed flag, `this+0x14` the 1024-entry u16 gain table, level in `*LVL`. The stat-to-Y builder `0x538F75FC` is skipped (the array is supplied by the test).

## 2. Y blocks (what the core sees)

`0x538F75FC` is the WaveDetectCorrect method. In its mode 2 [E, mode2_emu.py]:

```
Y[r][c] = low16( ((S[r*5w + c] - ped) * g) >> 13 )         S = u32 hardware statistic at P+0xBC4 (sub-row 0 of each group of 5w)
g = 0x2000 (flat; arg10 = 0)
ped = (223 * (u16@P+0x14BCA + u16@P+0x14BCC) / 2 + 128 + 105 * u16@P+0x14BC8) >> 8
```

The result is stored at `P+0x24BD0` as u16[64][64] (64 x 62 used). The DNG makernote tag 0x0405 contains this array verbatim (dng-tags.md), so a user DNG shows what the core saw. The reader of the tag is `0x537F4F10..0x537F50AC` (Gb := Gr after load), the writer `0x5380E2xx..0x5380E3FC`.

## 3. Tables (firmware constants; not copied here, `tools/re/shadow_ref.py` reads them from RTOS.bin)

| name | address | content |
|---|---|---|
| TA | `0x54048F3C` | u16 x4 = [4, 1, 2, 3]: menu code (0 Auto, 1 Low, 2 Med, 3 High) -> gain-table index |
| TB | `0x54049384` | u16 x6 = [0, 256, 512, 1024, 256, 0]: gains; **index 4 (`0x5404938C`) is Auto's gain** (our build raises it from 256 to 1024) |
| TC | `0x540493A0` | u16 x97 ISO limiter, index = round(8*Sv) - 8 clamped to 0x60. Entries 0..80 are 2048; 81..87 are 1712, 1400, 1112, 848, 608, 384, 184; 88..96 are 0. (With Sv = 5.0 at ISO 100, index 81 is about ISO 6800 and 88 is ISO 12800; the arithmetic is ours, the idx formula is [C].) |
| CURVE | `0x54048D34` | u16 x256, 4096 = 1.0, monotone non-increasing from 8160 to 4096 (shadow gain curve) |
| HLTAB | `0x54048534` | u16 x1024 highlight-correction gain table (the literal is `0x54048532`, first load at +2), from 8192 (x2.0) down to 4097..; values lie in 4097 .. 8192 |

Level thresholds (strength s -> level): `s <= 0xB9` 0; `s < 0x184` 1; `s < 0x260` 2; `s <= 0x350` 3; `s <= 0x456` 4; `s <= 0x574` 5; `s <= 0x6AC` 6; else 7 [E].

## 4. Strength, the ISO limiter and the gain table

```
cap   = TC[min(idx, 0x60)]               idx = ISO index sb[0x44]
gain  = TB[ TA[setting] ]                (Auto: TB[4])
fixed settings (1, 2, 3): r3 = 0x800
Auto:                     r3 = decision (section 5)
strength = ((min(r3, cap) * gain) >> 11) & 0xFFFF
```

With the stock gains the fixed levels give strength cap/8 (Low, gain 0x100), cap/4 (Medium) and cap/2 (High, 0x400) at low ISO. Our Auto with gain 0x400 and the learned t reaches High.
Live view and movie (modes 1, 2) apply a five-frame smoothing of the raw strengths after this step (ring of the last five, first frame fills it) [E, test_fw].

Gain table built into `this+0x14` by `0x5391F084` (u16[1024], 4096 = 1.0) [E]:

- without highlight correction: `t[i] = 0x1000 + trunc(s * (CURVE[i] - 0x1000) / 1024)` for i < 256 (the division rounds toward zero: add 1023 before the arithmetic shift for negatives), `t[i] = 0x1000` above;
- with highlight correction: `cur[i] = (0x1000 + q(CURVE[2i]) + 0x1000 + q(CURVE[2i+1])) >> 1` for i < 128 (q as above, `0x1000` above), and `t[j] = (HLTAB[j] * cur[j]) >> 12` for all 1024 entries.
  The highlight path therefore multiplies the whole table by the HL gain curve (up to 2.0 in the darkest entries), because with highlight correction the raw is 1 EV darker.
- The table is rebuilt unless the strength is 0 and highlight correction is off.

## 5. The stock Auto decision and the 16-bit wrap

Stock Auto (setting 0) in `shadow_ref.strength()`, with `hl` the highlight shift and `N = w*h` [E, the model matches the real core in all 400 cases]:

```
v     = (Y << hl) & 0xFFFF                       the doubling for highlight correction
dark  = count(v <= 0x1F)
hist  = histogram of v for v < 0x200
thr   = (N * 0x51EB851F >> 32) >> 5              about N/100 (1 %)
cum   = running sum of hist[0..0x7F], wrapped to 16 bits ; idx = first i with cum > thr
no idx (or P[0x6E0] in {1, 2}):  strength forced to 0 (the multiply is skipped)
r4    = max(0x800 - 24*idx, 0)
t7    = (7N/10) & 0xFFFF ; if t7 > dark: r3 = r4 & 0xFFF8
else  t9 = (9N/10) & 0xFFFF ; if t9 < dark: r3 = 0
      else r3 = ((0x2800 * (t9 - dark) / N) * r4 >> 11) & 0xFFFF
```

**Finding: the stock Auto computes 0 on real shots.** `Y` comes from hardware sums whose values exceed 16 bits (section 2 keeps only the low 16 bits), so (our reading of why) almost no blocks fall below 0x80 and no 1 % point is found [I]; `idx` is none and the strength is forced to 0.
Run on the Y arrays of all 35 public GR IV DNGs, the model gives strength 0 for every one (`allshadow.py`, not kept; the arrays are in tag 0x0405) [E]. So the camera's own Auto does nothing on real data, and `Auto` is effectively "off" unless forced by a fixed level.
Consequence for modelling: any estimate of "what Auto would do" must use the wrapped data; a model on true luminance (the learned version in section 7 uses the AWB statistics) shows a behaviour the camera never had.
Forced-zero cases kept by our hook: `sb[0x8A]` or `sb[0x8B]` set.

## 6. Highlight correction gate (AE side)

`0x53669218` makes the decision; the AE settings are filled by `0x53681324` (A = `[this+0x10]`) [C]:

- `A[0x3AA] <- P[0x7E4]` (0 Auto, 1 On, 2 Off);
- `A[0xA0]` = minimum Sv <- `P+0x778`, `A[0xA4]` = maximum Sv <- `P+0x774` (floats; Sv 5.0 = ISO 100, 6.0 = ISO 200);
- `A[0x5B]` = applied flag (set at `0x5366CD38` from `AE+0x157C`); if `A[0x5B]` and `min < 6.0 < max`, then `A[0xA0] = 6.0` (`0x536814BC..0x5368150C`): with highlight correction applied the minimum ISO is raised to 200;
- `A[0x9C]` from a `P[0x770]` switch (table `0x53681900`).

**On and Auto use the same ISO gate** [I]: the settings fill copies `P[0x7E4]` unchanged into `A[0x3AA]` and the ISO window above does not branch on it. This was the session's conclusion; the notes do not contain a separate emulation of Auto vs On, so treat it as [I].
Effect on the pictures: the core's `hl` shift (raw 1 EV darker, every channel doubled) and the HLTAB multiplier in the gain table.

## 7. Our hook and the learned Auto (`core/src/fw/aspect/shadowml.ts`, `tools/shadowml/`)

- Hook word `0x5391F3A4` (directly after the Y-array builder call `0x5391F3A0`; the live-view call `0x5391F800` branches back to the same word, so both paths pass it): `ldr r2,[fp,#-0x450]` becomes a branch to the stub.
  The stub keeps the forced-zero cases (branch to `0x5391F784`), calls `shadowml(ctx, P = sl (r10), mode = sb[0x8D], hl = [fp-0x438], idx = r7)` with the stack 8-byte aligned, continues at `0x5391F784` (stock zero path) on a negative result, otherwise at `0x5391F4D8` with `r3 = t` and `r7 = 1`,
  exactly where the camera's Auto joins its common code. The fixed levels jump from `0x5391F334` to `0x5391F4E8` and never reach the hook.
- Auto's gain `TB[4]` goes 0x100 -> 0x400: `strength = min(t, cap) / 2` with `t = 2 * strength`.
- Model: the learned estimate of how much the median of five retouchers (MIT-Adobe FiveK, 975 images) would lift the shadows. Features (29, see `tools/shadowml/ref.py`): log2 percentiles (1, 2, 5, 10, 25, 50, 75, 90, 95, 98, 99 %) of the block luminance
  (the green plane `Gr` of the AWB statistics; independent of the white balance), mean log, the share of blocks 1..5 stops below the median, near-clipped blocks, centre vs border, the ISO index, mode, hl, valid fraction, shadow depths below the median, R/G and B/G cast.
  Gradient-boosted trees, 100 trees in the committed model (sha256 `b3895f1c...`, `shadowml-data.ts`), integer leaf values; blob format and arithmetic in `tools/shadowml/ref.py` (`t = clamp(off + ((S*mul + 0x8000) >> 16), lo, hi)`, wrapping 32-bit sum, then limited to 0x800).
  The output `t = 0 .. 0x800` is still capped by the camera's ISO limiter. Held-out regret 0.0256 vs 0.0310 for no lift and 0.0334 for the camera's own Auto rule computed on non-wrapped data (commit text). The model is data: a new blob (`gen.py [model.bin]`) needs no new code.
  The training pipeline and labels (the FiveK retoucher renders, cost curves) lived in the session scratchpad and are not in the repository; only the blob is.
- Live view / movie (modes 1, 2) run the core on every frame: the module computes on every 4th call and holds in between (state word `0x558372FC`); stills (modes 0, 3) always compute and never touch the state.
- Scratch: one `operator new` allocation of 1552 bytes, two disjoint halves of 776 bytes (stills, live view), pointer in `0x558372D4`. If the allocation fails the call returns -1 (the camera's no-correction result) and the next call retries.
  This is the same concurrency reason as in awb.md 2.11: the still and live view paths can run the core at the same time. Module stack 276 bytes.
- Tested by `tools/shadowml/test_host.py`, `test_arm.py`, `test_fw.py`, `stack_fw.py` (testing.md): hooked image vs the base image fed with t from ref.py, live-view sequences, fixed levels and forced-zero bytes identical to the base, both entry alignments of the core, instruction counts, image diff against the build without shadowLearn
  (exactly the hook word, `TB[4]`, the appended shadow area and the compensation word beyond v8c) [E].
