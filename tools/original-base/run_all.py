#!/usr/bin/env python3
"""Fit every slot (current / adobe / original base), bake cubes, check re-import, write compare.csv.
Usage: python3 run_all.py [--out /home/claude/work/out] [--src /mnt/user-data/uploads/ClaudeWork/GRMod]
Stages are cached as JSON in <out>/slots; delete a file to refit it. Third-party LUTs are read from --src and never copied."""
import argparse, csv, glob, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obase import *

ap = argparse.ArgumentParser()
ap.add_argument('--out', default='/home/claude/work/out')
ap.add_argument('--src', default='/mnt/user-data/uploads/ClaudeWork/GRMod')
ap.add_argument('--jobs', type=int, default=2)
args = ap.parse_args()
OUT, SRC = args.out, args.src
FUJI_DIR = f'{SRC}/gfx-eterna-55-3d-lut-v110/33Grid/F-Log2'
ARRI_DIR = f'{SRC}/ARRI  LogC3 to Rec709 3D-LUTs'
CUR_DIR = f'{SRC}/1_相机里的20个/LUT'
for d in ('slots/current', 'slots/adobe', 'slots/original', 'cubes/original', 'cubes/adobe', 'sheets'):
    os.makedirs(f'{OUT}/{d}', exist_ok=True)

# slot number -> (family, original LUT file)
ORIG = {0: ('fuji', f'{FUJI_DIR}/FLog2_to_PROVIA_33grid_V.1.00.cube'),
        1: ('fuji', f'{FUJI_DIR}/FLog2_to_CLASSIC-Neg._33grid_V.1.00.cube'),
        2: ('fuji', f'{FUJI_DIR}/FLog2_to_REALA-ACE_33grid_V.1.00.cube'),
        3: ('fuji', f'{FUJI_DIR}/FLog2_to_ETERNA_33grid_V.1.00.cube')}
for n, f in {7: '3110-Film-A', 8: '5121-City', 9: '6311-Pastel', 10: '3411-Film-Teal-and-orange', 11: '3150-Film-process-Bleach-bypass',
             12: '9210-Day-for-Night', 13: '9211-Day-for-Night', 14: '3240-Faded', 15: '6220-Sommer'}.items():
    ORIG[n] = ('arri', f'{ARRI_DIR}/{f}.cube')
CUR = {int(os.path.basename(p)[:2]): p for p in glob.glob(f'{CUR_DIR}/*.cube')}
NAME = {n: os.path.basename(p)[:-5] for n, p in CUR.items()}
NAME[0] = '00 Provia'
assert len(CUR) == 20

br = Bridge()
cam = br.cam()
scene = load_scene()
log = open(f'{OUT}/run_log.txt', 'w')
def say(*a):
    s = ' '.join(str(x) for x in a); print(s, flush=True); log.write(s + '\n'); log.flush()

def cached(path, fn):
    if os.path.exists(path): return json.load(open(path))
    r = fn(); json.dump(r, open(path, 'w')); return r

def slot_of(r): return {k: r['params'][k] for k in ('M1', 'ck', 'P2') if k in r['params']}
def render_slot(slot): return br.apply(slot, cam)

# ---------------------------------------------------------------- 2. exposure + original targets
provia = Cube(ORIG[0][1])
k, info = fit_exposure(scene, cam, provia)
say(f'EXPOSURE k = {k:.5f} (scene-linear gain on cal_scene)  residual on {info["n"]} near-neutral colours: rms dL* {info["rms"]:.3f}, mean {info["mean"]:+.3f}, max |dL*| {info["max_abs"]:.3f}')
json.dump(dict(k=k, **info), open(f'{OUT}/exposure.json', 'w'))
cubes_o = {n: Cube(p) for n, (fam, p) in ORIG.items()}
lc = srgb_to_lab(cam); neutral = (np.hypot(lc[:, 1], lc[:, 2]) < 6) & (lc[:, 0] >= 25) & (lc[:, 0] <= 75)
targets, clipinfo = {}, {}
for n, (fam, p) in ORIG.items():
    enc = encode(scene, k, fam)
    raw = cubes_o[n].lookup(enc)
    targets[n] = np.clip(raw, 0, 1)
    dl = srgb_to_lab(targets[n])[neutral, 0] - lc[neutral, 0]
    clipinfo[n] = dict(enc_lt0=float(np.mean(enc.min(1) < 0)), enc_gt1=float(np.mean(enc.max(1) > 1)),
                       out_clipped=float(np.mean((raw.min(1) < 0) | (raw.max(1) > 1))), neutral_dL=float(dl.mean()))
    say(f'{n:02d} {fam}: scene->log input outside 0..1: {100*clipinfo[n]["enc_lt0"]:.1f}% <0, {100*clipinfo[n]["enc_gt1"]:.1f}% >1; LUT output clipped {100*clipinfo[n]["out_clipped"]:.1f}%; mean L* diff vs CAL_CAM on neutrals {dl.mean():+.2f}')

