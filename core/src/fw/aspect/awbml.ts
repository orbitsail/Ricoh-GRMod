// SPDX-License-Identifier: GPL-2.0-only
/**
 * Experimental: a learned auto white balance for the plain Auto (GR IV / HDF / Monochrome, firmware 1.11).
 *
 * The module of `tools/awbml/awbml.c` (an FFCC-style model, Barron & Tsai 2017, trained on 2234 SimpleCube++ scenes
 * converted to the camera's AWB statistics and calibrated on real GR IV studio shots; integer only, bit-exact with
 * `tools/awbml/ref.py`) runs at the end of the Auto estimate (0x53938B28): the call of the final stage
 * (0x53938970, which turns the weighted parents into the gains and writes them to this+4 .. +0xA) is replaced by a
 * stub that makes that call and then lets the module overwrite the red and blue gains (this+4, this+0xA) with the
 * learned estimate. It reads the AWB's own block statistics (the settings block S, kept in r5 for the whole
 * function): 64 x 62 block means and counts, and the scene brightness.
 *
 * Only the plain Auto (this+0xAF88 == 0) is touched; White Priority and Warmth Priority stay as the camera has them. When
 * the scene has too few usable blocks (under 5 % of the pixels) the camera's own result is kept.
 *
 * Two paths, told apart by the estimate's third argument (r2, copied to r7 at the entry and untouched up to the hook: 0 for
 * live view, which calls LiveViewWhiteBalance::Execute, the still record pointer for a still, which comes from
 * WbCalcProcess; the stub passes it as is_still):
 *  - Live view runs on every frame, so the estimate is computed on the first call and then on every fourth (a full
 *    estimate is about 2.2 M instructions), the calls in between repeat the last result; leaving plain Auto forgets it. The
 *    camera's own boxcar smoothing still follows on the final gains.
 *  - A still always computes fresh from its own statistics: no throttle, no repeat, no temporal filter, and it never reads or
 *    changes the live view's state (counter, cached result, filter). The two paths may run in different tasks, so each has
 *    its own region of the scratch memory (one allocation of two regions, kept in the one RAM slot).
 *
 * Temporal filter (FFCC's, live view only): each computing call's estimate is an observation whose variance is the spread of
 * the softmax marginals mapped through a measured table (what the estimate really varies by from frame to frame); a Kalman
 * filter per axis (parameters and that table in the KF table, nothing to change in the code) smooths the estimate over the
 * computing calls, so live view does not jump; two confident frames in a row, both far from the state in the same
 * direction, restart it (scene change). Leaving plain Auto clears the state.
 *
 * Live view's S has v24/v28/v2c never written (0) and e30 from a record word nothing writes (so probably 0, which would read as a
 * very dark scene), so live view treats the exposure data as missing (the context's live view exposure mode, 1); stills keep using S.
 *
 * The context's AF89 flag (on in this build) makes the module also write 0 to this+0xAF89 whenever it overrides the gains with a valid estimate (a repeated live view result too; never on a fallback or in another mode):
 * the final stage sets that byte when the camera's own sums are all zero, and the live view smoother then holds the previous
 * value; a learned estimate does not depend on those sums.
 *
 * Layout: the context, the module and the stub are appended (as the other modules), then the 79 KB of tables
 * (`awbml-data.ts`); build.ts installs this after every other addition, so they all keep the places they have
 * without it (the image then differs from one without it only in the call word and the appended bytes). The module's scratch memory (2 x 35 KB, one `operator new` call, made once) is kept in the RAM word
 * 0x558372DC, which the start-up zero fill must clear (the literal at 0x53000460 is extended to 0x55837300 if not
 * already, as the look slots do).
 */
import { FirmwareError } from '../types';
import { assembleWords, branchTarget } from './arm';
import { Patch, expectWord, u32le } from './build';
import { AWBML_CODE, AWBML_CODE_LENGTH, AWBML_MAGIC, AWBML_PERIOD, AWBML_SCRATCH_BYTES } from './awbml-code';
import { AWBML_DATA, AWBML_DATA_LENGTH, AWBML_OFFSETS } from './awbml-data';

/** The Auto estimate (CWhiteBalanceAuto, vtable 0x5421B510 slot 2) and the places in it this hook relies on. */
const AUTO_ESTIMATE = 0x53938b28;
const S_TO_R5 = 0x53938b40; // mov r5, r1   (S, for the whole function)
const THIS_TO_R4 = 0x53938b4c; // mov r4, r0   (this)
const ARG3_TO_R7 = 0x53938b54; // mov r7, r2   (the estimate's 3rd argument: 0 in live view, the still record for a still)
const FINAL_CALL = 0x53938e2c; // bl final stage
const FINAL_STAGE = 0x53938970;
/** Operator new. */
export const AWBML_ALLOC = 0x538e09b0;
/** The scratch buffer's pointer (free RAM before the heap; zeroed at start-up). */
export const AWBML_SLOT = 0x558372dc;
/** Literal: end of the start-up zero fill. 44 unused bytes up to the heap (0x55837300) follow it. */
const ZERO_FILL_END = 0x53000460;

