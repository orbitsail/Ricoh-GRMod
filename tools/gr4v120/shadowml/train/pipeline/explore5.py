from tfit import *
import cv2
v='cam'
for nm in ['0459402554','8247413060','5988854121','4024978768','9182216745']:
    s=STAT[nm]; x=s[f'{v}_x_0']; j=s['J']; m=flatmask(s,v,xmin=560)
    lx=np.log(np.maximum(x,1)); lj=np.log(np.maximum(j,1e-4))
    # basis: poly in lx (deg 4) ; plus blurred lx
    def design(extra):
        cols=[lx[m]**p for p in range(5)]+[e[m] for e in extra]
        return np.stack(cols,1)
    base=design([]); co=np.linalg.lstsq(base,lj[m],rcond=None)[0]; r0=(lj[m]-base@co).std()
    out=[('base',round(r0,3))]
    for sig in (4,10,25,60):
        b=cv2.GaussianBlur(lx.astype(np.float32),(0,0),sig)
        A=design([b]); co=np.linalg.lstsq(A,lj[m],rcond=None)[0]; out.append((sig,round((lj[m]-A@co).std(),3),round(co[-1],2)))
    # radial
    yy,xx=np.mgrid[0:240,0:360]; rr=(((xx-180)/180)**2+((yy-120)/120)**2)
    A=design([rr]); co=np.linalg.lstsq(A,lj[m],rcond=None)[0]; out.append(('rad',round((lj[m]-A@co).std(),3),round(co[-1],2)))
    print(nm,out)
