"""Joint tone-curve consistency across HC / non-HC groups for each global shadow strength s (block level, luma)."""
from tfit import *
import json
KJ=json.load(open('T_final_lo560.json'))['k']
SLs=[0,256,512,1024]
def blocks(v,s_,n,cvmax=0.30,xlo=15):
    s=STAT[n]
    x0=s[f'{v}_x_0']; cv=np.sqrt(np.maximum(s[f'{v}_x2_0']-x0*x0,0))/np.maximum(x0,1)
    m=(cv<cvmax)&(s['J']>1e-4)&(s[f'{v}_xl_{s_}']>xlo)&(s[f'{v}_idxmean']<600)
    return s[f'{v}_xl_{s_}'][m]*np.exp(KJ[n]), s['J'][m], s[f'{v}_idxmean'][m]
def run(v):
    res={}
    for sg in SLs:
        X=[];J=[];G=[];I=[]
        for n in IDS:
            x,j,i=blocks(v,sg,n); X.append(x);J.append(j);G.append(np.full(len(x),HC[n]));I.append(i)
        X=np.concatenate(X);J=np.concatenate(J);G=np.concatenate(G);I=np.concatenate(I)
        # common T from all
        T=fit_T(X,J,lo=15,hi=4095,nb=60,min_n=30)
        r=np.log(T(X))-np.log(J)
        sh=I<130
        # group-specific T mismatch in shadow-affected x range
        Tn=fit_T(X[G==0],J[G==0],lo=15,nb=60,min_n=30); Th=fit_T(X[G==1],J[G==1],lo=15,nb=60,min_n=30)
        xs=np.geomspace(40,1000,25)
        mis=np.sqrt(np.mean((np.log(Tn(xs))-np.log(Th(xs)))**2))
        mis_lo=np.sqrt(np.mean((np.log(Tn(xs[xs<400]))-np.log(Th(xs[xs<400])))**2))
        res[sg]=dict(rms_all=r.std(),rms_shadow=r[sh].std(),rms_nonHC=r[G==0].std(),rms_HC=r[G==1].std(),mismatch=mis,mismatch_lo=mis_lo)
        print(v,'s=%4d'%sg,'rms all %.4f shadow %.4f nonHC %.4f HC %.4f | T_nonHC vs T_HC rms log-diff over x 40-1000: %.4f (x<400: %.4f)'%(r.std(),r[sh].std(),r[G==0].std(),r[G==1].std(),mis,mis_lo))
    return res
for v in ('mat','hyb'): run(v)
