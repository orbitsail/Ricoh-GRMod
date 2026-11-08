"""C (final). CV with the chosen configuration, baselines with bootstrap CIs, fit on all rows, integer quantisation, export.
Outputs: cv_final.json, model_C_trees.json / model_C.bin (expert-C target, the shipped model), model_M_trees.json / model_M.bin (median-of-five target, alternative)."""
import sys, os, json, struct
sys.dont_write_bytecode=True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, sim, train as TR
from sklearn.model_selection import GroupKFold
ref=sim.ref; NAMES=ref.NAMES; USE=TR.USE; SG=TR.SG
CFG={'C':dict(n=60,d=2,lr=0.08,leaf=10),'M':dict(n=100,d=2,lr=0.05,leaf=20,loss='huber')}
TGT={'C':'sC','M':'sM'}; LSCALE=16      # leaf units: 1/16 of t; mul = 65536/16
def weights(rows): return np.array([r['costC'].max()-r['costC'].min() for r in rows])+1e-6
def gbrt(X,y,w,cfg):
    return TR.GradientBoostingRegressor(n_estimators=cfg['n'],max_depth=cfg['d'],learning_rate=cfg['lr'],min_samples_leaf=cfg['leaf'],subsample=0.7,loss=cfg.get('loss','squared_error'),random_state=0).fit(X,y,sample_weight=w)
def to_trees(m,lr):
    """sklearn ensemble -> nested tuples for ref.build_blob; leaf = round(lr * value * 16); returns (off, trees)"""
    off=int(round(float(m.init_.predict(np.zeros((1,len(USE))))[0])))
    trees=[]
    for est in m.estimators_[:,0]:
        t=est.tree_
        def rec(n):
            if t.children_left[n]==-1: return ('leaf',int(round(lr*float(t.value[n,0,0])*LSCALE)))
            thr=int(np.floor(t.threshold[n])); f=USE[t.feature[n]]
            return ('split',f,thr,rec(t.children_left[n]),rec(t.children_right[n]))
        trees.append(rec(0))
    return off,trees
