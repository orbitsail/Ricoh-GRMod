"""Real-raw scene data for the original-base fits: pairs of (scene-linear ProPhoto D50 from a DNG's own ColorMatrix,
the camera's Standard JPEG colour) from /home/claude/work/dngcheck/pairs.json. Training-set selection and exposure."""
import json
import numpy as np
from obase import srgb_to_lab, render

PAIRS = '/home/claude/work/dngcheck/pairs.json'
HUE_NAMES = ['red-magenta 0-30', 'orange 30-60', 'yellow 60-90', 'yellow-green 90-120', 'green 120-150', 'green-cyan 150-180',
             'cyan 180-210', 'cyan-blue 210-240', 'blue 240-270', 'violet 270-300', 'magenta 300-330', 'pink-red 330-360']
L_EDGES = [0, 20, 40, 60, 80, 100.001]
C_EDGES = [6, 20, 40, 1e9]          # chroma bins above the near-neutral cut (C < 6)

def load():
    d = json.load(open(PAIRS))
    return (np.array(d['scene_linear_prophoto_d50']), np.array(d['jpeg_srgb']), np.array(d['image_index']), d)

def lch(rgb):
    lab = srgb_to_lab(rgb)
    return lab[:, 0], np.hypot(lab[:, 1], lab[:, 2]), np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360

def choose_holdout(jpeg, idx, n=2):
    """Hold out the pair of whole images (each >= 1000 blocks) whose combined hue histogram (C>=6) and mean chroma are closest to the
    whole pool's: a representative, not an easy, test set. Deterministic."""
    import itertools
    L, C, H = lch(jpeg)
    allh = np.histogram(H[C >= 6], bins=12, range=(0, 360))[0] / max(1, (C >= 6).sum())
    cands = [i for i in np.unique(idx) if (idx == i).sum() >= 1000]
    def score(comb):
        m = np.isin(idx, comb)
        h = np.histogram(H[m & (C >= 6)], bins=12, range=(0, 360))[0] / max(1, (m & (C >= 6)).sum())
        return np.abs(h - allh).sum() + abs(np.log(C[m].mean() / C.mean()))
    return sorted(int(i) for i in min(itertools.combinations(cands, n), key=score))

def select_train(jpeg, idx, holdout, target=2500, n_neutral=300, seed=1):
    """Stratified subset of the non-held-out pairs: 12 hue x 5 L* x 3 chroma cells with a common cap (found by bisection so the
    total ~ target), plus up to n_neutral near-neutrals (C<6) spread over lightness. Returns (train indices, coverage report)."""
    rng = np.random.default_rng(seed)
    L, C, H = lch(jpeg)
    avail = ~np.isin(idx, holdout)
    cell = (np.minimum((H // 30).astype(int), 11) * 5 + np.digitize(L, L_EDGES[1:-1])) * 3 + np.digitize(C, C_EDGES[1:-1])
    chrom = avail & (C >= C_EDGES[0])
    members = {c: np.where(chrom & (cell == c))[0] for c in np.unique(cell[chrom])}
    for c in members: rng.shuffle(members[c])
    nn_budget = n_neutral
    def total(cap): return sum(min(cap, len(v)) for v in members.values())
    lo, hi = 1, 5000
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if total(mid) <= target - nn_budget: lo = mid
        else: hi = mid - 1
    cap = lo
    sel = [v[:cap] for v in members.values()]
    # near-neutrals: equal count per L* quintile-ish (20 bins over the L* range) up to n_neutral
    nidx = np.where(avail & (C < C_EDGES[0]))[0]
    bins = np.digitize(L[nidx], np.linspace(0, 100, 21)[1:-1])
    per = {b: nidx[bins == b] for b in np.unique(bins)}
    for v in per.values(): rng.shuffle(v)
    take, r = [], 0
    while len(take) < n_neutral and any(len(v) > r for v in per.values()):
        for b in sorted(per):
            if len(per[b]) > r and len(take) < n_neutral: take.append(per[b][r])
        r += 1
    sel.append(np.array(take, int))
    tr = np.sort(np.concatenate(sel))
    cov = dict(cap=int(cap), n=int(len(tr)), n_neutral=int(len(take)),
               per_hue=[dict(sector=HUE_NAMES[h], available=int((chrom & (H // 30 == h)).sum()), selected=int(((H[tr] // 30 == h) & (C[tr] >= 6)).sum()),
                             mean_chroma_sel=float(C[tr][(H[tr] // 30 == h) & (C[tr] >= 6)].mean()) if ((H[tr] // 30 == h) & (C[tr] >= 6)).any() else 0.0,
                             max_chroma_avail=float(C[chrom & (H // 30 == h)].max()) if (chrom & (H // 30 == h)).any() else 0.0) for h in range(12)],
               empty_cells=int(180 - len(members)),
               cells_below_cap=int(sum(len(v) < cap for v in members.values())))
    return tr, cov

def fit_k(scene, jpeg, provia):
    """Global gain k: FLog2_to_PROVIA(F-Log2(k*scene)) vs the JPEG, CIE L*, near-neutral (JPEG C<6) pairs with JPEG L* 25..75, least squares in log k."""
    from scipy.optimize import least_squares
    L, C, H = lch(jpeg)
    sel = (C < 6) & (L >= 25) & (L <= 75)
    def resid(logk): return srgb_to_lab(render(scene[sel], np.exp(logk[0]), 'fuji', provia))[:, 0] - L[sel]
    grid = np.linspace(np.log(1e-2), np.log(1e2), 241)
    g = grid[np.argmin([np.sum(resid([x]) ** 2) for x in grid])]
    r = least_squares(resid, [g], diff_step=1e-4)
    rr = resid(r.x)
    return float(np.exp(r.x[0])), dict(n=int(sel.sum()), rms=float(np.sqrt(np.mean(rr ** 2))), mean=float(rr.mean()), max_abs=float(np.abs(rr).max()))
