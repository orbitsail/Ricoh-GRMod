# CPU-applied LUT (experimental)

Source: the README of the earlier session's source archive (2026-11-02), on GR Mod 0.8.6 (commit `1f4216e`), GR IV fw 1.11. Code: `tools/cpulut/cpulut.c`, `tools/cpulut/gen.py` (compiles the module to `core/src/fw/aspect/cpulut-code.ts`),
`core/src/fw/aspect/cpulut.ts`. Repository history: `04da8e5` (experimental CPU LUT correction for added slots at the JPEG step), `f307bd9` (look at the exposure, table sums, picture memory; code before the tables).

## What it does

Added look slots are rendered by the image hardware with a matrix, hue sectors, curves and a post-curve matrix; for many LUTs that is within 1-3 dE00 of the `.cube` and no closer. Before the JPEG is stored, the camera's CPU maps every pixel of the finished
pictures through a correction table (the picture the hardware made -> the picture the `.cube` makes). Live view is not changed (it shows the hardware rendering); RAW files are not changed; a JPEG developed from a RAW in the camera is corrected.

## Mechanism

- Hook: the start of `JpegEncodeMacroProcess::Execute` (`0x537034B4`), as the halation and date-imprint modules do; installed after halation so it runs first (halation and the date imprint then work on the corrected picture).
  The module maps the YCbCr 4:2:2 pictures the encoder is about to compress: main picture, screennail, thumbnail. Cache maintenance goes through `0x538F0448` (cache object), `0x538F04D8` (invalidate), `0x538F04C4` (clean).
- Table: 17 x 33 x 33 lattice over Y (node i at 16 i, last at 256), Cb and Cr (node j at 8 j, last at 256); node (b, r, y) at index `(b*33 + r)*17 + y`, two words per node (`Y' | Cb' << 16` and `Cr'`, values with 4 fraction bits, 0..4095; above 255 clipped). 148 104 bytes per look.
  Tetrahedral interpolation with weights of 1/16. The two pixels of a 4:2:2 pair share Cb and Cr: each is looked up with its own Y, Y' goes to each pixel, the mean of the two Cb' (Cr') to the pair. No division, position independent, no global data.
- Which look: `FRAME_LOOK`, the look at the start of the exposure (or of the RAW being developed), so that a look changed while pictures are still processed does not change theirs; else `LOOK_STASH` (the look the development step last ran with). Looks without a table are untouched.
- The ctx holds each table's word sum; a table that does not add up (not in memory as built) is not used and the picture stays as the hardware made it.
- Layout: ctx, module and stub are appended before the tables (code next to halation's); the tables (148 KB per look) follow.
- GR Mod builds the table from its model of the slot (fit of slot parameters `spec.json`, `icon_cov.f32`, `table.u32` per look; the fit scripts and per-look data were in the session archive).

## Numbers (simulation, 59 held-out photos; 2026-11-02)

- 18 looks vs their `.cube`: mean dE00 1.38 -> 0.66 (8-bit rounding alone is 0.37); pixels with dE > 3: 8.7 % -> 0.8 %. City 2.92 -> 0.87, UltraMax 400 2.69 -> 0.79, Pastel 2.34 -> 0.65.
- Cost: about 1.1 - 1.3 x 10^9 instructions per main picture; at 660 MHz an estimated +2 to +4 s per picture (**not measured on a camera**).
- Status when written: not run on a real camera.

## Limits

No correction in live view; the table is made for each look's default parameters, so changing saturation etc. in the camera makes it less accurate; cropping or downsizing a JPEG in playback may correct again (halation and the date imprint behave the same); RAW unchanged.

## Daily builds with it

Daily v1 used the CPU LUT for six looks (02 Reala Ace, 07 ARRI Film A, 08 ARRI City, 09 ARRI Pastel, 10 ARRI Teal Orange, 16 UltraMax 400) but had wrong icons and was dropped; v2 onward are recommended **without** the CPU correction (history.md). Earlier test builds: a full one with 18 tables (look 12 and 13 Night not corrected) and a small one with three (City, Pastel, UltraMax 400).

## Rebuilding

The source archive had `patches/` (nine commits on top of 0.8.6: two for cpu-lut, seven daily) and a git bundle; the repository's `cpu-lut` and `daily` branches now hold them. Steps: check out, `python3 tools/cpulut/gen.py`, build with the `cpuLut: [{ style, table }]` option (testing.md for the build command),
simulator checks with the old scripts `test_mod2.py`, `test_real2.py`, `check_chain2.py` (they are not in the repository). The evaluation set (250 MB) was not archived.
