import os
import sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hcommon import *
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
e=new_emu(); rng=random.Random(5)
seen=[]
def hk(uc,a,s,u): seen.append((uc.reg_read(UC_ARM_REG_R7),uc.reg_read(UC_ARM_REG_R4),uc.reg_read(UC_ARM_REG_R5)))
e.mu.hook_add(UC_HOOK_CODE,hk,begin=0x53938e2c,end=0x53938e30)
f89=[]
for r2 in (0,0x60700000,0x1234):
  for t in range(6):
    S,nblk=rand_S(rng); S['s34']=0; S['b50']=0; setup_S(e,S,nblk)
    Wb=bytes(rng.randrange(256) for _ in range(nblk+4)); e.wb(e.r32(A_OBJ+0xAF8C),Wb)
    setup_cal(e,rng)
    seen.clear()
    e.call(0x53938B28,A_OBJ,SBASE,r2)
    f89.append((r2,e.rb(A_OBJ+0xAF89,1)[0]))
    assert seen and seen[0][0]==r2, (seen,r2)
    assert seen[0][1]==A_OBJ and seen[0][2]==SBASE
print('r7 at 0x53938E2C == original r2 (this=r4, S=r5) in 18/18 runs')
# force "no valid block": all stats zero
S,nblk=rand_S(rng); S['s34']=0;S['b50']=0
for k in range(4): S['P'][k]=[0]*nblk
setup_S(e,S,nblk); e.wb(e.r32(A_OBJ+0xAF8C),bytes(nblk+4)); setup_cal(e,rng)
e.call(0x53938B28,A_OBJ,SBASE,0)
print('all-zero stats: F89 =',e.rb(A_OBJ+0xAF89,1)[0],'gains this+4,+0xA =',e.r16(A_OBJ+4),e.r16(A_OBJ+0xA))
print('normal runs F89 distribution',sorted(set(f89)))
