import sys, struct
from capstone import *
import os
# The stock RTOS.bin (decoded RTOS section of the official fw 1.11; never committed) is found through $GRIV_RTOS.
rt=open(os.environ.get('GRIV_RTOS') or 'RTOS.bin','rb').read(); BASE=0x53000000
md=Cs(CS_ARCH_ARM,CS_MODE_ARM); md.detail=False
def dis(a,n=0x100):
    o=a-BASE
    for i in md.disasm(rt[o:o+n],a):
        print('%08x: %-8s %s'%(i.address,i.mnemonic,i.op_str))
def dis_fn(a,maxn=0x1000):
    # until pop with pc / bx lr heuristics
    o=a-BASE; out=[]
    for i in md.disasm(rt[o:o+maxn],a):
        out.append(i); 
        if (i.mnemonic.startswith('ldm') and 'pc' in i.op_str) or (i.mnemonic=='bx' and i.op_str=='lr') : 
            if len(out)>4: break
    for i in out: print('%08x: %-8s %s'%(i.address,i.mnemonic,i.op_str))
def w(a): return struct.unpack('<I',rt[a-BASE:a-BASE+4])[0]
def xbl(t):
    """find bl/b to t"""
    res=[]
    for off in range(0,len(rt)-4,4):
        v=struct.unpack('<I',rt[off:off+4])[0]
        if (v>>25)&7==5 and (v>>28)!=15:
            imm=v&0xffffff
            if imm&0x800000: imm-=1<<24
            tgt=BASE+off+8+imm*4
            if tgt==t: res.append((BASE+off,'bl' if v&(1<<24) else 'b'))
    return res
def xword(val):
    pat=struct.pack('<I',val); res=[];i=0
    while True:
        i=rt.find(pat,i)
        if i<0:break
        if i%4==0: res.append(BASE+i)
        i+=1
    return res
if __name__=='__main__':
    c=sys.argv[1]; a=int(sys.argv[2],16)
    if c=='d': dis(a,int(sys.argv[3],16) if len(sys.argv)>3 else 0x100)
    elif c=='f': dis_fn(a)
    elif c=='xbl': print([(hex(x),k) for x,k in xbl(a)])
    elif c=='xw': print([hex(x) for x in xword(a)])

def fstart(a):
    o=a-BASE
    while o>0:
        if struct.unpack('<I',rt[o:o+4])[0]==0xe1a0c00d and (struct.unpack('<I',rt[o+4:o+8])[0]>>16)==0xe92d: return BASE+o
        o-=4

def scan(lo,hi,pred):
    out=[]
    for a in range(lo,hi,4):
        o=a-BASE
        for i in md.disasm(rt[o:o+4],a):
            if pred(i): out.append(i)
    return out
