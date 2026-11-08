# SPDX-License-Identifier: GPL-2.0-only
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, sys, numpy as np, warnings
import _paths
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import RidgeCV
from sklearn.neighbors import KNeighborsRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
fk=[r for r in json.load(open('fk_table.json')) if 'error' not in r and len(r['experts'])==5 and r['ev100'] is not None]
gr=json.load(open('gr_table.json'))
green=_paths.EXCLUDE
sel=[i for i,r in enumerate(gr) if r['ec']==0 and r['name'] not in green]
SHAPE=['s_q2','s_q10','s_q25','s_q50','s_q75','s_q90','s_q98','s_std','s_rng','s_top_minus_bottom','s_centre_minus_all','s_cell_std','s_cell_max_minus_mean']
def X_of(rows,fs,ev=True): return np.array([[r[f] for f in fs]+([r['ev100']] if ev else []) for r in rows],float)
def cons(rows,t,letters=None): return np.array([np.mean([e[t] for l,e in r['experts'].items() if letters is None or l in letters]) for r in rows])
Ljpg=np.array([gr[i]['disp']['L_p50'] for i in sel]); Lmean=np.array([gr[i]['disp']['L_mean'] for i in sel])
def run(name, mk, fs, ev, t='L_p50', letters=None):
    Xf=X_of(fk,fs,ev); Xg=X_of([gr[i] for i in sel],fs,ev); y=cons(fk,t,letters)
    ps=[mk(s).fit(Xf,y).predict(Xg) for s in range(3)]
    p=np.mean(ps,0); ref=Ljpg if t=='L_p50' else Lmean
    gap=p-ref
    print('%-44s %-7s mean gap %+5.1f L*  sd %4.1f  (sem %.1f)'%(name,t,gap.mean(),gap.std(ddof=1),gap.std(ddof=1)/np.sqrt(len(gap))))
    return gap
gb=lambda s: HistGradientBoostingRegressor(max_depth=3,learning_rate=0.05,max_iter=250,min_samples_leaf=20,random_state=s)
rf=lambda s: RandomForestRegressor(300,min_samples_leaf=5,random_state=s,n_jobs=1)
rg=lambda s: make_pipeline(StandardScaler(),RidgeCV(alphas=np.logspace(-2,3,20)))
kn=lambda s: make_pipeline(StandardScaler(),KNeighborsRegressor(25,weights='distance'))
print('n GR (EC=0, normal JPEG) =',len(sel))
for t in ('L_p50','L_mean'):
    run('GB shape+ev',gb,SHAPE,True,t); run('GB shape (no ev100)',gb,SHAPE,False,t)
    run('RF shape+ev',rf,SHAPE,True,t); run('Ridge shape+ev',rg,SHAPE,True,t); run('kNN25 shape+ev',kn,SHAPE,True,t)
print('\nper expert (GB shape+ev, p50):')
for l in 'abcde': run('expert '+l,gb,SHAPE,True,'L_p50',[l])
# dependence of gap on ev100 and contrast
gap=run('GB shape+ev (again)',gb,SHAPE,True)
ev=np.array([gr[i]['ev100'] for i in sel]); sd=np.array([gr[i]['s_std'] for i in sel]); hc=np.array([gr[i]['hc'] for i in sel])
print('\ncorr(gap, ev100)=%.2f  corr(gap, scene log-std)=%.2f  corr(gap,hc)=%.2f'%(np.corrcoef(gap,ev)[0,1],np.corrcoef(gap,sd)[0,1],np.corrcoef(gap,hc)[0,1]))
for lo,hi in ((0,9),(9,12),(12,20)):
    m=(ev>=lo)&(ev<hi)
    if m.sum()>1: print('ev100 in [%d,%d): n=%d mean gap %+5.1f sd %.1f'%(lo,hi,m.sum(),gap[m].mean(),gap[m].std(ddof=1)))
# Domain check: where do GR features sit within FiveK distribution?
Xf=X_of(fk,SHAPE,True); Xg=X_of([gr[i] for i in sel],SHAPE,True)
z=(Xg-Xf.mean(0))/Xf.std(0)
print('\nGR features |z| max per feature (vs FiveK):', np.round(np.abs(z).max(0),1))
print('FiveK ev100 pct 5/50/95:', np.round(np.percentile(Xf[:,-1],[5,50,95]),1), ' GR:', np.round(np.percentile(Xg[:,-1],[5,50,95]),1))
