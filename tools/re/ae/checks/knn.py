# SPDX-License-Identifier: GPL-2.0-only
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import json, numpy as np, sys
import _paths
sys.path.insert(0,'.')
fk=[r for r in json.load(open('fk_table.json')) if 'error' not in r and len(r['experts'])==5 and r['ev100'] is not None]
gr=json.load(open('gr_table.json'))
green=_paths.EXCLUDE
sel=[r for r in gr if r['ec']==0 and r['name'] not in green]
print('nFK',len(fk),'nGRsel',len(sel))
S=['s_q2','s_q10','s_q25','s_q50','s_q75','s_q90','s_q98','s_std','s_rng','s_top_minus_bottom','s_centre_minus_all','s_cell_std','s_cell_max_minus_mean']
X=lambda rows:np.array([[r[f] for f in S]+[r['ev100']] for r in rows])
Xf,Xg=X(fk),X(sel); mu,sd=Xf.mean(0),Xf.std(0); Zf=(Xf-mu)/sd; Zg=(Xg-mu)/sd
yf=np.array([np.mean([e['L_p50'] for e in r['experts'].values()]) for r in fk])
Lg=np.array([r['disp']['L_p50'] for r in sel])
# domain: per-feature z of GR, and NN distance vs FiveK's own leave-one-out NN distance
D=np.sqrt(((Zg[:,None]-Zf[None])**2).sum(-1)); Dff=np.sqrt(((Zf[:,None]-Zf[None])**2).sum(-1)); np.fill_diagonal(Dff,np.inf)
print('NN dist GR median %.2f max %.2f | FiveK self-NN median %.2f p95 %.2f'%(np.median(D.min(1)),D.min(1).max(),np.median(Dff.min(1)),np.percentile(Dff.min(1),95)))
print('GR mean z per feature', dict(zip(S+['ev100'],np.round(Zg.mean(0),2))))
print('ev100 FK p5/50/95',np.percentile(Xf[:,-1],[5,50,95]).round(1),'GR',np.percentile(Xg[:,-1],[5,50,95]).round(1))
for k in (15,):
    nn=np.argsort(D,1)[:,:k]; pred=yf[nn].mean(1); gap=pred-Lg
    print('k=%d gap L* mean %+.2f sd %.2f median %+.2f  stops@17 mean %+.2f sd %.2f'%(k,gap.mean(),gap.std(ddof=1),np.median(gap),gap.mean()/17,gap.std(ddof=1)/17))
    g=json.load(open('gap_by_expert.json')); sl=dict(zip(g['names'],g['slope']))
    s=np.array([sl[r['name']] for r in sel]); st=gap/np.maximum(s,6)
    print('  local slope mean %.1f; stops via local slope mean %+.2f sd %.2f median %+.2f'%(s.mean(),st.mean(),st.std(ddof=1),np.median(st)))
    print('  n positive (experts brighter)', (gap>0).sum(),'/',len(gap))
    # without ev100
    Dn=np.sqrt(((Zg[:,None,:-1]-Zf[None,:,:-1])**2).sum(-1)); nn2=np.argsort(Dn,1)[:,:k]; g2=yf[nn2].mean(1)-Lg
    print('  shape-only kNN gap mean %+.2f sd %.2f'%(g2.mean(),g2.std(ddof=1)))
    for k2 in (5,30,60):
        nn3=np.argsort(D,1)[:,:k2]; print('  k=%d gap mean %+.2f'%(k2,(yf[nn3].mean(1)-Lg).mean()))
    print('  baseline: FiveK mean expert median L* %.1f, GR sel JPEG median L* mean %.1f'%(yf.mean(),Lg.mean()))
# anchoring check: does experts' output depend on as-shot level once scene shape+ev100 known?
from sklearn.linear_model import LinearRegression
lvl=np.array([r['lvl_mean'] for r in fk])
A=np.c_[Zf]; m1=LinearRegression().fit(A,yf); res=yf-m1.predict(A)
m2=LinearRegression().fit(np.c_[A,lvl],yf)
print('anchoring: partial slope of expert L* on as-shot level (stops) given shape+ev100: %.2f L*/stop; corr(resid,lvl)=%.2f'%(m2.coef_[-1],np.corrcoef(res,lvl)[0,1]))
# where GR sits in as-shot level
gl=np.array([r['lvl_mean'] for r in sel]); print('as-shot lvl_mean FK median %.2f, GR sel median %.2f'%(np.median(lvl),np.median(gl)))
# leakage: can SHAPE+ev100 predict lvl_mean?
from sklearn.model_selection import cross_val_predict, KFold
from sklearn.ensemble import HistGradientBoostingRegressor
p=cross_val_predict(HistGradientBoostingRegressor(max_depth=3,max_iter=200),Zf,lvl,cv=KFold(5,shuffle=True,random_state=0))
print('CV R2 of as-shot level from SHAPE+ev100: %.2f'%(1-((lvl-p)**2).sum()/((lvl-lvl.mean())**2).sum()))
p=cross_val_predict(HistGradientBoostingRegressor(max_depth=3,max_iter=200),Zf[:,:-1],lvl,cv=KFold(5,shuffle=True,random_state=0))
print('CV R2 of as-shot level from SHAPE only: %.2f'%(1-((lvl-p)**2).sum()/((lvl-lvl.mean())**2).sum()))
