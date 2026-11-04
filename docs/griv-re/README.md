# Ricoh GR IV firmware 1.11: reverse-engineering notebook

## 概述（给机主）

这个目录是 GR IV 固件 1.11 逆向工作的永久笔记，原来的发现只存在于会话的临时目录里，会话结束就没了。
内容：自动白平衡（AWB）的原厂流程和我们的学习型挂钩、实时取景（LV）曝光的真实来源、阴影/高光校正的核心和我们的树模型挂钩、
DNG 厂商注释里可用来做测试数据的标签、CPU 套 LUT 实验、模拟器测试怎么跑，以及 7.x 到 8.2 的版本史。
每条结论都标了证据等级：[E] 在模拟器里逐位验证过，[C] 只读了代码，[I] 推断。
最重要的教训：模拟器里被桩掉（stub）的东西都是盲区，8.0 的绿色照片就是这么来的（拍照时 S+0x68/0x6E 增益字不是 0x2000，
而是每台机器自己的系数，约 1.56 / 3.02）；发布前一定要拿真实 DNG 对一遍。
动固件之前先读这个目录。注意：训练得到的模型参数（ffcc_cube_meta.npz）和测试用的场景数据不在仓库里，见 `testing.md` 的"外部输入"。

## Index

| file | content |
|---|---|
| [firmware-layout.md](firmware-layout.md) | container and RTOS image, address bases, memory map and MMU, tasks and OS, allocation pools, the module / hook mechanism of this fork |
| [awb.md](awb.md) | stock auto white balance (estimator, tables, manager, live view vs still, settings block S, WB mode routing, capture gain words, smoothing), our learned module (hook, algorithm, scratch layout, ctx field table) |
| [exposure.md](exposure.md) | where the live exposure really comes from (AE, ComPropIf, E/X/D buffers), property floats vs AE values, EXIF writers, still record fields, quantisation, open questions |
| [shadow-highlight.md](shadow-highlight.md) | shadow/highlight correction core 0x5391F230, tables, gain table, ISO limiter, the 16-bit wrap, highlight gate, our hook and the tree model |
| [dng-tags.md](dng-tags.md) | the DNG makernote tags used as test data and their layouts |
| [cpu-lut.md](cpu-lut.md) | the CPU-applied LUT experiment |
| [testing.md](testing.md) | the unicorn harness, what each suite checks, what is stubbed, how to run, expected output, external inputs |
| [history.md](history.md) | versions v1 .. v7, 8.0 .. 8.2: what changed and why, build hashes |
| `../../tools/re/` | the small analysis scripts that produced the [E] results (see its README) |

## Conventions

- **Firmware**: Ricoh GR IV (also HDF and Monochrome), firmware 1.11, `fwdc248b.bin` container. Only the RTOS section matters here.
- **RTOS.bin**: the decoded RTOS section, ARM32 little endian. Code address = file offset + `0x53000000` (BASE).
- **Initialised data**: at start-up `0x57480` bytes from image address `0x5437B640` are copied to RAM `0x55000000`. So the RAM address
  `0x55000000 + k` is the image address `0x5437B640 + k` (for k < 0x57480). `tools/re/fwlib.py` `off()` does this mapping. RAM above that
  (heap, zero-filled globals) has no image.
- **The mod builds keep the official addresses**: only the hook words and the appended area differ from the official RTOS, so every
  address in these notes is valid for the official image and for our builds (the appended area starts at the end of the official image, 0x543D2AC0).
- **Tags** (keep them when you edit these files): `[E]` emulated: the real firmware function was run in unicorn and agrees bit-exactly with a
  model or with the stated behaviour; `[C]` read from the code only; `[I]` inferred or interpreted (not shown by code or emulation);
  `[?]` unknown. An untagged statement is a definition or a plain fact of this repository.
- **Source of a claim**: written in parentheses when it matters, for example (awb_spec §4), (awbmgr Follow-up 4), (lvexp), (review final3).
  These were session notes; their content is merged here and the originals are gone.
- **Test data** are user-supplied GR IV DNGs and public studio shots; no file names or personal data belong in this directory.
- **Never commit** firmware binaries (`RTOS.bin`, `fwdc248b.bin`, partition dumps) or tables extracted from them (`*.f64`, `*.npy`, ...).

## Pitfalls and lessons

1. **Whatever the emulator stubs is a blind spot.** The test emulator set the capture gain words S+0x68 / S+0x6E to 0x2000. On the camera they
   carry per-unit factors (about 1.563 R / 3.019 B at capture) and the stock final stage output is proportional to them. 8.0 therefore shipped
   with green stills; 8.1 scaled the stills, 8.2 also scales live view by its own words (awb.md section 2.9, history.md). Before shipping,
   compare against real DNGs and list every stubbed input of the harness (testing.md).
2. **A float that looks like the live exposure may be a user setting.** The record words at +0x38D20.. (Av, Tv, ISO, EC) are the user's dial
   settings, written only when a value is set (an auto ISO leaves them alone). The live exposure is the AE's, published through the property
   store (exposure.md). Two wrong turns came from this: "word4 is a Bv" and "the EXIF writers 0x537FD980 etc. are getters".
3. **Functions named "getter" by pattern may be writers.** 0x537FD980 (Tv), 0x537FDB00 (Av) and 0x537FE310 (ISO) are EXIF tag writers
   (`CommonExifEntryDataSetter`), not getters of the exposure.
4. **Two tasks, no locks.** `LiveViewWb` and `WbCalcProcess` call the same Auto estimate on an SMP T-Kernel without any lock, so any module state
   needs a region per path (awb.md 2.11, 3.4). The shadow hook has the same split. Live-view-only state (throttle, filter) must never be touched by a still.
5. **Absence of a store is not proof of a zero.** The static search that found no writer of record word 4 concluded "probably always 0"; the
   real source was elsewhere. Say "no writer found by static search" and keep it `[I]`.
6. **Attribute functions by vtable, not by address neighbourhood.** 0x53938F00..0x53939174 and 0x5393931C belong to `CWhiteBalanceCte`, not to Auto
   (awb_spec §0).
7. **The stock shadow Auto computes 0 on real shots**: its block sums wrap at 16 bits (shadow-highlight.md), so "Auto" in the camera mostly does nothing.
   Any model of "what Auto does" must be run on the wrapped data, not on the true luminance.
8. **Test DNGs are firmware 1.01 files** (public studio shots, user shots may be 1.11). Recorded gains match the 1.11 emulation to about 1 %, but
   the capture-gain words and anything per-unit cannot be seen in a DNG.
9. **Per-unit values are not emulable.** The gain words come from a per-unit adjustment object at run time (awb.md 2.9); only a camera log shows them.
10. **Bit-exact float behaviour matters**: the exposure quantisation is `(int)(68 + 8x) - 68` in float32 with vmla/vnmls; the module reimplements it
    in integers and the equivalence is exhaustively tested over all 2^32 bit patterns (`tools/awbml/test_fl8.c`).
11. **Repository tests depend on files outside the repository** (trained parameters, scene sets, baseline builds). See testing.md before trusting a green run.
12. **Do not push to the upstream repository.** Push only to the fork (see the root `CLAUDE.md`).

## Where the evidence came from

Static disassembly (capstone), unicorn emulation of the real functions, 35 public GR IV DNGs (makernote statistics, recorded white balance), public
studio raws, a trained-model pipeline (SimpleCube++ for AWB, MIT-Adobe FiveK for shadow), and independent reviews of three builds
(memory map, boot MMU table, stack depths, relocation, byte-by-byte image accounting). Review findings are merged into the individual files.