def run(jobs):
    with ThreadPoolExecutor(args.jobs) as ex: return list(ex.map(lambda j: j(), jobs))

def job_original(n):
    def f():
        def fit(): return br.fit_target(targets[n], NAME[n])
        r = cached(f'{OUT}/slots/original/{NAME[n]}.json', lambda: dict(zip(('title',), (NAME[n],)), **fit()))
        return r
    return f
res_o = dict(zip(ORIG, run([job_original(n) for n in ORIG])))
say('\nORIGINAL-BASE FIT (slotApply(CAL_CAM) vs target, CIEDE2000)'); say('slot  mean   p95')
for n in ORIG: say(f'{NAME[n]:28s} {res_o[n]["meanDE2000"]:.3f}  {res_o[n]["p95DE2000"]:.3f}')

# ---------------------------------------------------------------- 3. current (ricoh) and adobe-base fits of the existing cubes
res_c = dict(zip(CUR, run([(lambda n=n: cached(f'{OUT}/slots/current/{NAME[n]}.json', lambda: dict(title=NAME[n], **br.fit_cube(CUR[n], 'ricoh')))) for n in CUR])))
res_a = dict(zip(CUR, run([(lambda n=n: cached(f'{OUT}/slots/adobe/{NAME[n]}.json', lambda: dict(title=NAME[n], **br.fit_cube(CUR[n], 'adobe')))) for n in CUR])))
say('\nADOBE-BASE FIT (cube(CAL_ADOBE) target, CIEDE2000)  [current ricoh fit on its own samples in brackets]')
for n in sorted(CUR): say(f'{NAME[n]:28s} {res_a[n]["meanDE2000"]:.3f}  {res_a[n]["p95DE2000"]:.3f}   [{res_c[n]["meanDE2000"]:.3f} / {res_c[n]["p95DE2000"]:.3f}]')

# ---------------------------------------------------------------- 4. baked cubes + re-import check
G = 33
gi = np.arange(G) / (G - 1)
grid = np.stack(np.meshgrid(gi, gi, gi, indexing='ij'), -1)[..., ::-1].reshape(-1, 3)   # b slowest, r fastest -> (r,g,b)
grid = np.array([[r, g, b] for b in gi for g in gi for r in gi])
def bake(slot, path, title):
    out = np.clip(br.apply(slot, grid), 0, 1)
    with open(path, 'w') as fh:
        fh.write(f'TITLE "{title}"\nLUT_3D_SIZE {G}\n')
        fh.write('\n'.join(f'{a:.6f} {b:.6f} {c:.6f}' for a, b, c in out) + '\n')
slots = {('original', n): slot_of(res_o[n]) for n in ORIG}
slots.update({('adobe', n): slot_of(res_a[n]) for n in CUR})
def job_bake(key):
    def f():
        fam, n = key
        p = f'{OUT}/cubes/{fam}/{NAME[n]}.cube'
        bake(slots[key], p, NAME[n])
        rr = cached(f'{OUT}/slots/reimport_{fam}_{NAME[n]}.json', lambda: br.fit_cube(p, 'ricoh'))
        d = br.de2000(br.apply(rr['params'], cam), render_slot(slots[key]))
        return float(d.mean()), float(np.percentile(d, 95))
    return f
