# SPDX-License-Identifier: GPL-2.0-only
"""Measure stack of actual 1.20 shadow core+stub+module with existing suite inputs."""
import json,random,sys
from pathlib import Path
out=Path(sys.argv[1]);root=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(root/'tools/gr4v120/shadowml'),str(root/'tools/gr4v120/re')]
sys.argv=[sys.argv[0],str(out/'120-final.rtos'),str(out/'120-awb.rtos')]
import test_fw as T
import numpy as np
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP
c=T.Core(str(out/'120-final.rtos'));rng=np.random.default_rng(31);rnd=random.Random(31)
state={};result={}
def trace(uc,a,s,u):
 sp=uc.reg_read(UC_ARM_REG_SP)
 if a==T.F_CORE:state.update(entry=sp,minimum=sp,hook=None,hookMin=None)
 if 'entry' not in state:return
 state['minimum']=min(state['minimum'],sp)
 if a==T.HOOK:state['hook']=sp;state['hookMin']=sp
 if state['hookMin'] is not None:state['hookMin']=min(state['hookMin'],sp)
c.mu.hook_add(UC_HOOK_CODE,trace)
for k in range(160):
 w,h,R,G,B,C=T.TH.scene(rng);mode=k%4
 P=T.TH.make_P(mode,w,h,R,G,B,C,rng);P=bytes(P)+bytes(T.P_SIZE-len(P))
 c.mu.mem_write(T.SLOT,bytes(4));state.clear();c.run(P,0,k%2,rnd.choice([0,10,25,40,60,80,95,120]),mode)
 assert state['hook'] is not None
 key='live' if mode in (1,2) else 'still'
 row=result.setdefault(key,{'calls':0,'fullCoreMax':0,'belowHookMax':0});row['calls']+=1
 row['fullCoreMax']=max(row['fullCoreMax'],state['entry']-state['minimum'])
 row['belowHookMax']=max(row['belowHookMax'],state['hook']-state['hookMin'])
report={'paths':result,'allocatorStubbed':True,'stockYBuilderStubbed':True,'realTaskStackUnknown':True}
(out/'shadow120-stack.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
