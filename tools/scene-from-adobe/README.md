# scene-from-adobe

Recovers the scene-referred (colorimetric) colours of GR Mod's 1026 calibration colours by undoing
Lightroom's "Adobe Standard" rendering with Adobe's own camera profile.

    python3 scene_from_adobe.py "RICOH GR IV HDF Adobe Standard.dcp"

The DCP is Adobe's copyrighted file: it is read from the given path and never stored in the repo.
Needs numpy, node and the repo's `node_modules` (esbuild bundles `bridge.ts`, which calls GR Mod's own
`Tone` from `core/src/color/look.ts`, so the inverse base tone curve is exactly the one GR Mod uses).

Chain (DNG spec 1.6, ch. 6): linear ProPhoto (D50) -> ProfileHueSatMap -> ProfileLookTable -> base tone
curve (hue preserving) -> sRGB. Starting from `CAL_ADOBE` the tool inverts the tone curve, then the
LookTable, then the HueSatMap (damped Gauss-Newton per colour, tables are trilinear), and checks the
result by running the forward model again (CIEDE2000 against `CAL_ADOBE`).
The HueSatMap data for the D65 illuminant is used (calibration colours assumed shot in daylight).

Output `out/cal_scene.json`: `scene_linear_prophoto_d50` (1026 triples), `colorimetric_srgb` (the same
colours as plain sRGB, no tone curve, clipped to gamut) and the round-trip error. These are derived numbers,
not the profile's tables.

Not modelled: BaselineExposure / exposure offsets (the scene scale is whatever GR Mod's tone model implies).
