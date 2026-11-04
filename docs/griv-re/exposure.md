# Exposure: where the live view and the still get Av / Tv / Sv

Firmware 1.11, static RE (capstone) plus emulation of the stock still builder against our integer reader. Tags: `[E]` emulated, `[C]` read from code, `[I]` inferred.
Why it matters: the AWB scene prior uses the scene brightness `e30 = 256 * (Av + Tv - Sv)` (8.8 EV). A still gets it from the exposure object; the live view record carries none (awb.md 2.4).

## 1. Corrections (old -> new)

| old claim | new | source |
|---|---|---|
| awbmgr Follow-up 3: LV e30 is probably 0 (record word +0x38D30 never written) | true that nothing writes +0x38D30, but irrelevant: the live exposure comes from the AE's property buffers (section 2) | lvexp |
| awbmgr Follow-up 6 / "mode 2" (8.0 final3, da75b02): the floats at record +0x38D20/24/28 (Av, Tv, ISO) are the published exposure properties "what the UI shows"; LV Bv = still e30 | they are the **user's dial settings**, written by the property setters only when a numeric value is set (an Auto ISO, value 0 or >= 0xFFFE, sets an invalid flag and leaves the float alone). Not the live exposure | lvexp, review final3 item 5 |
| review final3: 0x537FDA48 (Tv), 0x537FDB00 (Av), 0x537FE38C (ISO) are getters (those are the Tv and ISO property-float branches and the Av entry; the function entries are Tv 0x537FD980, Av 0x537FDB00, ISO 0x537FE310, with the property-float branches at 0x537FDA48, 0x537FDB80, 0x537FE38C; review final5) that use +0x38D24 etc. only in manual modes, contradicting "what the UI shows" | they are **EXIF tag writers** (`CommonExifEntryDataSetter`, class typeinfo 0x53FA639C, vtable 0x53FA6348, dispatcher 0x537FE414 on EXIF tag ids). They write the property value into the EXIF only when the exposure mode is set by hand and fall back to +0xB98/+0xB9C/+0xBA0 otherwise | lvexp |
| `+0x38D20..` words 0..2 "likely mirror P[0xB98], P[0xB9C], P[0xBA0]" | they do not mirror the still fields in auto modes (they are stale or invalid there) | lvexp |

8.2 (commit 0cecdaa, final5) replaced the property-float read ("mode 2" of da75b02) by the AE read below.

## 2. The chain (all [C] unless tagged)

```
AE (task) exposure-program functions     I+0xD0 Tv, I+0xD4 Av, I+0xD8 Sv  (I = AeInternalInformation object)
  -> publisher 0x536822DC (AeInternalInformation.cpp)
       Tv = I+0xD0 (0x536836AC), Av = I+0xD4, Sv = I+0xD8
       Sv limited by 0x53683830(I) when byte I+8 is set (0x5368260C)
       posts kind-0 messages ids 0x5D (Tv), 0x5E (Av), 0x5F (Sv) via 0x53752D14 / 0x53752E30 / 0x53752F4C (id 0x60 -> D+0x4E4 via 0x53753068), post routine 0x538DD430; all called only from 0x536822DC
  -> ComPropIf task executes the setters (slot 3 0x5375AD68, kind 0 -> 0x5375AB34, table RAM 0x55018EF8 = image 0x54394538):
       id 0x5D Tv 0x5374D028 -> 0x5375E97C;  0x5E Av -> 0x5375E9BC;  0x5F Sv -> 0x5375E9FC;  0x60 +4E4
       they write X[1] + offset (and X[1]+0xD20..), then commit 0x5375CD2C: swap X[0] / X[1], then memcpy(new X[1] <- new X[0], 0x1090) (memcpy 0x53156140 uses NEON vld1.8/vst1.8)
  -> read side: D = X[0]:  Tv float D+0x4D8,  Av float D+0x4DC,  Sv float D+0x4E0,  D+0x4E4 (P[0xBA4] uses it)
```

Objects:

