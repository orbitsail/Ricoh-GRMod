// SPDX-License-Identifier: GPL-2.0-only
/**
 * Auto white balance, the plain Auto: part of the way from its own tuning towards White Priority's
 * (GR IV / HDF / Monochrome, firmware 1.11). On the camera the plain Auto keeps indoor light a little
 * too warm, and White Priority makes it too white.
 *
 * The AWB takes its tuning from one of CWhiteBalanceTuningParameter{Standard, White, Atmosphere,
 * CTE} (Auto, Auto WB White Priority, Auto WB Warmth Priority, CTE). 0x53964400 picks the class by
 * the mode (0 Auto, 1 Warmth, 2 White, 3 CTE) and copies one column of its tables into each of the
 * AWB's 33 light-source frames; the mode byte (+0xAF88) is read nowhere else, so the modes differ
 * only in these tables. Each class has byte tables of 24 rows x 33 columns, read by getters
 * `table[row * 33 + column]` (0x53966500 .. 0x53966668; vtables at 0x54335AE0 Standard, 0x54335B40
 * White, 0x54335BC0 Atmosphere): a column is a frame, a row one of 24 brightness levels of the
 * statistics (the warm frames weigh nothing in the brightest ones). One table weighs the frame
 * (0..255, read at 0x53963C20), two shift it (128 = none, 0x53963B68 / 0x53963BC4):
 *   Standard   0x55054EB4 (shared with Atmosphere), 0x550554e4, 0x550551CC
 *   White      0x55055B14,                          0x550557FC, 0x55055E2C
 * A fourth table (0x55054B9C, the frame's kind) is shared by all four classes. The modes differ in
 * some frames, mostly in the darker rows: White's values are the highest, Atmosphere's the lowest;
 * in the four brightest rows only one frame differs, by 5. Here Standard's own two tables become
 * Standard + share x (White - Standard), and Standard gets its own copy of the shared table with the
 * same blend: its vtable entry (0x54335AF0) points at a copy of the official getter that reads the
 * copy. White and Warmth Priority stay exactly as they are. Data and one table pointer; no logic
 * is changed. Read from the official 1.11 file; the blend is between two of Ricoh's own tunings.
 */
import { FirmwareError } from '../../types';
import { Patch, expectWord } from './build';

const RAM_SRC = 0x543b3100;
const RAM_DST = 0x55000000;
const ROWS = 24;
const COLS = 33;
const BYTES = ROWS * COLS;

const STD_T2 = 0x55054eb4;
const STD_T4 = 0x550554e4;
const STD_T5 = 0x550551cc;
const WHITE_T2 = 0x55055b14;
const WHITE_T4 = 0x550557fc;
const WHITE_T5 = 0x55055e2c;
/** Standard's vtable entries for its three tables; the first is the getter it shares with Atmosphere. */
const STD_VT_T2 = 0x54335af0;
const STD_VT_T4 = 0x54335af8;
const STD_VT_T5 = 0x54335afc;
const ATM_VT_T2 = 0x54335bd0;
const GET_T2 = 0x53966500;
const GET_T4 = 0x5396651c;
const GET_T5 = 0x53966534;

function fail(message: string): never {
  throw new FirmwareError('unexpected-layout', `auto WB blend: ${message}`);
}

/** Address in the image of an address in the initialised data. */
function inImage(address: number): number {
  return RAM_SRC + (address - RAM_DST);
}

function movw(rd: number, imm: number): number {
  return (0xe3000000 | ((imm >>> 12) & 0xf) << 16 | rd << 12 | (imm & 0xfff)) >>> 0;
}

function movt(rd: number, imm: number): number {
  return (0xe3400000 | ((imm >>> 12) & 0xf) << 16 | rd << 12 | (imm & 0xfff)) >>> 0;
}

/** The official getter of a table at `table` (as at 0x53966500): r1 row, r2 column. */
function getterWords(table: number): number[] {
  return [0xe3a03021, movw(0, table & 0xffff), 0xe0222193, movt(0, table >>> 16), 0xe7d00002, 0xe12fff1e];
}

