from common import *
ids=[os.path.basename(p)[:-4] for p in DNGS]
D=[np.load(f'{CACHE}/{nm}_stats.npz') for nm in ids]
edges=np.geomspace(560,4000,12)
def spread(sel,get):
    X=[];Jv=[];I=[]
    for k,s in enumerate(D):
        if sel(s)!=True: continue
        x,j=get(s)
        x2=s['cam_x2_0']; cv=np.sqrt(np.maximum(x2-s['cam_x_0']**2,0))/np.maximum(s['cam_x_0'],1)
        m=(cv<0.1)&(s['cam_f_ge140']>0.99)&(x>560)&(j>0)
        X.append(x[m]);Jv.append(j[m]);I.append(np.full(m.sum(),k))
    X=np.concatenate(X);Jv=np.concatenate(Jv)
    res=[]
    for a,b in zip(edges[:-1],edges[1:]):
        m=(X>=a)&(X<b)
        if m.sum()>20: res.append(np.std(np.log(Jv[m])))
    return np.mean(res), len(X)
for grp,sel in (('nonHC',lambda s:int(s['hc'])==0),('HC',lambda s:int(s['hc'])==1)):
  for v in ('cam','mat'):
    for jn in ('J','J601','Jg'):
        def get(s):
            x=s[f'{v}_x_0']
            if jn=='Jg': return s[f'{v}_ch'][1], s['Jch'][1]
            if v=='mat' and False: pass
            return x, s[jn]
        print(grp,v,jn,spread(sel,get))
