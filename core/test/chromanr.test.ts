/**
 * Chroma-only noise reduction patch (core/src/fw/aspect/chromanr.ts, tools/chromanr/apply.ts).
 * Needs the official firmware 1.11: core/testdata/private/official.bin or the file named by
 * GRMOD_OFFICIAL; the suite is skipped when it is not there.
 */
import { describe, expect, it } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { Engine, fw } from '../src';

const P = new URL('../testdata/private/', import.meta.url).pathname;
const path = process.env.GRMOD_OFFICIAL || P + 'official.bin';
const have = existsSync(path);

const SITE = fw.aspect.CHROMA_NR_SITE;
const siteOffset = fw.RTOS_OFFSET + (SITE - fw.RTOS_VA);

function diffOffsets(a: Uint8Array, b: Uint8Array): number[] {
  expect(b.length).toBe(a.length);
  const out: number[] = [];
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) out.push(i);
  return out;
}

function word(d: Uint8Array, o: number): number {
  return (d[o] | (d[o + 1] << 8) | (d[o + 2] << 16) | (d[o + 3] << 24)) >>> 0;
}

describe.skipIf(!have)('chroma NR patch', () => {
  const official = have ? new Uint8Array(readFileSync(path)) : new Uint8Array();

  // The two encodings: 12800 = 0x32 ror 24, 3200 = 0xc8 ror 28.
  it('has the instruction words of mov r2,#12800 and mov r2,#3200', () => {
    expect(fw.aspect.CHROMA_NR_OFFICIAL_WORD).toBe(0xe3a02c32);
    expect(fw.aspect.CHROMA_NR_WORD).toBe(0xe3a02ec8);
    const imm = (w: number): number => { const rot = ((w >>> 8) & 0xf) * 2; const v = w & 0xff; return rot === 0 ? v : ((v >>> rot) | (v << (32 - rot))) >>> 0; };
    expect(imm(fw.aspect.CHROMA_NR_OFFICIAL_WORD)).toBe(12800);
    expect(imm(fw.aspect.CHROMA_NR_WORD)).toBe(3200);
  });

  it('on the official file changes exactly the instruction word and the compensation word', () => {
    const f = new fw.Firmware(official);
    const r = fw.aspect.applyChromaNr(f.decoded);
    const diff = diffOffsets(f.decoded, r.decoded);
    // mov r2,#0x3200 -> mov r2,#0xc80: bytes 0 and 1 of the word differ
    const compOffset = fw.COMP_OFFSET;
    expect(r.compensation.kind).toBe('official-layout');
    expect(r.compensation.offset).toBe(compOffset);
    for (const o of diff) expect((o >= siteOffset && o < siteOffset + 4) || (o >= compOffset && o < compOffset + 4)).toBe(true);
    expect(diff.filter((o) => o >= siteOffset && o < siteOffset + 4)).toEqual([siteOffset, siteOffset + 1]);
    expect(word(f.decoded, siteOffset)).toBe(0xe3a02c32);
    expect(word(r.decoded, siteOffset)).toBe(0xe3a02ec8);
    expect(fw.sum32(r.decoded)).toBe(0);
    const built = fw.build(f, r.decoded);
    const checks = fw.selfCheck(official, built.out, r.ranges, r.decoded);
    expect(Object.keys(checks).filter((k) => checks[k] !== true)).toEqual([]);
    // the Y (luma) threshold set-up is untouched
    expect(word(r.decoded, fw.RTOS_OFFSET + (0x53924548 - fw.RTOS_VA))).toBe(word(f.decoded, fw.RTOS_OFFSET + (0x53924548 - fw.RTOS_VA)));
  });

  it('on a finished GR Mod build changes only the instruction word and the end-of-RTOS sum word', async () => {
    const eng = await Engine.open(official);
    const base = await eng.buildFirmware([], [], [], { monoUnlock: true });
    const f = new fw.Firmware(base.file);
    const r = fw.aspect.applyChromaNr(f.decoded);
    expect(r.compensation.kind).toBe('grmod-trailer');
    const rtos = fw.sectionsOf(f.decoded).find((s) => s.name === 'RTOS')!;
    expect(r.compensation.offset).toBe(rtos.offset + rtos.size - 4);
    const diff = diffOffsets(f.decoded, r.decoded);
    const allowed = (o: number): boolean => (o >= siteOffset && o < siteOffset + 4) || (o >= r.compensation.offset && o < r.compensation.offset + 4);
    expect(diff.every(allowed)).toBe(true);
    expect(diff.length).toBeLessThanOrEqual(8);
    expect(diff.length).toBeGreaterThanOrEqual(3);
    const built = fw.build(f, r.decoded);
    // frames that changed are written stored (as GR Mod does), so the file is a little longer
    expect(built.out.length).toBeGreaterThanOrEqual(base.file.length);
    const checks = fw.selfCheck(base.file, built.out, r.ranges, r.decoded);
    expect(Object.keys(checks).filter((k) => checks[k] !== true)).toEqual([]);
    expect(fw.verifyContainer(built.out).checks.decoded_sum_zero).toBe(true);
    // the same file as a build that has the option from the start
    const direct = await eng.buildFirmware([], [], [], { monoUnlock: true, chromaNr: true });
    expect(direct.sha256).toBe(await fw.sha256Hex(built.out));
    expect(direct.file.length).toBe(built.out.length);
  });

  it('refuses a file that already has the patch', async () => {
    const eng = await Engine.open(official);
    const done = await eng.buildFirmware([], [], [], { monoUnlock: true, chromaNr: true });
    const f = new fw.Firmware(done.file);
    expect(() => fw.aspect.applyChromaNr(f.decoded)).toThrowError(/already in this firmware/);
    try {
      fw.aspect.applyChromaNr(f.decoded);
    } catch (e) {
      expect((e as fw.FirmwareError).code).toBe('already-applied');
    }
    // and the official file twice
    const once = fw.aspect.applyChromaNr(new fw.Firmware(official).decoded);
    expect(() => fw.aspect.applyChromaNr(once.decoded)).toThrowError(/already/);
  });

  it('refuses code that is not firmware 1.11 (every fingerprint word, and the instruction word itself)', () => {
    const d = new fw.Firmware(official).decoded;
    for (const [address, value] of fw.aspect.CHROMA_NR_FINGERPRINT) {
      const o = fw.RTOS_OFFSET + (address - fw.RTOS_VA);
      expect(word(d, o)).toBe(value >>> 0); // the fingerprint is right for the official file
      const bad = d.slice();
      bad[o] ^= 0x01;
      let code = '';
      try {
        fw.aspect.applyChromaNr(bad);
      } catch (e) {
        code = (e as fw.FirmwareError).code;
      }
      expect(code, `0x${address.toString(16)}`).toBe('unexpected-layout');
    }
    // a different threshold at the site (e.g. another firmware's constant) is refused too
    const other = d.slice();
    other[siteOffset + 1] = 0x2d;
    expect(() => fw.aspect.applyChromaNr(other)).toThrowError(/unexpected instruction/);
  });

  it('refuses a payload that is not an RTOS at the expected place', () => {
    const d = new fw.Firmware(official).decoded;
    const bad = d.slice();
    bad[fw.RTOS_OFFSET - 16] = 0x58; // section name 'XTOS'
    expect(() => fw.aspect.applyChromaNr(bad)).toThrow();
  });
});
