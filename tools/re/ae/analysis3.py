# SPDX-License-Identifier: GPL-2.0-only
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, sys, numpy as np, warnings
import _paths
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
fk=[r for r in json.load(open('fk_table.json')) if 'error' not in r and len(r['experts'])==5 and r['ev100'] is not None]
gr=json.load(open('gr_table.json'))
green=_paths.EXCLUDE
sel=[i for i,r in enumerate(gr) if r['ec']==0 and r['name'] not in green]
SHAPE=['s_q2','s_q10','s_q25','s_q50','s_q75','s_q90','s_q98','s_std','s_rng','s_top_minus_bottom','s_centre_minus_all','s_cell_std','s_cell_max_minus_mean']
X_of=lambda rows: np.array([[r[f] for f in SHAPE]+[r['ev100']] for r in rows],float)
Xf=X_of(fk); Xg=X_of([gr[i] for i in sel])
# local slope of display L* per stop of EXPOSURE at the median pixel, from each image's own raw->JPEG relation
def local_slope(name):
    z=np.load('gr/%s.npz'%name); ry=z['raw_y'].astype(np.float64); jy=z['jpg_y'].astype(np.float64)
    H,W=ry.shape; m=(slice(int(.12*H),int(.88*H)),slice(int(.12*W),int(.88*W)))
    a=np.log2(np.maximum(ry[m],2**-10)).ravel(); b=np.log2(np.maximum(jy[m],2**-10)).ravel()
    xs=[];ys=[]
    for lo in np.arange(-10,0.01,0.25):
        s=(a>=lo)&(a<lo+0.25)
        if s.sum()>40: xs.append(np.median(a[s])); ys.append(np.median(b[s]))
    xs=np.array(xs); ys=IsotonicRegression(increasing=True).fit(xs,ys).predict(xs)
    lm=np.median(a)
    Lf=lambda lx: F.lstar(2.0**np.interp(lx,xs,ys))
    return float((Lf(lm+0.5)-Lf(lm-0.5))), float(lm)
sl=np.array([local_slope(gr[i]['name'])[0] for i in sel])
print('local slope L*/stop at median: mean %.1f  min %.1f  max %.1f'%(sl.mean(),sl.min(),sl.max()))
Ljpg=np.array([gr[i]['disp']['L_p50'] for i in sel])
res={}
for tag,letters in [('consensus','abcde')]+[(l,l) for l in 'abcde']:
    y=np.array([np.mean([r['experts'][l]['L_p50'] for l in letters]) for r in fk])
    ps=[]
    for s in range(5):
        idx=np.random.RandomState(s).choice(len(fk),int(.85*len(fk)),replace=False)
        ps.append(HistGradientBoostingRegressor(max_depth=3,learning_rate=0.05,max_iter=250,min_samples_leaf=20,random_state=s).fit(Xf[idx],y[idx]).predict(Xg))
    p=np.mean(ps,0); gap=p-Ljpg; stops=gap/np.maximum(sl,6.0)
    res[tag]=(gap,stops)
    print('%-9s GR median is darker(+)/brighter(-) than this expert would make it: mean %+5.2f L* = %+5.2f stops   sd %.2f stops   median %+5.2f'%(tag,gap.mean(),stops.mean(),stops.std(ddof=1),np.median(stops)))
# bootstrap CI for the consensus mean (resampling both the GR scenes and the FiveK training set)
rng=np.random.RandomState(1); bs=[]
y=np.array([np.mean([e['L_p50'] for e in r['experts'].values()]) for r in fk])
for b in range(60):
    idx=rng.choice(len(fk),len(fk),replace=True); m=HistGradientBoostingRegressor(max_depth=3,learning_rate=0.05,max_iter=250,min_samples_leaf=20,random_state=b).fit(Xf[idx],y[idx])
    gi=rng.choice(len(sel),len(sel),replace=True); st=((m.predict(Xg)-Ljpg)/np.maximum(sl,6.0))[gi]; bs.append(st.mean())
print('consensus mean stops: bootstrap 90%% interval [%+.2f, %+.2f]'%(np.percentile(bs,5),np.percentile(bs,95)))
# scatter vs experts' own spread: inter-expert sd of p50 in stops (using typical slope)
inter=np.array([np.std([e['L_p50'] for e in r['experts'].values()],ddof=1) for r in fk])
print('inter-expert sd of the median L*: %.1f L* = %.2f stops (typical slope %.0f L*/stop)'%(inter.mean(),inter.mean()/sl.mean(),sl.mean()))
json.dump({k:{'gap_L':list(map(float,v[0])),'stops':list(map(float,v[1]))} for k,v in res.items()}|{'names':[gr[i]['name'] for i in sel],'slope':list(map(float,sl))},open('gap_by_expert.json','w'))
# FiveK as-shot geometric-mean level vs GR (HC/EC corrected)
lvl=np.array([r['lvl_mean'] for r in fk]); print('\nFiveK as-shot mean-log level (Y, stops below white): median %.2f  p10 %.2f  p90 %.2f  sd %.2f'%(np.median(lvl),np.percentile(lvl,10),np.percentile(lvl,90),lvl.std()))
g=np.array([r['g_meanlog']+r['hc']-r['ec'] for r in gr if r['iso']<3200]); print('GR AE level HC/EC-corrected (G, stops below white): median %.2f p10 %.2f p90 %.2f sd %.2f'%(np.median(g),np.percentile(g,10),np.percentile(g,90),g.std(ddof=1)))
