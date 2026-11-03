// SPDX-License-Identifier: GPL-2.0-only
/**
 * Auto white balance, the plain Auto: part of the way from its own tuning towards White Priority's
 * (GR IV / HDF / Monochrome, firmware 1.11). On the camera the plain Auto keeps indoor light a little
 * too warm, and White Priority makes it too white.
 *
 * The AWB takes its tuning from one of CWhiteBalanceTuningParameter{Standard, White, Atmosphere,
 * CTE} (Auto, Auto WB White Priority, Auto WB Warmth Priority, CTE). Each class has three byte
 * tables of 24 rows x 33 columns, read by getters `table[row * 33 + column]` (0x5393E444 ..
 * 0x5393E5AC; vtables at 0x542FE760 Standard, 0x542FE7C0 White, 0x542FE840 Atmosphere):
 *   Standard   0x55053E04 (shared with Atmosphere), 0x55054434, 0x5505411C
 *   White      0x55054A64,                          0x5505474C, 0x55054D7C
 * The modes differ only in some columns of the darker rows (indoor light): White's values are the
 * highest, Atmosphere's the lowest, the bright rows are alike. Here Standard's own two tables become
 * Standard + share x (White - Standard), and Standard gets its own copy of the shared table with the
 * same blend: its vtable entry (0x542FE770) points at a copy of the official getter that reads the
 * copy. White and Warmth Priority stay exactly as they are. Data and one table pointer; no logic
 * is changed. Read from the official 1.11 file; the blend is between two of Ricoh's own tunings.
 */
import { FirmwareError } from '../types';
import { Patch, expectWord } from './build';

const RAM_SRC = 0x5437b640;
const RAM_DST = 0x55000000;
const ROWS = 24;
const COLS = 33;
const BYTES = ROWS * COLS;

const STD_T2 = 0x55053e04;
const STD_T4 = 0x55054434;
const STD_T5 = 0x5505411c;
const WHITE_T2 = 0x55054a64;
const WHITE_T4 = 0x5505474c;
const WHITE_T5 = 0x55054d7c;
/** Standard's vtable entries for its three tables; the first is the getter it shares with Atmosphere. */
const STD_VT_T2 = 0x542fe770;
const STD_VT_T4 = 0x542fe778;
const STD_VT_T5 = 0x542fe77c;
const ATM_VT_T2 = 0x542fe850;
const GET_T2 = 0x5393e444;
const GET_T4 = 0x5393e460;
const GET_T5 = 0x5393e478;

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

/** The official getter of a table at `table` (as at 0x5393E444): r1 row, r2 column. */
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

/**
 * The plain Auto `share` of the way to White Priority (0 < share < 1; 0.5 is half way), for the
 * warm indoor light where the two differ.
 */
export function installAwbBlend(p: Patch, share = 0.5): void {
  if (!(share > 0 && share < 1)) throw new FirmwareError('internal', 'auto WB blend: share must be between 0 and 1');
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
  // Standard's own tables, in place.
  writeTable(p, STD_T4, blend(p, STD_T4, WHITE_T4, share), 'auto WB: plain Auto towards White Priority (table 2 of 3)');
  writeTable(p, STD_T5, blend(p, STD_T5, WHITE_T5, share), 'auto WB: plain Auto towards White Priority (table 3 of 3)');
  // The table it shares with Warmth Priority: a copy for Standard, read by a copy of the getter.
  const table = p.append(blend(p, STD_T2, WHITE_T2, share), 16);
  const getter = p.append(getterWords(table), 16);
  p.setWord(STD_VT_T2, getter, 'auto WB: plain Auto reads its own copy of the shared table');
}
