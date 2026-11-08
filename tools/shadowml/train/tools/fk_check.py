"""Make SP/shadowml/check.png: 3 pairs (raw-side Y tone-mapped | expert C) + raw-vs-expert tone curve.  usage: python3 -I fk_check.py [npz ...]"""
import sys, os, json, numpy as np
R = (__import__('os').environ.get('GRIV_WORK', '.') + '/shadowml')
sys.path.insert(0, R + '/tools'); import fk_load
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
paths = sys.argv[1:]
if not paths:
    # pick: darkest scene, highest ISO, and one typical (all with expert C flagged ok), distinct cameras
    cand = []
    for f in sorted(os.listdir(R + '/fivek')):
        if not f.endswith('.npz') or f.startswith('.'): continue
        z = np.load(f'{R}/fivek/{f}'); m = json.loads(str(z['meta_json']))
        if 'c' in m['experts'] and m['experts']['c']['align_flag'] == 'ok':
            by = z['blocks_y']; cand.append((f, m['model'], m['iso'] or 0, float(np.median(by)), m['categories']))
    cand.sort(key=lambda t: t[3]); picks = [cand[len(cand) // 50]]
    for c in sorted(cand, key=lambda t: -t[2]):
        if c[1] != picks[0][1]: picks.append(c); break
    mid = cand[len(cand) // 2]
    if mid[1] not in [p[1] for p in picks]: picks.append(mid)
    for c in cand:
        if len(picks) >= 3: break
        if c[1] not in [p[1] for p in picks]: picks.append(c)
    paths = [f'{R}/fivek/{p[0]}' for p in picks[:3]]
srgb = lambda x: np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(np.clip(x, 1e-9, None), 1 / 2.4) - 0.055)
fig, ax = plt.subplots(len(paths), 3, figsize=(15, 3.6 * len(paths)), gridspec_kw=dict(width_ratios=[1, 1, 0.8]))
for r, p in enumerate(paths):
    d = fk_load.load(p); m = d['meta']; ry = d['raw_y']; e = d['experts']['c']; ey = e['y']
    gain = 0.18 / max(np.percentile(ry, 50) * 1.0, 1e-5); gain = min(gain, 0.9 / max(np.percentile(ry, 99.5), 1e-5)) if False else gain
    ax[r, 0].imshow(np.clip(srgb(ry * gain), 0, 1), cmap='gray', vmin=0, vmax=1)
    ax[r, 0].set_title(f"{m['name']}\n{m['make']} {m['model']}  ISO {m['iso']}  {m['categories']['light']}/{m['categories']['time']}\nraw-side Y x{gain:.1f} (median->0.18), sRGB gamma", fontsize=8)
    ax[r, 1].imshow(np.clip(srgb(ey), 0, 1), cmap='gray', vmin=0, vmax=1)
    ax[r, 1].set_title(f"expert C (ProPhoto Y, sRGB gamma)\nspearman(logY)={e['rho']:.3f}  flag={e['align_flag']}  shift=({e['shift_px'][0]:.2f},{e['shift_px'][1]:.2f})px", fontsize=8)
    for a in ax[r, :2]: a.axis('off')
    x = np.log2(np.clip(ry.ravel(), 2 ** -12, None)); y = np.log2(np.clip(ey.ravel(), 2 ** -12, None))
    bins = np.linspace(-12, 1.5, 28); idx = np.digitize(x, bins)
    xs, med, lo, hi = [], [], [], []
    for b in range(1, len(bins)):
        s = y[idx == b]
        if len(s) > 50: xs.append((bins[b - 1] + bins[b]) / 2); med.append(np.median(s)); lo.append(np.percentile(s, 10)); hi.append(np.percentile(s, 90))
    ax[r, 2].fill_between(xs, lo, hi, alpha=0.25); ax[r, 2].plot(xs, med, 'k-', label='median')
    ax[r, 2].plot([-12, 1], [-12, 1], 'r:', lw=0.8, label='identity'); ax[r, 2].set_xlabel('log2 raw Y (rel. white)'); ax[r, 2].set_ylabel('log2 expert-C Y')
    ax[r, 2].set_title('per-pixel tone curve (10-90% band)', fontsize=8); ax[r, 2].legend(fontsize=7); ax[r, 2].grid(alpha=0.3)
plt.tight_layout(); plt.savefig(R + '/check.png', dpi=80); print('wrote', R + '/check.png', paths)
