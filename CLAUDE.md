# GR Mod (fork orbitsail/Ricoh-GRMod): notes for Claude

Desktop tool that builds modified firmware for the Ricoh GR IV / HDF / Monochrome (fw 1.11), GR III and GR IIIx. GR IV code is shared and pinned by `core/test/gr4-unchanged.test.ts`.

## What this fork adds (GR IV fw 1.11 only)

- Learned auto white balance (`awbLearn`): an FFCC-style integer model replaces the plain Auto's R/B gains. `tools/awbml/`, `core/src/fw/aspect/awbml*.ts`. Kalman filter on live view only; stills compute fresh from their own statistics.
- ML shadow Auto (`shadowLearn`): a tree model replaces the camera's Auto decision of the shadow-correction core. `tools/shadowml/`, `core/src/fw/aspect/shadowml*.ts`.
- CPU LUT (`cpuLut`, experimental): the camera's CPU applies a look's own .cube to the JPEG. `tools/cpulut/`.
- Table builds of the stock AWB (`awbBlend`, `awbFit`) and the brighter Auto screen (`brightAuto`).

**Read `docs/griv-re/README.md` before any firmware reverse engineering** (conventions, pitfalls, the files for AWB, exposure, shadow/highlight, DNG tags, testing, history).
Small analysis scripts are in `tools/re/` (set `GRIV_RTOS` to the stock RTOS section).

## Build

- Install: `npm install`. Firmware needs the official file (`core/testdata/private/official.bin`, never committed; also in the private pack as `official/official.bin`).
- Test firmware: `npx vite-node tools/testfw/build.ts OFFICIAL.bin OUT.bin '{"brightAuto":"balanced","awbFit":true,"awbLearn":true,"shadowLearn":true}'`
- Regenerate embedded modules after editing the C or the reference: `python3 tools/awbml/gen.py`, `python3 tools/shadowml/gen.py` (needs clang + ld.lld + llvm-objcopy, or `GRMOD_ZIG=1` with ziglang). Never edit `*-code.ts`, `*-data.ts`, `*_const.h` by hand.

## Tests

- TypeScript: `npm test` and `npm -w core run typecheck`.
- Module suites (Python, need numpy, unicorn, gcc; they read inputs that live outside the repo: set `GRIV_DATA`, `GRIV_BASELINES` and `GRIV_RTOS` to the private pack, see `docs/griv-re/testing.md` section 4; a missing one stops with a message naming it):
  `cd tools/awbml && python3 test_host.py && python3 test_arm.py && python3 test_fuzz.py`, then `python3 test_fw.py [NEW_RTOS [V6_RTOS]]` (defaults to the pack's final5 and v6; ends with `RESULT all passed`).
  `cd tools/shadowml && python3 test_host.py && python3 test_arm.py && python3 test_fw.py PRE_RTOS BASE_RTOS`.
  `cd tools/re && GRIV_RTOS=... python3 awb_emu_check.py 1 1` (3502/3502) and `python3 shadow_check.py` (400 cases, 0 mismatches).
- The machine may have only 2 cores: do not run the long suites in parallel with other agents' runs.

## Rules

- Never commit firmware binaries (`RTOS.bin`, `fwdc248b.bin`, partition dumps) or tables extracted from them (`*.f64`, `*.npy`, dumps). Quote a few values inline at most.
- Push only to the fork `orbitsail/Ricoh-GRMod` (remote `fork`). Never push to the upstream `Maxwooow/ricoh-grmod` (remote `origin`). Commit only when asked.
- Keep the evidence tags in the RE notes: `[E]` emulated bit-exact, `[C]` read from code, `[I]` inferred, `[?]` unknown. When a new finding contradicts an old one, write old claim -> new claim and the source; do not silently overwrite.
- Anything the emulator stubs is a blind spot (8.0 shipped green stills because the capture gain words were 0x2000 in tests). Verify against real DNGs before shipping.
- No personal information in the repository: no names, home paths or photo file names; say "user-supplied DNGs".
- Module code must stay integer-only, position independent and bit-exact with its Python reference (`ref.py`); hooks assert the words they replace (`expectWord`).
- Two tasks (live view and still) reach the same estimate with no locks: keep per-path scratch.
- License of the sources: GPL-2.0-only (SPDX header on new files).
