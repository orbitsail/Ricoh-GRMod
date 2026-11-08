import sys, struct, json, os, glob
SP=__import__('os').environ.get('GRIV_WORK', '.')
sys.path.insert(0, SP+'/grdng'); sys.path.insert(0, SP+'/drange')
import numpy as np
from tiff import read_all
from mn import load_mn
PIPE=SP+'/shadowml/pipeline'
CACHE=PIPE+'/cache'
DNGS=sorted(glob.glob('/mnt/user-data/uploads/Downloads/*.dng'))
SUMMARY={r['id']:r for r in json.load(open(SP+'/grdng/ext/summary.json'))}
def srgb2lin(v):
    v=np.asarray(v,np.float32)
    return np.where(v<=0.04045, v/12.92, ((v+0.055)/1.055)**2.4).astype(np.float32)
def lin2srgb(v):
    v=np.clip(np.asarray(v,np.float32),0,None)
    return np.where(v<=0.0031308, v*12.92, 1.055*v**(1/2.4)-0.055).astype(np.float32)

M_SRGB2XYZ=np.array([[0.4124564,0.3575761,0.1804375],[0.2126729,0.7151522,0.0721750],[0.0193339,0.1191920,0.9503041]])
def cam2srgb_matrix(nm):
    """dcraw-style: wb'd camera RGB -> linear sRGB, using DNG ColorMatrix1/2 interpolated (mired) at the as-shot CCT."""
    d,t,out=read_all(dng_path(nm)); r=out['_ifds'][0][2]
    cm1=np.array(r['ColorMatrix1']).reshape(3,3); cm2=np.array(r['ColorMatrix2']).reshape(3,3)
    asn=np.array(r['AsShotNeutral'])
    T=5000.
    for _ in range(30):
        w=np.clip((1/T-1/6504.)/(1/2856.-1/6504.),0,1)
        cm=w*cm1+(1-w)*cm2
        X,Y,Z=np.linalg.inv(cm)@asn; x,y=X/(X+Y+Z),Y/(X+Y+Z)
        n=(x-0.3320)/(0.1858-y); T=np.clip(449*n**3+3525*n**2+6823.3*n+5520.33,2000,12000)
    A=cm@M_SRGB2XYZ; A=A/A.sum(1,keepdims=True)
    return np.linalg.inv(A), T

STUDIO=sorted(glob.glob('/mnt/user-data/uploads/Downloads/DPReview_GRIV/*.dng'))
def _studio_summary():
    for p in STUDIO:
        nm=os.path.basename(p)[:-4]
        data,t,out,mt,ents,vpos,cnt=load_mn(p); ifd0=out['_ifds'][0][2]
        ex=[r for (n_,o,r) in out['_ifds'] if n_.endswith('exif')][0]
        SUMMARY[nm]=dict(id=nm,wp=mt.value(ents[0x201]),drx='00000000',N=ex.get('FNumber'),iso=ex.get('ISO'),asn=ifd0.get('AsShotNeutral'))
_studio_summary()
def dng_path(nm):
    for p in DNGS+STUDIO:
        if os.path.basename(p)[:-4]==nm: return p
