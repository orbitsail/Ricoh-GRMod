# Exposure: where the live view and the still get Av / Tv / Sv

Firmware 1.11, static RE (capstone) plus emulation of the stock still builder against our integer reader. Tags: `[E]` emulated, `[C]` read from code, `[I]` inferred.
Why it matters: the AWB scene prior uses the scene brightness `e30 = 256 * (Av + Tv - Sv)` (8.8 EV). A still gets it from the exposure object; the live view record carries none (awb.md 2.4).

## 1. Corrections (old -> new)

| old claim | new | source |
|---|---|---|
| awbmgr Follow-up 3: LV e30 is probably 0 (record word +0x38D30 never written) | true that nothing writes +0x38D30, but irrelevant: the live exposure comes from the AE's property buffers (section 2) | lvexp |
| awbmgr Follow-up 6 / "mode 2" (8.0 final3, da75b02): the floats at record +0x38D20/24/28 (Av, Tv, ISO) are the published exposure properties "what the UI shows"; LV Bv = still e30 | they are the **user's dial settings**, written by the property setters only when a numeric value is set (an Auto ISO, value 0 or >= 0xFFFE, sets an invalid flag and leaves the float alone). Not the live exposure | lvexp, review final3 item 5 |
| review final3: 0x537FDA48 (Tv), 0x537FDB00 (Av), 0x537FE38C (ISO) are getters that use +0x38D24 etc. only in manual modes, contradicting "what the UI shows" | they are **EXIF tag writers** (`CommonExifEntryDataSetter`, class typeinfo 0x53FA639C, vtable 0x53FA6348, dispatcher 0x537FE414 on EXIF tag ids). They write the property value into the EXIF only when the exposure mode is set by hand and fall back to +0xB98/+0xB9C/+0xBA0 otherwise | lvexp |
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
