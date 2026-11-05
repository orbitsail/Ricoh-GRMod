# SPDX-License-Identifier: GPL-2.0-only
import numpy as np, json, glob
from scipy.stats import spearmanr
def lg(a): return np.log2(np.maximum(a.astype(np.float64),2**-10))
out=[]
for f in sorted(glob.glob('gr/*.npz')):
    z=np.load(f); m=json.loads(str(z['meta_json'])); a=lg(z['raw_y']); b=lg(z['jpg_y'])
    variants={'same':b,'flipLR':b[:,::-1],'flipUD':b[::-1],'rot180':b[::-1,::-1]}
    r={k:spearmanr(a.ravel(),v.ravel())[0] for k,v in variants.items()}
    # shift test: best integer shift within +-3 px
    best=(0,0,-2)
    H,W=a.shape
    for dy in range(-3,4):
        for dx in range(-3,4):
            aa=a[3+dy:H-3+dy,3+dx:W-3+dx]; bb=b[3:H-3,3:W-3]
            c=np.corrcoef(aa.ravel(),bb.ravel())[0,1]
            if c>best[2]: best=(dy,dx,c)
    out.append((m['name'],m['orient'],a.shape,z['raw_g'].shape,m['jpeg_size'],m['raw_size'],round(r['same'],3),round(max(r['flipLR'],r['flipUD'],r['rot180']),3),best[:2],round(best[2],3)))
for o in out: print(*o)
