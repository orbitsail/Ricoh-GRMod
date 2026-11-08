"""Task 2: tone curve T, HC hypotheses, camera vs matrixed RGB."""
from tfit import *
import json
nonhc=[n for n in IDS if not HC[n]]; hc=[n for n in IDS if HC[n]]
tabHC=np.array(S.table(0,1),np.float32)/4096
R={}
def pack(ids,v,xf):
    out={}
    for n in ids:
        s=STAT[n]; m=flatmask(s,v,xmin=0)&(s[f'{v}_Ymean']>=560)
        x=xf(s); out[n]=(x[m],s['J'][m],m)
    return out
for v in ('cam','mat'):
    print('=====',v)
    dn=pack(nonhc,v,lambda s:s[f'{v}_Ymean'])
    T0,k0=fit_T_k(dn,iters=4)
    allr=np.concatenate([resid(T0,dn[n][0],dn[n][1],k0[n]) for n in nonhc])
    print('nonHC fit (k per image): rms log %.4f   k:'%allr.std(),{n:round(k0[n],3) for n in nonhc})
    # code-domain error
    cr=np.concatenate([code8(T0(dn[n][0]*np.exp(k0[n])))-code8(dn[n][1]) for n in nonhc]); print('   rms 8-bit code %.2f  median|d| %.2f'%(cr.std(),np.median(np.abs(cr))))
    T0n,_=fit_T_k(dn,iters=0+1)  # same? no k: first iter k=0
    Tn=fit_T(np.concatenate([dn[n][0] for n in nonhc]),np.concatenate([dn[n][1] for n in nonhc]))
    print('nonHC fit (no k): rms log %.4f'%np.concatenate([resid(Tn,dn[n][0],dn[n][1]) for n in nonhc]).std())
    res={}
    # HC group hypotheses (T0 fixed from nonHC)
    for hyp in ('H0','H1','H2','H3'):
        rr=[];ks=[]
        for n in hc:
            s=STAT[n]; m=flatmask(s,v,xmin=0)&(s[f'{v}_Ymean']>=560)
            Y=s[f'{v}_Ymean'][m]; j=s['J'][m]; idx=np.clip(s[f'{v}_idxmean'][m],0,1023).astype(int)
            if hyp=='H0': pred=lambda lk: T0(Y*np.exp(lk))
            elif hyp=='H1': pred=lambda lk: T0(Y*np.exp(lk)*tabHC[idx])
            elif hyp=='H2': pred=lambda lk: srgb2lin(np.minimum(lin2srgb(T0(Y*np.exp(lk)))*tabHC[idx],1.0))
            else:
                def pred(lk):
                    e=lin2srgb(T0(Y*np.exp(lk))); i3=np.clip((e*4095).astype(int)>>2,0,1023)
                    return srgb2lin(np.minimum(e*tabHC[i3],1.0))
            f=lambda lk: np.mean((np.log(np.maximum(pred(lk),1e-6))-np.log(j))**2)
            r=minimize_scalar(f,bounds=(-1.5,1.5),method='bounded'); lk=r.x
            rr.append(np.log(np.maximum(pred(lk),1e-6))-np.log(j)); ks.append(lk)
            rr0=np.log(np.maximum(pred(0.0),1e-6))-np.log(j)
        rrc=np.concatenate(rr)
        res[hyp]=(rrc.std(),ks)
        print(hyp,'HC group (T0 from nonHC) rms log %.4f ; k per image mean %.3f sd %.3f'%(rrc.std(),np.mean(ks),np.std(ks)))
    # T fitted on HC group under H1 vs T0
    dh=pack(hc,v,lambda s:s[f'{v}_x_0'])
    Th,kh=fit_T_k(dh,iters=4)
    allr=np.concatenate([resid(Th,dh[n][0],dh[n][1],kh[n]) for n in hc]); print('HC-only T under H1: rms %.4f'%allr.std(),'k sd %.3f'%np.std(list(kh.values())))
    Th0,_=fit_T_k(dh,iters=0+1)
    xs=np.geomspace(1200,4000,12)
    print('T0 (nonHC) vs Th (HC,H1) ratio at x:',np.round(Th(xs)/T0(xs),3))
    print('   (HC T fit with k allowed; k mean absorbed) overlap-range ratio')
    # without k: pooled curves
    Tn_h=fit_T(np.concatenate([dh[n][0] for n in hc]),np.concatenate([dh[n][1] for n in hc]))
    print('   no-k HC-only T / nonHC no-k T:',np.round(Tn_h(xs)/Tn(xs),3))
    # H0 comparison no-k: HC T on raw Y
    dh0=pack(hc,v,lambda s:s[f'{v}_Ymean']); Th_0=fit_T(np.concatenate([dh0[n][0] for n in hc]),np.concatenate([dh0[n][1] for n in hc]))
    xs0=np.geomspace(560,2000,10); print('   H0 (no HLTAB): HC curve vs Y / nonHC curve:',np.round(Th_0(xs0)/Tn(xs0),3))
    json.dump({'lx':list(map(float,T0.lx)),'lj':list(map(float,T0.lj)),'k':k0},open(f'T0_{v}.json','w'))
    json.dump({'lx':list(map(float,Th.lx)),'lj':list(map(float,Th.lj)),'k':kh},open(f'Th_{v}.json','w'))
