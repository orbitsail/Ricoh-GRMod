# Stock auto exposure (AE): measured behaviour and accuracy

Question: is the camera's own auto exposure accurate enough that replacing it could pay off? This is a black-box study from DNG files; no firmware was changed for it. What the firmware does (metering input, weights, target, program lines, convergence) is read in exposure.md, section "Stock AE: metering and target (read-only study)", where the code was read.
Tags: `[I]` marks an interpretation. The numbers are measurements on the data below and carry the uncertainty stated next to them. Names of photos are not recorded here (public DPReview files and user-supplied DNGs).

## 1. Result in five lines

1. In ordinary scenes the AE keeps the frame's mean log brightness about 3.5 to 3.7 EV below sensor white (after undoing highlight correction and exposure compensation), with a typical scatter of +-0.3 EV. It is consistent.
2. Against five professional retouchers (MIT-Adobe FiveK) the camera JPEG is about 0.2 EV brighter than their average, 90 % interval 0.1 to 0.4 EV. The retouchers differ from each other by more than that: one wants the image 0.6 EV darker than the camera makes it, one 0.2 EV brighter. [I] No systematic exposure error to correct was found.
3. The method cannot see per-scene errors smaller than about 0.4 EV (the retouchers' own disagreement), so "no detectable error" is not "no error".
4. Highlights: of the 31 frames with EC = 0, 5 have more than 0.1 % of their raw samples at or near sensor white and 2 have more than 1 % (DSLR shots in FiveK: 36 % and 16 %, but they include manual and compensated shots we cannot filter out). Most of the margin is HC, a 1 EV drop of the exposure that the camera takes on purpose (in Auto it is switched on by a near-white block in the picture and by ISO 200 or more, section 9); no other highlight rule was seen in the data. [I]
5. Weak spots: a lit lamp in a dark room (the AE protects the lamp: the five frames of this kind sit 0.5 to 3.1 EV below its usual level, and the retouchers' model prefers the four darkest brighter, by roughly 0.5 to 1.4 EV, the size depending on how it is converted) and the ISO ceiling at night. Both rest on very few frames.

## 2. Data

- 35 public DPReview GR IV DNGs (firmware 1.01, aperture priority, one photographer, mostly a daylight walk) and 8 user-supplied DNGs from a GR IV HDF (firmware 1.11 mod build, program AE, indoor, night). 43 files in total.
- Display-domain comparison: only frames with exposure compensation 0 and a correct embedded JPEG. Seven of the user's frames come from a build with the white balance bug (green JPEG): raw statistics are used, their JPEG is not. 24 frames remain, 22 independent scenes (three of them are one burst at the same EV).
- Reference: MIT-Adobe FiveK, 1005 raw files with five experts (A..E) each; 974 usable (all five versions present, exposure data present).
- The FiveK scenes are not unlike the GR scenes: the median nearest-neighbour distance of the GR frames in the feature space is 1.25, FiveK to FiveK 1.26 (review); one frame is an outlier (4.5).
- Narrowness of the sample: all public files are from one day and one photographer; only three have an exposure value below 8 (two at ISO 6400 / 8000, one at ISO 250). Everything about dim scenes rests on those and on the user's frames.

## 3. Method

Luminance on both sides is a colorimetric Y.
- Raw side (GR and FiveK identical code): black-subtract, divide by (white - black), half-resolution CFA binning, Y = wY . (R, G, B) with wY from the inverse DNG ColorMatrix at the scene's colour temperature (no ForwardMatrix on the GR), default crop, EXIF orientation, 384 px long side. A sample counts as clipped at 98 % of the white level.
- Display side: experts' TIFFs are ProPhoto with a pure 1.8 gamma (205 of 205 sampled TIFFs, read from the ICC), decoded with a LUT and the ProPhoto D50 luminance weights; the GR side is the sRGB decode of the full-size JPEG in the DNG (sub-IFD 1), Rec. 709 weights. Y = 1 is the display white on both sides. L* (CIE) percentiles of Y give the brightness profile.
- Prediction of what the experts would do: gradient boosted trees (depth 3, 250 iterations, five 85 % subsamples) from exposure-invariant raw shape features (relative log-luminance quantiles 2..98 %, spread, top minus bottom, centre minus all, 4 x 4 cell spread and cell maximum) plus a scene brightness index `ev100 = log2(N^2 / t) - log2(ISO / 100)`. The as-shot level is not a feature. Target: the median L* of the experts' images (and each expert separately).
- Gap = predicted expert median L* - the camera JPEG's median L*, converted to EV with each frame's own raw-to-JPEG slope at its median (mean 17.3 L* per EV, divided by at least 6).
- Noise floor: the five experts' median L* differ by an SD of 8.0 L* (about 0.46 EV) per scene; the model's cross-validated error is 7.6 L* (6.2 to 6.5 with the as-shot level as a feature).
- Re-derived independently (a second reader, other code): the L* and Y conventions, the orientation handling (all 43 files match their own JPEG at zero shift, rank correlation of log luminance 0.92 to 0.995, flipped versions 0.04 to 0.79), the medians of 3 FiveK and 3 GR frames, and a k-nearest-neighbour version of the gap.

## 4. What the AE regulates (measured)

The level is `mean over the frame of log2(G / white)` of the green samples (raw, relative to white, values floored at 2^-12), plus 1 for HC on, minus the exposure compensation. 41 frames with ISO below 3200:

| statistic | value (EV below white) |
|---|---|
| median | -3.66 |
| interquartile range | -3.95 .. -3.41 |
| median absolute deviation | 0.28 |
| SD (all, including lamp scenes) | 0.74 |
| median, EC = 0 frames only (29) | -3.50 |
| median of the per-frame median instead of the log mean | -3.58 |

- The same quantity for the FiveK DSLR raws (Y instead of G, as shot, 1005 files from several bodies, manual and compensated shots included): median -3.84, 10 to 90 % range -5.29 .. -2.79, SD 1.08. The GR with the same definition (Y, HC and EC undone, 41 frames): median -3.52, range -4.28 .. -3.19, SD 0.62. Levels are not strictly comparable between sensors (white level conventions), but the GR's spread is much narrower.
- Six frames lie more than 0.7 EV from the median, all of them darker: five of the user's indoor frames (four of them lamp scenes) and one dim daylight frame. None is brighter.
- A centre-weighted power mean (p = 0.7) of the luminance fits the level better than the plain log mean: SD 0.40 EV against 0.64 .. 0.74. Dark-room scenes with a lamp still sit 2 to 3 EV below the normal level, so a highlight / point-light term exists on top [I].
- The makernote's EffectiveLV (0x002D / 1024) is the exposure setting in EV100 plus the compensation (mean +0.04, SD 0.13), not an independent scene measurement (dng-tags.md).
- HC (makernote 0x0069 byte 0) acts like a base ISO of 200: the raw is about 1 EV lower with HC on, the DNG BaselineExposure is higher by about 1 EV (HC off -0.55 .. -0.51, HC on +0.31 .. +0.49). In these files HC is 1 at ISO 200, 250, 400, 500, 800, 6400, 8000 and 0 at ISO 100 (all public files) and at ISO 640 (two user files). The code settles what HC is (exposure.md, section 4 of the AE study; section 9 here): a user setting with Auto / On / Off; On applies it at ISO 200 or more, Auto also needs a near-white block in the central part of the picture and a headroom test [C]. So HC 0 at ISO 100 is forced by the ISO gate, and the two ISO 640 frames with HC 0 mean Auto without a near-white block, Off, or an Auto exclusion, depending on the camera's setting [?].

## 5. Camera against the retouchers

Sign: negative = the camera is brighter than the expert would make it. 24 frames, EV:

| | A | B | C | D | E | consensus (mean of five) |
|---|---|---|---|---|---|---|
| mean gap | -0.64 | -0.33 | -0.27 | -0.06 | +0.17 | -0.23 |
| per-scene SD | 0.39 | 0.45 | 0.44 | 0.46 | 0.45 | 0.41 |

- Consensus, 90 % interval: 0.09 to 0.39 EV (the camera brighter), resampling both the scenes and the FiveK training set. 20 of 24 frames have the consensus darker than the camera.
- Same with the 22 independent scenes: -0.24 [-0.38, -0.09].
- Per-scene SD of the gap (0.41 EV) is no larger than the experts' disagreement (0.46 EV): nothing scene-dependent is visible above the noise.
- Dependence on the scene: no trend of the gap with the scene brightness index once the two frames at ISO 6400 / 8000 are set aside (22 frames: slope 0.01 EV per EV100, r = 0.06); with all 24 the correlation is 0.43, carried by the ISO 8000 frame. Without those two frames the mean gap is -0.30 EV with a per-scene SD of 0.28 EV. By thirds of ev100 (all 24; negative = camera brighter): dark -0.04 (SD 0.57, contains the ISO 8000 frame), middle -0.29 (0.19), bright -0.36 (0.33). HC on -0.21 (20 frames), HC off -0.34 (4 frames): no difference worth reading.
- The gap grows with the AE's own level scatter (slope about 0.3 EV per EV of level, r = 0.39, 22 frames; 0.6 and r = 0.62 with all 24), not 1.0 [I]: when the AE sits higher or lower than its usual level, the retouchers partly follow, so part of that scatter is scene-justified.
- Independent cross-check (k = 15 nearest FiveK neighbours, 24 frames): experts minus camera = -3.4 L* (SD 6.4), about -0.20 EV, interval -5.5 .. -1.1 L*; per expert A -11.2, B -5.1, C -3.5, D -0.7, E +3.5 L*. Same signs and order.
- Robustness (all give the same direction and size): other model families and feature sets, ev100 perturbed, dedup of the burst, and the as-shot level of each image added as a feature (see below): -0.27 and -0.19 EV for two ways of defining that level.
- **The reference is not independent of the camera it was shot with.** After the shape features and ev100 are accounted for, the experts' L* still rises by about 4.9 L* per EV of as-shot level (partial correlation 0.37): the retouchers started from the DSLR's exposure. So the target contains some of the DSLR AE. The camera's default rendered level (log mean plus BaselineExposure) has a median of -3.97 against -3.89 for the FiveK DSLRs, so this can move the gap by only about 0.1 EV; but "the GR AE agrees with retouched DSLR images" is weaker than "the GR AE is right". [I]
- Brightness here means the rendered JPEG including the camera's tone curve, shadow correction and highlight correction, not the raw exposure alone.

## 6. Highlights

Share of EC = 0 frames with raw samples at or above 98 % of white:

| set | n | more than 0.1 % of samples | more than 1 % |
|---|---|---|---|
| GR, all | 31 | 5 (16.1 %) | 2 (6.5 %) |
| GR, ISO below 3200 | 29 | 4 (13.8 %) | 1 (3.4 %) |
| GR, HC on, ISO below 3200 | 21 | 4 (19.0 %) | 1 (4.8 %) |
| GR, HC off (all ISO 100) | 8 | 0 | 0 |
| FiveK DSLR shots | 1005 | 35.7 % | 16.1 % |
| GR, exposure value 11 or more (daylight) | 15 | 3 (20.0 %) | 1 (6.7 %) |
| FiveK, exposure value 11 or more | 488 | 30.3 % | 13.7 % |

- The two GR frames above 1 % are a daylight frame with a bright sky (3.4 %) and a night frame at ISO 6400 (1.7 %, probably over-counted, see below). The other three above 0.1 % are two daylight frames (0.45 % and 0.13 %) and the user's lamp frame (0.8 %).
- Counts are tiny: with 31 frames the GR rate at the 0.1 % level has a 90 % interval of 7 to 31 % (exact binomial), and 1 to 19 % for 2 of 31 at the 1 % level. HC off is eight frames (six independent scenes): no conclusion about the AE alone.
- HC is why the GR looks safer [I]: with HC on the raw is about 1 EV below the level the same AE would give with HC off (section 4), so the raw keeps 1 EV more headroom than a DSLR exposed to the same display brightness. A DSLR that is exposed without such a margin clips more. In Auto the HC test looks for a near-white block, so this margin follows the scene (section 9). At ISO 100 HC does not exist: the eight ISO-100 frames did not clip, but they are too few to say whether the AE alone leaves enough room there.
- The FiveK count includes deliberate manual and compensated exposures which the available table cannot separate, so it is an upper bound for the DSLR auto exposure; the GR advantage in this table is therefore larger than a clean comparison would show.
- The white level written in the DNG is below true saturation (16383) at ISO 6400 / 8000 (white level 14320, black 1024): real white is about 0.21 EV above "1.0" there, so the clipped share is slightly over-counted at those frames. Below ISO 400 the effect is under 0.02 EV.

## 7. Weak spots

- **Lamp in a dark room.** The AE regulates to the lamp (point-light protection) and leaves the room below its usual level. The user's frames are the only ones of this type (4 of the 6 outliers in section 4; the other two are a lit desk indoors and a dim daylight frame), all in one room, all with the green JPEG of the white-balance bug (their luminance is slightly off), so these numbers are a hint, not a measurement:

| frame | HC | ISO | AE level below the usual -3.66 (EV) | raw 99.9 % point (EV from white; > 0 = at white) | experts' preference, brighter(+): slope conversion / curve inversion (EV) |
|---|---|---|---|---|---|
| lamp 1 | on | 500 | 0.5 | +0.75 | +0.22 / +0.26 |
| lamp 2 | on | 200 | 1.05 | +0.10 | +0.69 / +0.41 |
| lamp 3 | on | 200 | 1.5 | -0.15 | +1.14 / +0.62 |
| lamp 4 | off | 100 | 2.2 | -0.47 | +1.09 / +0.52 |
| lamp 5 | off | 100 | 3.1 | -1.19 | +1.42 / +0.78 |
| usual level, HC off | off | 640 (two frames) | -0.2 and -0.24 (slightly above the usual level) | -1.9 | -0.18, -0.10 / -0.40, -0.36 |

  The two conversions differ by up to a factor of two because the camera's tone curve is flat in these dark frames (local slope 7 to 9 L* per EV for the two darkest, against 17 elsewhere), and the model extrapolates: FiveK holds few lamp-in-the-dark scenes. The direction is the same in all five and the two frames at the usual level show no such gap. The raw 99.9 % point of the HC-on lamp frames is at or near white, so the lamp is nearly clipped even though the room is dark.
- **ISO ceiling.** One night frame at ISO 8000 (the highest ISO in the set) sits low: most likely the auto ISO limit and the slowest allowed shutter speed were reached, so the AE could not reach its usual level [I].

## 8. Limits of this study

- 24 display-domain frames (22 scenes), mostly daylight, from one photographer; public files are firmware 1.01 and the user's are 1.11. Conclusions for dim and artificial-light scenes rest on a handful of frames.
- The JPEG compared is the preview embedded in the DNG; it was not checked against a camera-written JPEG of the same exposure. (A white-balance-bug frame's JPEG turned green as the bug predicted, which supports "same pipeline" for colour, not for tone.) [?]
- The Image Control look of each file was not read: the public files look like the default.
- FiveK exposure compensation and exposure program were not available (the raw files had been deleted after processing).
- The makernote decode of HC beyond its exact agreement with BaselineExposure is not independently verified.
- Cross-validation folds are by image, but FiveK contains bursts; the quoted model error is slightly optimistic.
- There is no absolute "correct" exposure: the camera was compared with what retouchers choose, which is a taste distribution (width about 0.46 EV per scene, 0.8 EV across the five).

## 9. What the firmware code says (read separately; exposure.md, "Stock AE: metering and target")

Static reading only, nothing emulated: [C] read from code, [I] inferred, [?] unknown.
- Input: the hardware block statistics become a 64 x 64 grid of `x = log2(Y) - 9`. A low-light lift `g(EV100)` is added per block: +1.5 EV for scenes at EV100 of 2 or less, fading to 0 at 5, 0 up to 12, -0.5 above 16. Dim scenes are metered brighter than they are, so the picture stays darker [C; intent I].
- Multi-segment metering: M = 0.35 centre-weighted mean + 0.35 mean of zone 1 + 0.15 mean of zone 3 + 0.15 mean of the brightest blocks, minus a 0 to 0.5 EV correction, with two floors against the dark zones. Centre-weighted and spot are plain weighted means. About fifteen constants in all [C].
- Target: P0 = +0.1456 in x units (Y = 566 of a full scale that is not pinned; 2.85 EV below white if the scale is 12 bit), 1 EV lower when HC is applied. Exposure compensation is not in the metering: it enters the program (Ev = Bv - EC), so M settles at P0 + EC [C data flow, I conclusion].
- HC: user setting Auto / On / Off. Off never applies it; On applies it at ISO 200 or more; Auto also needs at least one block of the central 52 x 52 with x of 2.5 or more (near white) and a headroom test [C]. This corrects the older note that On and Auto share one gate (shadow-highlight.md section 6).
- Face and AF-frame matches can replace M when a state word is 0; their formulas were not decoded [C entry, ?].
- Not found: a backlight flag, a snow / sky / beach rule, a night-scene switch, a point-light rule other than the HC block test. The still-capture stages and part of the per-frame logic were not read, so absence there is [?].
- Not read: the controller's step sizes and smoothing, the 28 register-domain AE modes, the ISO-ceiling behaviour of the program, which zone wedge is "sky".
- Against the measurements, no outright disagreement: the -3.66 EV level fits only if the Y full scale is x = 3 (12 bit), the target then being 2.85 EV below white, with the bright-weighted terms closing the gap to the mean; a centre- and bright-weighted blend explains why a power mean fits better than a plain log mean; the lift g, the brightest-block term and the floors darken lamp scenes (the amounts need those frames' block arrays); EffectiveLV = EV100 + EC follows from the program equation; no HC at ISO 100 agrees [I].
- Weak spots from the code [I]: the one-block trigger of HC Auto, the deliberate dim-scene darkening, no backlight classifier, fixed zone weights.

## 10. Consequence for the fork

[I] No replacement of the AE. The measured average error is about 0.2 EV, smaller than the experts' own spread, and the method cannot see anything under 0.4 EV per scene. The only visible weak spot (lamp in a dark room) is a trade-off the stock design chose in favour of highlights (the bright-part term and the HC drop). The metering itself is small (about fifteen constants), so a patch would be cheap, but what it can do is a global exposure offset or a different weight of the bright-part term: highlights traded for shadows, with nothing in the data saying the stock trade is wrong. The controller and the program are large, were not read, and the whole loop cannot be exercised in the emulator; a wrong exposure cannot be fixed afterwards.
If it is ever wanted, the narrowest candidates (addresses in exposure.md section 9 there) are the three target literals (global offset; the HC -1 and +1 must stay paired) and the bright-part weight (the weights must keep summing to 1), to be checked on frames from a camera before anything is flashed. None of this was tried on a camera.

## 11. Reproduction

The scripts that produced these numbers (extraction of the DNG luminance and JPEG, makernote scan, FiveK table, the expert model, the robustness runs, the figures) are in the owner's archive, not in this repository; they need the FiveK raw files and the user-supplied DNGs (not in the repository either), and the readers in `tools/shadowml/train/tools`. The same luminance recipe was used for the FiveK shadow model (shadow-highlight.md).