- Singleton `S0 = 0x5537960C` (guard word `0x55379608` bit 0; getter `0x5372B620`). `E` = ComPropIf = `[S0+4]` = `[0x55379610]`: created by `0x5372B6B0` kind 1: `new(0x51C)` at `0x5372B6EC`, ctor `0x537500D8`, stored at `0x5372B700`;
  vtable `0x53F8EDE8`; mutex `E+0x2C`. No delete path found in the singleton code, so it lives for the session [I].
- `X = [E+0x518]`: `new(0xC)` at `0x53750258`, ctor `0x5375AE3C`, stored `0x53750274`. `X[0]` = read buffer, `X[1]` = work buffer, both halves of one 0x2120-byte block from pool 0xD
  (`0x538DD620(0xD)`, alloc at `0x5375024C`, pool table `0x5539FEF8`). Each half is 0x1090 bytes, so `|X[0] - X[1]| == 0x1090`.
- Locked getters (lock `E+0x2C`, timeout `[0x53FE18C8]` = forever): Tv `0x53756608` -> `0x5375C558`; Av `0x5375665C` -> `0x5375C568`; Sv `0x537566B0` -> `0x5375C578`. The stock live-view user of the live value is `CreateLvGainMap`
  `0x5393DF24` (called by `LiveViewGainMap` `0x5362F51C`), which calls the Sv getter.
- Writers of the AE triple: the I+0xD0/D4/D8 triple is written by 14 AE exposure-program functions `0x5367BB30 .. 0x5367E46C` (each sets all three), `0x53678DBC` (Tv, Av) and `0x5367A7B4` (Sv).
- Publish triggers: `0x53682654` <- `0x5368267C` <- the AE LV loop `0x53665CE8` event bit 1 (`0x53665E84` normal path, `0x53666170` skip path); `0x536826A4` (bits 0x10..0x100); `0x5367B008` (capture shooting info; re-publishes before reading back).
  Bit 1 is set by `0x5366633C` case event `0x040E0001` (`0x536663C0..0x53666414`) when `0x53666218` says so (frame-phase tables at `0x53EB4E94..`, or >= 0x50 ticks since the last publish `[this+0x84]`): a per-LV-frame cadence, few frames or <= ~80 ms [I].

## 3. The still record fields

The still builder takes Av, Tv, Sv from the record P (shooting record) and S+0x24/0x28/0x2C/0x30 from them:

| P field | meaning | written by |
|---|---|---|
| P[0xB98] | Av (float) | `0x5367B0A0..E4` from the locked getters `0x5375665C` / `0x53756608` / `0x537566B0` in `0x5367B008` (also bit-4 handler `0x53665D5C`, AE command `0x20000004` = message `0x61C40802`, AeCommandListener `0x5368555C` case `0x536856F0` -> `0x53685EFC`, = FE step `0x303`; FESequencePlanner map `0x53659700..0x5365971C`, table `0x53EB2684`) |
| P[0xB9C] | Tv (float) | the same; may be overwritten from a sensor / exposure register at `0x53659DD4` (FESequenceController, also P+0x4D8 / P+0xBAC) when rec+0x974 == 0 and further conditions (truncated in the original notes); source `[obj+0x6EC]` u32, (v - C)/8 EV |
| P[0xBA0] | Sv (float), raw getter value, **no -1 EV added by the builder** | the same |
| P[0xBA4] | uses D+0x4E4 [I] | |
| P[0xBB7] | highlight correction applied -> S+0x51 (+1 EV in the AWB position) | |
| P[0xB11] | capture exposure marker (1 for kinds 9/0xA/0xD, set by `0x537111C8`) | |

Order Av, Tv, Sv. Sv scale: 5.0 = ISO 100, 6.0 = ISO 200 (ISO = 3.125 * 2^Sv).

LiveViewWhiteBalance::Execute copies the message record's +0xB98..0xBB7 into P_lv (0x5364A338..0x5364A354, confirmed by eye at 0x5364A338..54), but **no LV-path writer of +0xB98..0xBA0 was found** (only `0x5367B0A4..` on FE step 0x303 and `0x53659DD4` for Tv), so those are stale in live view [I].

## 4. Quantisation (the stock still builder, which our reader copies exactly)

Both S builders turn APEX values into integers as the still builder `0x53933D84` (`0x53933E10..0x53933F64`) does:

