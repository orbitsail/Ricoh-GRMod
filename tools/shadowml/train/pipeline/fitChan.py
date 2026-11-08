"""Evidence for camera-RGB vs matrixed-RGB: if the tone curve acts per channel after the matrix, one curve should fit R,G,B."""
from tfit import *
VARS=('cam','mat','hyb')
for grpname,ids in (('nonHC',[n for n in IDS if not HC[n]]),('HC',[n for n in IDS if HC[n]]),('all',IDS)):
    for v in VARS:
        X=[[],[],[]];Jv=[[],[],[]]
        for n in ids:
            s=STAT[n]; m=flatmask(s,v,xmin=0)&(s[f'{v}_Ymean']>=560)
            for c in range(3):
                x=s[f'{v}_ch'][c][m]; j=s['Jch'][c][m]; ok=(x>150)&(j>1e-4)&(x<4090)
                X[c].append(x[ok]);Jv[c].append(j[ok])
        X=[np.concatenate(a) for a in X];Jv=[np.concatenate(a) for a in Jv]
        Tc=[fit_T(X[c],Jv[c],lo=150) for c in range(3)]
        Xa=np.concatenate(X);Ja=np.concatenate(Jv); Tall=fit_T(Xa,Ja,lo=150)
        sep=np.concatenate([np.log(Tc[c](X[c]))-np.log(Jv[c]) for c in range(3)]).std()
        com=np.concatenate([np.log(Tall(X[c]))-np.log(Jv[c]) for c in range(3)]).std()
        xs=np.geomspace(300,3500,6)
        print(grpname,v,'rms separate T per channel %.4f | common T %.4f'%(sep,com),'| per-channel T ratio R/G, B/G at x:',np.round(Tc[0](xs)/Tc[1](xs),2),np.round(Tc[2](xs)/Tc[1](xs),2))
