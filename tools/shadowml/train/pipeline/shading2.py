"""Common radial shading gain V(u)=exp(a u+b u^2+c u^3) across all images (robust), tone curve per HC group. Writes vp_common.json"""
from common import *
from tfit import *
import tfit, json, sys
from scipy.optimize import least_squares
v='cam'
yy,xx=np.mgrid[0:240,0:360]; u=(((xx+.5)/360*2-1)**2+((yy+.5)/240*2-1)**2)/2
NP=int(sys.argv[1]); sel=sys.argv[2] if len(sys.argv)>2 else 'all'
ids=[n for n in IDS if sel=='all' or (sel=='nonhc' and not HC[n]) or (sel=='hc' and HC[n]) or (sel=='n28' and SUMMARY[n]['N']<=2.9) or (sel=='nge4' and SUMMARY[n]['N']>2.9)]
d={}
for n in ids:
    m=flatmask(STAT[n],v,xmin=400); d[n]=(STAT[n][f'{v}_x_0'][m],STAT[n]['J'][m],m)
def V(p,m):
    uu=u[m]; return np.exp(sum(p[k]*uu**(k+1) for k in range(NP)))
p=np.zeros(NP)
groups={g:[n for n in ids if HC[n]==g] for g in (0,1)}
for it in range(4):
    Ts={}
    for g,gi in groups.items():
        if not gi: continue
        X=np.concatenate([d[n][0]*V(p,d[n][2]) for n in gi]); J=np.concatenate([d[n][1] for n in gi]); Ts[g]=fit_T(X,J,lo=400)
    def f(p):
        out=[]
        for n in ids:
            out.append((np.log(Ts[HC[n]](d[n][0]*V(p,d[n][2])))-np.log(d[n][1]))[::3])
        return np.concatenate(out)
    r=least_squares(f,p,loss='soft_l1',f_scale=0.05); p=r.x
print('params',p, 'V(corner)=%.3f V(edge-mid)=%.3f'%(V(p,np.array([[True]])*0+ (u>=0.999))[0] if False else np.exp(sum(p[k] for k in range(NP))), np.exp(sum(p[k]*0.5**(k+1) for k in range(NP)))))
for n in ids:
    r=np.log(Ts[HC[n]](d[n][0]*V(p,d[n][2])))-np.log(d[n][1]); r0=np.log(Ts[HC[n]](d[n][0]))-np.log(d[n][1])
    print(n,HC[n],'N=%.1f'%SUMMARY[n]['N'],'rms %.3f -> %.3f'%(r0.std(),r.std()))
json.dump({n:list(p) for n in IDS},open(f'vp_common_{NP}_{sel}.json','w'))