```
na = (int)(68 + 8*Av) - 68      S+0x24 = 32*na            (= 256*Av on the half-stop grid)
nt = (int)(68 + 8*Tv) - 68      S+0x28 = 32*nt
ns = (int)(8*Sv - 8) + 8        S+0x2C = 32*ns
S+0x30 = 32*(na + nt - ns)       (= v24 + v28 - v2c)
```

The float arithmetic is `vmla`/`vnmls` (product by 8 exact, sum rounded to nearest-even to 24 bits) then `vcvt.s32.f32` (toward zero). `awbml.c` `fl8()` reproduces this with integer code only and was checked on **all 2^32** bit patterns against strict float32
(`tools/awbml/test_fl8.c`) [E]; it rejects NaN, infinity, |x| >= 16 and sums <= 0. The test suite also compares the module with the stock still builder on emulated runs (test_fw section 5).
Property converters (user settings side, for reference): Av `0x538F5120` (F*10 looked up in a 27-entry table -> index/2; fallback trunc(2*log2(F²)+0.25)/2), Tv `0x538F53C0` (num/den in the 40-entry table at `0x53FE5E10` -> index/2-5; fallback trunc(2*log2(1/t)+0.25)/2),
Sv `0x538F55B8` (35-entry table -> index/2+1; fallback trunc(2*log2(ISO/3.125)+0.25)/2; ISO 100 -> 5). Ranges Av 0..13, Tv -5..14.5, Sv 1..18. Setters `0x538210FC` Tv, `0x5382116C` Av, `0x538211E0` ISO, `0x53821250` EC store at
rec+0x38C00+0x124/0x120/0x128/0x12C with invalid flags at rec+0x38CD1/CD0/CD2/CD4; dispatcher `0x53821320` (property ids 0x12 Tv, 0x13 Av, 0x14 ISO, 0x16 EC).

## 5. How the module reads it (`lv_exposure` in awbml.c, `ctx->lv_exp == 2`, live view only)

1. `S+0x70 == 4` (movie / full grid) -> fail. Guard word `0x55379608` bit 0 must be set.
2. `E = [0x55379610]`: non-null, 4-aligned, inside RAM `[0x55000000, 0x80000000 - 0x520)`; `[E]` must equal the vtable `0x53F8EDE8`.
3. `X = [E+0x518]`: non-null, aligned, in RAM. `a = [X]`, `b = [X+4]`: aligned, `|a - b| == 0x1090`, and each buffer `[p, p+0x1090)` inside one of the two RAM ranges (`0x55000000..0x80000000`, `0x40000000..0x53000000`).
4. Read the three words at `a + 0x4D8 + 4k` **twice** (and the pointers again); accept only when pointers and words agree (the commit swaps the buffers and memcpys under a lock the module does not take); two tries, else fail.
5. All three zero -> fail. Quantise as in section 4. Accept only `na` in [8, 80], `nt` in [-40, 120], `ns` in [24, 120] and `e30` in [-1800, 3100]. Result `v24 = 32*na`, `e30 = 32*(na + nt - ns)`.
6. Any failure (and a movie live view) falls back to "exposure missing" (`v24 = -0x880`), the behaviour without this source. Stills never use this path (they read S).

Verified by host and ARM tests with an emulated property store (every broken link, torn reads, movie), exhaustive quantiser test, firmware-level parity against the stock still builder, memory-safety review (the module reads only the slot word, the planes and exactly the three words) [E]
(review final3: 32 288 direct calls of the decoder vs an IEEE model, 0 differences; window edge, wrap and misaligned S[0] read only the three words or nothing; stack 24 bytes).

## 6. Open questions and the one log that would settle them

Open [I]:

