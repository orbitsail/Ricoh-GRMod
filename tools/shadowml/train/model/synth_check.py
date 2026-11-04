"""Label-method self-test: render a scene with a KNOWN s0 (plus noise and a global exposure/gamma change standing in for the retoucher), recover s*."""
import sys, glob, json, os
sys.dont_write_bytecode=True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, sim, make_labels as ML
rng=np.random.default_rng(0)
files=sorted(glob.glob(sim.SP+'/shadowml/fivek/*.npz'))[::12][:20]
rows=[]
for f in files:
    d=sim.fk_load.load(f); kst,ev=sim.scene_info(d)
    for iso,hl in [(200,1)]:
        xd,valid=ML.prep(d['raw_y'],kst,hl,ML.P)
        for s0 in (0,128,256,512,1024):
            E=sim.render(np.maximum(xd,0.5),s0,hl)*2.3                      # arbitrary exposure
            E=E*np.exp(rng.normal(0,0.05,E.shape))                           # 5 % pixel noise
            c,_=ML.label_costs(xd,valid,E,hl,ML.P); rows.append((s0,ML.best(c)))
r=np.array(rows)
for s0 in (0,128,256,512,1024):
    v=r[r[:,0]==s0,1]; print('true s=%4d  recovered mean %.0f  sd %.0f  range %d..%d'%(s0,v.mean(),v.std(),v.min(),v.max()))
