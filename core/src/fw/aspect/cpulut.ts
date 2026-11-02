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
 * its model of the slot (see tools/cpulut). Which look the picture has: FRAME_LOOK, the look at the
 * start of the exposure (the date imprint's hook there, installed with the module) or of the RAW
 * file being developed, so that a look chosen while pictures are still being processed does not
 * change theirs; LOOK_STASH (the look the development step last ran with) when that is not set.
 * Looks without a table are left alone.
 *
 * Layout: the context, the module and its stub are appended before the tables, so the code the
 * camera runs sits next to halation's and the date imprint's; the tables (148 KB a look) come
 * after. The context holds each table's sum of words, which the module checks before use.
 *
 * Not shown: live view (it shows the hardware's rendering). RAW files are not changed; a JPEG
 * developed from one in the camera is corrected.
 */
import { FirmwareError } from '../types';
import { assembleWords, branchTarget } from './arm';
import { Patch, concat, u32le } from './build';
import { CPULUT_CODE, CPULUT_CODE_LENGTH } from './cpulut-code';
import { installExposureOrientation } from './datestamp';
import { FRAME_LOOK, LOOK_STASH } from './lookstash';

export const CPULUT_NY = 17;
export const CPULUT_NC = 33;
/** Two words per node: Y' | Cb' << 16 and Cr', with 4 fraction bits (0..4095). */
export const CPULUT_TABLE_BYTES = CPULUT_NY * CPULUT_NC * CPULUT_NC * 8;
/** Looks the module knows (style numbers below this), and most tables. */
export const CPULUT_LOOKS = 64;

/** JpegEncodeMacroProcess::Execute. */
const JPEG_EXECUTE = 0x537034b4;
/**
 * The cache calls of halation and the date imprint, made in the same order (before reading the
 * planes, after writing them). Their names follow halation.ts; the review of the module found
 * 0x538F04D8 cleaning and invalidating in task context and 0x538F04C4 ending in DCIMVAC.
 */
const CACHE = 0x538f0448;
const CACHE_FLUSH_FOR_READ = 0x538f04d8;
const CACHE_CLEAN = 0x538f04c4;
/** 'CLT2': context with FRAME_LOOK, LOOK_STASH and the tables' sums. */
export const CPULUT_MAGIC = 0x32544c43;
/** Offset of the tables' address in the context (filled in once the tables are appended). */
const TABLES_AT = 5 * 4;

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

/** The sum of a table's little-endian words, modulo 2^32 (as the module adds them). */
export function cpulutTableSum(table: Uint8Array): number {
  const v = new DataView(table.buffer, table.byteOffset, table.byteLength);
  let s = 0;
  for (let i = 0; i + 4 <= table.length; i += 4) s = (s + v.getUint32(i, true)) >>> 0;
  return s;
}

/**
 * Install the module and the looks' tables (the added slots must have been installed with
 * `stashLook`), and the hook that keeps the look at the start of each exposure (FRAME_LOOK).
 */
export function installCpuLut(p: Patch, looks: readonly CpuLutLook[]): void {
  if (looks.length < 1 || looks.length > CPULUT_LOOKS) fail('internal', 'cpu LUT: number of looks');
  const map = new Uint8Array(CPULUT_LOOKS);
  const sums = new Array<number>(CPULUT_LOOKS).fill(0);
  looks.forEach((l, k) => {
    if (!(Number.isInteger(l.style) && l.style >= 0 && l.style < CPULUT_LOOKS) || map[l.style]) fail('internal', 'cpu LUT: style of a look');
    if (!(l.table instanceof Uint8Array) || l.table.length !== CPULUT_TABLE_BYTES) fail('internal', 'cpu LUT: table size');
    const v = new DataView(l.table.buffer, l.table.byteOffset, l.table.byteLength);
    for (let i = 0; i < CPULUT_TABLE_BYTES; i += 8) {
      const lo = v.getUint32(i, true), hi = v.getUint32(i + 4, true);
      if ((lo & 0xffff) > 4095 || lo >>> 16 > 4095 || hi > 4095) fail('internal', 'cpu LUT: table value out of range');
    }
    map[l.style] = k + 1;
    sums[k] = cpulutTableSum(l.table);
  });
  const first = p.word(JPEG_EXECUTE);
  let tail: string;
  if (first === 0xe1a0c00d) tail = `mov ip,sp;b #${JPEG_EXECUTE + 4}`;
  else if (first >>> 24 === 0xea) tail = `b #${branchTarget(JPEG_EXECUTE, first)}`;
  else fail('unexpected-layout', 'cpu LUT: unexpected JPEG encode entry');
  installExposureOrientation(p);
  const ctx = p.append(new Uint8Array([...u32le([CACHE, CACHE_FLUSH_FOR_READ, CACHE_CLEAN, FRAME_LOOK, LOOK_STASH, 0, looks.length, CPULUT_MAGIC]), ...map, ...u32le(sums)]), 16);
  const code = p.append(cpulutModule(), 16);
  const stub = p.append((at) => assembleWords(
    `push {r0-r3,ip,lr}
     ldr r1,[r1,#8]
     movw r0,#${ctx & 65535};movt r0,#${ctx >>> 16}
     bl #${code}
     pop {r0-r3,ip,lr}
     ${tail}`, at), 16);
  const tables = p.append(concat(looks.map((l) => l.table)), 16);
  p.setWord(ctx + TABLES_AT, tables, 'cpu LUT: the tables');
  p.setWord(JPEG_EXECUTE, (0xea000000 | (((stub - (JPEG_EXECUTE + 8)) >> 2) & 0xffffff)) >>> 0, 'cpu LUT at the JPEG encode step');
}
