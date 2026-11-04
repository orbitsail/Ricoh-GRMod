# DNG makernote tags used as test data

The camera's DNG files carry the AWB statistics, the white balance it used and several settings in the DNG private data. We use them to test the AWB and shadow models against what the camera recorded.
Readers: `tools/re/mn.py` (loader and tag-name table), `tools/re/tiff.py` (TIFF reader), `tools/re/parse.py` (dump one file and save the statistics), `tools/re/dngload.py` (`load405`), `tools/re/dngwb.py` (tags of many files).
Test data are user-supplied GR IV DNGs and the 35 public DPReview GR IV DNGs (firmware 1.01). No file names belong in this repository.

## Container

- `DNGPrivateData` (IFD0) starts with `"RICOH\0II"` and holds a Pentax-style IFD at offset 8, little endian (`mn.load_mn`: `Tiff(data, base=vpos, order='<')`, `ifd(8)`). Entry positions are relative to the start of that block.
- `mn.py` `PTAGS` is the Pentax tag-name table (from the public Pentax makernote lists). Names are not verified for Ricoh; use the numeric tag.
- Exif IFD: `ExposureTime`, `FNumber`, `ISO`, `ExposureCompensation` give Av = 2 log2(N), Tv = -log2(t), Sv = log2(ISO / 3.125) for `e30 = round((Av + Tv - Sv) * 256)`. `Software` carries the firmware version ("... Ver. 1.11").

## Tags

| tag | type / size | content |
|---|---|---|
| `0x0405` | 73740 bytes | **AWB / shadow statistics block**, layout below |
| `0x0201` | 4 values | WhitePoint: the white balance gains the camera finally used (R, G1, G2, B), 1.13 fixed point, G = 8192. Agrees with the DNG's AsShotNeutral: neutral R = 8192 / R gain, B = 8192 / B gain. Example of a real file: [16768, 8192, 8192, 19616] -> AsShotNeutral 0.4885, 1.0, 0.4176 [E] |
| `0x0019` | 1 value | WB code. Values seen: 0 and 18. Code 18 on a file whose recorded gains match the stock mode-1 estimate (R 2.05 / B 2.40 vs emulated 2.12 / 2.32) [I: 1 = Warmth priority]. The writer of this tag was not found in the firmware [?] |
| `0x0069` | 4 bytes | byte 0 is the highlight-correction flag (used as `hl` / S+0x51 in the probes; a file with bytes `01 02 00 00` was HC on) [I]; the other bytes were not decoded [?] |
| `0x0079` | 2 values | shadow correction: seen as [2, 4] in a test file; the pair's meaning (setting vs applied level) is not established [?]. The camera's setting is `P[0x7E5]`: 0 Auto, 1 Low, 2 Med, 3 High, 4 Off |
| `0x0221` | KelvinWB | 16 colour temperature points of the camera's own Planckian curve: at byte `2 + 8*i` (i = 1..16) four u16: `code`, `-`, `rg`, `bg`; temperature = 20000 - (code & 0x7FFF), gains = rg/8192, bg/8192. Used to relight scenes to a given K |
| `0x0222` | ColorInfo | 8 numbers near 8192 (look like factory calibration; not used) |
| `0x0068` | AWBInfo | small pair, seen as [0, 1]; not decoded [?] |
| `0x0033` | PictureMode | 3 values; not used |

## 0x0405 layout (73 740 = 0x1200C bytes)

```
+0x0000  u16 w, u16 h                          grid size (64, 62 on the GR IV)
+0x0004  u16 Y[64][64]  (0x2000 bytes)         the shadow core's Y-block array = P+0x24BD0 (see shadow-highlight.md 2)
+0x2004  u32 R  [64][64]  (0x4000 bytes)       P+0x14BD0   block mean, 12 bit (<= 0xF6D useful), vignetting corrected, only non-saturated pixels
+0x6004  u32 Gr [64][64]                       P+0x18BD0
+0xA004  u32 B  [64][64]                       P+0x20BD0
+0xE004  u32 cnt[64][64]                       P+0x26BD0   valid pixels per block (1584 = 48 x 33 groups of 2 x 2 pixels when complete)
+0x12004 u32                                   P+0xBC0 (4 bytes)
+0x12008 u16, u16                              P+0x2EBE4, P+0x2EBE6
```

Order and offsets are from the writer (`0x5380E2xx..0x5380E3FC`) and reader (`0x537F4F10..0x537F50AC`) [C] and from the sizes (4 + 0x2000 + 4 x 0x4000 + 4 + 2 + 2 = 73 740 ✓). The planes are the same arrays the stock AWB reads (S+0..S+0x10, awb.md 2.3); Gb is not stored and is set equal to Gr on load.
Earlier notes called the first u16 block "encrypted / scrambled, not decoded"; it is the Y array (drange NOTES2, emulated in `mode2_emu.py`).

Relation to the raw data (public DNGs): statistics ≈ (raw - 64) / 4 x vignetting gain x (0.920, 1, 0.974) for (R, G, B), measured at the image centre (the first write-up said 0.916 / 0.973; the code constants 0.920 / 0.974 are the later value).

## How the tags are used

- **AWB tests**: feed the planes (R, Gr, Gr, B, cnt) with `x0 = y0 = 0`, `w = 64`, `h = 62`, stride 64, `b51 = 1` (EV +1) and `m18 = 1584` into `awb_ref.py` or the module reference; compare the gains with tag `0x0201`.
  Result for the 35 public DNGs: after a fixed ratio (R 0.6313, B 0.3313) the simulated gains differ from the recorded ones by 0.64 % (R) and 0.83 % (B) on average, 2.3 % at worst (awb.md 2.10).
  Scripts like `hc_e30.py` (not kept) tried exposure offsets (0, -1, -0.5, +0.5 EV in Sv) and exact vs half-stop quantised APEX to find the best fit to `0x0201`; the first exposure computation in an early `gr4_check.py` had one EV too many (median error 3.2-3.35° instead of the 3.61° later quoted).
- **Shadow tests**: the Y array (`0x0405` +4) with the highlight flag and ISO index reproduces the strength the stock Auto would compute (always 0 on the 35 files, see shadow-highlight.md 5).
- **Studio calibration**: the DPReview studio raws (daylight and warm light, ISO 100 and 200) gave the true neutral (raw R/G, B/G) by measuring the colour checker's grey patches in the raw: daylight 0.340 / 0.669, warm 0.665 / 0.322; their `0x0405` statistics were fed to the models. The warm shots used auto white balance: recorded WB (R/G 0.5278, B/G 0.3963) vs emulated stock Auto (0.5248, 0.3965), the first check of the simulator on a real warm-light photo. The daylight shots were manual white balance (= the grey card), so the simulator only shows what Auto would choose.
  The camera's own JPEG preview in that DNG shows grey patches within 2 levels in R, G, B for the manual-WB shot (so the colour processing adds no warmth), and N8 = 174 / 150 / 127 for the auto-WB warm shot (stock Auto left much orange).
- **Firmware version caveat**: public DNGs are firmware 1.01, our emulation is 1.11; they agree within the numbers above, and nothing in a DNG shows the per-unit capture gain words (awb.md 2.9).
