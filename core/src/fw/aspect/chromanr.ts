// SPDX-License-Identifier: GPL-2.0-only
/**
 * Chroma-only noise reduction from ISO 3200 (GR IV / HDF / Monochrome, firmware 1.11).
 *
 * The colour noise reduction circuit (CNR, "Suppre": IO_CNR.OTF_CSPR_REG / OFL_CSPR_REG) has a
 * second, half-resolution pass that the camera switches on only at high ISO. The switch is
 * `NoiseReductionCoordinator::GetCbCrFilterFlag` at 0x539245c0 (ARM): it returns `iso >= T`
 * (`cmp r5,r0; movlt r0,#0; movge r0,#1` at 0x539245f4), with the threshold T kept in RAM at
 * 0x55052c5c. The threshold is not read from a table: the first call fills it in (guarded by the
 * byte at 0x553a0b58, which is zero after boot) from a switch on the platform id returned by
 * 0x538e7fd0. The platform id of the GR IV is 2, or 5 for the 0x288 board; both reach
 * 0x5392465c, `mov r2,#0x3200; movw r3,#0x2c5c; movt r3,#0x5505; mov r0,r2; str r2,[r3]`
 * (T = 12800). Only id 4 gets 0x640000 (never on).
 * The ISO value compared is the nominal ISO from the table at 0x541d7734 (1/8-stop steps:
 * 2500, 3200, 4000, ...), so T = 3200 means the second pass runs at 3200 and above and not at
 * 2500 and below.
 *
 * The luma twin, `GetYFilterFlag` at 0x539244ac, reads its own threshold (0x55052c60, set to
 * 0xc8000 at 0x53924548) and is not touched. The initial value 12800 that the RAM image holds at
 * 0x55052c5c is dead (it is overwritten by the first call before anything reads it) and is left
 * alone.
 *
 * One instruction word changes: `mov r2,#0x3200` (e3a02c32) becomes `mov r2,#0xc80` (e3a02ec8).
 * Data only; no code is added. Read from a disassembly and run in an emulator against the
 * official 1.11 file; not tried on a camera.
 */
import { RTOS_OFFSET, RTOS_VA } from '../profile';
import { FirmwareError } from '../types';
import { sectionsOf, sum32 } from '../container';
import type { Range } from '../types';
import { Patch } from './build';

/** The threshold load in GetCbCrFilterFlag's lazy initialisation. */
export const CHROMA_NR_SITE = 0x5392465c;
export const CHROMA_NR_OFFICIAL_WORD = 0xe3a02c32; // mov r2, #0x3200 (12800)
export const CHROMA_NR_WORD = 0xe3a02ec8; // mov r2, #0xc80 (3200)
export const CHROMA_NR_OFFICIAL_ISO = 12800;
export const CHROMA_NR_ISO = 3200;

/** Words that must be exactly as in the official file around the change (address, value). */
export const CHROMA_NR_FINGERPRINT: readonly (readonly [number, number])[] = [
  [0x539245c0, 0xe1a0c00d], // GetCbCrFilterFlag: mov ip, sp
  [0x539245c8, 0xe3004b58], // movw r4, #0xb58 (first-call flag 0x553a0b58)
  [0x539245cc, 0xe345453a], // movt r4, #0x553a
  [0x539245e8, 0xe3023c5c], // movw r3, #0x2c5c
  [0x539245ec, 0xe3453505], // movt r3, #0x5505
  [0x539245f4, 0xe1550000], // cmp r5, r0
  [0x539245f8, 0xb3a00000], // movlt r0, #0
  [0x539245fc, 0xa3a00001], // movge r0, #1
  [0x5392465c, CHROMA_NR_OFFICIAL_WORD],
  [0x53924660, 0xe3023c5c], // movw r3, #0x2c5c
  [0x53924664, 0xe3453505], // movt r3, #0x5505
  [0x53924668, 0xe1a00002], // mov r0, r2
  [0x5392466c, 0xe5832000], // str r2, [r3]
  [0x53924548, 0xe3a02932], // GetYFilterFlag's mov r2, #0xc8000 (must stay)
  [0x53924640, 0x1a00000d], // bne to the error path for any other platform id
];

function fail(code: string, message: string): never {
  throw new FirmwareError(code, message);
}

const hex = (n: number): string => '0x' + (n >>> 0).toString(16);

/** Where `installChromaNr` finds the word: ok, already applied, or something else. */
export function chromaNrState(patch: Patch): 'official' | 'applied' | 'unknown' {
  let w: number;
  try {
    w = patch.word(CHROMA_NR_SITE);
  } catch {
    return 'unknown';
  }
  if (w === CHROMA_NR_WORD) return 'applied';
  if (w === CHROMA_NR_OFFICIAL_WORD) return 'official';
  return 'unknown';
}

/**
 * Switch the half-resolution chroma pass on from ISO 3200 instead of 12800. Throws
 * `already-applied` when the patch is already in, `unexpected-layout` when any word differs from
 * firmware 1.11 (e.g. another firmware version).
 */
