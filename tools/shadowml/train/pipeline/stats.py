"""Pass A: block (360x240) statistics per image, per variant (cam/mat) and strength."""
from common import *
import cv2, time, shadow_ref as S
cv2.setNumThreads(2)
SL=[0,256,512,1024]
BW,BH=360,240
W=np.array([77,150,29],np.float32)/256
def ds(a): return cv2.resize(a,(BW,BH),interpolation=cv2.INTER_AREA)
def hcflag(nm): return int(SUMMARY[nm]['drx'][:2],16)
TABS={(s,h):np.array(S.table(s,h),np.float32)/4096 for s in SL for h in (0,1)}
def variant_rgb(cam,M,v):
    if v=='cam': return cam
    return np.clip(cam@M.T.astype(np.float32),0,4095)   # 'mat' and 'hyb' (hyb = matrixed colour, index from camera RGB)
def lumidx(rgb):
    Y=rgb@W
    i=np.clip(np.floor(Y).astype(np.int32)>>2,0,1023)
    return Y,i
def vfield(vp,H=2064,W=3096):
    py,px=np.mgrid[0:H,0:W].astype(np.float32)
    r2=((px+0.5)/W*2-1)**2+((py+0.5)/H*2-1)**2
    u=r2/2
    return np.exp(vp[0]*u+vp[1]*u*u).astype(np.float32)
def run(nm,vp=None,tag='stats'):
    out_p=f'{CACHE}/{nm}_{tag}.npz'
    if os.path.exists(out_p): return
    cam=np.load(f'{CACHE}/{nm}_cam.npy')
    if vp is not None: cam=np.minimum(cam*vfield(vp)[...,None],4095)
    j=np.load(f'{CACHE}/{nm}_jpg.npy').astype(np.float32)
    M,Tk=cam2srgb_matrix(nm); hc=hcflag(nm)
    o={'hc':hc}
    jl=j@np.array([.2126,.7152,.0722],np.float32)
    o['J']=ds(jl); o['Jch']=np.stack([ds(j[...,c]) for c in range(3)])
    # camera-Y-weighted JPEG luma too (601-ish weights) for comparison
    o['J601']=ds(j@W)
    for v in ('cam','mat','hyb'):
        rgb=variant_rgb(cam,M,v); Y,i=lumidx(rgb)
        XL=np.clip(cam@M.T.astype(np.float32),0,4095)@np.array([.2126,.7152,.0722],np.float32)
        if v=='hyb': i=lumidx(cam)[1]
        o[f'{v}_idxmean']=ds(i.astype(np.float32)); o[f'{v}_f_lt130']=ds((i<130).astype(np.float32)); o[f'{v}_f_ge140']=ds((i>=140).astype(np.float32))
        o[f'{v}_Ymean']=ds(Y)
        for s in SL:
            g=TABS[(s,hc)][i]
            x=np.minimum(Y*g,4095)
            o[f'{v}_x_{s}']=ds(x); o[f'{v}_x2_{s}']=ds(x*x)
            o[f'{v}_xl_{s}']=ds(np.minimum(XL*g,4095))
            if s==0:
                o[f'{v}_ch']=np.stack([ds(np.minimum(rgb[...,c]*g,4095)) for c in range(3)])
    np.savez_compressed(out_p,**o)
    print(nm,flush=True)
if __name__=='__main__':
    import json,sys
    tag=sys.argv[1]; vpf=sys.argv[2] if len(sys.argv)>2 else None
    vps=json.load(open(vpf)) if vpf else {}
    for p in (STUDIO if (len(sys.argv)>3 and sys.argv[3]=='studio') else DNGS):
        nm=os.path.basename(p)[:-4]
        run(nm,vps.get(nm) or list(vps.values())[0],tag)
