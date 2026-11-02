// SPDX-License-Identifier: GPL-2.0-only
/**
 * Experimental: the added slots' own .cube, applied by the camera's CPU to the finished pictures.
 *
 * The image hardware renders an added slot with its matrix, hue sectors, curves and post-curve
 * matrix; for many LUTs that comes within 1–3 dE00 of the .cube and no closer. The module of
 * `tools/cpulut/cpulut.c` runs at the start of JpegEncodeMacroProcess::Execute (0x537034B4), as
 * the halation and date imprint modules do, and maps every pixel of the YCbCr 4:2:2 pictures the
 * encoder is about to compress (main picture, screennail, thumbnail) through the look's correction
 * table: the picture the hardware made -> the picture the .cube makes. Installed after halation, so
 * it runs first: halation and the date imprint then work on the corrected picture.
 *
 * A table is a 17 x 33 x 33 lattice over Y, Cb and Cr (`CPULUT_TABLE_BYTES`), made by GR Mod from
 * its model of the slot (see tools/cpulut). Which look the picture has comes from the word the
 * development step leaves (LOOK_STASH, see lookstash.ts); looks without a table are left alone.
 *
 * Not shown: live view (it shows the hardware's rendering). RAW files are not changed; a JPEG
 * developed from one in the camera is corrected.
 */
import { FirmwareError } from '../types';
import { assembleWords, branchTarget } from './arm';
import { Patch, concat, u32le } from './build';
import { CPULUT_CODE, CPULUT_CODE_LENGTH } from './cpulut-code';

export const CPULUT_NY = 17;
export const CPULUT_NC = 33;
/** Two words per node: Y' | Cb' << 16 and Cr', with 4 fraction bits (0..4095). */
export const CPULUT_TABLE_BYTES = CPULUT_NY * CPULUT_NC * CPULUT_NC * 8;
/** Looks the module knows (style numbers below this). */
export const CPULUT_LOOKS = 64;

/** JpegEncodeMacroProcess::Execute. */
const JPEG_EXECUTE = 0x537034b4;
const CACHE = 0x538f0448;
const CACHE_FLUSH_FOR_READ = 0x538f04d8;
const CACHE_CLEAN = 0x538f04c4;
/** 'CLT1' */
export const CPULUT_MAGIC = 0x31544c43;

export interface CpuLutLook {
  /** Style number (an added slot: 34 + k). */
  style: number;
  /** The correction table, CPULUT_TABLE_BYTES bytes as tools/cpulut makes it. */
  table: Uint8Array;
}

function fail(code: string, message: string): never {
  throw new FirmwareError(code, message);
}

export function cpulutModule(): Uint8Array {
  const raw = typeof Buffer !== 'undefined' ? Uint8Array.from(Buffer.from(CPULUT_CODE, 'base64')) : Uint8Array.from(atob(CPULUT_CODE), (c) => c.charCodeAt(0));
  if (raw.length !== CPULUT_CODE_LENGTH) fail('internal', 'cpu LUT module: length');
  return raw;
}

/**
 * Install the module and the looks' tables. `stash` is the word the development step leaves
 * (the added slots must have been installed with `stashLook`).
 */
export function installCpuLut(p: Patch, looks: readonly CpuLutLook[], stash: number): void {
  if (looks.length < 1 || looks.length > CPULUT_LOOKS) fail('internal', 'cpu LUT: number of looks');
  const map = new Uint8Array(CPULUT_LOOKS);
  looks.forEach((l, k) => {
    if (!(Number.isInteger(l.style) && l.style >= 0 && l.style < CPULUT_LOOKS) || map[l.style]) fail('internal', 'cpu LUT: style of a look');
    if (!(l.table instanceof Uint8Array) || l.table.length !== CPULUT_TABLE_BYTES) fail('internal', 'cpu LUT: table size');
    const v = new DataView(l.table.buffer, l.table.byteOffset, l.table.byteLength);
    for (let i = 0; i < CPULUT_TABLE_BYTES; i += 8) {
      const lo = v.getUint32(i, true), hi = v.getUint32(i + 4, true);
      if ((lo & 0xffff) > 4095 || lo >>> 16 > 4095 || hi > 4095) fail('internal', 'cpu LUT: table value out of range');
    }
    map[l.style] = k + 1;
  });
  const first = p.word(JPEG_EXECUTE);
  let tail: string;
  if (first === 0xe1a0c00d) tail = `mov ip,sp;b #${JPEG_EXECUTE + 4}`;
  else if (first >>> 24 === 0xea) tail = `b #${branchTarget(JPEG_EXECUTE, first)}`;
  else fail('unexpected-layout', 'cpu LUT: unexpected JPEG encode entry');
  const tables = p.append(concat(looks.map((l) => l.table)), 16);
  const ctx = p.append(new Uint8Array([...u32le([CACHE, CACHE_FLUSH_FOR_READ, CACHE_CLEAN, stash, tables, looks.length, CPULUT_MAGIC]), ...map]), 16);
  const code = p.append(cpulutModule(), 16);
  const stub = p.append((at) => assembleWords(
    `push {r0-r3,ip,lr}
     ldr r1,[r1,#8]
     movw r0,#${ctx & 65535};movt r0,#${ctx >>> 16}
     bl #${code}
     pop {r0-r3,ip,lr}
     ${tail}`, at), 16);
  p.setWord(JPEG_EXECUTE, (0xea000000 | (((stub - (JPEG_EXECUTE + 8)) >> 2) & 0xffffff)) >>> 0, 'cpu LUT at the JPEG encode step');
}
