# SPDX-License-Identifier: GPL-2.0-only
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sys, rawpy, numpy as np
import _paths; import tiff_min as tiff
fs=[l.strip() for l in open('grfiles.txt')]
for p in fs:
    if not any(k in p for k in _paths.PRIV['wl_names']): continue
    data,t,out=tiff.read_all(p); ifds={n:r for n,o,r in out['_ifds']}
    s=ifds['ifd0.sub0']
    with rawpy.imread(p) as r:
        img=r.raw_image_visible; c=r.raw_colors_visible
        g=img[(c==1)]
        v,n=np.unique(g[g>13000],return_counts=True); top=sorted(zip(n,v))[-3:]
        print(p[-14:], 'tag WL',s.get('WhiteLevel'),'BL',s.get('BlackLevel'),'rawpy wl',r.white_level,'bl',r.black_level_per_channel[:1],'G top values (count,val)',top)