keys = list(slots)
rb = dict(zip(keys, run([job_bake(kk) for kk in keys])))
say('\nRE-IMPORT CHECK: convertCube(baked cube, ricoh) vs the slot it was baked from, CIEDE2000 on CAL_CAM'); say('cube                              mean   p95')
for kk in keys: say(f'{kk[0]:9s} {NAME[kk[1]]:24s} {rb[kk][0]:.3f}  {rb[kk][1]:.3f}')
say(f'worst mean {max(v[0] for v in rb.values()):.3f}  (limit 0.5)')

# ---------------------------------------------------------------- 5. comparison csv
def chroma(rgb): l = srgb_to_lab(rgb); return np.hypot(l[:, 1], l[:, 2])
rend = {('current', n): render_slot(slot_of(res_c[n])) for n in CUR}
rend.update({('adobe', n): render_slot(slots[('adobe', n)]) for n in CUR})
rend.update({('original', n): render_slot(slots[('original', n)]) for n in ORIG})
rows = []
def cmp(n, v):
    if (v, n) not in rend: return ['', '', '']
    a, b = rend[('current', n)], rend[(v, n)]
    return [f'{br.de2000(a, b).mean():.3f}', f'{chroma(b).mean() / chroma(a).mean():.3f}', f'{(srgb_to_lab(b)[:, 0] - srgb_to_lab(a)[:, 0]).mean():+.2f}']
for n in sorted(CUR):
    rows.append([NAME[n]] + cmp(n, 'adobe') + cmp(n, 'original'))
with open(f'{OUT}/compare.csv', 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['slot', 'dE2000_current_to_adobe', 'chroma_ratio_adobe/current', 'dL_adobe-current', 'dE2000_current_to_original', 'chroma_ratio_original/current', 'dL_original-current'])
    w.writerows(rows)
say('\nCOMPARE (mean over CAL_CAM colours)  dE: current->adobe | current->original | chroma ratio ad/or | dL* ad/or')
for r in rows: say(f'{r[0]:24s} {r[1]:>6s} | {r[4]:>6s} | {r[2]:>6s} {r[5]:>6s} | {r[3]:>6s} {r[6]:>6s}')
# extra: slot 00 (PROVIA) vs plain Standard
say('\nPROVIA original vs plain CAL_CAM: dE2000 mean', f'{br.de2000(rend[("original",0)], cam).mean():.3f}', 'chroma ratio', f'{chroma(rend[("original",0)]).mean()/chroma(cam).mean():.3f}', 'dL*', f'{(srgb_to_lab(rend[("original",0)])[:,0]-lc[:,0]).mean():+.2f}')

# ---------------------------------------------------------------- 5b. was the relative cube "look minus neutral"?
# current - CAL_CAM (display-space delta)  vs  original look - original neutral, both on CAL_CAM colours.
say('\nRELATIVE-CUBE CHECK: delta = (render - CAL_CAM) in sRGB display values on the 1026 colours')
say('Fuji: neutral = PROVIA (actual);  ARRI: neutral not staged, so the implied neutral = orig_look - delta is compared across looks (should be one and the same)')
def dE(a, b): return br.de2000(a, b)
for n in (1, 2, 3):
    delta_cur = rend[('current', n)] - cam
    delta_org = targets[n] - targets[0]
    implied = np.clip(cam + delta_org, 0, 1)
    say(f'{NAME[n]:24s} dE2000(current, CAL_CAM+(look-PROVIA)) = {dE(rend[("current", n)], implied).mean():.2f}   |  dE2000(current, original-fit) = {dE(rend[("current", n)], rend[("original", n)]).mean():.2f}')
imp = {n: np.clip(targets[n] - (rend[('current', n)] - cam), 0, 1) for n in range(7, 16)}
ref = np.mean([imp[n] for n in imp], 0)
for n in imp: say(f'{NAME[n]:24s} implied ARRI neutral vs mean over looks: dE2000 {dE(imp[n], ref).mean():.2f}')
say(f'implied ARRI neutral vs CAL_CAM: dE2000 {dE(ref, cam).mean():.2f}, dL* {(srgb_to_lab(ref)[:,0]-lc[:,0]).mean():+.2f}')

json.dump(dict(NAME={str(a): b for a, b in NAME.items()}, k=k), open(f'{OUT}/tmp/meta.json', 'w'))
np.savez(f'{OUT}/tmp/renders.npz', **{f'{v}_{n}': r for (v, n), r in rend.items()}, cam=cam)
br.close()
