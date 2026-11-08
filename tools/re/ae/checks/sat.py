# SPDX-License-Identifier: GPL-2.0-only
import rawpy, numpy as np, json
fs=[l.strip() for l in open('grfiles.txt')]
gr={r['name']:r for r in json.load(open('gr_table.json'))}
for p in fs:
    with rawpy.imread(p) as r:
        img=r.raw_image_visible; c=r.raw_colors_visible; w=r.white_level; bl=r.black_level_per_channel
        mx=[int(img[c==k].max()) for k in range(3)]
        top=[int((img[c==k]>=0.98*(w-bl[k])+bl[k]).sum()) for k in range(3)]
    n=[k for k in gr if k in p.split('/')[-1]]
    print(p.split('/')[-1][-20:], 'white',w,'bl',bl[:2],'max',mx,'n>=98%',top, n and gr[n[0]]['lvl_clip_frac'])