/** ctx flag: a gain override also clears Auto+0xAF89 (the camera's all-zero-sums hold flag, read by the live view smoother). On: its only reader is the live view smoother. */
export const AWBML_AF89 = 1;

/** ctx word, live view only: 1 = the exposure data in S (v24 = 0, e30 from a record word nothing writes) is treated as missing, the same as the camera's no-exposure marker; 0 = use S+0x30 as it is. Stills always use S. */
export const AWBML_LV_EXP = 1;

/** Order of the tables in the context (struct awbml_ctx in awbml.c) after magic, alloc and slot; the period, the AF89 flag and the live view exposure mode follow them. */
const TABLE_ORDER = ['LOG', 'BIAS', 'FSPEC', 'TW', 'ATAN', 'EXPA', 'EXPB', 'TANH', 'GEXP', 'RECIP', 'CAL', 'KF', 'LN'] as const;

function fail(code: string, message: string): never {
  throw new FirmwareError(code, message);
}

function unbase64(text: string): Uint8Array {
  return typeof Buffer !== 'undefined' ? Uint8Array.from(Buffer.from(text, 'base64')) : Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
}

export function awbmlModule(): Uint8Array {
  const raw = unbase64(AWBML_CODE);
  if (raw.length !== AWBML_CODE_LENGTH) fail('internal', 'learned AWB module: length');
  return raw;
}

export function awbmlData(): Uint8Array {
  const raw = unbase64(AWBML_DATA);
  if (raw.length !== AWBML_DATA_LENGTH) fail('internal', 'learned AWB tables: length');
  return raw;
}

/** What `installAwbLearn` appended (for tests): the stub, the module, the context and the tables. */
export interface AwbLearnLayout {
  stub: number;
  code: number;
  ctx: number;
  data: number;
}

/** The learned white balance for the plain Auto. */
export function installAwbLearn(p: Patch): AwbLearnLayout {
  // The hook relies on r4 = this, r5 = S, r7 = the 3rd argument (untouched to the hook), and the final-stage call.
  expectWord(p, ARG3_TO_R7, 0xe1a07002); // mov r7, r2
  expectWord(p, S_TO_R5, 0xe1a05001); // mov r5, r1
  expectWord(p, THIS_TO_R4, 0xe1a04000); // mov r4, r0
  expectWord(p, FINAL_CALL - 8, 0xe1a00004); // mov r0, r4
  expectWord(p, FINAL_CALL - 4, 0xe24b1038); // sub r1, fp, #0x38
  const call = p.word(FINAL_CALL);
  if (call >>> 24 !== 0xeb || branchTarget(FINAL_CALL, call) !== FINAL_STAGE) fail('unexpected-layout', 'learned AWB: unexpected call of the final stage');
  if (p.word(ZERO_FILL_END) !== 0x55837300) {
    expectWord(p, ZERO_FILL_END, 0x558372d4);
    p.setWord(ZERO_FILL_END, 0x55837300, 'start-up zero fill also clears the 44 unused bytes before the heap');
  }
  const module = awbmlModule();
  const data = awbmlData();
  const ctx = p.append(u32le([AWBML_MAGIC, AWBML_ALLOC, AWBML_SLOT, ...TABLE_ORDER.map(() => 0), AWBML_PERIOD, AWBML_AF89, AWBML_LV_EXP]), 16);
  const code = p.append(module, 16);
  const stub = p.append((at) => assembleWords(
    `push {r4-r6,lr}
     mov r6,r0
     bl #${FINAL_STAGE}
     movw r0,#${ctx & 65535};movt r0,#${ctx >>> 16}
     mov r1,r6
     mov r2,r5
     mov r3,r7
     bl #${code}
     pop {r4-r6,pc}`, at), 16);
  const tables = p.append(data, 16);
  TABLE_ORDER.forEach((name, k) => p.setWord(ctx + 12 + 4 * k, tables + AWBML_OFFSETS[name], `learned AWB: ${name} table`));
  if (AWBML_SCRATCH_BYTES <= 0) fail('internal', 'learned AWB: scratch size');
  p.setWord(FINAL_CALL, (0xeb000000 | (((stub - (FINAL_CALL + 8)) >> 2) & 0xffffff)) >>> 0, 'learned AWB after the final stage of the plain Auto');
  return { stub, code, ctx, data: tables };
}
