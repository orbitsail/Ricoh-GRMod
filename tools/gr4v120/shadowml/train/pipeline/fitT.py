"""Task 2 final: per-channel tone curve T on matrixed RGB (after WB, shading, HC-gain H1), index>=140 flat blocks, per-image brightness factor k."""
from tfit import *
import json
W709=np.array([.2126,.7152,.0722])
import sys
LO=float(os.environ.get('TLO','560'))
def chan_data(ids,v='mat'):
    d={}
    for n in ids:
        s=STAT[n]; m=flatmask(s,v,xmin=0)&(s[f'{v}_Ymean']>=560)
        X=[];J=[]
        for c in range(3):
            x=s[f'{v}_ch'][c][m]; j=s['Jch'][c][m]; ok=(x>=LO)&(x<4090)&(j>2e-3)&(j<0.995)
            X.append(x[ok]);J.append(j[ok])
        d[n]=(np.concatenate(X),np.concatenate(J),m)
    return d
def luma_pred(T,s,m,lk,v='mat'):
    return sum(W709[c]*T(s[f'{v}_ch'][c][m]*np.exp(lk)) for c in range(3))
def luma_resid(T,n,lk,v='mat'):
    s=STAT[n]; m=flatmask(s,v,xmin=0)&(s[f'{v}_Ymean']>=560)
    return np.log(np.maximum(luma_pred(T,s,m,lk,v),1e-6))-np.log(s['J'][m])
def fitall(ids,v='mat'):
    d=chan_data(ids,v); T,k=fit_T_k(d,iters=5,lo=LO); return T,k,d
if __name__=='__main__':
    nonhc=[n for n in IDS if not HC[n]]; hc=[n for n in IDS if HC[n]]
    out={}
    for name,ids in (('all',IDS),('nonHC',nonhc),('HC',hc)):
        T,k,d=fitall(ids)
        rc=np.concatenate([resid(T,d[n][0],d[n][1],k[n]) for n in ids])
        rl=np.concatenate([luma_resid(T,n,k[n]) for n in ids])
        rl0=np.concatenate([luma_resid(T,n,0) for n in ids])
        print(name,'channel-level rms log %.4f | luma-level rms log %.4f (k=0: %.4f) | k sd %.3f'%(rc.std(),rl.std(),rl0.std(),np.std(list(k.values()))))
        out[name]=(T,k)
    # compare curves
    xs=np.array([300,400,600,800,1000,1500,2000,3000,4000])
    for a,b in (('nonHC','HC'),('nonHC','all'),('HC','all')):
        print(a,'/',b,np.round(out[a][0](xs)/out[b][0](xs),3))
    T,k=out['all']
    json.dump({'lx':list(map(float,T.lx)),'lj':list(map(float,T.lj)),'k':{n:float(v) for n,v in k.items()},'LO':LO,'T_nonHC':{'lx':list(map(float,out['nonHC'][0].lx)),'lj':list(map(float,out['nonHC'][0].lj))},'T_HC':{'lx':list(map(float,out['HC'][0].lx)),'lj':list(map(float,out['HC'][0].lj))}},open(f'T_final_lo{int(LO)}.json','w'))
    print('k:',{n:round(float(v),3) for n,v in k.items()})
    print('support: lx range',np.exp(T.lx[0]),np.exp(T.lx[-1]),'slopes lo/hi',T.sl_lo,T.sl_hi)
