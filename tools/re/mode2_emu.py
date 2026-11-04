import os
import sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,'.')
from fwemu import Emu
import numpy as np
F=0x538F75FC
P=0x60100000; WORK=0x60400000
def run(stat0, A=1000,B=1000,C=1000,D=1000, w=64,h=62, ab4=1, mode=2, extra=None, cnt=1584):
    e=Emu(); mu=e.mu
    mu.mem_write(P, bytes(0x80000)); mu.mem_write(WORK, bytes(0x10000))
    e.w16(P+0xBB8,w); e.w16(P+0xBBA,h)
    e.w16(P+0x14BC8,A); e.w16(P+0x14BCA,B); e.w16(P+0x14BCC,C); e.w16(P+0x14BCE,D)
    e.w16(P+0x2EBE4,4000); e.w16(P+0x2EBE6,3000)
    # HW stat region at P+0xBC4: [row][5][w] u32 : sub-row 0 = stat0
    st=np.zeros((h,5,w),dtype='<u4'); st[:,0,:]=stat0
    mu.mem_write(P+0xBC4, st.tobytes())
    if extra: extra(e)
    r=e.call(F, WORK, P+0xBB8, P+0x848, P+0x2EBE8, stack=(mode, ab4, ab4, 0x1234, 0, 0, 1))
    Y=np.frombuffer(e.rb(P+0x24BD0,64*h*2),'<u2').reshape(h,64)
    return Y,e
if __name__=='__main__':
    rng=np.random.default_rng(0)
    s=rng.integers(0,600000,(62,64))
    Y,e=run(s)
    ped=None
    d=(Y.astype(np.int64)-s)%65536
    print(np.unique(d)[:10], len(np.unique(d)))
