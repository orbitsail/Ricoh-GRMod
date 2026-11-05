# SPDX-License-Identifier: GPL-2.0-only
# scratch helper for the AE study (read-only); imports the repository helpers
import os, sys, struct, re
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import xr
from xr import w, pr, fstart, callers, lits, movwt, cstr, find_str, bl_targets, fend, IMG, BASE, W, ADDR
import numpy as np

def refs(addr):
    """code sites that build the address (literal pool word or movw/movt)"""
    out = []
    for a in lits(addr):
        out.append(('lit', a))
    for a in movwt(addr):
        out.append(('mov', a))
    return out

def litsite_users(litaddr):
    """find ldr rX,[pc,#imm] instructions reading the literal at litaddr"""
    res = []
    for a in range(litaddr - 4096, litaddr, 4):
        v = w(a)
        # ldr rd,[pc,#imm] : cond 0101 U001 1111 rd imm12
        if (v & 0x0F7F0000) == 0x051F0000:
            imm = v & 0xFFF
            up = (v >> 23) & 1
            tgt = a + 8 + (imm if up else -imm)
            if tgt == litaddr:
                res.append(a)
    return res

def users(addr):
    """instruction sites that load the 32-bit value addr (ldr pc-rel from literal, or movw/movt)"""
    out = []
    for l in lits(addr):
        for u in litsite_users(l):
            out.append(u)
    out += movwt(addr)
    return sorted(set(out))

def fn_of(a):
    return fstart(a)

def dasm(a, n=40):
    pr(a, n)
