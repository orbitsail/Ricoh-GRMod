# SPDX-License-Identifier: GPL-2.0-only
"""Shared feature code for the AE study.
raw side : exposure-invariant shape features of the scene-referred luminance map (raw_y, linear, relative to sensor white)
display  : percentile profile of L* of a display-referred luminance map (expert output or camera JPEG)
"""
import numpy as np

QP = [1, 5, 10, 25, 50, 75, 90, 95, 99]

def lstar(Y):
    Y = np.clip(np.asarray(Y, np.float64), 0, 1.0)
    f = np.where(Y > 0.008856, np.cbrt(Y), 7.787 * Y + 16.0 / 116.0)
    return 116.0 * f - 16.0

def display_profile(Y):
    """L* percentiles, mean, fraction near white / near black of a display-referred relative luminance map"""
    L = lstar(Y).ravel()
    d = {'L_mean': float(L.mean())}
    q = np.percentile(L, QP)
    for p, v in zip(QP, q): d['L_p%d' % p] = float(v)
    d['white_frac'] = float((L >= 97.0).mean())     # Y >= ~0.93
    d['black_frac'] = float((L <= 5.0).mean())
    return d

def raw_features(raw_y, clip_blocks=None, floor_stops=-10.0):
    """raw_y : (H,W) linear Y relative to sensor white level (oriented like the display image).
    Returns dict of exposure-invariant shape features + the as-shot level (kept separate, prefix lvl_)."""
    y = np.maximum(np.asarray(raw_y, np.float64), 2.0 ** floor_stops)
    l = np.log2(y)
    H, W = l.shape
    m = float(l.mean())
    d = {'lvl_mean': m, 'lvl_med': float(np.median(l))}
    q = np.percentile(l, [2, 10, 25, 50, 75, 90, 98])
    for p, v in zip([2, 10, 25, 50, 75, 90, 98], q): d['s_q%d' % p] = float(v - m)
    d['s_std'] = float(l.std())
    d['s_rng'] = float(q[-1] - q[0])
    # spatial
    t, b = l[:H // 3].mean(), l[-(H // 3):].mean()
    d['s_top_minus_bottom'] = float(t - b)
    c = l[H // 4: 3 * H // 4, W // 4: 3 * W // 4].mean()
    d['s_centre_minus_all'] = float(c - m)
    # large-scale contrast: spread of 4x4 cell means
    ys = np.linspace(0, H, 5).astype(int); xs = np.linspace(0, W, 5).astype(int)
    cells = np.array([l[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].mean() for i in range(4) for j in range(4)])
    d['s_cell_std'] = float(cells.std())
    d['s_cell_max_minus_mean'] = float(cells.max() - m)
    # fraction of pixels brighter than 1/2 white (exposure dependent: kept as an 'extent of highlights' feature)
    d['lvl_f_gt_half'] = float((y > 0.5).mean())
    d['lvl_f_gt_q'] = float((y > 0.9).mean())
    d['lvl_p999'] = float(np.log2(np.percentile(y, 99.9)))
    d['lvl_p99'] = float(np.log2(np.percentile(y, 99.0)))
    if clip_blocks is not None:
        cb = np.asarray(clip_blocks, np.float64)
        d['lvl_clip_frac'] = float(cb.mean())
        d['lvl_clip_blocks'] = float((cb > 0.05).mean())
    return d

def exposure_per_stop_slope(Y):
    """d(mean L*)/d(stop) when the display-linear luminance is scaled: used to convert L* differences to stops"""
    a = lstar(np.clip(Y * 2 ** 0.5, 0, 1)).mean(); b = lstar(np.clip(Y / 2 ** 0.5, 0, 1)).mean()
    return float(a - b)
