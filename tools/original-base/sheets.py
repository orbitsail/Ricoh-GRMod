#!/usr/bin/env python3
"""Patch sheets: rows = looks, columns = reference (plain Standard) / current / adobe / original; each cell an 8x8 grid of
64 representative calibration colours as rendered by slotApply. Needs run_all.py's <out>/tmp/renders.npz."""
import argparse, json, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from obase import srgb_to_lab

def pick64(cam):
    lab = srgb_to_lab(cam); C = np.hypot(lab[:, 1], lab[:, 2]); h = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    chosen = []
    # 8 neutrals spread over lightness
    nidx = np.where(C < 6)[0]
    for t in np.linspace(lab[nidx, 0].min(), lab[nidx, 0].max(), 8):
        chosen.append(int(nidx[np.argmin(np.abs(lab[nidx, 0] - t))]))
    # 8 skin-ish: hue 35..75 deg, chroma 12..40, spread over lightness
    sidx = np.where((h > 35) & (h < 75) & (C > 12) & (C < 40) & (lab[:, 0] > 30))[0]
    for t in np.linspace(lab[sidx, 0].min(), lab[sidx, 0].max(), 8):
        c = int(sidx[np.argmin(np.abs(lab[sidx, 0] - t))])
        if c not in chosen: chosen.append(c)
    # remaining: farthest-point sampling in Lab
    while len(chosen) < 64:
        d = np.min(np.linalg.norm(lab[:, None, :] - lab[chosen][None], axis=2), axis=1)
        chosen.append(int(np.argmax(d)))
    head, rest = chosen[:16], chosen[16:]
    rest.sort(key=lambda i: (round(h[i] / 45), lab[i, 0]))     # grouped by hue, light to dark within
    return np.array(head + rest)

def cell(rgb, px=20):
    img = np.zeros((8 * px, 8 * px, 3), np.uint8)
    q = (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)
    for i in range(64): img[(i // 8) * px:(i // 8 + 1) * px, (i % 8) * px:(i % 8 + 1) * px] = q[i]
    return Image.fromarray(img)

def sheet(rows, cols, R, idx, path, title, names):
    px, pad, lw, hh = 20, 10, 190, 56
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
    W = lw + len(cols) * (8 * px + pad) + pad; H = hh + len(rows) * (8 * px + pad) + pad
    im = Image.new('RGB', (W, H), (24, 24, 24)); d = ImageDraw.Draw(im)
    d.text((pad, 8), title, fill=(230, 230, 230), font=font)
    for j, (cname, _) in enumerate(cols): d.text((lw + j * (8 * px + pad), 34), cname, fill=(180, 180, 180), font=font)
    for i, n in enumerate(rows):
        y = hh + i * (8 * px + pad); d.text((pad, y + 70), names[str(n)], fill=(230, 230, 230), font=font)
        for j, (cname, key) in enumerate(cols):
            k = key if key == 'cam' else f'{key}_{n}'
            if k in R: im.paste(cell(R[k][idx]), (lw + j * (8 * px + pad), y))
    im.save(path)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='/home/claude/work/out'); a = ap.parse_args()
    R = dict(np.load(f'{a.out}/tmp/renders.npz')); meta = json.load(open(f'{a.out}/tmp/meta.json'))
    idx = pick64(R['cam'])
    cols = [('Standard (no look)', 'cam'), ('current', 'current'), ('adobe base', 'adobe'), ('original base', 'original')]
    os.makedirs(f'{a.out}/sheets', exist_ok=True)
    sheet([0, 1, 2, 3], cols, R, idx, f'{a.out}/sheets/fuji.png', 'Fuji family (64 calibration colours via slotApply)', meta['NAME'])
    sheet(list(range(7, 16)), cols, R, idx, f'{a.out}/sheets/arri.png', 'ARRI family', meta['NAME'])
    sheet([4, 5, 6, 16, 17, 18, 19, 20], cols[:3], R, idx, f'{a.out}/sheets/other.png', 'Leica / other photo-input looks (no original base)', meta['NAME'])
    print('ok')