function blend(p: Patch, own: number, white: number, share: number): Uint8Array {
  const a = p.readMapped(own, BYTES);
  const b = p.readMapped(white, BYTES);
  return Uint8Array.from(a, (v, i) => Math.round(v + share * (b[i] - v)));
}

/** Words of `bytes` written over the image copy of the table at `address` (only those that change). */
function writeTable(p: Patch, address: number, bytes: Uint8Array, reason: string): void {
  const at = inImage(address);
  for (let i = 0; i < BYTES; i += 4) {
    const v = (bytes[i] | (bytes[i + 1] << 8) | (bytes[i + 2] << 16) | (bytes[i + 3] << 24)) >>> 0;
    if (p.word(at + i) !== v) p.setWord(at + i, v, reason);
  }
}

/** The official tables and getters this aspect relies on are where 1.11 has them. */
function checkLayout(p: Patch): void {
  expectWord(p, STD_VT_T2, GET_T2);
  expectWord(p, ATM_VT_T2, GET_T2);
  expectWord(p, STD_VT_T4, GET_T4);
  expectWord(p, STD_VT_T5, GET_T5);
  const official = (g: number, table: number): void => {
    getterWords(table).forEach((w, k) => { if (p.word(g + 4 * k) !== w) fail(`unexpected getter at 0x${g.toString(16)}`); });
  };
  official(GET_T2, STD_T2);
  official(GET_T4, STD_T4);
  official(GET_T5, STD_T5);
}

/**
 * Plain Auto's three tables replaced: `t2` the weights, `t4` and `t5` the two corrections, each 24 rows
 * x 33 columns in the firmware's order (`table[row * 33 + column]`). White and Warmth Priority keep theirs.
 */
export function installAwbTables(p: Patch, t2: Uint8Array, t4: Uint8Array, t5: Uint8Array, why: string): void {
  if (t2.length !== BYTES || t4.length !== BYTES || t5.length !== BYTES) throw new FirmwareError('internal', `auto WB tables: each must be ${BYTES} bytes`);
  checkLayout(p);
  // Standard's own tables, in place.
  writeTable(p, STD_T4, t4, `${why} (table 2 of 3)`);
  writeTable(p, STD_T5, t5, `${why} (table 3 of 3)`);
  // The table it shares with Warmth Priority: a copy for Standard, read by a copy of the getter.
  const table = p.append(t2, 16);
  const getter = p.append(getterWords(table), 16);
  p.setWord(STD_VT_T2, getter, 'auto WB: plain Auto reads its own copy of the shared table');
}

/** Plain Auto's three tables as the official 1.11 file has them (for building replacements). */
export function officialAutoTables(p: Patch): { t2: Uint8Array; t4: Uint8Array; t5: Uint8Array; white: { t2: Uint8Array; t4: Uint8Array; t5: Uint8Array } } {
  checkLayout(p);
  return {
    t2: p.readMapped(STD_T2, BYTES), t4: p.readMapped(STD_T4, BYTES), t5: p.readMapped(STD_T5, BYTES),
    white: { t2: p.readMapped(WHITE_T2, BYTES), t4: p.readMapped(WHITE_T4, BYTES), t5: p.readMapped(WHITE_T5, BYTES) },
  };
}

/**
 * The plain Auto `share` of the way to White Priority (0 < share < 1; 0.5 is half way), for the
 * warm indoor light where the two differ.
 */
export function installAwbBlend(p: Patch, share = 0.5): void {
  if (!(share > 0 && share < 1)) throw new FirmwareError('internal', 'auto WB blend: share must be between 0 and 1');
  checkLayout(p);
  installAwbTables(p, blend(p, STD_T2, WHITE_T2, share), blend(p, STD_T4, WHITE_T4, share), blend(p, STD_T5, WHITE_T5, share),
    'auto WB: plain Auto towards White Priority');
}
