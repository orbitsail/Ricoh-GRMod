"""Build one tone curve T over the whole range: T_final_lo560 above x=560 (well determined), empirical pooled toe (method C of shadow3.py) below.
Output: T_full.npz (x 0..4095 step 0.25 -> J) + T_full.png"""
import os, sys, json
os.environ['STAT_TAG']='sv3'
sys.path.insert(0,(__import__('os').environ.get('GRIV_WORK', '.') + '/shadowml/pipeline'))
import numpy as np
from tfit import Tcurve, STAT, IDS
import common
TF=json.load(open(common.PIPE+'/T_final_lo560.json'))
XG=np.arange(16384)/4.0
x=np.maximum(XG,1e-2)
TA=Tcurve(TF['lx'],TF['lj']); TA.sl_lo=1.0
TAv=TA(x)
edges=np.geomspace(20,600,24); ctr=np.sqrt(edges[:-1]*edges[1:]); R=[]
for n in IDS:
    s=STAT[n]; X=s['mat_xl_0']; J=s['J']; x0=s['mat_x_0']; cv=np.sqrt(np.maximum(s['mat_x2_0']-x0*x0,0))/np.maximum(x0,1)
    ok=(J>1e-4)&(X>1)&(cv<0.30); ref=ok&(X>=600)&(X<=1000)&(cv<0.1); c=np.median((J/X)[ref])
    R.append([J[ok&(X>=a)&(X<b)].sum()/X[ok&(X>=a)&(X<b)].sum()/c if (ok&(X>=a)&(X<b)).sum()>=8 else np.nan for a,b in zip(edges[:-1],edges[1:])])
R=np.array(R); med=np.nanmedian(R,0); good=~np.isnan(med)
cx,cr=ctr[good],med[good]
cbar=TAv[int(800*4)]/800.0
rho=np.interp(np.log(x),np.log(cx),cr)
lo=np.log(x)<np.log(cx[0]); rho=np.where(lo,cr[0]*(x/cx[0])**0.1,rho)
TC=x*cbar*rho
# smooth blend over 480..640 in log x so the join is continuous
w=np.clip((np.log(x)-np.log(480))/(np.log(640)-np.log(480)),0,1)
Tf=np.exp((1-w)*np.log(np.maximum(TC,1e-9))+w*np.log(TAv))
Tf=np.maximum.accumulate(Tf); Tf[0]=0
np.savez('T_full.npz',x=XG,J=Tf.astype(np.float32),toe_x=cx,toe_rho=cr,n_img=len(IDS))
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
fig,ax=plt.subplots(1,3,figsize=(16,4.5))
xs=XG[1:];
ax[0].loglog(xs,Tf[1:],'k',label='T full'); ax[0].loglog(xs,TAv[1:],'r:',label='T_final_lo560 (power-law toe)'); ax[0].axvline(579,c='g',ls='--'); ax[0].legend(); ax[0].set_xlabel('x (12-bit linear)'); ax[0].set_ylabel('J'); ax[0].grid(alpha=.3)
ax[1].semilogx(cx,cr,'o-',label='empirical rho (pooled 35 DNG)'); ax[1].set_xlabel('x'); ax[1].set_ylabel('J/x relative'); ax[1].legend(); ax[1].grid(alpha=.3)
sr=lambda v:255*np.where(v<=.0031308,12.92*v,1.055*np.maximum(v,1e-9)**(1/2.4)-.055)
ax[2].plot(xs[:4096*4:4],sr(Tf[1:][:4096*4:4]),'k'); ax[2].axvline(579,c='g',ls='--'); ax[2].set_xlabel('x'); ax[2].set_ylabel('sRGB code'); ax[2].grid(alpha=.3)
plt.tight_layout(); plt.savefig('T_full.png',dpi=90)
print('toe',list(zip(cx.round(0),cr.round(3)))); print('T(100,300,579,1000,4095)=',[float(Tf[int(v*4)]) for v in (100,300,579,1000,4095)])
