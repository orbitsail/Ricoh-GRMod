// Node-side bridge to GR Mod's own colour code (core/src/color). Bundled with esbuild by scene_from_adobe.py.
// stdin: JSON {op, ...}; stdout: JSON.
//   {op:"data"}               -> {adobe, cam, toneParams}            (CAL_ADOBE, CAL_CAM, TONE_PARAMS)
//   {op:"toPre", rgb:[...]}   -> {out:[...]}   display (sRGB-encoded) -> linear ProPhoto before the tone curve
//   {op:"toDisplay", pre:[...]} -> {out:[...]} linear ProPhoto after LookTable -> display (sRGB-encoded)
import { readFileSync } from 'node:fs';
import { CAL_ADOBE, CAL_CAM, TONE_PARAMS } from '../../core/src/color/data';
import { Tone } from '../../core/src/color/look';

const req = JSON.parse(readFileSync(0, 'utf8'));
const tone = new Tone(TONE_PARAMS);
let res: unknown;
if (req.op === 'data') res = { adobe: Array.from(CAL_ADOBE), cam: Array.from(CAL_CAM), toneParams: TONE_PARAMS };
else if (req.op === 'toPre') res = { out: Array.from(tone.toPre(Float64Array.from(req.rgb))) };
else if (req.op === 'toDisplay') res = { out: Array.from(tone.toDisplay(Float64Array.from(req.pre))) };
else throw new Error('unknown op');
process.stdout.write(JSON.stringify(res));
