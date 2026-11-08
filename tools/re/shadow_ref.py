"""Python reference of the firmware's shadow-correction core (RICOH GR IV 1.11, 0x5391F230 + curve builder 0x5391F084)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fwlib import u16s, rd
import numpy as np
TA = u16s(0x54048f3c, 4)      # [4,1,2,3] menu code (0=Auto,1=Low,2=Med,3=High) -> gain-table index
TB = u16s(0x54049384, 6)      # [0,256,512,1024,256,0]
TC = u16s(0x540493a0, 97)     # ISO limiter, 97 entries (index = round(8*Sv)-8, clamp 0x60)
CURVE = u16s(0x54048d34, 256) # shadow gain curve (4096 = 1.0)
HLTAB = u16s(0x54048534, 1024)   # highlight-correction gain table (literal 0x54048532, first load at +2)
LEVEL_EDGES = [(0xb9,0),(0x183,1),(0x25f,2),(0x350,3),(0x456,4),(0x574,5),(0x6ac,6)]

def level_of(s):
    if s <= 0xb9: return 0
    if s < 0x184: return 1
    if s < 0x260: return 2
    if s <= 0x350: return 3
    if s <= 0x456: return 4
    if s <= 0x574: return 5
    if s <= 0x6ac: return 6
    return 7

def strength(y, setting, hl, idx44, w=64, h=62, b8ab=False):
    N = w*h
    cap = TC[min(idx44, 0x60)]
    code = TA[setting] if setting <= 3 else 0
    gain = TB[code]
    info = {}
    if setting == 0:
        v = (np.asarray(y, dtype=np.uint32) << hl) & 0xffff
        dark = int((v <= 0x1f).sum())
        hist = np.bincount(v[v < 0x200], minlength=0x200)
        thr = (N * 0x51eb851f >> 32) >> 5
        cum = 0; idx = None
        for i in range(0x80):
            cum = (cum + int(hist[i])) & 0xffff
            if cum > thr: idx = i; break
        info.update(dark=dark, thr=thr, idx=idx)
        if idx is None or b8ab:
            info['r3'] = 0
            return 0, 0, info          # no valid 1 % point (or P[0x6e0] in {1,2}): strength forced to 0 (the multiply is skipped)
        else:
            r4 = max(0x800 - 24*idx, 0)
            t7 = (7*N)//10 & 0xffff
            if t7 > dark: r3 = r4 & 0xfff8
            else:
                t9 = (9*N)//10 & 0xffff
                if t9 < dark: r3 = 0
                else:
                    r0 = (0x2800*(t9 - dark))//N
                    r3 = ((r0*r4) >> 11) & 0xffff
        info['r3'] = r3
    else:
        r3 = 0x800
    m = min(r3, cap)
    s = ((m*gain) >> 11) & 0xffff
    return s, level_of(s), info

def table(s, hl):
    """u16[1024] gain table (4096 = 1.0) built into this+0x14 by 0x5391F084"""
    if not hl:
        t = np.full(1024, 0x1000, dtype=np.int64)
        for i in range(256):
            d = (s*(CURVE[i]-0x1000))
            d = -((-d + 0) // 1024) if d < 0 and False else (d + (1023 if d < 0 else 0)) >> 10   # asr after +0x3ff for negatives (trunc toward zero)
            t[i] = 0x1000 + d
        return t
    cur = np.full(1024, 0x1000, dtype=np.int64)
    def q(v):
        d = s*(v-0x1000)
        return (d + (1023 if d < 0 else 0)) >> 10
    for i in range(128):
        cur[i] = (0x1000 + q(CURVE[2*i]) + 0x1000 + q(CURVE[2*i+1])) >> 1
    return np.array([(HLTAB[j]*int(cur[j])) >> 12 for j in range(1024)])
