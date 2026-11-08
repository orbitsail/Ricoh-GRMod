"""Pass 1: per DNG -> half-res camera RGB (12-bit scale, black-subtracted, camera WB applied, clipped) and half-res linear-sRGB JPEG. cache/<id>_cam.npy, _jpg.npy (float16, HxWx3 3096x2064)."""
from common import *
import rawpy, io, cv2
from PIL import Image
cv2.setNumThreads(2)
def extract(p,save=True):
    nm=os.path.basename(p)[:-4]
    if save and os.path.exists(f'{CACHE}/{nm}_jpg.npy'): return
    r=rawpy.imread(p)
    s=r.sizes; assert r.raw_pattern.tolist()==[[0,1],[3,2]]
    raw=r.raw_image
    top,left=s.crop_top_margin,s.crop_left_margin; h,w=s.crop_height,s.crop_width
    c=raw[top:top+h,left:left+w].astype(np.float32)
    bl=np.array(r.black_level_per_channel,np.float32)  # all 64
    wl=float(r.white_level)
    x=np.clip((c-bl[0])/(wl-bl[0]),0,1)*4095.0   # 12-bit relative to white
    R=x[0::2,0::2]; G=(x[0::2,1::2]+x[1::2,0::2])*0.5; B=x[1::2,1::2]
    wp=SUMMARY[nm]['wp']; gr,gb=wp[0]/8192.0, wp[3]/8192.0
    cam=np.stack([np.minimum(R*gr,4095),G,np.minimum(B*gb,4095)],-1)
    if save: np.save(f'{CACHE}/{nm}_cam.npy',cam.astype(np.float32))
    d,t,out=read_all(p); rec=out['_ifds'][2][2]
    j=d[rec['StripOffsets']:rec['StripOffsets']+rec['StripByteCounts']]
    im=np.asarray(Image.open(io.BytesIO(j)).convert('RGB'))
    lin=srgb2lin(im/255.0)
    lin=cv2.resize(lin,(w//2,h//2),interpolation=cv2.INTER_AREA)
    if not save: return cam,lin
    np.save(f'{CACHE}/{nm}_jpg.npy',lin.astype(np.float16))
    print(nm,cam.shape,flush=True)
if __name__=='__main__':
    os.makedirs(CACHE,exist_ok=True)
    for p in DNGS: extract(p)
