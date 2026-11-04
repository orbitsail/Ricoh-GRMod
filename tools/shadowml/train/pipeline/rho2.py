"""rho vs linear-input x (not index): ratio JPEG/linear, normalised in the linear mid-range; groups: Auto non-HC, Auto HC (HLTAB in x), studio (shadow correction Off)."""
from tfit import *
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
STU=[os.path.basename(p)[:-4] for p in STUDIO]
for n in STU: STAT[n]=dict(np.load(f'{CACHE}/{n}_{TAG}.npz')); HC[n]=0
edges=np.geomspace(20,1500,22); ctr=np.sqrt(edges[:-1]*edges[1:])
def rho_x(n,v='mat'):
    s=STAT[n]; X=s[f'{v}_xl_0']; J=s['J']
    x0=s[f'{v}_x_0']; cv=np.sqrt(np.maximum(s[f'{v}_x2_0']-x0*x0,0))/np.maximum(x0,1)
    ok=(J>1e-4)&(X>1)&(cv<0.30)
    ref=ok&(X>=600)&(X<=1000)&(cv<0.1)
    c=np.median((J/X)[ref]) if ref.sum()>10 else np.nan
    r=[];cn=[]
    for a,b in zip(edges[:-1],edges[1:]):
        m=ok&(X>=a)&(X<b); cn.append(m.sum()); r.append(J[m].sum()/X[m].sum()/c if m.sum()>=8 else np.nan)
    return np.array(r),np.array(cn),c
if __name__=='__main__':
    fig,ax=plt.subplots(1,2,figsize=(14,5.5))
    G={'Auto, no HC (ISO100) n=9':[n for n in IDS if not HC[n]],'Auto, HC (ISO>=200) n=26':[n for n in IDS if HC[n]],'studio, shadow Off (ISO100) n=2':STU}
    cols=['C0','C1','k']
    summ={}
    for (g,ids),col in zip(G.items(),cols):
        rs=[]
        for n in ids:
            r,cn,c=rho_x(n)
            if np.isnan(c): continue
            ax[0].plot(ctr,r,color=col,lw=0.6,alpha=0.5); rs.append(r)
        med=np.nanmedian(np.array(rs),0); summ[g]=med
        ax[1].plot(ctr,med,'-o',color=col,ms=3,label=g)
    for a in ax: a.set_xscale('log');a.axhline(1,color='gray',lw=0.5);a.set_xlabel('linear input x (12-bit, WB+matrix+shading+HC gain)');a.set_ylabel('JPEG / linear, normalised at x=600-1000');a.set_ylim(0,1.8)
    ax[0].set_title('per image');ax[1].set_title('median by group');ax[1].legend(fontsize=8)
    plt.tight_layout();plt.savefig('rho_vs_x.png',dpi=90)
    print('x   ',np.round(ctr,0))
    for g,m in summ.items(): print(g[:22],np.round(m,2))
