// SPDX-License-Identifier: GPL-2.0-only
/**
 * Experimental: a learned Auto for Shadow Correction (GR IV / HDF / Monochrome, firmware 1.11).
 *
 * What Auto now does: a learned estimate of how much the median of five professional retouchers (MIT-Adobe FiveK, 975 images)
 * would lift the shadows of the scene. The model (100 gradient-boosted trees, `tools/gr4v120/shadowml/model/model_final.bin`, embedded
 * as `shadowml-data.ts`) sees relative-brightness features only: log2 percentiles of the block luminance (the green plane of the
 * AWB's block statistics), the share of blocks 1..5 stops below the median, near-clipped blocks, centre against border, the
 * ISO index, the mode, the R/G and B/G colour cast. Its output t = 0 .. 0x800 is still capped by the camera's own ISO limiter.
 * On held-out images the regret is 0.0256, against 0.0310 for applying no lift and 0.0334 for the camera's own Auto rule computed
 * on non-wrapped data. The camera's own Auto computes 0 on real shots: the shadow-correction core (ToneControlTuning,
 * 0x53947230) takes the strength from a histogram of a block-luminance array (sb[0x54] == 0) whose block sums wrap at 16 bits.
 * The module of `tools/gr4v120/shadowml/shadowml.c` (integer only, bit-exact with `tools/gr4v120/shadowml/ref.py`) replaces that decision. The
 * model is data: a new blob (`gen.py [model.bin]`) needs no new code.
 *
 * Hook (0x539473A4, directly after the call of the Y-array builder 0x5391F1D4; the live-view call at 0x53947800 branches back
 * to the same word, so both paths pass it): the instruction `ldr r2,[fp,#-0x450]` is replaced by a branch to a stub that
 *   - keeps the camera's forced-zero cases (sb[0x8A] or sb[0x8B] set: branch to 0x53947784, the stock zero path),
 *   - calls `shadowml(ctx, P = sl, mode = sb[0x8D], hl = [fp-0x438], idx = r7)` with the stack 8-byte aligned,
 *   - on a negative result continues at the stock zero path 0x53947784,
 *   - otherwise continues at 0x539474D8 with r3 = t and r7 = 1, exactly where the camera's own Auto joins its common code:
 *     strength = (min(t, ISO cap) * gain) >> 11, the live-view five-frame smoothing, the level thresholds and the gain table.
 * The fixed levels (Low / Medium / High / Off) jump from 0x53947334 to 0x539474E8 and never reach this word.
 *
 * Auto's gain (TB[4] at 0x54080044, used by Auto only) goes from 0x100 to 0x400, so that Auto can reach High:
 * strength = min(t, cap) / 2, t = 2 * strength (the gain of Low is 0x100, of High 0x400, of the old Auto 0x100).
 *
 * Live view / movie (mode 1, 2) run the core on every frame: the module computes on every 4th call and holds the result in
 * between (one RAM word, SHADOWML_SLOT, below the heap; zero at start-up). Stills (mode 0, 3) always compute and never touch it.
 *
 * Working memory: one operator-new allocation (two disjoint halves, stills and live view, 776 bytes each; its pointer in the free
 * RAM word SHADOWML_SCRATCH_SLOT, zero at start-up) keeps the module's stack at about 300 bytes. If the allocation fails the
 * call gives the camera's no-correction result and the next one retries.
 *
 * Layout: the context, the module, the stub and the model blob are appended after everything else (as the learned white balance),
 * so every other addition keeps its place without this one. The state word is in the free RAM words before the heap at
 * 0x55839040; the start-up zero fill (the literal at 0x53000460) is extended to 0x55839040 if it is not already.
 */
import { FirmwareError } from '../../types';
import { assembleWords } from './arm';
import { Patch, expectWord, u32le } from './build';
import { SHADOWML_CODE, SHADOWML_CODE_LENGTH, SHADOWML_MAGIC } from './shadowml-code';
import { SHADOWML_DATA, SHADOWML_DATA_LENGTH } from './shadowml-data';

/** The hook word and the places around it that the stub relies on. */
export const SHADOWML_HOOK = 0x539473a4;
const CALL_Y_BUILDER = 0x539473a0; // bl 0x5391F1D4 (stills / RAW)
const LV_CALL = 0x53947800; // the live-view call of the same builder, followed by b 0x539473A4
const LV_BACK = 0x53947804;
const COMMON = 0x539474d8; // ldrb r5,[sb,#0x8D]: where Auto joins the common code with r3 = t, r7 = 1
const ZERO_PATH = 0x53947784; // the stock forced-zero path
/** Auto's gain table entry (TB[4]) and its values. */
export const SHADOWML_GAIN = 0x54080044;
export const SHADOWML_GAIN_OLD = 0x100;
export const SHADOWML_GAIN_NEW = 0x400;
/** Live view / movie: compute on every this-many-th call. */
export const SHADOWML_PERIOD = 4;
/** The throttling state word (free RAM before the heap; zeroed at start-up). */
export const SHADOWML_SLOT = 0x5583903c;
/** The firmware's operator new (the module calls it once) and the RAM word that keeps the scratch pointer (zero at start-up). */
export const SHADOWML_ALLOC = 0x539084bc;
export const SHADOWML_SCRATCH_SLOT = 0x55839014;
const ZERO_FILL_END = 0x53000460;

