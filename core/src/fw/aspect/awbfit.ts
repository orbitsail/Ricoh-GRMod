// SPDX-License-Identifier: GPL-2.0-only
/**
 * Auto white balance, the plain Auto: tables fitted so that a lamp or bright area in the frame no longer
 * pulls the whole picture warm (GR IV / HDF / Monochrome, firmware 1.11).
 *
 * The plain Auto keeps less of a warm light's colour on surfaces than on the light itself: the frame for
 * a neutral under about 2600-2800 K (light-source frame 20, parent 15) corrects 34 % of the cast in all
 * three Auto modes, the frames of warmer-looking surfaces 58 % (Auto) to 87 % (White Priority). A
 * lampshade, a lit wall or a highlight shows the light's own colour, so when one is in the frame the
 * estimate moves towards the weak correction and the picture turns warm, whichever Auto mode is set.
 *
 * Worse, that parent (15) does not count towards the AWB's confidence, so when it is most of what the
 * camera sees the final stage blends the gains back towards 1:1 and nothing is corrected at all.
 *
 * Here: v5's tables (plain Auto half way to White Priority, `awbblend.ts`) with frame 20 corrected like the
 * warm-surface frames (221 = 73 %) up to EV 11, back to the official values by EV 15; and parent 15
 * counted in the confidence (one word of code, all Auto modes). Checked with a bit-exact model of the
 * camera's AWB (it reproduces the white balance recorded in 35 GR IV DNGs to about 1 %): indoor scenes
 * where a lamp or white wall took most of the frame no longer keep the light's full colour; the 35 real
 * GR IV daylight scenes come out the same. White and Warmth Priority keep their official tables.
 */
import { FirmwareError } from '../types';
import { Patch, expectWord } from './build';
import { installAwbTables } from './awbblend';
import { AWB_FIT_T2, AWB_FIT_T4, AWB_FIT_T5 } from './awbfit-data';

function bytes(hex: string): Uint8Array {
  if (!/^[0-9a-f]*$/.test(hex) || hex.length !== 24 * 33 * 2) throw new FirmwareError('internal', 'auto WB fit: bad table data');
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = parseInt(hex.slice(2 * i, 2 * i + 2), 16);
  return out;
}

/**
 * In the parent stage (0x53936748, one call per parent) the AWB adds each parent's weight to its
 * confidence n20 (this+0x20), except for parent 15, the neutral under about 2600-2800 K: the code compares
 * the parent object with this+0x6520 and skips the add when equal. With little else in the frame (a lamp,
 * a lit wall, a white room) n20 stays near zero, the final stage then blends the gains to 1:1 and the
 * light's full colour is kept, in every Auto mode. Comparing with this+0x6521 instead (never a parent
 * object) lets parent 15 count like the others.
 */
const N20_SKIP = 0x53936830;
const N20_SKIP_OFFICIAL = 0xe2833020; // add r3, r3, #0x20  (r3 = this + 0x6520, parent 15)
const N20_SKIP_NEVER = 0xe2833021; // add r3, r3, #0x21  (no parent object there)

/** Plain Auto with the fitted tables, and parent 15 counted in the confidence (all Auto modes). */
export function installAwbFit(p: Patch): void {
  expectWord(p, N20_SKIP - 4, 0xe2873c65); // add r3, r7, #0x6500
  expectWord(p, N20_SKIP, N20_SKIP_OFFICIAL);
  expectWord(p, N20_SKIP + 4, 0xe1580003); // cmp r8, r3
  expectWord(p, N20_SKIP + 8, 0x11d732b0); // ldrhne r3, [r7, #0x20]
  installAwbTables(p, bytes(AWB_FIT_T2), bytes(AWB_FIT_T4), bytes(AWB_FIT_T5), 'auto WB: plain Auto fitted against lamps in the frame');
  p.setWord(N20_SKIP, N20_SKIP_NEVER, 'auto WB: the neutral-under-warm-light parent counts towards the confidence');
}
