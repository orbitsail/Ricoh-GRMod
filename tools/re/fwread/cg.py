# SPDX-License-Identifier: GPL-2.0-only
import sys; import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s, bisect, collections, struct, pickle, os
from s import w
import capstone
def fstarts(lo,hi):
    out=[]
    a=lo
    while a<hi:
        v=w(a)
        if v==0xE1A0C00D:
            for k in range(1,5):
                u=w(a+4*k)
                if (u&0xFFFF0000)==0xE92D0000 and (u&0x4000):
                    out.append(a); break
        a+=4
    return out
LO,HI=0x53640000,0x53690000
FS=fstarts(LO,HI)
def fn_at(a):
    i=bisect.bisect_right(FS,a)-1
    return FS[i] if i>=0 else None
def fn_end(f):
    i=bisect.bisect_right(FS,f)
    return FS[i] if i<len(FS) else f+0x1000
def calls(f):
    end=fn_end(f)
    res=collections.OrderedDict()
    for site,t in s.bl_targets(f,end):
        res.setdefault(t,[]).append(site)
    return res
def callers_of(t):
    return [(fn_at(a),a) for a,k in s.callers(t)]
