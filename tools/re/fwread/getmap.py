# SPDX-License-Identifier: GPL-2.0-only
import os,re,struct,sys
from capstone import *
rt=open(os.environ['GRIV_RTOS'],'rb').read()
BASE=0x53000000
md=Cs(CS_ARCH_ARM,CS_MODE_ARM)
def W(a): return struct.unpack('<I',rt[a-BASE:a-BASE+4])[0]
def dis(a,n):
    return list(md.disasm(rt[a-BASE:a-BASE+4*n],a))
def btarget(a):
    v=W(a)
    if ((v>>25)&7)==5 and (v>>28)!=15:
        o=v&0xffffff
        if o&0x800000:o-=1<<24
        return BASE+(a-BASE)+8+o*4, bool((v>>24)&1)
    return None
def inner_off(g):
    ins=dis(g,40)
    for k,i in enumerate(ins):
        if i.mnemonic=='ldr' and '#0x518' in i.op_str:
            for j in range(k+1,k+4):
                t=btarget(ins[j].address)
                if t:
                    inner=t[0]
                    L=dis(inner,6)
                    s=' ; '.join(f'{x.mnemonic} {x.op_str}' for x in L[:5])
                    return inner,s
    return None,None
def run(fs,fe):
    for a in range(fs,fe,4):
        t=btarget(a)
        if not t or not t[1]: continue
        tg=t[0]
        if 0x53755000<=tg<0x5375d000:
            inner,s=inner_off(tg)
            print(hex(a),'GET',hex(tg),(hex(inner) if inner else ''),s)
        elif 0x53682c00<=tg<0x53683900:
            print(hex(a),'SET',hex(tg),' ; '.join(f'{x.mnemonic} {x.op_str}' for x in dis(tg,2)))
        else:
            print(hex(a),'call',hex(tg))
if __name__=='__main__':
    run(int(sys.argv[1],16),int(sys.argv[2],16))
