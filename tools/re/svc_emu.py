import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fwemu import Emu
from unicorn.arm_const import *
from unicorn import *
e=Emu()
# svc stubs: "ldr ip,[pc,#..]; svc #n; ldm..." -> return 0 at once
svcs=[]
def hk(uc,a,s,u):
    svcs.append(a); uc.reg_write(UC_ARM_REG_R0,0); uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
SVC=0x553a1370
e.w32(SVC,0x542fe568); e.w32(SVC+4,0); e.w32(SVC+8,0)
# hook every svc wrapper: find "svc" instructions
from capstone import *
md=Cs(CS_ARCH_ARM,CS_MODE_ARM)
rt=e.rt
import struct
n=0
for off in range(0,0x1200000,4):
    v=struct.unpack('<I',rt[off:off+4])[0]
    if (v&0x0f000000)==0x0f000000 and (v>>28)==0xe:
        # svc: wrapper start is typically 4 instr before ('stmdb sp!,{r4}')
        a=0x53000000+off
        # find function entry: scan back for stmdb sp!,{r4}
        for k in range(1,5):
            w=struct.unpack('<I',rt[off-4*k:off-4*k+4])[0]
            if w==0xe92d0010:
                e.mu.hook_add(UC_HOOK_CODE,hk,begin=a-4*k,end=a-4*k+4); n+=1; break
print('svc stubs hooked',n)
try:
    r=e.call(0x5393ceac,SVC,count=20_000_000)
except Exception as ex:
    print('ERR',ex); print(hex(e.mu.reg_read(UC_ARM_REG_PC)))
st=e.r32(SVC+4); lv=e.r32(SVC+8)
print('Still wrapper',hex(st),'LV wrapper',hex(lv))
for n_,wr in (('Still',st),('LV',lv)):
    if not wr: continue
    mgr=e.r32(wr+8)
    print(n_,'wrapper vptr',hex(e.r32(wr)),'type',e.r32(wr+4),'mgr',hex(mgr),'mgr vptr',hex(e.r32(mgr)))
    for off in (0x28,0x2c,0x30,0x34,0x38,0x3c,0x40):
        c=e.r32(mgr+off); print('   mgr+%#x ->'%off,hex(c),'vptr',hex(e.r32(c)) if c else None)
print('--- S after init')
import struct
for n_,wr in (('Still',st),('LV',lv)):
    mgr=e.r32(wr+8); S=e.r32(mgr+0x40)
    print(n_,hex(S),'v24',struct.unpack('<i',e.rb(S+0x24,4))[0],'v28',struct.unpack('<i',e.rb(S+0x28,4))[0],'v2c',struct.unpack('<i',e.rb(S+0x2c,4))[0],'e30',struct.unpack('<i',e.rb(S+0x30,4))[0],'S70',e.r32(S+0x70),'S34',e.r32(S+0x34))