1. Cadence: how stale is `D+0x4D8..` relative to the preview frame the statistics come from (publish only at bit-1 events, per-LV-frame cadence assumed)?
2. Does the AE's `Sv` already include highlight correction or dual-gain? Static analysis cannot tell. The stock estimator adds 1 EV (`S+0x51`) separately for HC; LV `S+0x51` is the byte `P+0x38D34`. If the AE's Sv already contains the HC offset the preview prior is 1 EV off with HC on.
3. Do the AE values equal what the still will use (the AE live-view target vs the capture exposure; the still's Tv may be overwritten from the sensor register at `0x53659DD4`)? The mean prior error was assessed in `ev_sensitivity` / `e8_ev_far` (review final3): colour shift of the estimate vs the true exposure for errors -8 .. +8 EV; small errors change the colour little, but we do not have the numbers recorded here.
4. Is the movie live view's buffer valid? The module refuses it (conservative).
5. Does the property buffer ever hold zeros in a valid LV (e.g. right after start-up)? The module treats all-zero as missing.

**The single camera log that would settle 1 to 3**: a log written from the hook (or from a debug build) on every computing live view call and on every still, with one record per call containing: path (live / still), `S+0x24`, `S+0x28`, `S+0x2C`, `S+0x30`, `S+0x51`, `S+0x68`, `S+0x6E`, `S+0x70`; for live view additionally the three raw words `D+0x4D8/4DC/4E0` (hex) and the pair `X[0]`, `X[1]`, plus a frame counter. Shoot: a bright and a dim scene, highlight correction on and off, exposure compensation changed in steps,
a manual-exposure dial change, a half-press then a full press for each. From it: (a) does the live record match the still record taken seconds later (questions 2 and 3, per HC state); (b) the lag after a dial change (question 1); (c) the real values of `S+0x68/0x6E` on both paths (awb.md 2.9) in the same log.
This log has not been taken; no camera access existed in the sessions that produced these notes.

## Review of the 8.2 build (final5) [E unless tagged]

- Verdict: OK to flash. Stills byte-identical to 8.1; any failure of the new read gives exactly 8.1's live view (9 failure states x 9 calls compared byte for byte).
- The read is reached only on computing live view calls; movie (S+0x70 == 4) returns before any read; every link is checked before it is dereferenced
  (45 link and edge cases with a read hook); the double read compares both pointers and all three words, with one retry.
- Pool 0xD is the "INFO" pool: base 0x5D7A0000, 1 MB, set up at 0x538E3BE0 [C]. So D lies in the accepted RAM range and the feature engages on the camera.
  Possible future hardening (not done): accept the buffers only inside [0x5D7A0000, 0x5D8A0000 - 0x1090] and drop the 0x40000000 range.
- Every accepted range is Normal RW identity-mapped memory in the boot L1 table; the device region 0x00000000..0x3FFFFFFF is never accepted.
- Quantisation: the module's fl8 (machine code, transliterated and checked in unicorn) equals a float32 model of the stock builder (non-fused vmla/vnmls,
  vcvt toward zero) for all 2^32 patterns; end to end it equals the stock still builder 0x53933D84 on 3,216 exposures. Assumes FPSCR round-to-nearest [I].
- Stack: deepest point below the estimate entry 592 B (8.1: 616 B).
- After boot the guard stays 0 until the singleton exists, and E is published only after its constructor has set the vtable, X and both buffers, so early calls fall back.
  Until the AE's first publish, D holds the constructor's values (or the last ones after playback); at most the first computing call uses them [I].
- Under 8.1 the live view's missing exposure differed from the true exposure by a median R/B factor of 1.051 on the test scenes.

## Stock AE: metering and target (read-only study)

Scope: how the stock GR IV fw 1.11 AE turns the live-view statistics into one metered value, compares it with a target and hands Tv/Av/Sv on, for P / Auto with multi-segment metering. Static reading of the decoded RTOS section only (code address = file offset + 0x53000000); nothing was emulated, so there is no [E] item here: [C] read from code, [I] inferred, [?] unknown. Functions are attributed by class and file-name strings (`AeLiveViewExposure` 0x53EB515D, `AeLiveViewCalcService`, `AeAlgorithm` 0x53EB531E, `AeInternalInformation` 0x53EB56CE, `AeCalculation/AeProgramDiagram/src/..` 0x53EB5560), not by neighbourhood. No tables or firmware bytes are copied; a few values are quoted.
Notation: AE = the `AeLiveViewExposure` object; `rec` = `[AE+8]`, its per-frame input record (not the still record S); `I` = `[AE+0x10]`, `AeInternalInformation` (settings in, results out); `m` = `[AE+0x14]`, the metering sub-object; `P` = the 0x1090-byte property record of section 5 (results at +0x4D8); `x` = log2(Y) - 9 of one block.

