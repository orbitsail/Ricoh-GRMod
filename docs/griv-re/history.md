# Version history of the GR IV firmware work (daily builds v1 .. v7, 8.0 .. 8.2)

Sources: the README of the earlier source archive (daily v1 .. v7, written in Chinese at the time), the commit log of `daily`, the commit messages, and the three independent reviews (`final`, `final2`, `final3`).
Hashes: "sha256 prefix" values are the ones the notes recorded for the flashed container `fwdc248b.bin` (first 16 hex digits, or as many as the note gave); `RTOS.bin` is the extracted RTOS section. Rows marked *computed* were hashed from the build files when these notes were written.
All builds are on GR Mod 0.8.6 (commit `1f4216e`), GR IV fw 1.11. Build options are in `core/src/fw/aspect/build.ts`.

## 1. Daily builds v1 .. v7 (2026-11-02 / 11-03)

| version | commit | what changed | container sha256 prefix |
|---|---|---|---|
| v1 | cpu-lut + PR #16 part | 20 looks, CPU LUT for six, bright Auto screen (PR #16), settings guard. **Wrong (numbered test) icons: dropped.** | `bf3523a62e65e78a` (~41.1 MB) |
| v2 | `daily_fw2` | icons fixed (the owner's 20 icons, 40 x 40 RGBA); without CPU correction (recommended). Option `ONLY=16` for UltraMax 400 CPU LUT only | `61095cf4b56c89b6` (~40.2 MB) |
| v3 | | Auto screen curve "balanced" with the room = official: too dark again. **Void, not flashed.** | `01a80ace6ec7715d` |
| v4 | `171f859`, `9e50fc6` | outdoor-mode Auto screen brightness between the official curve and PR #16's (curve 53 64 78 96 128 185 265 345 400 435 465 550 660 815 970 1130 1320 1500: indoors about 1.5 x official and 0.8 x PR #16; bright light as PR #16 up to 1500) | `c1c64244606007e9` (~40.2 MB) |
| v5 | `22efbae`, `014aacd` | plain Auto's tables half way to White Priority (`awbBlend` 0.5): data and a table pointer only, no algorithm change. 0 = stock Auto, 1 = White Priority | `4039dbd06baee13d` (~40.3 MB) |
| v6 | `7d1bd8c` | `awbFit`: frame 20 (neutral under ~2600-2800 K; stock corrects 34 %) corrected 73 % up to EV 11, back to stock by EV 15; one code word `0x53936830` (`add r3,r3,#0x20` -> `#0x21`) so parent 15 counts towards the AWB confidence `n20` (all Auto modes). Emulated stock-vs-model 201/201 bit-exact; the 35 daylight scenes unchanged | `b15a247e0cb99f2e` (~40.3 MB) |
| v7 | `18097b1` | learned Auto (FFCC-style, awb.md 3): replaces the plain Auto's R and B gains after the final stage; every 4th call full, 411 scenes x 3 modes checked in the emulator; studio daylight 0.02° (v6 2.6°), warm 0.01° (v6 4.2°). Nothing flown on a camera at the time | `a145572c4a2cad25` (~40.4 MB) |

The v7 build differs from v6 in two places only: one call word (`0x53938E2C`) and the 96 KB appended at the end.

## 2. v7 refinements (labels used for builds in the session; mapping to commits inferred from commit order [I])

| label | commit | change |
|---|---|---|
| v7b, v7c | | intermediate builds (referenced as baselines in the tests: `PREV_RTOS` default `fw8/v7b`); their exact purpose was not recorded [?] |
| v8 | `5ed819b` | temporal filter over the illuminant, live view (Kalman per axis; posterior spread as the observation variance) |
| v8b | `1174353` | calibrated filter variance (17-knot `R_eff` table) and the two-frame scene-change rule |
| v8c | `4c1c356` (merged into the shadow branch as `6d36628`) | separate paths for stills and live view (estimate's third argument r2 -> r7 -> `is_still`), per-path scratch regions (one `operator new`, two regions), `ctx->af89`, bounds-safe indexing (found by review), `test_fuzz.py`; live view treats the exposure as missing (`lv_exp` 1) |
| shadow | `ac0f8f4` .. `13d1ab9`, `816afc5` | learned Auto for Shadow Correction (hook `0x5391F3A4`, `TB[4]` 0x100 -> 0x400): placeholder model, then per-path scratch (pointer `0x558372D4`, module stack 276 B), the trained model (FiveK, 100 trees, sha256 `b3895f1c...`) is the committed one |

## 3. 8.x

| version | build | commit | what and why | hashes |
|---|---|---|---|---|
| **8.0** | `final` | `e6a9323` (AWB v8c + learned shadow) [I] | first build with both learned modules, reviewed independently: container OK, every differing byte vs v6 / v7b / v8c accounted for, image hook words only, 36 interleaved live-view / still estimates equal the reference. **Shipped with green stills**: the model's gains (calibrated at S+0x68/0x6E = 0x2000) were written unscaled, but at capture the stock final stage output carries the per-unit factors (~1.563 R / 3.019 B); live view (unity words) looked right. The emulator stubbed those words. | container `5d34b6ab...`, RTOS `9a10a8ee...` (review final) |
| **8.1** | `final2` | `dac35b0` (+ `77aa0c2` removing a stray empty file) | a still's gains are scaled: `(g * S[0x68] + 0x1000) >> 13` for R, `S[0x6E]` for B, at most 0xFFFF (new `put_gains` at `0x54423F30`, still only). Unity words give exactly the previous output; live view byte-identical. The module grew 10344 -> 10504 B, so the AWB stub, tables and the whole shadow area moved by 0xA0 | container `cb771e1d...`, RTOS `5ab1a674...` (review final2) |
| (intermediate) | `final3` | `da75b02` | live view "exposure mode 2": read Av/Tv/ISO floats at record +0x38D20/24/28 (`v24 = 32 nAv`, `e30 = 32 (nAv + nTv - nSv)`). **Wrong source**: those are user dial settings (exposure.md). Module grew by 0x1C0 (10 952 B); ctx `lv_exp` 1 -> 2 | container `3bece657...`, RTOS `dc00d10e...` (review final3) |
| (intermediate) | `final4` | `f3a83b2` [I] | live view output scaled by its own S+0x68/0x6E (ctx `lv_scale`, default 1; cached gains and filter state stay in model units; zero word leaves the gain alone) | container `db9678088594f6ec`, RTOS `49069d6484dcb47f` (*computed*) |
| **8.2** | `final5` | `0cecdaa` | live view exposure from the AE's ComPropIf buffers `D+0x4D8/4DC/4E0` instead of the property floats: pointer-chain validation, double read against torn values, movie fallback, quantisation bit-exact with the still builder (all 2^32 float patterns), read only on computing calls. Includes `lv_scale` | container `12196e9ec74974b9`, RTOS `370efac1f7ee72b2` (*computed*) |

Naming: the 8.0 / 8.1 / 8.2 labels come from the task description; `final`, `final2` .. `final5` are the build directory names of the reviewed files. Which of `final3` / `final4` were handed to the owner is not recorded here [?].
An extra build `final3/ns` (RTOS same length, sha `ec685a9b...`) was never reviewed and is unexplained.

## 4. Lessons recorded per step

- v6 -> v7: the stock tables could only be fitted so far; "with a lamp in the frame the estimate stays warm" needs a model over the whole statistics (learned-AWB feasibility study: lamp tests, stock 19.7 % of scenes got warmer by >= 0.15 log2 R/B with an added lamp vs 6.1 % for the learned model).
- v7 -> v8: live view runs the estimate every frame; a 4-call throttle plus a filter avoids jumps; the camera's own boxcar still follows.
- v8c: two tasks reach the estimate with no locks; any shared scratch is a bug (awb.md 2.11).
- 8.0 -> 8.1: **an emulator that stubs an input hides bugs in it** (testing.md section 3). Verify against real DNGs, and log the real gain words.
- da75b02 -> 0cecdaa: a float that exists is not necessarily live; check the writer, the setter conditions and the consumer (exposure.md).
- Static "no writer found" is not a value (awbmgr Follow-up 3's "probably 0").
