"""Model-light shadow diagnostic: rho = J / (709-weighted matrixed linear x with s=0 table) vs luma index; constant in the linear toe unless a shadow gain acts."""
from tfit import *
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
W709=np.array([.2126,.7152,.0722],np.float32)
bins=np.array([0,8,16,24,32,48,64,80,96,112,130,150,200,300])
def rho_img(n,v='mat'):
    s=STAT[n]
    X=np.tensordot(W709,s[f'{v}_ch'],1)   # includes HC gain (s=0 table)
    J=s['J']; idx=s[f'{v}_idxmean']
    ok=(J>0)&(X>0)
    ref=ok&(X>=600)&(X<=1200)&(s[f'{v}_f_ge140']>0.99)
    c=np.median((J/np.maximum(X,1e-3))[ref]) if ref.sum()>20 else np.nan
    out=[];cnt=[]
    for a,b in zip(bins[:-1],bins[1:]):
        m=ok&(idx>=a)&(idx<b)&(s[f'{v}_f_lt130']>0.5 if b<=130 else True)
        # ratio of sums (robust, weight by brightness)
        out.append(J[m].sum()/X[m].sum()/c if m.sum()>=5 else np.nan); cnt.append(m.sum())
    return np.array(out),np.array(cnt),c
if __name__=='__main__':
    ctr=0.5*(bins[:-1]+bins[1:])
    fig,ax=plt.subplots(1,2,figsize=(14,5))
    R={}
    for n in IDS:
        r,cnt,c=rho_img(n); R[n]=(r,cnt,c)
        ax[HC[n]].plot(ctr,r,'-o',ms=3,lw=0.8,label=n)
    from shadow_ref import table
    for a,t in zip(ax,('non-HC (ISO100): expected no-op = 1.0','HC (ISO>=200): flat 1.0 = no-op')):
        for sv,col in ((256,'g'),(512,'darkorange'),(1024,'r')):
            tab=np.array(table(sv,0),float)/4096
            a.plot(np.arange(0,300),tab[:300],color=col,ls='--',lw=2,label=f's={sv} (expected)')
        a.axhline(1,color='k',lw=0.5);a.set_xlabel('luma index i (Y>>2)');a.set_ylabel('rho/c  (JPEG lum / linear input, normalised)');a.set_title(t);a.set_ylim(0.5,2.5);a.set_xlim(0,300)
    ax[0].legend(fontsize=5,ncol=2)
    plt.tight_layout();plt.savefig('rho_vs_index.png',dpi=90)
    # summary: mean rho in index<40 and 40-100
    for n in IDS:
        r,cnt,c=R[n]; print(n,HC[n],'c=%.3f'%c,'rho/c i<32: %.3f  32-64: %.3f  64-96: %.3f  96-130: %.3f   nblk(<64)=%d'%(np.nansum(r[:4]*cnt[:4])/max(cnt[:4].sum(),1),np.nansum(r[4:6]*cnt[4:6])/max(cnt[4:6].sum(),1),np.nansum(r[6:9]*cnt[6:9])/max(cnt[6:9].sum(),1),np.nansum(r[8:10]*cnt[8:10])/max(cnt[8:10].sum(),1),cnt[:6].sum()))
