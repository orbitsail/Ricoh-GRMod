import { describe, expect, it } from 'vitest';
import { CAL_ADOBE, CAL_CAM, convertCube, convertXmp, deltaE2000Lab, lab, slotApply } from '../src/color/index';
import { percentile } from '../src/color/math';
import { encodeTableText, makeRgbTable, nameXml, xmpDoc } from './color-helpers/xmp-encode';

function cubeOf(n: number, f: (r: number, g: number, b: number) => number[]): string {
  const lines = ['TITLE "test"', `LUT_3D_SIZE ${n}`];
  for (let b = 0; b < n; b++) for (let g = 0; g < n; g++) for (let r = 0; r < n; r++)
    lines.push(f(r / (n - 1), g / (n - 1), b / (n - 1)).map((v) => v.toFixed(6)).join(' '));
  return lines.join('\n') + '\n';
}
const identity = cubeOf(33, (r, g, b) => [r, g, b]);
const warm = cubeOf(9, (r, g, b) => { const v = (r + g + b) / 3; return [v, v * 1.02, v * 0.98]; });
const mean = (a: ArrayLike<number>): number => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i]; return s / a.length; };
const de = (a: Float64Array, b: ArrayLike<number>): { mean: number; p95: number } => {
  const d = deltaE2000Lab(lab(a), lab(Float64Array.from(b)));
  return { mean: mean(d), p95: percentile(d, 95) };
};

describe('convertCube base', () => {
  it("'ricoh' is the default", () => {
    for (const t of [identity, warm]) {
      const a = convertCube(t);
      expect(convertCube(t, { base: 'ricoh' })).toEqual(a);
    }
  });

  it("identity cube with base 'adobe' renders CAL_CAM close to CAL_ADOBE", () => {
    const cam = Float64Array.from(CAL_CAM);
    const before = de(cam, CAL_ADOBE);
    const res = convertCube(identity, { base: 'adobe' });
    const after = de(slotApply(res.params, cam), CAL_ADOBE);
    const xmp = convertXmp(xmpDoc({ PresetType: 'Look', RGBTable: 'AA11', Table_AA11: encodeTableText(makeRgbTable(5, (r, g, b) => [r, g, b])) }, nameXml('Identity')));
    const viaXmp = de(slotApply(xmp.params, cam), CAL_ADOBE);
    console.log(`CAL_CAM vs CAL_ADOBE dE2000: mean ${before.mean.toFixed(3)} p95 ${before.p95.toFixed(3)}`);
    console.log(`identity cube, base adobe: mean ${after.mean.toFixed(3)} p95 ${after.p95.toFixed(3)} (reported ${res.meanDE2000.toFixed(3)} / ${res.p95DE2000.toFixed(3)})`);
    console.log(`identity xmp (RGB table): mean ${viaXmp.mean.toFixed(3)} p95 ${viaXmp.p95.toFixed(3)}`);
    expect(after.mean).toBeLessThan(before.mean);
    expect(after.mean).toBeLessThan(2);
    expect(res.meanDE2000).toBeCloseTo(after.mean, 9);
    // the cube path is the same computation as convertXmp for an identity look
    expect(after.mean).toBeCloseTo(viaXmp.mean, 2);
  });

  it("base 'adobe' skips refine with a warning", () => {
    const res = convertCube(warm, { base: 'adobe', refine: true });
    expect(res.refined).toBeUndefined();
    expect(res.warnings.length).toBe(1);
  });
});
