from common import *
import cv2
def shifts(nm,n=4):
    cam=np.load(f'{CACHE}/{nm}_cam.npy'); j=np.load(f'{CACHE}/{nm}_jpg.npy').astype(np.float32)
    a=np.log(cam@np.array([77,150,29],np.float32)/256/4095+2e-3); b=np.log(j@np.array([.2126,.7152,.0722],np.float32)+2e-3)
    a=a-cv2.GaussianBlur(a,(0,0),6); b=b-cv2.GaussianBlur(b,(0,0),6)
    H,W=a.shape; out=np.zeros((n,n,3))
    th,tw=H//n,W//n
    win=cv2.createHanningWindow((tw,th),cv2.CV_32F)
    for i in range(n):
        for k in range(n):
            ta=a[i*th:(i+1)*th,k*tw:(k+1)*tw].astype(np.float32); tb=b[i*th:(i+1)*th,k*tw:(k+1)*tw].astype(np.float32)
            (dx,dy),resp=cv2.phaseCorrelate(ta,tb,win); out[i,k]=(dx,dy,resp)
    return out
if __name__=='__main__':
    import sys
    for nm in sys.argv[1:]:
        o=shifts(nm); print(nm); print(np.round(o[...,0],2)); print(np.round(o[...,1],2)); print(np.round(o[...,2],2))
