# Firmware layout (GR IV, fw 1.11)

## 1. Container and RTOS image

The update file `fwdc248b.bin` (official: 38 648 776 bytes, see `OFFICIAL_SIZE` / `OFFICIAL_SHA256` in `core/src/fw/profile.ts`) is described in the header comment of
`core/src/fw/container.ts`:

- `0x00` header of 0x80 bytes (project number at 0x30, 0x78 = proj | proj << 16, 0x7C = 0xA55A5AA5);
- `0x80` an LZ stream of frames (`u16` big-endian prefix + body; prefix 0 ends; bit 0x8000 = stored frame; 8 KB window running across frames;
  decoded frame size 0x8000 first, then 0x6000 each, last partial);
- footer: model records of 0x80 bytes, then 0x18 bytes (proj | proj << 16, 0xA55A5AA5, fw type, stream length, decoded length, file checksum);
- the file's little-endian 32-bit word sum is 0, and so is the decoded payload's.

The independent review of a built file (review final) found: container opens, `verifyContainer` 8/8, `selfCheckGrown` 21/21, the RTOS re-extracts identically,
file/payload sums 0, footer consistent, 2794 frames of which 416 stored full (0x6000) [E].
The decoded payload holds several sections; the one we patch is `RTOS`. Official RTOS length 0x13D2AC0 (20 785 856 bytes); `core/src/fw/profile.ts`
has the section table, `core/src/fw/aspect/build.ts` the constants `BASE`, `OFFICIAL_RTOS_LENGTH`, `APPEND_LIMIT`.

## 2. Address bases and the RTOS image

- RTOS.bin is ARM32 little endian, base `0x53000000` (address = base + file offset).
- Initialised data: `0x57480` bytes at image address `0x5437B640` are copied to RAM `0x55000000` at boot (`build.ts` `RAM`). Note `0x5437B640 + 0x57480 =
  0x543D2AC0`, the end of the official image: the init data is the image tail, and our appended area starts right after it.
- Code ends and strings/data start around `0x53EA0000` (xr.py `CODE_END`); the instruction scan helpers use `0x54000000` as the end of code. [I: rough bounds]
- The appended area must stay below `0x55000000` (`APPEND_LIMIT`); the daily build with all modules appends about 0x6C000 bytes (RTOS 0x143EAC0). [from the file sizes of the 8.2 build]
- The OS is "SMP T-Kernel 1.00.01" (string in the image): true multicore, lower priority number = higher priority [I].

## 3. Memory map and MMU

From the reviews [C] (review final, final3):

- Boot first-level translation table at `0x53004000`.
- `0x55000000 .. 0x7FFFFFFF`: read/write sections, no holes (mmu_window).
- The section `0x544xxxxx` is mapped XN = 0, AP = read-only: this is the same section that holds code earlier builds (v6, v7b) already ran, so
  appended code executes there; it cannot be written at run time.
- TTBR0 is written at `0x530830A4` and `0x53086C90` (found at the task switch) [C]. Whether tasks see different mappings was not examined; all our state is in the flat
  RW RAM above, which both paths use.
- Heap: module scratch memory is taken with the firmware's `operator new` and the heap starts at `0x55837300`. The 44 bytes `0x558372D4 .. 0x558372FF`
  are unused free RAM before the heap, zeroed by the start-up fill (see 6).

RAM words our modules use:

| address | owner | content |
|---|---|---|
| `0x558372D4` | shadowml (`SHADOWML_SCRATCH_SLOT`) | pointer to the shadow module's scratch (one `operator new`, 2 x 776 bytes); 0 at start-up |
| `0x558372DC` | awbml (`AWBML_SLOT`) | pointer to the AWB module's scratch (one `operator new`, 2 x 35 468 bytes); 0 at start-up |
| `0x558372FC` | shadowml (`SHADOWML_SLOT`) | the live view / movie throttling state word |

The independent review scanned every reference to `0x558372C0 .. 0x5583730F` in the official and the final images (review final, d_refs); the module sources state these
words are free RAM before the heap [C]. Check that scan again before adding a new slot.

## 4. Tasks and OS objects

- Module table at `0x53FE1A94`, 16 bytes per entry, created through `0x538E32C4` -> a `cre_tsk`-like `0x538E31E4` [C].
  - id `0x2E` "LiveViewWb": priority 80/82, stack 16384, group "FE";
  - id `0x84` "WbCalcProcess": priority 84/84, stack 8192, group "BE".