### A. Changes to older notes (old claim -> new claim)

| old claim | new claim | source |
|---|---|---|
| shadow-highlight.md 6: "On and Auto use the same ISO gate [I]" | Off never applies HC. On is ISO-gated only. Auto needs the same ISO gate and a scene test (at least one block of the central 52x52 with x >= 2.5) and a headroom test. | `0x53669218` [C] |
| open question 2 above: whether the AE's Sv "already includes HC" cannot be told statically | The loop adds HC itself as a separate term: target lowered by 1 EV (`0x536679CC`) and the Bv estimate E adds 1.0 to Sv (`0x53667C1C`) when the HC-applied flag `rec+0xA9` is set. Whether the published Sv (I+0xD8) contains the +1 stays [?]. | `0x53667938`, `0x53667AE8` [C] |
| README pitfall 2: the user's Av, Tv, ISO, EC words are at rec+0x38D20.. (clarification) | The property record P also carries the user's dial floats: Av/Tv/Sv/EC at P+0x6E4/+0x6E8/+0x6EC/+0x6F0 (read by `0x53665624`, signed byte at +0x6FA). Inputs, not results; the module's +0x4D8 words are the results. | [C] |

### B. The chain [C]

Statistics event (task `0x536669C0`, bit 0, stage 1 `0x5366CEF8`) -> per-frame function `0x5366C520` -> block builder `0x5366B0B8` (statistics -> x) -> metering `0x53677350` (M) -> target `0x53667938` (P0) -> d = P0 - M -> `0x53667AE8` (scene value E) and controller `0x53667C80` -> AeAlgorithm dispatcher `0x536746A4` (28 modes) -> I+0xD0/D4/D8 -> publishers `0x5377B0D0..0x5377B158`. Stages 2, 3, 4 (`0x53669CC0`, `0x5366DA10`, `0x5366ADB8`; half-press and capture variants, stage 4 meters with flash data) were not read in detail [?].

### 1. Input: hardware statistics, one float per block

- The block luminance comes from the ISP's block detection (ProAeAwbUnit): ResultWd buffers of 0x2E030 bytes, 64x64 u32 planes, luma planes at +0x14018 and +0x18018 [C]. Firmware computes no statistics; it only combines (`0x5366ABA0`, one u16 Y per block, NEON multiply), applies a per-block vignetting gain (`0x5366AEE0`) and takes the log (`0x538D3298`, Q8 log2; Y = 0 gives -9.0). Result: 4096 floats at AE+0x14AC, grid 64x64 (dims at 0x53EC2770 / 0x53EC1B20) [C]. The combine and vignetting steps were mapped but not re-read in detail.
- Full scale of Y is not pinned [?]. The AE's own constants fit x = 3.0 (12-bit): the HC test uses x >= 2.5 and the target is x = +0.1456 [I].
- Verdict: small and fixed.

### 2. Metering: five means, three weight literals, two floors

