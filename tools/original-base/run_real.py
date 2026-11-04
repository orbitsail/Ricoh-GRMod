#!/usr/bin/env python3
"""Original-base slots fitted on real raw data (not the Adobe-inverted calibration colours): scene = DNG-colorimetric block means,
Standard colours = the camera's own JPEG blocks (/home/claude/work/dngcheck/pairs.json, see realscene.py).
Usage: python3 run_real.py [--out /home/claude/work/out2] [--src <LUT folder>] [--prev /home/claude/work/prev] [--cur /home/claude/work/out]
Writes <out>/{train.json, exposure.json, slots/original, cubes/original, compare.csv, sheets/fuji.jpg, sheets/arri.jpg, run_log.txt}.
Third-party LUTs are only read from --src; nothing derived from them is meant to be committed."""
import argparse, csv, glob, json, os, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obase import *
from realscene import *
from preview import slot_apply

ap = argparse.ArgumentParser()
ap.add_argument('--out', default='/home/claude/work/out2')
ap.add_argument('--cur', default='/home/claude/work/out')
ap.add_argument('--prev', default='/home/claude/work/prev')
ap.add_argument('--src', default='/mnt/user-data/uploads/ClaudeWork/GRMod')
ap.add_argument('--jobs', type=int, default=2)
args = ap.parse_args()
OUT, SRC = args.out, args.src
FUJI_DIR = f'{SRC}/gfx-eterna-55-3d-lut-v110/33Grid/F-Log2'
ARRI_DIR = f'{SRC}/ARRI  LogC3 to Rec709 3D-LUTs'
for d in ('slots/original', 'cubes/original', 'sheets'): os.makedirs(f'{OUT}/{d}', exist_ok=True)
ORIG = {0: ('fuji', f'{FUJI_DIR}/FLog2_to_PROVIA_33grid_V.1.00.cube'), 1: ('fuji', f'{FUJI_DIR}/FLog2_to_CLASSIC-Neg._33grid_V.1.00.cube'),
        2: ('fuji', f'{FUJI_DIR}/FLog2_to_REALA-ACE_33grid_V.1.00.cube'), 3: ('fuji', f'{FUJI_DIR}/FLog2_to_ETERNA_33grid_V.1.00.cube')}
for n, f in {7: '3110-Film-A', 8: '5121-City', 9: '6311-Pastel', 10: '3411-Film-Teal-and-orange', 11: '3150-Film-process-Bleach-bypass',
             12: '9210-Day-for-Night', 13: '9211-Day-for-Night', 14: '3240-Faded', 15: '6220-Sommer'}.items():
    ORIG[n] = ('arri', f'{ARRI_DIR}/{f}.cube')
def nm(d, n):
    g = sorted(glob.glob(f'{d}/{n:02d} *.json')); return os.path.basename(g[0])[:-5] if g else None
NAME = {n: nm(f'{args.cur}/slots/current', n) for n in range(1, 21)}
NAME[0] = '00 Provia'
log = open(f'{OUT}/run_log.txt', 'w')
def say(*a):
    s = ' '.join(str(x) for x in a); print(s, flush=True); log.write(s + '\n'); log.flush()

