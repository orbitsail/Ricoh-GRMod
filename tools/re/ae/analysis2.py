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
SHAPE=['s_q2','s_q10','s_q25','s_q50','s_q75','s_q90','s_q98','s_std','s_rng','s_top_minus_bottom','s_centre_minus_all','s_cell_std','s_cell_max_minus_mean']
CLIP=['lvl_clip_frac','lvl_clip_blocks','lvl_f_gt_half','lvl_f_gt_q']
TARG=['L_mean','L_p10','L_p25','L_p50','L_p75','L_p90','L_p99']
X_of=lambda rows,fs: np.array([[r[f] for f in fs]+[r['ev100']] for r in rows],float)
cons=lambda rows,t: np.array([np.mean([e[t] for e in r['experts'].values()]) for r in rows])
def fit_predict(fs):
    Xf=X_of(fk,fs); Xg=X_of(gr,fs); out={}
    for t in TARG:
        ms=[]
        for seed in range(5):   # small ensemble over seeds/subsamples
            rng=np.random.RandomState(seed); idx=rng.choice(len(fk),int(0.85*len(fk)),replace=False)
            m=HistGradientBoostingRegressor(max_depth=3,learning_rate=0.05,max_iter=250,min_samples_leaf=20,random_state=seed).fit(Xf[idx],cons(fk,t)[idx]); ms.append(m.predict(Xg))
        out[t]=np.mean(ms,0)
    return out
P1=fit_predict(SHAPE); P2=fit_predict(SHAPE+CLIP)
def Linv(L):
    f=(L+16)/116.0
    return np.where(f>0.206893, f**3, (f-16/116.0)/7.787)
def emp_curve(name):
    z=np.load('gr/%s.npz'%name); ry=z['raw_y'].astype(np.float64); jy=z['jpg_y'].astype(np.float64)
    H,W=ry.shape; m=(slice(int(.12*H),int(.88*H)),slice(int(.12*W),int(.88*W)))
    a=np.log2(np.maximum(ry[m],2**-10)).ravel(); b=np.log2(np.maximum(jy[m],2**-10)).ravel()
    # monotone fit of display vs raw (log-log); use binned medians then isotonic
    bins=np.arange(-10,0.01,0.25); xs=[];ys=[]
    for lo in bins:
        s=(a>=lo)&(a<lo+0.25)
        if s.sum()>40: xs.append(np.median(a[s])); ys.append(np.median(b[s]))
    xs=np.array(xs); ys=np.array(ys)
    iso=IsotonicRegression(increasing=True).fit(xs,ys)
    return xs,iso.predict(xs),np.median(a)
rows=[]
for i,r in enumerate(gr):
    xs,ys,lmed=emp_curve(r['name'])
    d=r['disp']
    out={'name':r['name'],'ec':r['ec'],'hc':r['hc'],'iso':r['iso'],'ev100':r['ev100']}
    # empirical raw->display mapping near the median: stops of raw needed to reach target display median
    def stops_to(Ltarget):
        Yt=float(Linv(Ltarget)); lt=np.log2(max(Yt,1e-6))
        # invert the curve (ys ascending in xs)
        if lt<=ys[0] or lt>=ys[-1]: return float('nan')
        return float(np.interp(lt,ys,xs)-lmed)
    for tag,P in (('A',P1),('B',P2)):
        out['pred_p50_'+tag]=float(P['L_p50'][i]); out['pred_mean_'+tag]=float(P['L_mean'][i])
        out['gap_p50_'+tag]=float(P['L_p50'][i]-d['L_p50'])      # + : experts want it brighter
        out['gap_mean_'+tag]=float(P['L_mean'][i]-d['L_mean'])
        out['gap_p10_'+tag]=float(P['L_p10'][i]-d['L_p10']); out['gap_p25_'+tag]=float(P['L_p25'][i]-d['L_p25']); out['gap_p75_'+tag]=float(P['L_p75'][i]-d['L_p75'])
        out['gap_p90_'+tag]=float(P['L_p90'][i]-d['L_p90']); out['gap_p99_'+tag]=float(P['L_p99'][i]-d['L_p99'])
        out['stops_p50_'+tag]=stops_to(P['L_p50'][i])
    out['L_p50']=d['L_p50']; out['L_mean']=d['L_mean']; out['L_p99']=d['L_p99']
    rows.append(out)
json.dump(rows,open('gr_gap.json','w'),indent=0)
green=_paths.EXCLUDE
def summ(sel,label,tag='A'):
    s=[r for r in rows if sel(r)]
    if not s: return
    for k in ('gap_p10','gap_p25','gap_p50','gap_p75','gap_p90','gap_p99','gap_mean','stops_p50'):
        v=np.array([r[k+'_'+tag] for r in s]); v=v[~np.isnan(v)]
        print('   %-10s n=%2d mean %+6.2f  sd %5.2f  median %+6.2f  (sem %.2f)'%(k,len(v),v.mean(),v.std(ddof=1),np.median(v),v.std(ddof=1)/np.sqrt(len(v))))
for tag,name in (('A','features: scene shape + brightness only'),('B','plus clipping features')):
    print('\n######## model',tag,name)
    print(' -- EC=0, not the green-bug JPEGs (JPEG is trustworthy):')
    summ(lambda r:r['ec']==0 and r['name'] not in green,'',tag)
    print(' -- EC=0 HC-on only:'); summ(lambda r:r['ec']==0 and r['name'] not in green and r['hc']==1,'',tag)
    print(' -- EC=0 HC-off only:'); summ(lambda r:r['ec']==0 and r['name'] not in green and r['hc']==0,'',tag)
print('\nper image (model A): name ec hc | camera p50 -> experts p50 (gap) | stops needed | camera mean -> experts mean')
for r in sorted(rows,key=lambda r:-r['gap_p50_A']):
    print('%-11s %+4.1f %d | %5.1f -> %5.1f (%+5.1f) | %+5.2f st | %5.1f -> %5.1f %s'%(r['name'],r['ec'],r['hc'],r['L_p50'],r['pred_p50_A'],r['gap_p50_A'],r['stops_p50_A'],r['L_mean'],r['pred_mean_A'],'(green JPEG)' if r['name'] in green else ''))
