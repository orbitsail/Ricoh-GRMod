"""Does the shadow region collapse onto ONE curve (J vs x) for the non-HC and HC groups, as function of the assumed global shadow strength s?"""
from rho2 import *
SLs=[0,256,512,1024]
def curve_s(n,s_,v,edges):
    s=STAT[n]; X=s[f'{v}_xl_{s_}']; J=s['J']
    x0=s[f'{v}_x_0']; cv=np.sqrt(np.maximum(s[f'{v}_x2_0']-x0*x0,0))/np.maximum(x0,1)
    ok=(J>1e-4)&(X>1)&(cv<0.30)
    x00=s[f'{v}_xl_0']
    ref=ok&(x00>=600)&(x00<=1000)&(cv<0.1)
    c=np.median((J/x00)[ref]) if ref.sum()>10 else np.nan   # normalise on region unaffected by shadow gain (s=0 x)
    r=[]
    for a,b in zip(edges[:-1],edges[1:]):
        m=ok&(X>=a)&(X<b); r.append(J[m].sum()/X[m].sum()/c if m.sum()>=8 else np.nan)
    return np.array(r)
edges=np.geomspace(25,500,14); 
for v in ('mat','hyb'):
  for s_ in SLs:
    cur={}
    for g,ids in (('n',[n for n in IDS if not HC[n]]),('h',[n for n in IDS if HC[n]])):
        cur[g]=np.nanmedian(np.array([curve_s(n,s_,v,edges) for n in ids]),0)
    d=np.log(cur['n']/cur['h']); 
    # bootstrap over images
    rng=np.random.default_rng(0); bs=[]
    allc={n:curve_s(n,s_,v,edges) for n in IDS}
    for _ in range(300):
        a=rng.choice([n for n in IDS if not HC[n]],9); b=rng.choice([n for n in IDS if HC[n]],26)
        cn=np.nanmedian(np.array([allc[n] for n in a]),0); ch=np.nanmedian(np.array([allc[n] for n in b]),0)
        bs.append(np.sqrt(np.nanmean(np.log(cn/ch)**2)))
    print(v,'s=%4d'%s_,'group disagreement rms(log) %.4f  [bootstrap 5-95%%: %.4f-%.4f]'%(np.sqrt(np.nanmean(d**2)),*np.percentile(bs,[5,95])),' signed mean %.3f'%np.nanmean(d))
