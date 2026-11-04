# Testing: the emulator harness and the suites

Rule 1 of this project: **an emulator result is only as good as its list of stubs.** 8.0 passed every suite and shipped green stills because the harness fed the capture gain words as 0x2000 (section 3). Read section 3 before trusting a green run, and compare with real DNGs.

## 1. Layers

| layer | what runs | tools |
|---|---|---|
| stock model | the real firmware AWB functions (RTOS.bin, ARM32) in unicorn vs the Python transcription | `tools/re/awb_emu_check.py`, `tools/re/shadow_check.py` |
| host | our C module (gcc, x86) vs the bit-exact Python reference, with and without ASan / UBSan | `tools/awbml/test_host.py` (+ `host.c`), `tools/shadowml/test_host.py` |
| ARM module | the compiled ARM module (as `gen.py` links it, at a test address) in unicorn vs the reference; instruction counts; register / stack / memory checks | `test_arm.py` in both tools |
| firmware image | the built RTOS.bin of a full build in unicorn, calling the real Auto estimate 0x53938B28 (or the shadow core 0x5391F230) as the camera does, vs the previous build and vs the reference | `tools/awbml/test_fw.py`, `tools/shadowml/test_fw.py`, `tools/shadowml/stack_fw.py` |
| memory safety | random corruption of the scratch under ASan / UBSan | `tools/awbml/test_fuzz.py` |
| quantiser | exhaustive check of `fl8()` over all 2^32 float patterns | `tools/awbml/test_fl8.c` |
| accuracy | angular error of the integer model vs the float model and the studio truth | `tools/awbml/accuracy.py`, `sim_filter*.py` (filter behaviour) |
| independent review | own harness `tools/re/rh2.py`: image at 0x53000000, init data copied, bump `operator new` (0x538E09B0 / 0x538E0A24) in 0x58000000.. that can be told to fail (logs every request), delete returns at once, `__stack_chk_fail` (0x53A786C0) and any unmapped access stop the run, `call()` sets r4..r11 to sentinels and checks them (AAPCS) and sp balance, poisons the stack below entry to measure the deepest use | review suites (not kept: memory, NULL allocation, edge grids, garbage scratch, preemption both ways, first-allocation race forced in both orders; instruction counts; stack depth vs official / v7b / v8c; fuzz with two seeds) |
| repository | `npm test` (vitest in `core`), `npm -w core run typecheck` | the TypeScript side; **no vitest test covers awbLearn or shadowLearn** (grep of `core/test`) |

## 2. The unicorn firmware harness (`tools/re/fwemu.py`, `hcommon.py`, `emuutil.py`)

- `Emu`: maps RTOS.bin at 0x53000000, copies the init data (0x57480 bytes from 0x5437B640) to 0x55000000, maps RAM 0x55000000+16 MB, scratch 0x60000000+64 MB, stack top 0x7E100000, enables VFP/NEON (CPACR, FPEXC); `call(fn, *args, stack=)` runs until a sentinel return address.
  `operator new` / `new[]` (0x538E09B0 / 0x538E0A24) are a bump allocator from 0x55800000 (zero-filled), delete (0x538E09EC / 0x538E0A60) and the assert/log helper 0x538ED930 return at once. Unmapped accesses are printed.
- `hcommon.new_emu()`: creates the Auto and Cte objects (`0x539371E4`, `0x53939218` at 0x60100000 / 0x60200000), sets the calibration singleton guard `0x553A136C = 1`, and **skips the weight-map generator 0x5393808C**. `setup_S` writes a settings block from a dict (the S fields of awb.md 2.3) and the five stat arrays; `rand_S` generates random scenes.
- `awb_ref.py` is the Python transcription (reads RTOS.bin for the constant tables through `$GRIV_RTOS`); `awb_emu_check.py [seed] [scale]` runs the real functions against it.
- Set `GRIV_RTOS` to the decoded stock RTOS section (`tools/re/README.md`). `capstone` and `unicorn` are Python packages.

## 3. What is stubbed or fed by the tests (the blind spots)