# ------------------------------------------------------------------ 1. data, hold-out, training set
scene, jpeg, idx, meta = load()
files = [p['file'] for p in meta['per_image']]
ho = choose_holdout(jpeg, idx)
tr, cov = select_train(jpeg, idx, ho)
te = np.where(np.isin(idx, ho))[0]
say(f'pairs {len(idx)}; held-out images {ho} = {[files[i] for i in ho]} ({len(te)} pairs); training subset {len(tr)} pairs (cell cap {cov["cap"]}, {cov["n_neutral"]} near-neutral)')
say(f'empty chromatic cells (of 180): {cov["empty_cells"]}, cells with fewer pairs than the cap: {cov["cells_below_cap"]}')
say('coverage per JPEG hue sector (chroma >= 6): available (non-held-out) -> selected, mean chroma of selection, max chroma available')
for r in cov['per_hue']: say(f'  {r["sector"]:22s} {r["available"]:5d} -> {r["selected"]:4d}   meanC {r["mean_chroma_sel"]:5.1f}   maxC {r["max_chroma_avail"]:5.1f}')
Lt, Ct, Ht = lch(jpeg[te])
say('held-out hue histogram (C>=6): ' + str(np.histogram(Ht[Ct >= 6], bins=12, range=(0, 360))[0].tolist()) + f'; held-out mean chroma {Ct.mean():.1f}')
json.dump(dict(train_index=tr.tolist(), heldout_images=ho, heldout_files=[files[i] for i in ho], coverage=cov), open(f'{OUT}/train.json', 'w'))