- Two separate tasks reach the Auto estimate, with no lock or semaphore in either Execute, either calc or the estimate (details in awb.md 2.11).
- The AE live-view loop is at `0x53665CE8` (event-flag driven; see exposure.md); the property store (ComPropIf) has its own task that executes setters.
- Messages: LiveViewWhiteBalance::Execute (`0x53649F20`) runs when msg[+0xC] == 0x500001; WbCalcProcess::Execute is `0x5370D9B4` (vtable `0x53F84C20` slot 8).
- Locked reads of the property store use the lock `E+0x2C` with timeout `[0x53FE18C8]` (= wait forever) [C]. We never take that lock (see exposure.md).

The source file of a function can be read from the assert strings: the assert helper is `0x538ED930` and the file name is passed in r2 of the `bl`. Files seen:
`src/LiveViewWhiteBalance.cpp`, `AeInternalInformation.cpp`, `src/R2Y/ToneControlTuning.cpp`.

## 5. Allocation

- `operator new` = `0x538E09B0`, `operator new[]` = `0x538E0A24`; delete = `0x538E09EC`, delete[] = `0x538E0A60` [C]. Test harnesses hook exactly these (fwemu.py, rh2.py).
- Pool allocator: pool table at `0x5539FEF8`; `0x538DD620(0xD)` returns pool 0xD from which the property store's 0x2120-byte block is carved (lvexp).
- Our modules call `operator new` once, on their first computing call (the function pointer comes through their context), and keep the pointer in the RAM slot above.
  If the allocation fails, the AWB module leaves the camera's own result; the shadow module returns -1 (no correction) and retries on the next call.
  The camera never frees these blocks (they live for the session).
- Stack: the module code adds a few hundred bytes to the calling task's stack. Measured below the Auto estimate entry (the camera's own estimate included): 616 bytes
  for stills, rejected live view and usable live view alike [E] (review final2/final3). Shadow: module 276 bytes (limit 320 asserted in `tools/shadowml/test_arm.py`),
  whole core path 1460 bytes [E] (review final3 e4).

## 6. The module / hook mechanism of this fork

All our native additions are small position-independent C modules compiled to ARM and appended to the RTOS image, reached through one rewritten instruction:

1. **Patch** (`core/src/fw/aspect/build.ts`, class `Patch`): `append(blob | (addr)=>words, alignment)` returns the address; `word()`, `setWord()`, `expectWord()` read and
   write 32-bit words. Every hook first asserts the words it relies on (`expectWord`) and fails with `unexpected-layout` if the image is not the official one.
2. **Module** (`tools/<name>/<name>.c`, compiled by `gen.py` into `<name>-code.ts` base64): integer only, no global data, no libcalls, position independent (`-fropi -frwpi`).
   `gen.py` links it at two addresses and compares, refuses `.data/.bss/.rodata/.got`, undefined symbols, and requires the entry at offset 0. Everything the module
   needs comes through a **context** (`ctx`) struct of 32-bit words: magic, the firmware's `operator new`, the RAM slot, pointers to its tables, tuning words.
3. **Stub**: a few instructions assembled by `arm.ts` (`assembleWords`) that make the original call, load the ctx address (`movw/movt`) and call the module with the camera's
   registers as arguments. The hook word is a `bl` or `b` to the stub.
4. **Data**: tables are appended after the code (AWB 79 KB; the shadow model blob ~5.5 KB). The ctx words for tables are filled with `setWord` after layout.
5. **Order**: `build.ts` installs `awbml` and then `shadowml` last, so every other addition keeps the places it has without them; the images then differ from a build without
   them only by the hook words and the appended bytes. Tests check this (`test_fw.py` section 4, 4b).
6. **Zero fill**: the RAM slots need a zero start value. The start-up zero fill ends at the literal at `0x53000460` (official value `0x558372D4`); both modules extend it to `0x55837300`
   (when not already) so that all three slots above are cleared.

Hook sites of the learned modules:

| module | hook word | original | note |
|---|---|---|---|
| awbml | `0x53938E2C` | `bl 0x53938970` (final stage of the Auto estimate) | stub calls the final stage, then the module; see awb.md |
| shadowml | `0x5391F3A4` | `ldr r2,[fp,#-0x450]` | replaced by a branch to the stub; also `TB[4]` at `0x5404938C` 0x100 -> 0x400; see shadow-highlight.md |
| cpulut | start of `JpegEncodeMacroProcess::Execute` `0x537034B4` | | see cpu-lut.md |
| brightAuto, awbBlend, awbFit | data and table pointers (plus one code word `0x53936830` add r3,r3,#0x20 -> #0x21 in awbFit) | | `brightauto.ts`, `awbblend.ts`, `awbfit.ts` |

Build options (`BuildOptions`, `core/src/fw/aspect/build.ts`): `cpuLut`, `brightAuto: 'bright' | 'balanced'`, `awbBlend: 0..1`, `awbFit`, `awbLearn`, `shadowLearn`.
`awbFit` replaces `awbBlend`; `awbLearn` is allowed together with `awbFit`.