| input | in the harness | on the camera |
|---|---|---|
| **S+0x68 / 0x6E (and 0x6A / 0x6C) capture gain words** | 0x2000 (or random in `rand_S`; test_fw varies them only since 8.1) | per-unit factors, about 1.563 R / 3.019 B at capture; LV: manager halfwords set at run time from a per-unit table (awb.md 2.9). **This hid the 8.0 green stills.** |
| S itself | written by the test; the S builders (0x53933D88, 0x53935F84) are not run in the fw tests (svc_emu.py runs the real service init, which yields v24 = v28 = v2c = e30 = 0 in live view) | built from the record at run time |
| calibration singleton 0x553A130C | guard forced to 1, ROM pointers or random tables (`setup_cal`) | constructed by 0x5393CBC4 (ROM pointers; real values c30 {2000 x 4}, c34 {3352, 2000, 2000, 1241}) |
| weight-map generator 0x5393808C | skipped (S50 != 0 path not exercised through the real code) | runs when S50 != 0 |
| user white balance shift (P[0x78E/78F], P[0x71A0E/F]), 0x5393236C headroom, LV smoothing 0x53932914 | not part of the Auto estimate tests (smoothing checked separately by `smooth_emu.py`) | applied after the estimate |
| property store (live view exposure) | a fake store laid out by the test (guard 0x55379608, slot 0x55379610, E with vtable 0x53F8EDE8, X at E+0x518, two 0x1090 buffers) | the real ComPropIf; real publish cadence and torn reads cannot be reproduced; tearing is simulated by changing words between two reads |
| other tasks, preemption | none in the fw tests (single thread); the independent review forced preemption and the first-allocation race with its own harness | two tasks on SMP, no locks (awb.md 2.11) |
| allocator | bump allocator that never fails (fails on demand in the review harness and in `host_run` failing-alloc cases) | pool allocator; may fail |
| MMU, caches, interrupts | none (the MMU table was reviewed statically: firmware-layout.md) | present |
| the stock shadow Y builder | skipped or fed with an array | needs OS objects |
| data sets | converted statistics (SimpleCube++ → GR IV stats, FiveK → GR IV stats), public DNG statistics (firmware 1.01) | real sensor on firmware 1.11 |

## 4. External inputs the repository tests need (not committed): the private pack

Everything the suites need is the repository **plus one private folder** (the "private pack", made from the session scratchpad by `tools/re/pack_private.py SCRATCHPAD STAGING`). Three environment variables point into it; a missing variable or file stops a script with a message that names the variable and this section (`tools/re/griv_env.py`).

```
private_pack/
  data/            GRIV_DATA        scene sets (same relative layout the scripts expect)
    cubepp_gr/*.npz                 SimpleCube++ converted to GR IV statistics (2236 files, 42 MB)
    learnawb/cube_eval_preds.npz    the model's predictions on the cube set (used by scenes.load_cube)
    grdng/ext/*.npz, summary.json   DPReview GR IV statistics (v1.01 files) and their EXIF rows
    grdng/v6_tables.npz             small, used by the training/eval scripts only
    studio/*.npz                    studio shots
    fivek_gr/*.npz                  FiveK converted (780 files, 12 MB; test_fw samples every 40th)
    dng/*.dng                       optional: public DPReview GR IV DNGs; shadowml/test_host.py adds real-photo scenes when present
  baselines/       GRIV_BASELINES   <name>/RTOS.bin, the decoded RTOS section of earlier builds
    v6 v7 v7b v8c final2 final4 final5 final5_ns shadow_pre shadow_base
    shadow_pre   = scratchpad cpulut/fw14/pre: stock + the current shadowLearn module (per-path scratch, trained model), the PRE of
                   shadowml/test_fw.py. Earlier shadow builds (fw9 and before) carry the old module and fail its module-location check.
    shadow_base  = scratchpad cpulut/fw9/base: the same stock image without shadowLearn, the BASE of test_fw.py. The two images differ only by
                   shadowLearn; no build without the AWB module is needed (cpulut/fw12/nawb_RTOS.bin is not used).
  official/        the official firmware
    official.bin                    the 1.11 container; copy to core/testdata/private/official.bin for the builder (gitignored)
    RTOS_1.11.bin                   its decoded RTOS section = GRIV_RTOS for tools/re, fwemu and all test_fw.py
    official_1.20/fwdc248b.bin      the 1.20 container that was examined (labelled; no test uses it)
  notes/           the session's scratch notes (*.md, *.txt, f_*.txt disassembly listings) with their relative paths
```

```
export GRIV_DATA=/path/private_pack/data GRIV_BASELINES=/path/private_pack/baselines GRIV_RTOS=/path/private_pack/official/RTOS_1.11.bin
cp /path/private_pack/official/official.bin core/testdata/private/official.bin
```

