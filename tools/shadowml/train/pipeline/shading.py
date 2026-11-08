"""Fit per-image radial shading gain V(u)=exp(a u + b u^2), u=r^2/2 (corner=1), jointly with a common tone curve, from block stats."""
from common import *
from tfit import *
import tfit, json, sys
from scipy.optimize import least_squares
tag=sys.argv[1]; out=sys.argv[2]; v='cam'
tfit.STAT={nm:dict(np.load(f'{CACHE}/{nm}_{tag}.npz')) for nm in IDS}
STAT=tfit.STAT
yy,xx=np.mgrid[0:240,0:360]; u=(((xx+.5)/360*2-1)**2+((yy+.5)/240*2-1)**2)/2
prev=json.load(open(sys.argv[3])) if len(sys.argv)>3 else {nm:[0,0] for nm in IDS}
res={}
for grp in (0,1):
    ids=[n for n in IDS if HC[n]==grp]
    # x in the stats already contains previous V (if tag corrected); we fit the *incremental* V
    d={n:(STAT[n][f'{v}_x_0'][flatmask(STAT[n],v,xmin=400)],STAT[n]['J'][flatmask(STAT[n],v,xmin=400)],flatmask(STAT[n],v,xmin=400)) for n in ids}
    vp={n:np.zeros(2) for n in ids}
    def vx(n,p):
        m=d[n][2]; return d[n][0]*np.exp(p[0]*u[m]+p[1]*u[m]**2)
    for it in range(5):
        X=np.concatenate([vx(n,vp[n]) for n in ids]); J=np.concatenate([d[n][1] for n in ids])
        T=fit_T(X,J,lo=400)
        for n in ids:
            f=lambda p:(np.log(T(vx(n,p)))-np.log(d[n][1]))
            r=least_squares(f,vp[n],loss='soft_l1',f_scale=0.05); vp[n]=r.x
    for n in ids:
        r=np.log(T(vx(n,vp[n])))-np.log(d[n][1])
        r0=np.log(T(d[n][0]))-np.log(d[n][1])
        res[n]=list(np.array(prev[n])+vp[n])
        print(grp,n,'N=%.1f'%SUMMARY[n]['N'],'a,b=%.3f %.3f'%tuple(vp[n]),'rms %.3f -> %.3f'%(r0.std(),r.std()),flush=True)
json.dump(res,open(out,'w'))