function fail(code: string, message: string): never {
  throw new FirmwareError(code, message);
}

function unbase64(text: string): Uint8Array {
  return typeof Buffer !== 'undefined' ? Uint8Array.from(Buffer.from(text, 'base64')) : Uint8Array.from(atob(text), (c) => c.charCodeAt(0));
}

export function shadowmlModule(): Uint8Array {
  const raw = unbase64(SHADOWML_CODE);
  if (raw.length !== SHADOWML_CODE_LENGTH) fail('internal', 'learned shadow correction module: length');
  return raw;
}

export function shadowmlData(): Uint8Array {
  const raw = unbase64(SHADOWML_DATA);
  if (raw.length !== SHADOWML_DATA_LENGTH) fail('internal', 'learned shadow correction model: length');
  return raw;
}

/** What `installShadowLearn` appended (for tests). */
export interface ShadowLearnLayout {
  ctx: number;
  code: number;
  stub: number;
  blob: number;
}

/** The learned Auto for Shadow Correction. */
export function installShadowLearn(p: Patch, options: { model?: Uint8Array } = {}): ShadowLearnLayout {
  // The words the hook and the stub rely on.
  expectWord(p, CALL_Y_BUILDER, 0xebff5f8b); // bl 0x5391F1D4
  expectWord(p, SHADOWML_HOOK, 0xe51b2450); // ldr r2,[fp,#-0x450]
  expectWord(p, COMMON, 0xe5d9508d); // ldrb r5,[sb,#0x8D]
  expectWord(p, ZERO_PATH, 0xe5d9508d); // ldrb r5,[sb,#0x8D]
  expectWord(p, 0x53947448, 0xe3a07001); // mov r7,#1
  expectWord(p, 0x539474f0, 0xe51b2448); // ldr r2,[fp,#-0x448]
  expectWord(p, LV_CALL, 0xebff5e73); // bl 0x5391F1D4 (live view)
  expectWord(p, LV_BACK, 0xeafffee6); // b 0x539473A4
  expectWord(p, 0x53947240, 0xe1a09003); // mov sb,r3
  expectWord(p, 0x53947258, 0xe5d3c08d); // ldrb ip,[r3,#0x8D]
  expectWord(p, 0x53947508, 0xe3550001); // cmp r5,#1
  if (p.word(SHADOWML_GAIN) !== SHADOWML_GAIN_OLD) fail('unexpected-layout', 'learned shadow correction: the gain table is not the official one');
  if (p.word(ZERO_FILL_END) !== 0x55839040) {
    expectWord(p, ZERO_FILL_END, 0x55839014);
    p.setWord(ZERO_FILL_END, 0x55839040, 'start-up zero fill also clears the 44 unused bytes before the heap');
  }
  const module = shadowmlModule();
  const blob = options.model ?? shadowmlData();
  const ctx = p.append(u32le([SHADOWML_MAGIC, 0, blob.length, SHADOWML_PERIOD, SHADOWML_SLOT, SHADOWML_ALLOC, SHADOWML_SCRATCH_SLOT]), 16);
  const code = p.append(module, 16);
  const stub = p.append((at) => assembleWords(
    `ldrb r0,[r9,#0x8a]
     ldrb r1,[r9,#0x8b]
     orrs r0,r0,r1
     bne #${ZERO_PATH}
     mov r4,sp
     bic sp,sp,#7
     sub sp,sp,#8
     str r7,[sp]
     movw r0,#${ctx & 65535};movt r0,#${ctx >>> 16}
     mov r1,r10
     ldrb r2,[r9,#0x8d]
     ldr r3,[fp,#-0x438]
     bl #${code}
     mov sp,r4
     cmp r0,#0
     blt #${ZERO_PATH}
     mov r3,r0
     mov r7,#1
     b #${COMMON}`, at), 16);
  const data = p.append(blob, 16);
  p.setWord(ctx + 4, data, 'learned shadow correction: model blob');
  p.setWord(SHADOWML_HOOK, (0xea000000 | (((stub - (SHADOWML_HOOK + 8)) >> 2) & 0xffffff)) >>> 0, 'learned Auto for Shadow Correction');
  p.setWord(SHADOWML_GAIN, SHADOWML_GAIN_NEW, 'Auto shadow correction can reach High');
  return { ctx, code, stub, blob: data };
}
