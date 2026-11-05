# SPDX-License-Identifier: GPL-2.0-only
import json, sys, numpy as np, warnings
warnings.filterwarnings('ignore')
from sklearn.ensemble import HistGradientBoostingRegressor, GradientBoostingRegressor
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import KFold, cross_val_predict
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
fk=[r for r in json.load(open('fk_table.json')) if 'error' not in r and len(r['experts'])==5 and r['ev100'] is not None]
gr=json.load(open('gr_table.json'))
SHAPE=['s_q2','s_q10','s_q25','s_q50','s_q75','s_q90','s_q98','s_std','s_rng','s_top_minus_bottom','s_centre_minus_all','s_cell_std','s_cell_max_minus_mean']
CLIP=['lvl_clip_frac','lvl_clip_blocks','lvl_f_gt_half','lvl_f_gt_q']
def X_of(rows, feats): return np.array([[r[f] for f in feats]+[r['ev100']] for r in rows],float)
TARG=['L_mean','L_p5','L_p10','L_p25','L_p50','L_p75','L_p90','L_p95','L_p99']
def cons(rows,t): return np.array([np.mean([e[t] for e in r['experts'].values()]) for r in rows])
def sd_between(rows,t): return np.array([np.std([e[t] for e in r['experts'].values()],ddof=1) for r in rows])
print('FiveK images', len(fk), '| GR images', len(gr))
print('target       mean   sd(over images)  inter-expert sd(mean over images)')
Y={t:cons(fk,t) for t in TARG}
for t in TARG: print('%-8s %7.1f %7.1f %7.1f'%(t,Y[t].mean(),Y[t].std(),sd_between(fk,t).mean()))
kf=KFold(5,shuffle=True,random_state=0)
res={}
for fs_name,fs in [('shape',SHAPE),('shape+clip',SHAPE+CLIP)]:
    X=X_of(fk,fs)
    print('\n== features:',fs_name)
    print('target   CV-R2(GB)  CV-RMSE(GB)  CV-R2(ridge)  RMSE(ridge)  baseline-sd')
    for t in TARG:
        y=Y[t]
        gb=HistGradientBoostingRegressor(max_depth=3,learning_rate=0.05,max_iter=250,min_samples_leaf=20,random_state=0)
        p=cross_val_predict(gb,X,y,cv=kf)
        rg=make_pipeline(StandardScaler(),RidgeCV(alphas=np.logspace(-2,3,20)))
        p2=cross_val_predict(rg,X,y,cv=kf)
        r2=lambda p:1-((y-p)**2).sum()/((y-y.mean())**2).sum()
        print('%-8s %6.2f %8.2f %12.2f %10.2f %10.2f'%(t,r2(p),np.sqrt(((y-p)**2).mean()),r2(p2),np.sqrt(((y-p2)**2).mean()),y.std()))
        res[(fs_name,t)]=(r2(p),np.sqrt(((y-p)**2).mean()))
json.dump({'%s|%s'%k:v for k,v in res.items()},open('cv_results.json','w'))