export function installChromaNr(patch: Patch): void {
  if (chromaNrState(patch) === 'applied') fail('already-applied', 'the chroma-only noise reduction patch is already in this firmware');
  for (const [address, value] of CHROMA_NR_FINGERPRINT) {
    let actual: number;
    try {
      actual = patch.word(address);
    } catch {
      return fail('unexpected-layout', `${hex(address)} is outside the image`);
    }
    if (actual !== value >>> 0) fail('unexpected-layout', `unexpected instruction at ${hex(address)} (found ${hex(actual)}, expected ${hex(value)}): not firmware 1.11`);
  }
  patch.setWord(CHROMA_NR_SITE, CHROMA_NR_WORD, 'chroma NR: second chroma pass from ISO 3200 (mov r2,#0xc80)');
}

/** Result of `applyChromaNr`. */
export interface ChromaNrResult {
  /** The new decoded payload (same length, word sum unchanged). */
  decoded: Uint8Array;
  /** Every part of the payload that differs, for `selfCheck`. */
  ranges: Range[];
  /** Decoded offset and before/after of the changed instruction word. */
  word: { offset: number; before: number; after: number };
  /** Decoded offset and before/after of the word that keeps the payload sum. */
  compensation: { offset: number; before: number; after: number; kind: 'grmod-trailer' | 'official-layout' };
}

const TRAILER_MAGIC = 'GRMODAR';

function readU32(d: Uint8Array, o: number): number {
  return (d[o] | (d[o + 1] << 8) | (d[o + 2] << 16) | (d[o + 3] << 24)) >>> 0;
}

function writeU32(d: Uint8Array, o: number, v: number): void {
  d[o] = v & 0xff;
  d[o + 1] = (v >>> 8) & 0xff;
  d[o + 2] = (v >>> 16) & 0xff;
  d[o + 3] = v >>> 24;
}

/**
 * Apply the patch to a decoded payload: an official 1.11 payload or one built by GR Mod (whose RTOS
 * section has grown; the word that keeps its payload sum at zero is the last word of the section,
 * after the `GRMODAR<n>` trailer). The payload word sum stays what it was (zero for a valid file).
 */
export function applyChromaNr(decoded: Uint8Array): ChromaNrResult {
  const rtos = sectionsOf(decoded).find((s) => s.name === 'RTOS');
  if (!rtos || rtos.offset !== RTOS_OFFSET) fail('unexpected-layout', 'no RTOS section at the expected place: not firmware 1.11');
  if (rtos.offset + rtos.size > decoded.length || rtos.size < 0x13d2ac0) fail('unexpected-layout', 'RTOS section is shorter than the official one');
  const patch = new Patch(decoded.slice(rtos.offset, rtos.offset + rtos.size));
  installChromaNr(patch);
  if (patch.words.length !== 1) fail('internal', 'expected exactly one changed word');
  const w = patch.words[0];
  const out = decoded.slice();
  const wordOffset = RTOS_OFFSET + (w.address - RTOS_VA);
  if (readU32(out, wordOffset) !== w.before) fail('internal', 'word before does not match');
  writeU32(out, wordOffset, w.after);

  // Which word keeps the payload sum? A GR Mod build ends its RTOS section with
  // "GRMODAR<n>" + one sum word; the official layout uses the compensation word inside
  // "MakeParameter" (profile.ts).
  const end = rtos.offset + rtos.size;
  let compOffset: number;
  let kind: ChromaNrResult['compensation']['kind'];
  const magicAt = end - 4 - (TRAILER_MAGIC.length + 1);
  let isTrailer = rtos.size > 0x13d2ac0;
  if (isTrailer) {
    for (let i = 0; i < TRAILER_MAGIC.length; i++) if (decoded[magicAt + i] !== TRAILER_MAGIC.charCodeAt(i)) isTrailer = false;
    const digit = decoded[magicAt + TRAILER_MAGIC.length];
    if (!(digit >= 0x30 && digit <= 0x39)) isTrailer = false;
  }
  if (isTrailer) {
    compOffset = end - 4;
    kind = 'grmod-trailer';
  } else if (rtos.size === 0x13d2ac0) {
    compOffset = RTOS_OFFSET + (0x54049394 - RTOS_VA);
    const guard = 'MakeParameter\0';
    const g = compOffset - 4;
    for (let i = 0; i < guard.length; i++) if (decoded[g + i] !== guard.charCodeAt(i)) fail('unexpected-layout', 'compensation word is not inside "MakeParameter"');
    kind = 'official-layout';
  } else {
    return fail('unexpected-layout', 'the RTOS section has grown but does not end with a GR Mod trailer; cannot keep the payload sum');
  }
  if (compOffset >= wordOffset - 3 && compOffset <= wordOffset + 3) fail('internal', 'compensation word overlaps the change');
  const before = readU32(out, compOffset);
  const delta = (w.after - w.before) >>> 0;
  const after = (before - delta) >>> 0;
  writeU32(out, compOffset, after);
  if (sum32(out) !== sum32(decoded)) fail('internal', 'payload word sum changed');
  return {
    decoded: out,
    ranges: [
      { what: 'chroma NR: second chroma pass threshold (mov r2,#0xc80)', offset: wordOffset, length: 4 },
      { what: kind === 'grmod-trailer' ? 'checksum word at the end of RTOS' : 'checksum compensation word', offset: compOffset, length: 4 },
    ],
    word: { offset: wordOffset, before: w.before, after: w.after },
    compensation: { offset: compOffset, before, after, kind },
  };
}
