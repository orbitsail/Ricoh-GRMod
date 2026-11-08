from tfit import *
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
nonhc=[n for n in IDS if not HC[n]]
v='cam'
d=gather(nonhc,v,lambda s:s[f'{v}_x_0'],xmin=560)
T,k=fit_T_k(d,iters=1)
fig,ax=plt.subplots(3,4,figsize=(18,10))
for r,nm in enumerate(['0459402554','8247413060','5988854121']):
    s=STAT[nm]; x=s[f'{v}_x_0']; j=s['J']
    R=np.log(T(np.maximum(x,1)))-np.log(np.maximum(j,1e-4))
    ax[r,0].imshow(code8(j)/255,cmap='gray');ax[r,0].set_title(nm+' JPEG')
    im=ax[r,1].imshow(R,cmap='RdBu',vmin=-.5,vmax=.5);ax[r,1].set_title('log(T(x)/J)')
    ax[r,2].imshow(code8(T(np.maximum(x,1)))/255,cmap='gray');ax[r,2].set_title('T(x) predicted')
    m=flatmask(s,v,xmin=560)
    ax[r,3].plot(x[m],j[m],'.',ms=1); xs=np.geomspace(560,4095,50); ax[r,3].plot(xs,T(xs),'r'); ax[r,3].set_xscale('log');ax[r,3].set_yscale('log')
plt.tight_layout();plt.savefig('explore4.png',dpi=60)
