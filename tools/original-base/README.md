# original-base

Fits GR IV slots to the *original* log -> look LUTs (Fujifilm F-Log2 -> film simulations, ARRI LogC3 Look Library) instead of
to the photo-input re-bases. Nothing third-party is stored here: the LUTs are read from `--src`, outputs go to `--out`.

    python3 run_all.py [--out /home/claude/work/out] [--src <folder with the LUTs>]   # fits, cubes, re-import check, compare.csv
    python3 sheets.py  [--out ...]                                                   # patch sheets (PNG)
    python3 preview.py in.jpg slot.json out.jpg                                       # slot applied to a Ricoh Standard JPEG

Needs numpy, scipy, Pillow, node, the repo's `node_modules` (esbuild bundles `bridge.ts`, i.e. GR Mod's own `convertTarget`,
`convertCube`, `slotApply`) and `tools/scene-from-adobe/out/cal_scene.json`.

## Pipeline (`obase.py`)

1. `scene_linear_prophoto_d50` (1026 colours, arbitrary scale) x k -> XYZ D50 (ROMM/ProPhoto matrix) -> Bradford -> XYZ D65.
2. -> linear gamut of the family: BT.2020 (= F-Gamut) for Fuji; ARRI Wide Gamut 3 for ARRI (ARRI's published AWG3 -> XYZ matrix,
   `ARRI, "ALEXA LogC Curve - Usage in VFX", 2017`, as listed in colour-science `ALEXA_WIDE_GAMUT_RGB_TO_XYZ_MATRIX`).
3. log encode, scene-linear with 0.18 = mid grey, no 0.9 reflection factor:
   * F-Log2: Fujifilm "F-Log2 Data Sheet" Ver.1.0; a=5.555556 b=0.064829 c=0.245281 d=0.384316 e=8.799461 f=0.092864 cut1=0.000889
     (y = c log10(a x + b) + d above cut1, e x + f below). The constants are taken from colour-science `CONSTANTS_FLOG2`; the
     LUT overview PDF shipped with the LUTs has no formula.
   * ARRI LogC3 EI 800: ARRI "ALEXA LogC Curve - Usage in VFX" (2017-03): cut=0.010591 a=5.555556 b=0.052272 c=0.247190
     d=0.385537 e=5.367655 f=0.092809 (y = c log10(a x + b) + d above cut, e x + f otherwise).
4. trilinear lookup in the 33^3 LUT (inputs clamped to 0..1, output clipped to 0..1 as GR Mod does).
5. **Assumption:** the LUT output (BT.709 / Rec.709 look) is used *directly* as GR Mod's display (sRGB-encoded) target, with no
   transfer-function conversion, which is exactly how the existing photo-input cubes treat their output.
6. `convertTarget(target, ...)` (core/src/color/convert.ts) fits the slot: the same fit as `convertCube(..., {base: 'adobe'})`
   but with the target given. Errors are CIEDE2000 of `slotApply(slot, CAL_CAM)` against the target on the 1026 colours.

## Exposure

One scene gain k for both families: 1-D least squares in log k so that the FLog2_to_PROVIA rendering of the near-neutral
calibration colours (CAL_CAM chroma < 6, CAL_CAM L* 25..75) matches CAL_CAM in CIE L*. Result and residual are printed by `run_all.py`
(`<out>/exposure.json`).

## Baked cubes

GR Mod imports .cube files with the 'ricoh' convention (the LUT acts on Standard-rendered display colours), so every fitted slot
is written as a 33^3 cube whose entry at grid point P is `slotApply(slot, P)` and re-imported with `convertCube` to check it
reproduces the slot (mean CIEDE2000 on CAL_CAM, printed by `run_all.py`).
Slots: `<out>/slots/{current,adobe,original}/NN Name.json` ({M1, ck, P2} under `params`, plus fit errors).

## Real-raw version (`run_real.py`, `realscene.py`)

`cal_scene.json` turned out about 2.5x under-saturated, so `run_real.py` replaces it with real data: `/home/claude/work/dngcheck/pairs.json`
(block means of 10 GR IV DNGs: `scene_linear_prophoto_d50` colorimetric from each DNG's own ColorMatrix, and the camera's Standard JPEG `jpeg_srgb`).

    python3 run_real.py [--out /home/claude/work/out2] [--cur /home/claude/work/out] [--src <LUT folder>] [--prev <photos>]

* Training set: stratified by JPEG CIELAB hue (12) x L* (5) x chroma (3) with a common cell cap, plus up to 300 near-neutrals; two whole images are held out
  as the test set (`choose_holdout`: the pair of images whose hue histogram / chroma best match the pool).
* k: one global gain on the scene so FLog2_to_PROVIA(F-Log2(k*scene)) matches the JPEG L* on near-neutral pairs, L* 25..75.
* Fit: `convertPairs(source, target)` (core/src/color/convert.ts; `convertTarget` is now `convertPairs(CAL_CAM, target)`), bridge op `fitPairs`.
  Errors are CIEDE2000 of `slotApply(slot, JPEG colours)` against the original-LUT target, on train and on the held-out images.
* Compare / cubes / sheets as above, written to `--out`. The data covers little red, magenta, cyan: those sectors are extrapolated by the fit.
