"""Task 3: pixel-level shadow prediction for s grid, per-image best s with block-bootstrap confidence.
Methods: 'A' = T from index>=140 data (>=560) with power-law extrapolation below (slope SLO);  'C' = toe taken from the pooled empirical curve of ALL 35 images assuming s=0 (tests image-to-image deviations only)."""
from common import *
import json, cv2, sys
import shadow_ref as S
from stats import vfield, ds, TABS
from tfit import Tcurve
cv2.setNumThreads(2)
TF=json.load(open(PIPE+'/T_final_lo560.json')); K=TF['k']
W709=np.array([.2126,.7152,.0722],np.float32); W601=np.array([77,150,29],np.float32)/256
VP=json.load(open(PIPE+'/vp_final.json'))
SGRID=[0,64,128,256,384,512,768,1024,1536]
XG=np.arange(16384)/4.0
def lut_A(slo):
    T=Tcurve(TF['lx'],TF['lj']); T.sl_lo=slo
    return T(np.maximum(XG,1e-2)).astype(np.float32)
def lut_C(medcurve_x,medcurve_rho):
    TA=lut_A(1.0); x=np.maximum(XG,1e-2)
    cbar=TA[int(800*4)]/800.0
    rho=np.interp(np.log(x),np.log(medcurve_x),medcurve_rho)
    lo=np.log(x)<np.log(medcurve_x[0]); rho=np.where(lo,medcurve_rho[0]*(x/medcurve_x[0])**0.1,rho)
    TC=x*cbar*rho; hi=x>=560; return np.where(hi,TA,TC).astype(np.float32)
def prep(nm):
    from extract import extract
    cam,jl=extract(dng_path(nm),save=False); cam=np.minimum(cam*vfield(VP[nm])[...,None],4095)
    M,_=cam2srgb_matrix(nm); mat=np.clip(cam@M.T.astype(np.float32),0,4095)
    Xl=mat@W709; Ym=mat@W601; Yc=cam@W601
    j=jl@W709
    return dict(Xl=Xl,im=np.clip(np.floor(Ym).astype(np.int32)>>2,0,1023),ic=np.clip(np.floor(Yc).astype(np.int32)>>2,0,1023),J=ds(j))
def predict(P,hc,s,lut,k,src='im'):
    g=TABS_ANY(s,hc)[P[src]]
    x=np.minimum(P['Xl']*g*np.exp(k),4095)
    return ds(lut[np.minimum((x*4).astype(np.int32),16383)])
_t={}
def TABS_ANY(s,hc):
    if (s,hc) not in _t: _t[(s,hc)]=np.array(S.table(s,hc),np.float32)/4096
    return _t[(s,hc)]
def analyse(nm,luts,hc,src='im'):
    P=prep(nm); k=K[nm]
    f130=ds((P[src]<130).astype(np.float32)); m=(f130>=0.8)&(P['J']>1e-4)
    out={'n_blocks':int(m.sum()),'mean_f130':float(f130.mean())}
    rows={}
    for name,lut in luts.items():
        L=[]
        for s in SGRID:
            pr=predict(P,hc,s,lut,k,src); L.append(np.log(np.maximum(pr,1e-6))[m]-np.log(P['J'][m]))
        rows[name]=np.array(L)   # [s, nblocks]
    yy,xx=np.nonzero(m); tile=(yy//30)*12+(xx//30)   # 8x12 tiles of 30x30 blocks
    return out,rows,tile
def best_s(L,tile,rng,nboot=300):
    # cost(s) = mean squared log residual ; also mean |.|
    cost=(L**2).mean(1); i0=int(np.argmin(cost))
    # continuous refinement: parabola through 3 grid points around min (on s)
    sg=np.array(SGRID,float); sh=sg[i0]
    if 0<i0<len(sg)-1:
        a,b,c=np.polyfit(sg[i0-1:i0+2],cost[i0-1:i0+2],2); sh=-b/(2*a) if a>0 else sg[i0]
        sh=float(np.clip(sh,sg[i0-1],sg[i0+1]))
    ut=np.unique(tile); bs=[]
    for _ in range(nboot):
        pick=rng.choice(ut,len(ut)); idx=np.concatenate([np.nonzero(tile==t)[0] for t in pick])
        bc=(L[:,idx]**2).mean(1); bs.append(sg[np.argmin(bc)])
    bs=np.array(bs)
    named=[0,256,512,1024]; nc=[cost[SGRID.index(s)] for s in named]
    return dict(cost=cost.tolist(),s_grid_best=float(sg[i0]),s_cont=sh,boot_p_s0=float((bs==0).mean()),boot_p_le64=float((bs<=64).mean()),boot_med=float(np.median(bs)),boot_lo=float(np.percentile(bs,5)),boot_hi=float(np.percentile(bs,95)),best_named=int(named[int(np.argmin(nc))]),
                bias_s0=float(L[0].mean()),sd_s0=float(L[0].std()))
if __name__=='__main__':
    # pooled empirical curve (all 35, s=0) for method C
    from tfit import STAT as STF, IDS, HC
    import tfit
    edges=np.geomspace(20,600,24); ctr=np.sqrt(edges[:-1]*edges[1:]); R=[]
    for n in IDS:
        s=STF[n]; X=s['mat_xl_0']; J=s['J']; x0=s['mat_x_0']; cv=np.sqrt(np.maximum(s['mat_x2_0']-x0*x0,0))/np.maximum(x0,1)
        ok=(J>1e-4)&(X>1)&(cv<0.30); ref=ok&(X>=600)&(X<=1000)&(cv<0.1); c=np.median((J/X)[ref])
        R.append([J[ok&(X>=a)&(X<b)].sum()/X[ok&(X>=a)&(X<b)].sum()/c if (ok&(X>=a)&(X<b)).sum()>=8 else np.nan for a,b in zip(edges[:-1],edges[1:])])
    med=np.nanmedian(np.array(R),0); good=~np.isnan(med)
    luts={'A_slope1.0':lut_A(1.0),'A_slope0.7':lut_A(0.7),'A_slope1.4':lut_A(1.4),'C_empirical':lut_C(ctr[good],med[good])}
    rng=np.random.default_rng(1); res={}
    for nm in IDS:
        info,rows,tile=analyse(nm,luts,HC[nm]); info['hc']=HC[nm]; info['iso']=SUMMARY[nm]['iso']
        for name in luts: info[name]=best_s(rows[name],tile,rng)
        res[nm]=info
        print(nm,'HC' if HC[nm] else '  ','nblk %4d'%info['n_blocks'],' | '.join('%s: s*=%4.0f cont %5.0f P(s=0)=%.2f bias0=%+.2f'%(k[:3],info[k]['s_grid_best'],info[k]['s_cont'],info[k]['boot_p_s0'],info[k]['bias_s0']) for k in luts),flush=True)
    json.dump(res,open(PIPE+'/shadow_results.json','w'),indent=1)
