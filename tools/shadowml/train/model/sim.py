"""Shared simulation: FiveK scene -> GR IV AE-scaled planes, ISO/HC variant, camera features (via the module's own ref.py), and GR renderings."""
import sys, os, json, glob
sys.dont_write_bytecode = True
SP = __import__('os').environ.get('GRIV_WORK', '.')
MODEL = SP + '/shadowml/model'
sys.path.insert(0, SP + '/shadowml/tools'); sys.path.insert(0, SP + '/drange')
sys.path.insert(0, '/home/claude/grmod-shadow/tools/shadowml')
import numpy as np
import fk_load
import ref            # the camera module's feature definition (read-only import)
import shadow_ref as SR

AE_TARGET = 8.84      # log2 of the mean-log of L (G plane x2 if HC): calibrated on the DPReview ec=0 shots, see ae_calib.py
PLANE_CAP = 8100.0     # G-plane saturation assumed in the simulation (assumption; sensitivity tested at 4095 / 7683)
PLANE_K = 4063.0      # plane units per unit of (linear Y relative to sensor white), as in fivek_tools/proc.py
GR_FNUM_MINSHUT = 1 / 60.
T = np.load(MODEL + '/T_full.npz'); TLUT = T['J'].astype(np.float64)       # J at x = i/4, x 0..4095.75
_tabs = {}
def gain_table(s, hl):
    k = (s, hl)
    if k not in _tabs: _tabs[k] = np.asarray(SR.table(s, hl), np.float64) / 4096.
    return _tabs[k]
def render(xd, s, hl):
    """GR_s = T(x * g_s(x)); xd = 12-bit linear luma in the (possibly 1 EV darker) raw domain."""
    idx = np.clip(xd.astype(np.int32) >> 2, 0, 1023)
    x = np.minimum(xd * gain_table(s, hl)[idx], 4095.0)
    return TLUT[np.minimum((x * 4).astype(np.int32), 16383)]
def iso_index(iso): return int(round(8 * np.log2(iso / 3.125))) - 8

def meanlog_L(Lb, valid):
    return np.log2(np.maximum(Lb[valid], 1)).mean()
def ae_scale(Lb, valid):
    """stops to add so that mean log2 max(L,1) over counted blocks == AE_TARGET (bisection: the floor at 1 makes it non-linear)"""
    lo, hi = -20., 20.
    for _ in range(50):
        mid = (lo + hi) / 2
        if meanlog_L(Lb * 2 ** mid, valid) < AE_TARGET: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def planes(d, kst, hl):
    """R, G, B, C (62*64 u32 arrays) for the scene exposed by kst stops (L domain), with HC (raw 1 EV darker) if hl."""
    by = d['blocks_y'].astype(np.float64); f = d['blocks_clip'].astype(np.float64)
    ok = f < 0.999
    yb = np.where(ok, np.maximum(by - f, 1e-6) / np.maximum(1 - f, 1e-3), 0.0)   # the camera averages the unclipped samples only
    L = PLANE_K * yb * 2 ** kst
    G = np.rint(np.minimum(L / 2 ** hl, PLANE_CAP))
    n = d['meta'].get('as_shot_neutral') or [0.5, 1, 0.6]
    R = np.rint(np.minimum(G * n[0] * 0.92, 65535)); B = np.rint(np.minimum(G * n[2] * 0.974, 65535))
    C = np.where(ok, np.rint(1584 * (1 - f)), 0)
    return [a.ravel().astype(np.uint32) for a in (R, G, B, C)], ok.ravel()

def scene_info(d):
    m = d['meta']; by = d['blocks_y'].astype(np.float64); f = d['blocks_clip'].astype(np.float64)
    ok = (f < 0.999).ravel()
    (R, G, B, C), _ = planes(d, 0.0, 0)
    L0 = G.astype(np.float64)
    kst = ae_scale(L0, ok)
    asshot = meanlog_L(L0, ok)
    ev_shot = np.log2(m['f_number'] ** 2 / m['exposure_time']) - np.log2(m['iso'] / 100.)
    ev_scene = ev_shot + (asshot - AE_TARGET)           # brightness the AE would have to cope with (EV100)
    return kst, ev_scene

def variants(ev_scene):
    """(iso, hl) variants. Bright scene: base ISO 100 (no HC) or 200 (HC) -- both appear in the DPReview set at the same EV, so train on both.
    Dark scene: f/2.8 at 1/60 s needs ISO = 100*2^(log2(2.8^2*60)-EV), clamped 200..6400 (HC is applied at ISO>=200, as in all 35 DPReview shots)."""
    need = 100 * 2 ** (np.log2(2.8 ** 2 / GR_FNUM_MINSHUT) - ev_scene)
    if need <= 200: return [(100, 0), (200, 1)]
    iso = 100 * 2 ** (round(3 * np.log2(min(need, 6400) / 100)) / 3)    # 1/3-stop ISO steps
    return [(int(round(iso)), 1)]

def feats(d, kst, hl, iso):
    (R, G, B, C), ok = planes(d, kst, hl)
    F = ref.features(R, G, B, C, 64, 62, hl, iso_index(iso), 0)
    return F