# ------------------------------------------------------------------ 3. exposure + Provia sanity
provia = Cube(ORIG[0][1])
trainimgs = ~np.isin(idx, ho)
k, info = fit_k(scene[trainimgs], jpeg[trainimgs], provia)
say(f'\nEXPOSURE k = {k:.5f} on {info["n"]} near-neutral pairs (JPEG C<6, L* 25..75; training images): rms dL* {info["rms"]:.3f}, mean {info["mean"]:+.3f}, max|dL*| {info["max_abs"]:.3f}')
def chroma(rgb): l = srgb_to_lab(rgb); return np.hypot(l[:, 1], l[:, 2])
pv = np.clip(provia.lookup(encode(scene, k, 'fuji')), 0, 1)
Lj, Cj, Hj = lch(jpeg)
chrom = Cj >= 6
pooled = chroma(pv)[chrom].mean() / Cj[chrom].mean()
per_hue = {}
for h in range(12):
    m = chrom & (Hj // 30 == h)
    if m.sum() >= 20: per_hue[HUE_NAMES[h]] = (float(chroma(pv)[m].mean() / Cj[m].mean()), int(m.sum()))
say(f'Provia vs JPEG chroma ratio (pairs with JPEG C>=6): pooled mean-of-chroma {pooled:.3f}; ratio of means per JPEG hue sector (n>=20):')
for h, (r, n) in per_hue.items(): say(f'   {h:22s} {r:.3f}  (n={n})')
dLall = srgb_to_lab(pv)[:, 0] - Lj
say(f'Provia - JPEG dL* over all pairs: mean {dLall.mean():+.2f}, in L* 25..75 {dLall[(Lj>=25)&(Lj<=75)].mean():+.2f}; mean dE2000 Provia vs JPEG {0:.0f}')
json.dump(dict(k=k, **info, provia_chroma_ratio_pooled=float(pooled), provia_chroma_ratio_per_hue=per_hue), open(f'{OUT}/exposure.json', 'w'))

# ------------------------------------------------------------------ 4. targets + fits
br = Bridge()
cubes = {n: (provia if n == 0 else Cube(p)) for n, (fam, p) in ORIG.items()}
targets = {}
for n, (fam, p) in ORIG.items():
    raw = cubes[n].lookup(encode(scene, k, fam)); targets[n] = np.clip(raw, 0, 1)
    enc = encode(scene, k, fam)
    say(f'{NAME[n]:24s} log input outside 0..1 on {100*np.mean((enc.min(1)<0)|(enc.max(1)>1)):.1f}% of pairs; LUT output clipped on {100*np.mean((raw.min(1)<0)|(raw.max(1)>1)):.1f}%')
def run(jobs):
    with ThreadPoolExecutor(args.jobs) as ex: return list(ex.map(lambda j: j(), jobs))
def job(n):
    def f():
        path = f'{OUT}/slots/original/{NAME[n]}.json'
        if os.path.exists(path): return json.load(open(path))
        r = br.fit_pairs(jpeg[tr], targets[n][tr], NAME[n])
        slot = {kk: r['params'][kk] for kk in ('M1', 'ck', 'P2') if kk in r['params']}
        d_tr = br.de2000(br.apply(slot, jpeg[tr]), targets[n][tr]); d_te = br.de2000(br.apply(slot, jpeg[te]), targets[n][te])
        r = dict(title=NAME[n], source='real raw pairs (pairs.json), k=%.5f' % k, **r,
                 train=dict(n=int(len(tr)), mean=float(d_tr.mean()), p95=float(np.percentile(d_tr, 95))),
                 heldout=dict(n=int(len(te)), mean=float(d_te.mean()), p95=float(np.percentile(d_te, 95))))
        json.dump(r, open(path, 'w')); return r
    return f
res = dict(zip(ORIG, run([job(n) for n in ORIG])))
say('\nFIT ERROR, CIEDE2000 of slot(JPEG colours) vs original-LUT target')
say(f'{"slot":24s} train mean  p95   | held-out mean  p95')
for n in ORIG: say(f'{NAME[n]:24s} {res[n]["train"]["mean"]:7.3f} {res[n]["train"]["p95"]:6.3f}   | {res[n]["heldout"]["mean"]:7.3f} {res[n]["heldout"]["p95"]:6.3f}')
slot_of = lambda r: {kk: r['params'][kk] for kk in ('M1', 'ck', 'P2') if kk in r['params']}

# ------------------------------------------------------------------ 5. comparison on held-out JPEG colours
def load_slot(kind, n):
    nmx = nm(f'{args.cur}/slots/{kind}', n) if n else None
    if nmx is None: return None
    d = json.load(open(f'{args.cur}/slots/{kind}/{nmx}.json')); return d['params'] if 'params' in d else d
jt = jpeg[te]
def rend_of(kind, n):
    if kind == 'original': return slot_apply(slot_of(res[n]), jt)
    s = load_slot(kind, n); return None if s is None else slot_apply(s, jt)
def de(a, b): return br.de2000(a, b)
def cmpv(a, b):
    if a is None or b is None: return ['', '', '']
    return [f'{de(a, b).mean():.3f}', f'{chroma(b).mean()/chroma(a).mean():.3f}', f'{(srgb_to_lab(b)[:,0]-srgb_to_lab(a)[:,0]).mean():+.2f}']
rows = []
for n in sorted(ORIG):
    cur = jt if n == 0 else rend_of('current', n)
    rows.append([NAME[n]] + cmpv(cur, rend_of('adobe', n) if n else None) + cmpv(cur, rend_of('original', n)))
with open(f'{OUT}/compare.csv', 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['slot', 'dE2000_current_to_adobe', 'chroma_ratio_adobe/current', 'dL_adobe-current', 'dE2000_current_to_original', 'chroma_ratio_original/current', 'dL_original-current'])
    w.writerows(rows)
say('\nCOMPARE on held-out JPEG colours (Provia: current = the JPEG itself): dE2000 cur->adobe | cur->original | chroma ratio ad/or | dL* ad/or')
for r in rows: say(f'{r[0]:24s} {r[1]:>6s} | {r[4]:>6s} | {r[2]:>6s} {r[5]:>6s} | {r[3]:>6s} {r[6]:>6s}')

# ------------------------------------------------------------------ 6. baked cubes + re-import check
G = 33; gi = np.arange(G) / (G - 1)
grid = np.array([[r, g, b] for b in gi for g in gi for r in gi])
cam = br.cam()
def jb(n):
    def f():
        p = f'{OUT}/cubes/original/{NAME[n]}.cube'
        out = np.clip(br.apply(slot_of(res[n]), grid), 0, 1)
        with open(p, 'w') as fh:
            fh.write(f'TITLE "{NAME[n]}"\nLUT_3D_SIZE {G}\n'); fh.write('\n'.join(f'{a:.6f} {b:.6f} {c:.6f}' for a, b, c in out) + '\n')
        rr = br.fit_cube(p, 'ricoh')
        d = br.de2000(br.apply(rr['params'], cam), br.apply(slot_of(res[n]), cam))
        return float(d.mean()), float(np.percentile(d, 95))
    return f
rb = dict(zip(ORIG, run([jb(n) for n in ORIG])))
say('\nRE-IMPORT CHECK: convertCube(baked cube, ricoh) vs the slot it was baked from, CIEDE2000 on CAL_CAM')
for n in ORIG: say(f'{NAME[n]:24s} {rb[n][0]:.3f}  {rb[n][1]:.3f}')
say(f'worst mean {max(v[0] for v in rb.values()):.3f}  (limit 0.5)')

# ------------------------------------------------------------------ 7. photo sheets
PHOTOS = [('2088064441', 'Photo 1'), ('1024732252', 'Photo 2'), ('7694003938', 'Photo 3')]
thumbs = []
for f, _ in PHOTOS:
    im = ImageOps.exif_transpose(Image.open(f'{args.prev}/{f}.jpg')).convert('RGB'); im.thumbnail((360, 360)); thumbs.append(np.asarray(im, float) / 255)
font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14); fsm = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 12)
import re
def pretty(n):
    base = re.sub(r'^\d+ ', '', NAME[n])
    return {0: 'Provia (Fujifilm standard)', 1: 'Classic Neg. (Fujifilm)', 2: 'Reala Ace (Fujifilm)', 3: 'Eterna (Fujifilm cinema)'}.get(n, base.replace('ARRI ', 'ARRI look: '))
