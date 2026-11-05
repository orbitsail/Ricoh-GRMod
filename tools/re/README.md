# tools/re: reverse-engineering helpers for GR IV fw 1.11

Small scripts that produced the [E] results in `docs/griv-re/`. Read `docs/griv-re/README.md` first. None of them contains firmware bytes or extracted tables; they read the stock RTOS from a file you provide.

## Setup

- `GRIV_RTOS=/path/to/RTOS.bin`: the decoded RTOS section (ARM32 LE, base 0x53000000) of the **official** fw 1.11 (from the official file with the repository's container code: `new fw.Firmware(file).decoded` then `fw.sectionsOf`, as `tools/testfw/build.ts` does for the `.rtos` file it writes). `awb_ref.py` also accepts `RTOS_BIN`.
  Never commit this file. Without the variable the scripts look for `RTOS.bin` in the current directory.
- Python 3 with `numpy`, `unicorn` (2.x), `capstone`. Run the scripts from this directory (they put their own directory on `sys.path`).

## Files

| file | purpose |
|---|---|
| `fwlib.py` | image access (`rd`, `w`, `u16s`, address mapping that includes the init-data copy), `dis`, `callers(target)`, `xrefs(value)`, `find_word`, `func_start`. Used by `shadow_ref.py` |
| `xr.py` | static cross-reference helpers (the lvexp set): `fstart`, `callers`, `lits`, `movwt`, `pr(addr, n)`, `cstr` |
| `t.py` | tiny capstone disassembly/xref helper (awbmgr set) |
| `fwemu.py` | unicorn runner for real firmware functions (bump allocator for operator new, assert helper skipped); see docs/griv-re/testing.md |
| `emuutil.py`, `hcommon.py` | AWB object/frame helpers and the settings-block (S) builder for the emulator; random scene generator; weight-map generator `0x5393808C` is skipped |
| `awb_ref.py` | Python transcription of the stock AWB (front end and estimators), bit-exact with the firmware; spec: `docs/griv-re/awb.md` |
| `awb_emu_check.py [seed] [scale]` | runs the real functions in unicorn against `awb_ref.py`; `python3 awb_emu_check.py 1 1` ends with `TOTAL 3502/3502 trials bit-exact (100.00%)` (16 s on 2 cores) |
| `smooth_emu.py`, `svc_emu.py`, `r7_emu.py` | emulation probes behind awb.md: live view boxcar smoothing (2.6), service init and S (2.1/2.4), r7 == r2 at the hook and the AF89 flag (3.1, 2.7). Probes, not asserts |
| `shadow_ref.py` | Python model of the shadow core 0x5391F230 and the gain-table builder 0x5391F084 (reads TA/TB/TC/CURVE/HLTAB from RTOS.bin) |
| `shadow_emu.py`, `shadow_check.py` | unicorn harness for the real core and the 400-case check (`cases 400 mismatches 0`) |
| `mode2_emu.py` | the Y-block builder 0x538F75FC (mode 2) in unicorn |
| `tiff.py`, `mn.py`, `dngload.py`, `parse.py`, `dngwb.py` | DNG/TIFF reader, makernote loader with the tag-name table, `load405`, a per-file dump that saves the AWB statistics (`parse.py file.dng [out.npz]`), a tag listing for many files (`dngwb.py 'dir/*.dng'`); layouts in `docs/griv-re/dng-tags.md` |
| `rh2.py` | the independent reviewer's unicorn harness (bump `operator new` that can fail, stack poison, AAPCS sentinels, sp balance) |
| `ae/` | the AE accuracy study (ae-accuracy.md): DNG and FiveK tables, the comparison with the five experts, checks. Reads `$GRIV_DATA/ae`; see `ae/README.md` |
| `fwread/` | static-reading helpers of the AE / exposure-program study (exposure.md): annotated disassembler, getter / setter pair map, UTF-16 string and pointer search; see `fwread/README.md` |

## Left out of this directory (and why)

- `*.bin` partition dumps and `*.f64` LUT tables of the session's `re/` folder: firmware data and extracted tables must not be committed.
- Scripts that hard-code large local data or paths and are one-shot probes: `greenbug/hc_e30.py`, `parse_all.py`, `runref.py`, `shadow_pred.py`, `stock.py` (depend on saved statistics), `drange/allshadow.py`, `dng_proxy.py`, `fx.py` (bulk helpers),
  the disassembly listings (`f_*.txt`, `disasm/`, `shadow_core_final.txt`; bulk listings), `review/*` suites other than `rh2.py` (they depend on the review's build directories), `awbmgr/modes_*.py` and `green*.py` (long, depend on emulated services and the greenbug statistics),
  `review/lvexp/s*.py` (search scripts that depend on `xr.py` and produced the negative results recorded in `docs/griv-re/exposure.md`), `awbsim/v6check`.
- Training pipelines (`learnawb/ffcc.py`, `shadowml/pipeline`, `shadowml/model`) and converted data sets: large; see testing.md section 4.