What is now in the repository (it used to be scratchpad-only):

| item | where |
|---|---|
| trained parameters `ffcc_cube_meta.npz` (filters `F[2][64][64]`, biases `B[3][64][64]`; 164 KB) | `tools/awbml/model/` (`ref.PARAMS`, env `AWBML_PARAMS` overrides). `gen.py` reproduces `awbml-data.ts` (sha256 `89122871...`) from it |
| shadow model blob `model_final.bin` (sha256 `b3895f1c...` = the blob embedded in `shadowml-data.ts`) | `tools/shadowml/model/` (force-added: `*.bin` is gitignored); env `SHADOWML_MODEL` overrides |
| scene synthesis (relight, lamp, highlights; `settings()` builds the S block) | `tools/awbml/synth_scenes.py` (imported as `SC` by `test_fw.py`; `scenes.py` is the evaluation-scene loader) |
| `awbsim` / `drange` helpers | `tools/re/` (`awb_ref`, `fwemu`, `hcommon`, `emuutil`, `dngload`, `shadow_ref`); the tests put `tools/re` on `sys.path` |
| training and data-conversion code (reference only; no data) | `tools/awbml/train/` (ffcc.py, cube_eval.py, convert.py for SimpleCube++, stats.py, FiveK proc/run, checks) and `tools/shadowml/train/` (pipeline, model, tools). Their paths are relative to `$GRIV_WORK` (a working directory laid out like the old scratchpad: `cubepp_raw/`, `fivek_gr/`, `grdng/`, ...) |

Still not reproducible from the repository: the raw public data sets (SimpleCube++ ~2 GB, FiveK, the DPReview DNG downloads; all public) and the conversion outputs of the pack (regenerate with `tools/awbml/train/convert.py` etc. from the downloads if the pack is lost). The baseline builds can also be rebuilt from the commits in history.md. The official firmware is the user's file and is never committed.

## 5. How to run

Requirements: python3 with numpy, unicorn (2.x; 2.1.4 used), capstone; gcc (host and ASan / UBSan); clang + ld.lld + llvm-objcopy, or `python -m ziglang` (`GRMOD_ZIG=1`) for `gen.py`; node with `npm install`.

```
# regenerate the embedded module and tables (writes core/src/fw/aspect/awbml-code.ts / awbml-data.ts; also shadowml-*.ts with tools/shadowml/gen.py [model.bin])
python3 tools/awbml/gen.py ; python3 tools/shadowml/gen.py ; git diff --stat      # must be empty if nothing changed

# AWB module
cd tools/awbml
python3 test_host.py              # env AWBML_NSEQ (300), AWBML_NRANDOM (3000), AWBML_NQUANT (3 000 000)
python3 test_arm.py [n_scenes n_random]    # default 40 80
python3 test_fuzz.py              # env FUZZ_SEQ (150)
gcc -O2 -DAWBML_HOST -ffp-contract=off -o /tmp/test_fl8 test_fl8.c && /tmp/test_fl8
python3 test_fw.py [NEW_RTOS.bin [V6_RTOS.bin]]   # default $GRIV_BASELINES/final5 and v6; env AWBML_QUICK=1 (every 4th scene), V8C_RTOS, V81_RTOS, FINAL3_RTOS (the previous build, default final4), PREV_RTOS (strict image check; default final4 with ALLOW_SHADOW_HOOKS), EXPECT_SHADOW=1 (PREV_RTOS is the same module without the shadow part)
# shadow module
cd ../shadowml
python3 test_host.py ; python3 test_arm.py [n_random] ; python3 test_fw.py [PRE_RTOS.bin BASE_RTOS.bin] ; python3 stack_fw.py      # test_fw defaults: $GRIV_BASELINES/shadow_pre and shadow_base
# stock-model checks (set GRIV_RTOS first)
cd ../re ; python3 awb_emu_check.py 1 1 ; python3 awb_emu_check.py 7 4 ; python3 shadow_check.py
# TypeScript
npm test ; npm -w core run typecheck
```

Building a firmware to test (needs the official file; not run when these notes were written): `npx vite-node tools/testfw/build.ts OFFICIAL.bin OUT.bin '{"brightAuto":"balanced","awbFit":true,"awbLearn":true,"shadowLearn":true}'` writes `OUT.bin` and `OUT.bin.rtos` (the decoded RTOS section) and prints the sha256.
The daily builds also used scripts `daily_fw*.mts` with the look slots and icons (not in the repository); their environment switches were `CURVE=balanced AWBFIT=1 AWBLEARN=1 SHADOWML=1`.

