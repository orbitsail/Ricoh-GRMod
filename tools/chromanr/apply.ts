// SPDX-License-Identifier: GPL-2.0-only
/**
 * Add the chroma-only noise reduction patch to a finished GR Mod firmware for the GR IV (1.11).
 *
 *   npx vite-node tools/chromanr/apply.ts IN.bin OUT.bin
 *
 * IN.bin is an already built (encoded) firmware file: the official fwdc248b.bin or any GR Mod
 * build of it, whatever its looks and features. The half-resolution chroma pass of the colour noise
 * reduction then switches on from ISO 3200 instead of 12800 (see core/src/fw/aspect/chromanr.ts);
 * one instruction word changes, and the word that keeps the payload's checksum at zero absorbs the
 * difference. The file is re-encoded with `build` (every other frame stays as it was), then
 * checked with the self-check GR Mod runs on every build (against IN.bin) and the updater's own
 * container checks. Nothing is written unless every check passes.
 *
 * Refuses: a file that already has the patch, a file whose code around the change is not that of
 * firmware 1.11 (for example 1.20), anything that is not a firmware container.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { fw } from '../../core/src';

const [input, output] = process.argv.slice(2);
if (!input || !output || process.argv.length !== 4) {
  console.error('usage: npx vite-node tools/chromanr/apply.ts IN.bin OUT.bin');
  process.exit(2);
}
if (input === output) {
  console.error('refusing to overwrite the input file; give a different OUT.bin');
  process.exit(2);
}

function die(message: string): never {
  console.error('chromanr: ' + message);
  process.exit(1);
}

const raw = new Uint8Array(readFileSync(input));
let firmware: fw.Firmware;
try {
  firmware = new fw.Firmware(raw);
} catch (e) {
  die(`${input} is not a firmware container: ${(e as Error).message}`);
}
let result: fw.aspect.ChromaNrResult;
try {
  result = fw.aspect.applyChromaNr(firmware.decoded);
} catch (e) {
  const err = e as fw.FirmwareError;
  die(err.code === 'already-applied' ? `${input} already has the chroma NR patch; nothing written` : `${err.message}`);
}

const built = fw.build(firmware, result.decoded);
const checks = fw.selfCheck(raw, built.out, result.ranges, result.decoded);
const failed = Object.keys(checks).filter((k) => checks[k] !== true);
if (failed.length > 0) die(`self-check failed: ${failed.join(', ')}`);
const verify = fw.verifyContainer(built.out, result.decoded);
const verifyFailed = Object.keys(verify.checks).filter((k) => verify.checks[k] !== true);
if (verifyFailed.length > 0) die(`container check failed: ${verifyFailed.join(', ')}`);
// The decoded payloads differ in exactly the two words.
let changed = 0;
for (let i = 0; i < result.decoded.length; i++) if (result.decoded[i] !== firmware.decoded[i]) changed++;
if (changed > 8) die(`${changed} payload bytes differ, expected at most 8`);

writeFileSync(output, built.out);
const hex = (n: number): string => '0x' + n.toString(16).padStart(8, '0');
console.log(JSON.stringify({
  ok: true,
  input: { bytes: raw.length, sha256: await fw.sha256Hex(raw) },
  output: { bytes: built.out.length, sha256: await fw.sha256Hex(built.out) },
  changedPayloadBytes: changed,
  instruction: { address: hex(fw.aspect.CHROMA_NR_SITE), before: hex(result.word.before), after: hex(result.word.after) },
  checksumWord: { kind: result.compensation.kind, payloadOffset: hex(result.compensation.offset), before: hex(result.compensation.before), after: hex(result.compensation.after) },
  reencodedFrames: built.reencoded,
  selfCheck: `${Object.keys(checks).length} checks passed`,
}, null, 2));
