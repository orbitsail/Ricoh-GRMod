import sys; sys.dont_write_bytecode=True; sys.path.insert(0,'.')
import numpy as np, train as TR, sim
from sklearn.model_selection import GroupKFold
rows=TR.dataset(); SG=TR.SG
for r in rows:
    c=r['costC']; r['rng']=c.max()-c.min()
    r['soft']={tau:float((SG*np.exp(-(c-c.min())/ (tau*max(c.max()-c.min(),1e-6)))).sum()/np.exp(-(c-c.min())/(tau*max(c.max()-c.min(),1e-6))).sum()) for tau in (0.1,0.3)}
X=np.array([[r['F'][i] for i in TR.USE] for r in rows],float); g=[r['cam'] for r in rows]
def run(tag,target,wt,cfg):
    y=np.array(target); w=np.array(wt); pred=np.zeros(len(rows))
    for tr,te in GroupKFold(5).split(X,y,g):
        m=TR.GradientBoostingRegressor(n_estimators=cfg['n'],max_depth=cfg['d'],learning_rate=cfg['lr'],min_samples_leaf=cfg['leaf'],subsample=0.7,loss=cfg.get('loss','squared_error'),random_state=0).fit(X[tr],y[tr],sample_weight=w[tr]); pred[te]=np.clip(m.predict(X[te]),0,2048)
    o=TR.report(rows,pred,tag,2*np.array([r['sC'] for r in rows])); print('%-28s regretC %.4f gain %+.4f regret5 %.4f rmse %.0f rho %.2f meanS %.0f'%(tag,o['regretC'],o['gain_vs_s0'],o['regret_5exp'],o['rmse_t'],o['spearman'],o['mean_s']))
sC=[2*r['sC'] for r in rows]; one=np.ones(len(rows)); rng=[r['rng'] for r in rows]
for cfg in (dict(n=60,d=2,lr=0.08,leaf=10),dict(n=100,d=3,lr=0.05,leaf=20)):
    print(cfg)
    run('sC unweighted',sC,one,cfg)
    run('sC w=range',sC,rng,cfg)
    for tau in (0.1,0.3):
        run('soft%.1f unweighted'%tau,[2*r['soft'][tau] for r in rows],one,cfg)
        run('soft%.1f w=range'%tau,[2*r['soft'][tau] for r in rows],rng,cfg)
