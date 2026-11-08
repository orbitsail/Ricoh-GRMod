from common import *
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from stats import hcflag
ids=[os.path.basename(p)[:-4] for p in DNGS]
fig,ax=plt.subplots(1,2,figsize=(13,5))
for nm in ids:
    s=np.load(f'{CACHE}/{nm}_stats.npz'); hc=int(s['hc'])
    for v,a in zip(('cam',),ax):
        x=s[f'{v}_x_0']; x2=s[f'{v}_x2_0']; cv=np.sqrt(np.maximum(x2-x*x,0))/np.maximum(x,1)
        m=(cv<0.1)&(s[f'{v}_f_ge140']>0.99)
        a.plot(x[m][::40],s['J'][m][::40],'.',ms=1,color='C1' if hc else 'C0')
for a in ax: a.set_xscale('log'); a.set_yscale('log')
plt.savefig('explore1.png',dpi=90)
