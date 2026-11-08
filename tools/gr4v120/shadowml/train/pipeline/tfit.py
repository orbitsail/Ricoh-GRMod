"""Tone-curve fitting library (block level)."""
from common import *
from scipy.optimize import minimize_scalar
from scipy.interpolate import PchipInterpolator
import shadow_ref as S
IDS=[os.path.basename(p)[:-4] for p in DNGS]
TAG=os.environ.get('STAT_TAG','sv')
def _ld(nm):
    d=dict(np.load(f'{CACHE}/{nm}_{TAG}.npz')); return {k:(v.astype(np.float32) if v.dtype==np.float16 else v) for k,v in d.items()}
STAT={nm:_ld(nm) for nm in IDS}
HC={nm:int(STAT[nm]['hc']) for nm in IDS}
def flatmask(s,v,cvmax=0.10,fmin=0.99,xmin=0):
    x=s[f'{v}_x_0']; cv=np.sqrt(np.maximum(s[f'{v}_x2_0']-x*x,0))/np.maximum(x,1)
    return (cv<cvmax)&(s[f'{v}_f_ge140']>fmin)&(x>xmin)&(s['J']>0)
class Tcurve:
    """T: x(12-bit linear, 0..4095) -> JPEG linear luma, piecewise-linear in log-log, power-law extrapolation."""
    def __init__(self,lx,lj):
        self.lx=np.asarray(lx); self.lj=np.asarray(lj)
        n=3
        self.sl_lo=(self.lj[n]-self.lj[0])/(self.lx[n]-self.lx[0]); self.sl_hi=(self.lj[-1]-self.lj[-1-n])/(self.lx[-1]-self.lx[-1-n])
    def __call__(self,x):
        lx=np.log(np.maximum(x,1e-3)); y=np.interp(lx,self.lx,self.lj)
        y=np.where(lx<self.lx[0],self.lj[0]+self.sl_lo*(lx-self.lx[0]),y)
        y=np.where(lx>self.lx[-1],self.lj[-1]+self.sl_hi*(lx-self.lx[-1]),y)
        return np.minimum(np.exp(y),1.0)
def fit_T(X,J,lo=None,hi=4095,nb=36,min_n=15):
    lo=lo or max(X.min(),50)
    e=np.geomspace(lo,hi,nb+1); c=[];v=[]
    for a,b in zip(e[:-1],e[1:]):
        m=(X>=a)&(X<b)
        if m.sum()>=min_n: c.append(np.median(np.log(X[m]))); v.append(np.median(np.log(J[m])))
    c=np.array(c); v=np.array(v)
    # light smoothing + monotone
    vs=np.convolve(np.pad(v,1,mode='edge'),[0.25,0.5,0.25],'valid'); vs[0]=v[0]; vs[-1]=v[-1]
    vs=np.maximum.accumulate(vs)
    return Tcurve(c,vs)
def gather(ids,v,getx,flat=True,**kw):
    out={}
    for nm in ids:
        s=STAT[nm]; m=flatmask(s,v,**kw)
        x=getx(s)
        m=m&(x>0)
        out[nm]=(x[m],s['J'][m],m)
    return out
def fit_k(T,x,j):
    f=lambda lk: np.mean((np.log(T(x*np.exp(lk)))-np.log(j))**2)
    r=minimize_scalar(f,bounds=(-1.0,1.0),method='bounded'); return r.x
def fit_T_k(data,iters=4,**kw):
    ids=list(data); k={nm:0.0 for nm in ids}
    for it in range(iters):
        X=np.concatenate([data[n][0]*np.exp(k[n]) for n in ids]); J=np.concatenate([data[n][1] for n in ids])
        T=fit_T(X,J,**kw)
        for n in ids: k[n]=fit_k(T,data[n][0],data[n][1])
        mk=np.mean([k[n] for n in ids])
        for n in ids: k[n]-=mk
    X=np.concatenate([data[n][0]*np.exp(k[n]) for n in ids]); J=np.concatenate([data[n][1] for n in ids])
    return fit_T(X,J,**kw),k
def resid(T,x,j,lk=0.0):
    return np.log(T(x*np.exp(lk)))-np.log(j)
def code8(lin): return 255*lin2srgb(lin)