def init_const(m): return float(m.init_.predict(np.zeros((1,len(USE))))[0])
def build(trees,off): return ref.build_blob(trees,mul=65536//LSCALE,off=off,lo=0,hi=ref.T_MAX)
def main():
    rows=TR.dataset(); import glob
    cache={}
    for r in rows:
        if r['name'] not in cache: cache[r['name']]=sim.fk_load.load(sim.SP+'/shadowml/fivek/%s.npz'%r['name'])
        d=cache[r['name']]; kst,_=sim.scene_info(d); r['planes']=sim.planes(d,kst,r['hl'])[0]
        if len(cache)>40: cache.clear()
    summary={}
    for key in ('C','M'):
        tg=TGT[key]; rr=[r for r in rows if not np.isnan(r[tg])]; cfg=CFG[key]
        X=np.array([[r['F'][i] for i in USE] for r in rr],float); y=np.array([2*r[tg] for r in rr],float); w=weights(rr); g=[r['cam'] for r in rr]
        names=np.array([r['name'] for r in rr])
        pred=np.zeros(len(rr)); cb=np.zeros(len(rr))
        for tr,te in GroupKFold(5).split(X,y,g):
            pred[te]=np.clip(gbrt(X[tr],y[tr],w[tr],cfg).predict(X[te]),0,2048)
            cb[te]=2*SG[int(np.argmin(sum(rr[i]['costC'] for i in tr)))]
        base={'model (GBRT, OOF)':pred,'constant (best train cost)':cb,'constant (train mean t)':np.full(len(rr),y.mean()),'stock rule, G plane':np.array([min(TR.stock_t(r),2048) for r in rr],float),
              'placeholder (d01>4 stops->Low)':np.array([TR.placeholder_t(r) for r in rr],float),'zero':np.zeros(len(rr))}
        # per-row metrics for bootstrap
        def per_row(tp):
            sp=np.array([TR.cap_s(t,r['F'][NAMES.index('idx')]) for t,r in zip(tp,rr)])
            rc=np.array([TR.cost_at(r['costC'],s)-r['costC'].min() for s,r in zip(sp,rr)])
            r5=np.array([np.mean([TR.cost_at(c,s) for c in r['costs'].values()])-np.mean([c.min() for c in r['costs'].values()]) for s,r in zip(sp,rr)])
            return sp,rc,r5
        PR={k:per_row(v) for k,v in base.items()}
        un=np.unique(names); rng=np.random.default_rng(0); idxs={u:np.nonzero(names==u)[0] for u in un}
        boots=[np.concatenate([idxs[u] for u in rng.choice(un,len(un))]) for _ in range(400)]
        tbl={}
        print('\n=== target %s  config %s  rows %d images %d'%(key,cfg,len(rr),len(un)))
        for k,v in base.items():
            sp,rc,r5=PR[k]; row=dict(rmse_t=float(np.sqrt(np.mean((2*sp-y)**2))),spearman=float(TR.spearmanr(v,y).statistic) if v.std()>0 else None,regretC=float(rc.mean()),regret5=float(r5.mean()),mean_s=float(sp.mean()))
            if k!='model (GBRT, OOF)':
                dC=[(PR['model (GBRT, OOF)'][1][b]-rc[b]).mean() for b in boots]; d5=[(PR['model (GBRT, OOF)'][2][b]-r5[b]).mean() for b in boots]
                row['model_minus_this_regretC']=[float(np.mean(dC)),float(np.percentile(dC,2.5)),float(np.percentile(dC,97.5))]
                row['model_minus_this_regret5']=[float(np.mean(d5)),float(np.percentile(d5,2.5)),float(np.percentile(d5,97.5))]
            tbl[k]=row
            extra=('  | model-this regretC %+.4f [%+.4f,%+.4f]  regret5 %+.4f [%+.4f,%+.4f]'%(*row['model_minus_this_regretC'],*row['model_minus_this_regret5'])) if 'model_minus_this_regretC' in row else ''
            print('  %-32s rmse_t %4.0f rho %5.2f regretC %.4f regret5 %.4f meanS %4.0f%s'%(k,row['rmse_t'],row['spearman'] or 0,row['regretC'],row['regret5'],row['mean_s'],extra))
        # oracle & label-noise ceiling
        print('  oracle regret5 (each expert picks its own optimum is 0; using the 5-expert-optimal constant per image):',float(np.mean([np.mean([TR.cost_at(c,SG[int(np.argmin(sum(r['costs'].values())))]) for c in r['costs'].values()])-np.mean([c.min() for c in r['costs'].values()]) for r in rr])))
        # group-wise CV per camera: error by camera (top groups)
        # fit on everything
        m=gbrt(X,y,w,cfg); off,trees=to_trees(m,cfg['lr'])
        blob=build(trees,off); open(sim.MODEL+f'/model_{key}.bin','wb').write(blob)
        json.dump(dict(off=off,mul=65536//LSCALE,lo=0,hi=ref.T_MAX,trees=trees,features=NAMES,used=[NAMES[i] for i in USE],cfg=cfg,target=tg),open(sim.MODEL+f'/model_{key}_trees.json','w'))
        fl=np.clip(m.predict(X),0,2048); it=np.array([ref.eval_model(blob,r['F']) for r in rr])
        pm=ref.parse_blob(blob); print('  blob: %d bytes, %d trees, %d nodes; float vs int: max |diff| %.2f  mean |diff| %.3f  (t units; t=2s)'%(len(blob),pm[0],pm[1],np.abs(fl-it).max(),np.abs(fl-it).mean()))
        imp=sorted(zip(m.feature_importances_,[NAMES[i] for i in USE]),reverse=True)[:8]; print('  top features:',[(n,round(float(v),3)) for v,n in imp])
        summary[key]=dict(cfg=cfg,table=tbl,blob_bytes=len(blob),n_trees=pm[0],n_nodes=pm[1],quant_max_diff=float(np.abs(fl-it).max()),quant_mean_diff=float(np.abs(fl-it).mean()),top=[(n,float(v)) for v,n in imp],rows=len(rr),images=len(un))
    json.dump(summary,open(sim.MODEL+'/cv_final.json','w'),indent=1,default=float)
if __name__=='__main__': main()
