"""C. Model: small GBRT -> t = 2 s, 5-fold CV grouped by camera model, baselines, integer quantisation, export.
Targets: 'C' (expert C, as specified) and 'M' (median of the five experts, reported as an alternative).  Re-runnable on whatever labels.json holds."""
import sys, os, json
sys.dont_write_bytecode=True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, sim, make_labels as ML
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import GroupKFold
from scipy.stats import spearmanr
ref=sim.ref; SR=sim.SR; SG=ML.SGRID
NAMES=ref.NAMES
EXCL={'mode','rg','bg'}              # mode is constant in training; rg/bg need real scene colour, which the FiveK sim does not have
USE=[i for i,n in enumerate(NAMES) if n not in EXCL]
def dataset():
    R=json.load(open(sim.MODEL+'/labels.json')); rows=[]
    for r in R:
        for v in r['variants']:
            L=v['labels']
            if 'c' not in L: continue
            costs={l:np.array(L[l]['cost']) for l in L}
            sM=float(np.median([L[l]['s'] for l in L])) if len(L)==5 else np.nan
            rows.append(dict(name=r['name'],cam=r['camera'],hl=v['hl'],iso=v['iso'],F=v['F'],sC=L['c']['s'],sM=sM,costC=costs['c'],costs=costs,idx=ref.__dict__.get('x',0)))
    return rows
def cost_at(curve,s):      # interpolate the stored cost curve at (possibly non-grid) strength s
    return np.interp(s,SG,curve)
def stock_t(r):
    """stock rule on the G plane (not the wrapped sums): strength() of the firmware reference with y = G plane; t = its r3 (the pre-cap, pre-gain strength)."""
    d=r['planes']; y=d[1].astype(np.uint32); iso_idx=r['F'][NAMES.index('idx')]
    s,lvl,info=SR.strength(y,0,r['hl'],iso_idx); return info.get('r3',0)
def placeholder_t(r): return 512 if r['F'][NAMES.index('d01')]>4*256 else 0
def cap_s(t,idx): return np.minimum(t,SR.TC[min(int(idx),0x60)])/2.0
def fit(X,y,cfg,seed=0):
    m=GradientBoostingRegressor(n_estimators=cfg['n'],max_depth=cfg['d'],learning_rate=cfg['lr'],min_samples_leaf=cfg['leaf'],subsample=0.7,loss=cfg.get('loss','squared_error'),random_state=seed)
    return m.fit(X,y)
CFGS=[dict(n=60,d=2,lr=0.08,leaf=10),dict(n=100,d=3,lr=0.05,leaf=10),dict(n=100,d=3,lr=0.05,leaf=20),dict(n=100,d=4,lr=0.04,leaf=15),dict(n=100,d=2,lr=0.05,leaf=20,loss='huber')]

def cv_eval(rows,target,cfg,planes_ok=True,nf=5):
    X=np.array([[r['F'][i] for i in USE] for r in rows],float); y=np.array([2*r[target] for r in rows],float)
    g=[r['cam'] for r in rows]; pred=np.zeros(len(rows)); const_best=np.zeros(len(rows)); const_mean=np.zeros(len(rows))
    for tr,te in GroupKFold(nf).split(X,y,g):
        m=fit(X[tr],y[tr],cfg); pred[te]=np.clip(m.predict(X[te]),0,2048)
        const_mean[te]=y[tr].mean()
        cs=sum(rows[i]['costC'] for i in tr); const_best[te]=2*SG[int(np.argmin(cs))]   # constant that minimises the summed training cost
    return X,y,pred,const_best,const_mean
def report(rows,t_pred,name,tgt_true):
    sp=np.array([cap_s(t,r['F'][NAMES.index('idx')]) for t,r in zip(t_pred,rows)])
    cC=np.array([cost_at(r['costC'],s) for s,r in zip(sp,rows)]); c0=np.array([r['costC'][0] for r in rows]); cm=np.array([r['costC'].min() for r in rows])
    # average over all five experts (images with five)
    ce=np.array([np.mean([cost_at(c,s) for c in r['costs'].values()]) - np.mean([c.min() for c in r['costs'].values()]) for s,r in zip(sp,rows)])
    rm=np.sqrt(np.mean((2*sp-tgt_true)**2)); rho=spearmanr(t_pred,tgt_true).statistic if np.std(t_pred)>0 else float('nan')
    out=dict(name=name,rmse_t=rm,spearman=rho,regretC=float((cC-cm).mean()),gain_vs_s0=float((c0-cC).mean()),regret_5exp=float(ce.mean()),mean_s=float(sp.mean()))
    return out
if __name__=='__main__':
    rows=dataset()
    # planes for the stock-rule baseline: regenerate from the scene (cheap)
    import glob
    cache={}
    for r in rows:
        if r['name'] not in cache:
            cache[r['name']]=sim.fk_load.load(sim.SP+'/shadowml/fivek/%s.npz'%r['name'])
        d=cache[r['name']]; kst,_=sim.scene_info(d); r['planes']=sim.planes(d,kst,r['hl'])[0]
        if len(cache)>40: cache.clear()
    print('rows',len(rows),'images',len({r['name'] for r in rows}),'camera groups',len({r['cam'] for r in rows}))
    for target in ('sC','sM'):
        rr=[r for r in rows if not np.isnan(r[target])]
        print('\n=== target',target,'(expert C)' if target=='sC' else '(median of five)', 'n=',len(rr))
        best=None
        for cfg in CFGS:
            X,y,pred,cb,cm=cv_eval(rr,target,cfg)
            res=report(rr,pred,str(cfg),y); print('  cfg',cfg,'rmse %.0f spearman %.2f regretC %.4f gain %.4f regret5 %.4f'%(res['rmse_t'],res['spearman'],res['regretC'],res['gain_vs_s0'],res['regret_5exp']))
            if best is None or res['regretC']<best[0]['regretC'] if target=='sC' else (best is None or res['regret_5exp']<best[0]['regret_5exp']): best=(res,cfg,pred,cb,cm,y)
        res,cfg,pred,cb,cm,y=best; print('  chosen',cfg)
        base={'model(GBRT)':pred,'const (min train cost)':cb,'const (train mean t)':cm,'stock rule on G plane':np.array([min(stock_t(r),2048) for r in rr],float),
              'placeholder (d01>4 stops -> Low)':np.array([placeholder_t(r) for r in rr],float),'zero (no correction)':np.zeros(len(rr))}
        tbl=[]
        for k,v in base.items():
            o=report(rr,v,k,y); tbl.append(o); print('  %-34s rmse_t %5.0f  spearman %5.2f  regretC %.4f  gain_vs_s0 %+.4f  regret5 %.4f  mean s %.0f'%(k,o['rmse_t'],o['spearman'] if o['spearman']==o['spearman'] else 0,o['regretC'],o['gain_vs_s0'],o['regret_5exp'],o['mean_s']))
        json.dump(dict(cfg=cfg,table=tbl,n=len(rr)),open(sim.MODEL+'/cv_%s.json'%target,'w'),indent=1,default=float)