`0x53677350(m, s0 = EVset, r3 = x array)`: m[2] = s0 (EV of the exposure that made the frame, Tv + Av - Sv with Sv 5 = ISO 100 [I]); m[0] = t0 = plain mean of x over the crop window (`0x536764FC`, margins `0x5367645C`); m[1] = m[2] + 5.0 (EV100 [I]); then a switch on the metering mode I+0x13E (<- P[0x773]): 0 multi `0x53676A10`, 1 centre-weighted `0x53675E68`, 2 spot `0x53675938`, 3 highlight `0x53676F20` [C].
Work array (`0x53674D98`): work = x + g(u), u = x + m[1] - m[0], i.e. the block's EV100. g (`0x53674CFC`) is piecewise linear: +1.5 for u <= 2, falling to 0 at u = 5; 0 for 5 < u <= 12 (a literal at 0x53674D94); falling to -0.5 at u = 16, -0.5 above [C]. Dim scenes are therefore metered up to 1.5 EV brighter than they are (the picture stays darker), very bright scenes up to 0.5 EV darker (picture a little brighter) [C; intent I].
Multi-segment [C], all in the log domain (means of log, never a log of a mean):
- w = window mean of work; cw = centre-weighted mean; z0, z1, z3 = means of zone labels 0, 1, 3 (`0x53676118`); h = mean of the blocks above m2, where m2 = mean of the blocks above t0 (`0x53676918` applied twice).
- cw' = (cw + w)/2 if w > cw else cw; z1' the same with z1; z3' = max(z3, w).
- M_raw = 0.35 cw' + 0.35 z1' + 0.15 z3' + 0.15 h (the weight of w itself is the literal 0.0; weights are the literals at 0x53676E60 / 64 / 68).
- c = clamp(0.2 (2.5 - (h - t0)), 0, 0.5), scaled by (16 - EV100)/4 for 12 < EV100 <= 16 and 0 above 16. Then a = M_raw - c; if z0 - 1.5 > a then a = min(z0 - 1.5, a + 1); if z1' - 1.5 > a then a = z1' - 1.5. M = a.
- If I+8 == 0, a face or AF-frame match can then replace M (section 3).
Centre-weighted: sum(w x)/sum(w) with a 16x16 u8 map indexed by block >> 2: 32 at the centre, 0 in the corners, 18 maps chosen by 6 * view + column (view from the crop class `0x53675E3C`, column from I+0x56E via table 0x53EC0A8C) in the RAM pointer table 0x550181E4; map sums run from 2408 (widest) to 620 (tightest) [C].
Zone labels: 16x16 u8 maps with labels 0..6 (centre 2x2 = 5, ring = 0, wedges 1..4, outer ring 6), RAM pointer table 0x5501819C. A selector I+0x39D (0..2, <- P[0xD8]) permutes which wedge a zone means (tables 0x53EC0A74..0x53EC0AA8); I read it as an orientation selector so that the same side is "up" [I]. Which wedge is sky is therefore unresolved [?].
Spot: unweighted mean of work over the central 8x8 blocks (4x4 in the 50 mm class; the 35 mm class has its own branch at 0x53675C20, not read) [C]. Highlight (mode 3): centre-rectangle maximum `0x53676870`, the same "mean above" helper, factors 0.8 / 0.7 / 0.3 and a thirds average; not restated [C entry, ?].
Crop class I+0x3B2 is set from a float zoom factor at P+0x7DC: < 1.2 -> 0, < 1.7 -> 1, < 2.6 -> 2, else 3 [C] (the 28 / 35 / 50 mm crops [I]); it selects window margins (0 / 6 / 14 blocks [I]) and map set.
Verdict: small and fixed. The whole multi-segment rule is about fifteen constants and two map families.

### 3. Scene logic

