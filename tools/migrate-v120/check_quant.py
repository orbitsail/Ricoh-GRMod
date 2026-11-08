# SPDX-License-Identifier: GPL-2.0-only
"""Compare 1.20 stock still-builder quantisation with the migrated integer reader reference."""
from pathlib import Path
import sys,struct,random,json
r=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(r/'tools/gr4v120/awbml'),str(r/'tools/gr4v120/re')]
import fwemu,ref
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
B=0x53000000;e=fwemu.Emu();P,T,S=0x60800000,0x60900000,0x60a00000
h=e.mu.hook_add(UC_HOOK_CODE,lambda uc,*_:uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR)),begin=0x5391f1d4,end=0x5391f1d4)
e.w32(T+0x40,S)
rng=random.Random(120);bad=[];rejected=0;compared=0
fb=lambda x:struct.unpack('<I',struct.pack('<f',x))[0]
trip=[(4.,7.,7.5),(2.,9.,4.),(6.5,5.,9.),(-5.,1.,3.)]
for k in range(3216):
 if k<len(trip):tv,av,sv=map(fb,trip[k])
 else:
  vals=[rng.uniform(-5,15),rng.uniform(1,10),rng.uniform(3,15)]
  if k%2:vals=[round(x*16)/16 for x in vals]
  tv,av,sv=[(fb(x)+rng.choice([-2,-1,0,1,2]))&0xffffffff for x in vals]
 e.wb(P,bytes(0x1000));e.wb(S,bytes(0x100));e.w32(P+0xb98,av);e.w32(P+0xb9c,tv);e.w32(P+0xba0,sv)
 for reg,v in [(UC_ARM_REG_R0,T),(UC_ARM_REG_R1,P),(UC_ARM_REG_SP,0x7e100000),(UC_ARM_REG_LR,0x7e000000)]:e.mu.reg_write(reg,v)
 e.mu.emu_start(0x5395bde8,0x5395bfd4,count=200000)
 got=struct.unpack('<i',e.rb(S+0x24,4))[0],struct.unpack('<i',e.rb(S+0x30,4))[0]
 q=[ref.fl8(av,68),ref.fl8(tv,68),ref.fl8(sv,-8)]
 if None in q:rejected+=1;continue
 compared+=1
 na,nt,ns=q[0]-68,q[1]-68,q[2]+8
 want=32*na,32*(na+nt-ns)
 if got!=want:bad.append({'words':[tv,av,sv],'got':got,'want':want})
print(json.dumps({'inputs':3216,'compared':compared,'outsideAcceptedRange':rejected,'mismatches':len(bad),'examples':bad[:5]}))
assert not bad
