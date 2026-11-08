import os
import sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fwemu import Emu
e=Emu()
MGR=0x60100000; S=0x60110000; AUTO=0x60120000; P=0x60200000
e.mu.mem_map  # already mapped 0x60000000+64MB
e.w32(MGR+0x40,S); e.w32(MGR+0x28,AUTO)
def setup(s70=0, d70=16667, d74=0, cur=0, a=14, b=14, autoflag=0):
    e.w32(S+0x70,s70)
    e.wb(AUTO+0xAF89,bytes([autoflag]))
    e.w32(P+0x38D70,d70); e.w16(P+0x38D74,d74)
    e.wb(P+0x71A0D,bytes([cur])); e.wb(P+0x71A0E,bytes([a])); e.wb(P+0x71A0F,bytes([b]))
def step(R,B):
    e.w16(P+0x672D8,R); e.w16(P+0x672DE,B)
    e.call(0x53932914,MGR,P)
    return e.r16(P+0x672D8), e.r16(P+0x672DE)
def run(label,seq,**kw):
    # fresh ring state
    for a in range(0x553a12a8,0x553a1304): e.mu.mem_write(a,b'\0')
    e.w32(0x55053abc,0xff)  # saved mode invalid -> forces reset on first call
    setup(**kw)
    out=[step(R,B) for R,B in seq]
    print(label,kw); print(' R:',[o[0] for o in out]);
    return out
seq=[(256,256)]*3+[(512,300)]*30
for d70 in (16667,33333,8333):
    run('step',seq,d70=d70)
run('movie s70=4',seq,d70=16667,s70=4)
run('d74=1',seq,d70=16667,d74=1)
run('mode cur=1',seq,d70=16667,cur=1)
run('autoflag=1',seq,d70=16667,autoflag=1)

print('--- reset tests')
def fresh():
    for a in range(0x553a12a8,0x553a1304): e.mu.mem_write(a,b'\0')
    e.w32(0x55053abc,0xff)
# 1. modes 13/14/15 never smooth
for cur in (13,14,15,2):
    fresh(); setup(d70=16667,cur=cur)
    out=[step(R,256)[0] for R in [256]*3+[512]*6]
    print('cur',cur,out)
# 2. user shift change resets
fresh(); setup(d70=16667,cur=0,a=14,b=14)
o=[step(R,256)[0] for R in [256]*3+[512]*3]
setup(d70=16667,cur=0,a=15,b=14)   # shift changed
o+=[step(R,256)[0] for R in [512]*3]
print('shift change after 3 smoothing frames',o)
# 3. WB mode change resets
fresh(); setup(d70=16667,cur=0)
o=[step(R,256)[0] for R in [256]*3+[512]*3]
setup(d70=16667,cur=1)
o+=[step(R,256)[0] for R in [512]*3]
print('mode change',o)
