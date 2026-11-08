// SPDX-License-Identifier: GPL-2.0-only
/**
 * Learned plain-Auto white balance, ported from the reviewed 8.2 module to GR IV 1.20.
 * Numeric algorithm, trained tables, separate still/live scratch regions, period-4 live
 * throttling and temporal filtering are unchanged. Both paths scale their output by
 * their own S+0x68/0x6E gain words; stills always compute from their own statistics.
 * Live exposure comes from the validated ComPropIf buffer chain. 1.20's still builder
 * now uses double-precision, nearest eighth-stop quantisation (538fb018/68/b8), which
 * the port implements in integers and checks against the actual stock builder.
 * Hook/register contracts are asserted below. The scratch pointer uses 0x5583901c;
 * the builder rejects HDR/diagnostic combinations that share the reserved words.
 * Address evidence: tools/port/gr4-120-learned-overrides.json; tests: tools/gr4v120/awbml.
 */
import { FirmwareError } from '../../types';
import { assembleWords, branchTarget } from './arm';
import { Patch, expectWord, u32le } from './build';
import { AWBML_CODE, AWBML_CODE_LENGTH, AWBML_MAGIC, AWBML_PERIOD, AWBML_SCRATCH_BYTES } from './awbml-code';
import { AWBML_DATA, AWBML_DATA_LENGTH, AWBML_OFFSETS } from './awbml-data';

/** The Auto estimate (CWhiteBalanceAuto, vtable 0x54252890 slot 2) and the places in it this hook relies on. */
const AUTO_ESTIMATE = 0x53960b8c;
const S_TO_R5 = 0x53960ba4; // mov r5, r1   (S, for the whole function)
const THIS_TO_R4 = 0x53960bb0; // mov r4, r0   (this)
const ARG3_TO_R7 = 0x53960bb8; // mov r7, r2   (the estimate's 3rd argument: 0 in live view, the still record for a still)
const FINAL_CALL = 0x53960e90; // bl final stage
const FINAL_STAGE = 0x539609d4;
/** Operator new. */
export const AWBML_ALLOC = 0x539084bc;
/** The scratch buffer's pointer (free RAM before the heap; zeroed at start-up). */
export const AWBML_SLOT = 0x5583901c;
/** Literal: end of the start-up zero fill. 44 unused bytes up to the heap (0x55839040) follow it. */
const ZERO_FILL_END = 0x53000460;

/** ctx flag: a gain override also clears Auto+0xAF89 (the camera's all-zero-sums hold flag, read by the live view smoother). On: its only reader is the live view smoother. */
export const AWBML_AF89 = 1;

/**
 * ctx word, live view only (stills always use S): where the exposure comes from.
 * 0 = use S as it is; 1 = treat the exposure as missing (the camera's no-exposure marker); 2 = read the AE's current decided Tv / Av / Sv (IEEE floats, APEX)
 * from the property store: ComPropIf singleton E = [0x5537b2a0] (guard word 0x5537b298 bit 0, vtable 0x53FC54D8), X = [E + 0x518], D = X[0], Tv = D+0x4D8,
 * Av = D+0x4DC, Sv = D+0x4E0 (the values a still copies into rec+0xB9C / 0xB98 / 0xBA0), quantised bit-exactly as the still builder (0x5395BDE8) does:
 * na = floor(68.5 + 8 Av) - 68, nt = floor(68.5 + 8 Tv) - 68, ns = floor(8 Sv - 7.5) + 8, S+0x24 = 32 na, S+0x30 = 32 (na + nt - ns). The pointer chain is validated
 * and the pair of reads repeated (the property commit swaps and copies the buffers); any failure, a movie live view (S+0x70 == 4) or a value out of range
 * falls back to 1, i.e. the behaviour without this source.
 */
export const AWBML_LV_EXP = 2;

/**
 * ctx word, live view only: 1 = the live view's output gains are scaled by that call's own S+0x68 / S+0x6E (the LV manager's words), exactly as a still's are.
 * Stock's final stage output is proportional to those words on both paths, so this is a no-op when they are 0x2000 and the stock-consistent correction when
 * they are not. The cached gains and the filter state stay in model units (scaled at output only; a zero word leaves the gain alone). 0 = unscaled.
 */
export const AWBML_LV_SCALE = 1;

/** Order of the tables in the context (struct awbml_ctx in awbml.c) after magic, alloc and slot; the period, the AF89 flag, the live view exposure mode and the live view scaling flag follow them. */
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
  if (p.word(ZERO_FILL_END) !== 0x55839040) {
    expectWord(p, ZERO_FILL_END, 0x55839014);
    p.setWord(ZERO_FILL_END, 0x55839040, 'start-up zero fill also clears the 44 unused bytes before the heap');
  }
  const module = awbmlModule();
  const data = awbmlData();
  const ctx = p.append(u32le([AWBML_MAGIC, AWBML_ALLOC, AWBML_SLOT, ...TABLE_ORDER.map(() => 0), AWBML_PERIOD, AWBML_AF89, AWBML_LV_EXP, AWBML_LV_SCALE]), 16);
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
