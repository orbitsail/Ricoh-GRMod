from tfit import *
nonhc=[n for n in IDS if not HC[n]]; hc=[n for n in IDS if HC[n]]
print(len(nonhc),len(hc))
for v in ('cam','mat'):
    d=gather(nonhc,v,lambda s:s[f'{v}_x_0'],xmin=560)
    T0,k0=fit_T_k(d,iters=1)  # no k
    T,k=fit_T_k(d,iters=4)
    for nm in nonhc:
        x,j,_=d[nm]; r0=resid(T0,x,j); r=resid(T,x,j,k[nm])
        print(v,nm,len(x),'rms nok %.3f  rms k %.3f  k %.3f ISO %d'%(r0.std(),r.std(),k[nm],SUMMARY[nm]['iso']))