def sheet(rows_n, path, title, with_adobe=True):
    cw = 360; pad = 6; lw = 170; hh = 62
    colspec = [('current look', 'current'), ('adobe-based fit', 'adobe'), ('original film LUT', 'original')]
    nc = len(PHOTOS) * len(colspec)
    ch = max(t.shape[0] for t in thumbs)
    W = lw + nc * (cw + pad) + pad; H = hh + len(rows_n) * (ch + pad) + pad
    im = Image.new('RGB', (W, H), (24, 24, 24)); d = ImageDraw.Draw(im)
    d.text((pad, 6), title, fill=(235, 235, 235), font=font)
    for pi, (f, pn) in enumerate(PHOTOS):
        for ci, (cn, _) in enumerate(colspec):
            x = lw + (pi * 3 + ci) * (cw + pad)
            if ci == 0: d.text((x, 26), pn, fill=(235, 235, 235), font=font)
            d.text((x, 44), cn, fill=(170, 170, 170), font=fsm)
    for ri, n in enumerate(rows_n):
        y = hh + ri * (ch + pad); d.text((pad, y + ch // 2 - 8), pretty(n), fill=(235, 235, 235), font=fsm)
        slots = {'current': None, 'adobe': load_slot('adobe', n) if n else None, 'original': slot_of(res[n])}
        s_cur = load_slot('current', n) if n else None
        for pi, t in enumerate(thumbs):
            for ci, (cn, key) in enumerate(colspec):
                x = lw + (pi * 3 + ci) * (cw + pad)
                if key == 'current': arr = t if n == 0 else (slot_apply(s_cur, t) if s_cur else None)
                else: arr = slot_apply(slots[key], t) if slots[key] else None
                if arr is None:
                    d.text((x + 8, y + ch // 2 - 6), 'no look' if key == 'current' else 'not available', fill=(110, 110, 110), font=fsm); continue
                im.paste(Image.fromarray((np.clip(arr, 0, 1) * 255 + 0.5).astype(np.uint8)), (x, y))
    im.save(path, quality=90)
sheet([0, 1, 2, 3], f'{OUT}/sheets/fuji.jpg', 'Fujifilm family: rows = looks; Provia "current" is the camera JPEG with no look')
sheet(list(range(7, 16)), f'{OUT}/sheets/arri.jpg', 'ARRI family: rows = looks')
br.close()
