// Node-side bridge to GR Mod's colour code (core/src/color) for the original-base tools. Bundled with esbuild by obase.py.
// stdin: JSON {op, ...}; stdout: JSON. Slots are {M1, ck, P2?} with ck as 3 arrays of 17 numbers.
//   {op:"cam"}                          -> {cam}                     CAL_CAM (1026 x 3, flat)
//   {op:"adobe"}                       -> {adobe}                   CAL_ADOBE
//   {op:"fitTarget", target, title?}    -> {params, meanDE2000, p95DE2000, meanDE, p95DE}   convertTarget
//   {op:"fitCube", path, base}          -> same, convertCube(file, {base})
//   {op:"fitCubeText", text, base}      -> same
//   {op:"apply", params, rgb}           -> {out}                     slotApply
//   {op:"de2000", a, b}                 -> {d}                       per-colour CIEDE2000 between two flat sRGB buffers
//   {op:"cube", path, rgb}              -> {out}                     applyCube (trilinear/tetra as GR Mod does)
import { readFileSync } from 'node:fs';
import { CAL_ADOBE, CAL_CAM, convertCube, convertTarget, deltaE2000Lab, lab, slotApply } from '../../core/src/color/index';
import { applyCube, parseCube } from '../../core/src/color/cube';

const req = JSON.parse(readFileSync(0, 'utf8'));
const toParams = (p: any) => ({ M1: p.M1, ck: p.ck.map((c: number[]) => Float64Array.from(c)), ...(p.P2 ? { P2: p.P2 } : {}) });
const fromConv = (c: any) => ({
  params: { M1: c.params.M1, ck: c.params.ck.map((k: ArrayLike<number>) => Array.from(k)), ...(c.params.P2 ? { P2: c.params.P2 } : {}) },
  meanDE: c.meanDE, p95DE: c.p95DE, meanDE2000: c.meanDE2000, p95DE2000: c.p95DE2000,
});
let res: unknown;
switch (req.op) {
  case 'cam': res = { cam: Array.from(CAL_CAM) }; break;
  case 'adobe': res = { adobe: Array.from(CAL_ADOBE) }; break;
  case 'fitTarget': res = fromConv(convertTarget(Float64Array.from(req.target), { title: req.title })); break;
  case 'fitCube': res = fromConv(convertCube(readFileSync(req.path, 'utf8'), { base: req.base })); break;
  case 'fitCubeText': res = fromConv(convertCube(req.text, { base: req.base })); break;
  case 'apply': res = { out: Array.from(slotApply(toParams(req.params), Float64Array.from(req.rgb))) }; break;
  case 'de2000': res = { d: Array.from(deltaE2000Lab(lab(Float64Array.from(req.a)), lab(Float64Array.from(req.b)))) }; break;
  case 'cube': res = { out: Array.from(applyCube(parseCube(readFileSync(req.path, 'utf8')), Float64Array.from(req.rgb))) }; break;
  default: throw new Error('unknown op');
}
process.stdout.write(JSON.stringify(res));
