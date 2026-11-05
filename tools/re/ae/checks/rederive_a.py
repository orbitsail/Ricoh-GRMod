# SPDX-License-Identifier: GPL-2.0-only
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sys, glob, json, numpy as np, collections
import _paths; import fk_load
def L(Y):
    Y=np.clip(Y.astype(np.float64),0,1); return np.where(Y>(6/29)**3,116*np.cbrt(Y)-16,903.2963*Y)
fk={r['name']:r for r in json.load(open('fk_table.json')) if 'error' not in r}
gr={r['name']:r for r in json.load(open('gr_table.json'))}
files=sorted(glob.glob(_paths.FIVEK + '/*.npz'))
trc=collections.Counter(); ymax=[]
for f in files[::40]:
    d=fk_load.load(f)
    for l,e in d['experts'].items():
        trc[str(e.get('trc'))[:60]]+=1
        if e['y'] is not None: ymax.append(np.percentile(e['y'],99.9))
print(trc.most_common(5)); print('expert Y p99.9 quantiles', np.percentile(ymax,[5,50,95,100]))
for f in [files[3],files[500],files[999]]:
    d=fk_load.load(f); n=d['meta']['name']
    mine={l:np.median(L(e['y'])) for l,e in d['experts'].items() if e['y'] is not None}
    print(n, {l:round(v,2) for l,v in mine.items()}, '| table', {l:round(v['L_p50'],2) for l,v in fk[n]['experts'].items()})
for n in _paths.PRIV['rederive_names']:
    z=np.load('gr/%s.npz'%n); print(n, round(np.median(L(z['jpg_y'])),2), 'table', round(gr[n]['disp']['L_p50'],2), 'jpgY max',float(z['jpg_y'].max()))
