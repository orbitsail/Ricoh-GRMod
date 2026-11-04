import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mn import load_mn
import numpy as np
def load405(path):
    data,t,out,mt,ents,vpos,cnt=load_mn(path)
    typ,n,pos=ents[0x0405]
    b=bytes(data[vpos+pos:vpos+pos+n])
    w,h=np.frombuffer(b[:4],'<u2')
    s0=np.frombuffer(b[4:4+8192],'<u2').reshape(64,64)
    pl=[np.frombuffer(b[0x2004+0x4000*k:0x2004+0x4000*(k+1)],'<u4').reshape(64,64) for k in range(4)]
    tail=b[0x12004:0x12004+8]
    return dict(w=int(w),h=int(h),s0=s0,R=pl[0],G=pl[1],B=pl[2],C=pl[3],tail=tail,raw=b,tags=ents)