## 6. What each suite checks and the success lines

| suite | checks | success looks like |
|---|---|---|
| `awb_emu_check.py` | 0x5393C4D4 accumulate, 0x5393926C atan2/magnitude, 0x538D3298 log2 (all), per-block entries (Auto, Cte), 0x53937BFC row weights, 0x539376A8 block loop, CTE estimate, Auto estimate | last line `TOTAL 3502/3502 trials bit-exact (100.00%)` for seed 1 scale 1 (re-run: 16 s on this 2-core machine); `12472/12472` for seed 7 scale 4 (from the spec; not re-run) |
| `shadow_check.py` | stock shadow core 0x5391F230: strength, level and gain table vs `shadow_ref.py`, 400 random cases | `cases 400 mismatches 0` and `strength/level agree [400, 400]` (re-run: under 1 s) |
| `awbml/test_host.py` | C (-O2 and ASan/UBSan) vs `ref.py` on SimpleCube++, gallery, studio and synthetic scenes (odd grids, clipped / zero blocks, empty scenes, `v24 = -0x880`, extreme e30, mode byte != 0, failing allocation); still vs live view; interleaved sequences; the exposure reader on a fake property store; quantiser vs strict float32 | final lines `total N mismatches 0`, exit status 0; `quantiser (ref.fl8 vs strict float32): ... mismatches 0`; `filter coverage in the sequences:` list |
| `awbml/test_arm.py` | ARM module vs `ref.py`, instruction count for a full scene, stills never write the live-view region, AF89 cleared only on an override, read order of the property words, sequences with period 4 and the filter | `ARM (unicorn) vs ref: N cases, 0 mismatches, K fallbacks` and `ARM (unicorn) sequences (...): N calls (M with a usable record), 0 mismatches`; `instructions for one full scene: ...` |
| `awbml/test_fuzz.py` | no out-of-bounds read or write with a randomly corrupted scratch | `fuzz: N calls with random scratch corruption: no out-of-bounds access (ASan / bounds / UBSan clean)` |
| `awbml/test_fl8.c` | `fl8()` over all 2^32 patterns x 2 bases vs strict float32 | `fl8: ... pattern/base pairs, ... accepted, mismatches 0` |
| `awbml/test_fw.py` | (1) every scene x modes 0, 1, 2 x live / still, fresh emulators: mode 0 equals the reference, modes 1, 2 and fallbacks equal the previous build, operator new called once, canary, r4-r11 preserved; (2) interleaved sequences with stills; (2b) varied S+0x68/6E; (3) stack depth and instruction counts; (4) image diff vs the previous build (only the call word and appended bytes); (4b) with `EXPECT_SHADOW`: hook word, TB[4], appended shadow area and the compensation word; (5) live view exposure from the property store vs the stock still builder; (6) vs the previous firmware without a usable store | per-section lines, then `RESULT all passed`, exit 0 |
| `shadowml/test_host.py` | C vs `ref.py` for the committed model, the placeholder and constant/random blobs on public DNG statistics, edge and random grids; ASan/UBSan child | `RESULT all passed` |
| `shadowml/test_arm.py` | ARM vs ref; throttled sequences; scratch: one allocation, writes only inside its halves, failed allocation then retry; deepest stack write | `ARM (unicorn) vs ref: N calls, 0 mismatches; r4-r11/sp preserved: N/N; record unchanged: N/N`, `deepest stack write: ... (limit 320)` |
| `shadowml/test_fw.py` | hooked image vs the base image fed with t from ref.py; live view / movie sequences; five-frame smoothing; fixed levels and forced-zero bytes identical to the base; both entry alignments; instruction counts; image diff vs the build without shadowLearn; stub words vs clang's assembler | `RESULT all passed` |

Typical sizes: one full AWB estimate is about 2.2 M instructions (the camera's own Auto about 2.9 M), +5.7 k for the filter; the shadow module stack is 276 bytes; the AWB path stack is 616 bytes below the estimate entry.
Wall-clock times of the Python suites were not recorded in the sources except the two re-run above; `test_fw.py` builds a fresh emulator pair per scene and mode (hundreds of pairs; runtime not recorded), and `awb_emu_check.py 7 4` runs about four times the trials of the seed-1 run.