Found [C]: low-light lift g; the bright-part terms inside M (h at 15 %, correction c, floors z0 - 1.5 and z1' - 1.5); HC with its scene test (section 4); face match (predicate `0x53674F20`, flag I+0x39C <- P[0x769], count I+0x17C, function `0x536752F0` with `0x53674F58`); AF-frame match (predicate `0x53674EA8`, link I+0x39E <- P[0x78C], rect I+0x3B4, function `0x53675C70` with `0x536756D8`, `0x53675458`, `0x536758C0`). Both matches run only when I+8 == 0 (I+8 = P[0x76F] == 1; meaning [?]); their blend formulas were not decoded.
Not found: an explicit backlight flag, a snow / sky / beach rule, a night-scene switch, a point-light rule other than the HC block test (searched the metering functions and the per-frame function; stages 2 and 3 not read, so absence there is [?]).

### 4. Target and compensation

- Target `0x53667938`, x units: P0 = log2(431.0 * 1.314) - 9 = +0.1456 (Y = 566.3); project type 4 (`0x538E7FD0`, byte via the pointer at 0x553A0850) uses 478.0 * 1.0 = -0.0993; constants at 0x53667A4C / 50 / 54. Plus a bias word AE+0x1494 that is only ever written 0.0 (`0x53667680`, `0x53667794`). Minus 1.0 when `rec+0xA9` (HC applied) is set, except when the state byte AE+0x1501 is 0x0B or 0x16 [C].
- d = P0 - M. The scene value `0x53667AE8`: E = (AE+0x1488 + AE+0x151C) + bias + Tv(sensor) + terms - (Sv + 1 if HC) - d, Tv(sensor) = log2(1e6 / time word), Sv = log2(gain word / rec+0x94) + 5.0; terms: +2.0 when sensor flag +0xB8, -2.0 when `rec+0xAA` (probably a 2-stop ND filter [I]). The bias cancels in E; P0 and HC do not [C]. E is clamped to [-12, 27] with flags at <= -6.5 and >= 22.5 (per-frame function) [C].
- Exposure compensation is not in the metering and not in P0 [C]. It enters the program: `0x536789FC` returns Ev_prog = Bv - I+0x34 - clamp(I+0x108 [+ I+0xE4 when I+0xFC == 0], -8, +8). I+0x108 is I+0x130 (<- P+0x6F0, the fourth user float after Av, Tv, Sv), set to 0 in AE modes 4, 5, 6 (`0x5367A7B4`, case 8 of `0x53681FF0`) [C data flow; that it is EC: I]. I+0x34 (`0x53681F04`, from the module at `0x53941DAC`) is also folded into E through AE+0x151C and cancels. I+0xE4 = (P+0x7C0 clamped to [0, 5.0], via I+0x90) * a table at 0x53EC2FC0 (3 columns); meaning [?]. At equilibrium in P: M = P0 + EC [I].
- HC: user setting P[0x7E4] -> I+0x3AA (0 Auto, 1 On, 2 Off). Gate `0x53669218` (result stored at `0x5366CD48`, applied flag I+0x5B): Off -> 0. On -> ISO gate only: if I+0x9C != 0 then (I+0x14 + 1) <= max Sv I+0xA4, else current Sv I+0xD8 >= I+0x14 + 1 (ISO 200; ISO 320 for type 4). Auto -> same gate AND any x >= 2.5 among rows 6..57, cols 2..53 of the x array (one block is enough) AND a headroom test against the mode's exposure limits; it holds its previous answer under a condition I did not identify (`0x536832B4`). Only the Auto scan path ends with a further forcing to 0 when AE+0x1501 is 0x0B/0x16 or I+0x3AC (<- P[0x7BB]) is 3..5; the On and hold paths return without it [C]. When applied: target -1, E +1 on Sv, minimum ISO raised to 200 (shadow-highlight.md 6), raw 1 EV darker.
- ISO window: I+0xA0 / I+0xA4 <- P+0x778 / P+0x774; base Sv I+0x14 = 5.0 (5.667 for type 4); absolute Sv limit I+0x10 = 16.0 (17.0); minimum shutter I+0x20 <- P+0x77C [I]. Shadow correction: nothing in the AE path read [?]. Metering mode does not move P0.
- Verdict: small and fixed (three target constants, one HC rule, one EC clamp).

### 5. Program

`AeProgramDiagram` dispatcher `0x5367D10C` on AE mode I+0x39: 0 P `0x5367CFBC`, 1 `0x5367BF08`, 2 `0x5367C160`, 3 `0x5367BCBC`, 4 / 5 / 6 `0x5367BB30` (no EC) [C]. P takes Ev from I+0x64 (set in `0x5367A9E8` from the `0x536789FC` value) and I+0x9C, and picks one of four line variants by I+0xC (u16 <- P[0x789]): 0 `0x5367C410`, 1 `0x5367C708`, 2 `0x5367C9E0`, 3..5 `0x5367CD38` [C]; meaning of the selector [?]. Variant 0 is float code, not a table: segments of slope 0.5 around anchors with constants 5, 7, 10, 11, 16 (Tv 7 at EV100 10, Tv 11 at EV100 16) [C, partly read; the anchor reading I], limited by the Sv window I+0xA0..A4, an Av window I+0xEC / I+0xF0 (from the lens module), a Tv floor (I+0x20) and I+0x70 / I+0x74. Behaviour at the ISO ceiling is not decoded [?]. Moderately large (about four variants times several modes).

### 6. Convergence

Controller `0x53667C80(d)`: with state not 0x0B..0x10 / 0x16 and I+8 == 0, d > +1.5 takes the branch at `0x53668834`; d < -1.5 sets AE+0x14FC = 1, AE+0x1574 = 0, and d < -3.0 takes `0x53668D64`. Otherwise d is turned into Q8 (d * 256) and combined with the Q10 log2 (table 0x53EBDF04) of the sensor time and gain words (0x2000 = 1.0x) into the next step; other compares use +-0.5, +-1.0 and counters to 3; `0x5366C3E8` is a "large change" test [C visible]. Step limits, smoothing and the AeAlgorithm hand-over (28 modes in the register domain) were not extracted [?]. Large and entangled. Still vs live view: stage 4 re-meters at half-press with flash data; whether a still reuses the last live-view result stays open (question 3 above).

### 7. Against the measured behaviour (ae-accuracy.md)

1. Level -3.66 EV below white: consistent only if Y white is x = 3: the target is then 2.85 EV below white, so the median needs M - mean(x) + mean(g) of about +0.8 EV, which the bright-weighted terms give. With a 14-bit white it would need less than -1 EV, below the -0.5 EV floor the code can produce [I]. A centre-weighted power mean fits better than the plain log mean because M is a centre- and bright-weighted blend, not a plain mean [I]. The code is not a power mean.
2. Lamp scenes 0.5..3.1 EV darker: the code has the mechanisms (g up to +1.5 EV in dim scenes, h and the floors raising M, c going to 0) but the amounts need the x array of those frames [I]. No disagreement found.
3. HC: ISO 100 never gets HC (needs ISO >= 200) [C], agrees. Two frames at ISO 640 with HC off: with the setting On the gate gives HC at any ISO >= 200 (no further exclusion on that path); with Auto it needs a block with x >= 2.5 and must pass the state / I+0x3AC exclusions. So the data mean Auto without near-white blocks, or Off, or an Auto exclusion [?]. The HC setting of those frames decides.
4. EffectiveLV = EV100(set) + EC: expected, because the program sets Ev_set = E - EC (- I+0xE4), so E = EV100(set) + EC whenever the program is not at a limit [C]. A word that tracks LV at r = 0.97 may be E; byte 109 of AEInfo cannot be mapped to a field [?].

### 8. Open questions [?]

1. Y full scale (pins every x threshold to a raw level). 2. Wedge-to-zone assignment, the face / AF blend formulas, the highlight-mode formula. 3. Controller step limits, smoothing, AeAlgorithm modes; ISO-ceiling behaviour in the program. 4. Meaning of I+8, I+0x9C, I+0xC, I+0x3AC, I+0xE4 / I+0x90, state AE+0x1501 values 0x0B..0x10 / 0x16, `0x536832B4`, the headroom test. 5. Stages 2, 3, 4: still-capture exposure vs the last live-view value. 6. Whether the published I+0xD8 includes the HC +1. 7. Whether project type 4 is the Monochrome (its ISO constants 5.667 / 6.667 / 17.0 look like a base ISO of about 160 [I]).

### 9. Interception candidates (addresses and what is available; no design)

- M, all modes: return of `0x53677350` at `0x536774A4` (s0 = M; m, I reachable); multi only: `0x53676D04` (s0 = a).
- Target: `0x53667938` return (P0 incl. bias and HC); literals 0x53667A4C / 50 / 54; HC subtract at `0x536679CC` (the 1.0 is the register loaded at `0x53667950`); bias load at `0x536679A0` (a bias there cancels in E and so only shifts the live-view loop, not the program).
- d and E: argument of `0x53667AE8` / `0x53667C80` (s0 = d); return of `0x53667AE8` (s0 = E); the HC +1 at `0x53667C1C`.
- EC / program Ev: return of `0x536789FC` (s0 = Ev_prog, I reachable); EC source `0x5367A7B4`.
- HC: gate return `0x53669218` (r0), stored at `0x5366CD48`; ISO window set in `0x53681324` (`0x536814BC..0x5368150C`).
- Constants as words: weights 0x53676E60 / 64 / 68, g plateau 0x53674D94 (0.0, but g would then jump at u = 5 and 12), HC block test `vmov #2.5` at `0x5366931C` (an immediate).
- All of these sit in code shared by live view, half-press and probably the still; a shift of P0 moves E and so the program exposure, a shift of the bias does not.
