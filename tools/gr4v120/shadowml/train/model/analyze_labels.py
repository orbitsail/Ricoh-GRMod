"""B reports: s* distribution, expert agreement (images with all five), alt-parameter robustness, example plots."""
import sys, os, json
sys.dont_write_bytecode=True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, sim, make_labels as ML
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
R=json.load(open(sim.MODEL+'/labels.json'))
rows=[]
for r in R:
    for v in r['variants']:
        for l,L in v['labels'].items(): rows.append((r['name'],r['camera'],v['hl'],v['iso'],l,L['s'],L['c0'],L['cmin'],L['c1024'],L['n']))
import collections
print('images',len(R),'variants',sum(len(r['variants']) for r in R),'labels',len(rows))
print('align flags:',collections.Counter(L['flag'] for r in R for v in r['variants'][:1] for L in v['labels'].values()))
sc=np.array([x[5] for x in rows if x[4]=='c']); hlc=np.array([x[2] for x in rows if x[4]=='c'])
print('expert C s*: n=%d mean %.0f median %.0f  s*=0: %.1f%%  s*>=1024: %.1f%%  s*>=768: %.1f%%'%(len(sc),sc.mean(),np.median(sc),100*(sc==0).mean(),100*(sc>=1024).mean(),100*(sc>=768).mean()))
print('  by HC: hl0 median %.0f / hl1 median %.0f'%(np.median(sc[hlc==0]),np.median(sc[hlc==1])))
for l in 'abcde':
    s=np.array([x[5] for x in rows if x[4]==l]);
    if len(s): print('  expert %s n=%d mean %.0f median %.0f  at1024 %.1f%%  at0 %.1f%%'%(l,len(s),s.mean(),np.median(s),100*(s>=1024).mean(),100*(s==0).mean()))
# improvement over s=0
imp=np.array([(x[6]-x[7])/max(x[6],1e-9) for x in rows if x[4]=='c']); print('relative cost reduction vs s=0, expert C: median %.2f'%np.median(imp))
# agreement (hl-matched variant, per image)
tab={}
for r in R:
    for v in r['variants']:
        if len(v['labels'])==5: tab[(r['name'],v['hl'])]=[v['labels'][l]['s'] for l in 'abcde']
A=np.array(list(tab.values()),float); print('images x variants with all five experts:',len(A),'(distinct images',len({k[0] for k in tab}),')')
if len(A)>5:
    cm=np.corrcoef(A.T); print('pearson corr matrix a..e:\n',np.round(cm,2));
    from scipy.stats import spearmanr
    sm=spearmanr(A).statistic; print('mean pairwise pearson %.2f  spearman %.2f'%((cm.sum()-5)/20,(sm.sum()-5)/20))
    med_all=np.median(A,1); print('C vs median of five: pearson %.2f  spearman %.2f  MAE %.0f'%(np.corrcoef(A[:,2],med_all)[0,1],spearmanr(A[:,2],med_all).statistic,np.abs(A[:,2]-med_all).mean()))
    loo=np.median(np.delete(A,2,1),1); print('C vs median of other four: pearson %.2f  MAE %.0f'%(np.corrcoef(A[:,2],loo)[0,1],np.abs(A[:,2]-loo).mean()))
    print('within-image sd of s* across experts: mean %.0f ; between-image sd of median %.0f'%(A.std(1,ddof=1).mean(),med_all.std()))
    for i,l in enumerate('abcde'): print('  %s vs median of other four: r=%.2f'%(l,np.corrcoef(A[:,i],np.median(np.delete(A,i,1),1))[0,1]))
# alt params
alt=collections.defaultdict(list)
for r in R:
    for v in r['variants']:
        L=v['labels'].get('c')
        if L and 'alt' in L:
            for k,s in L['alt'].items(): alt[k].append((L['s'],s))
for k,v in alt.items():
    v=np.array(v,float); print('alt %-8s  corr with base %.2f  mean shift %+.0f  MAE %.0f'%(k,np.corrcoef(v[:,0],v[:,1])[0,1],(v[:,1]-v[:,0]).mean(),np.abs(v[:,1]-v[:,0]).mean()))
# histogram
fig,ax=plt.subplots(1,2,figsize=(12,4))
ax[0].hist(sc,bins=np.arange(-8,1040,16),color='C0'); ax[0].set_xlabel('s* (expert C)'); ax[0].set_ylabel('count'); ax[0].set_title('label distribution (Low=256, Med=512, High=1024)')
for x in (256,512,1024): ax[0].axvline(x,c='gray',ls=':')
if len(A): ax[1].scatter(A[:,2]+np.random.default_rng(0).normal(0,5,len(A)),med_all+np.random.default_rng(1).normal(0,5,len(A)),s=8); ax[1].set_xlabel('s* expert C'); ax[1].set_ylabel('s* median of five'); ax[1].plot([0,1024],[0,1024],'k:')
plt.tight_layout(); plt.savefig('labels_hist.png',dpi=90)
# example plots: images spanning s*
import glob
ex=[]; byname={r['name']:r for r in R}
cand=[(r['name'],v) for r in R for v in r['variants'] if 'c' in v['labels'] and v['hl']==1 or (len(r['variants'])==1 and 'c' in v['labels'])]
cand.sort(key=lambda t:t[1]['labels']['c']['s'])
pick=[cand[int(i)] for i in np.linspace(0,len(cand)-1,6)]
fig,axs=plt.subplots(2,6,figsize=(24,8))
for j,(nm,v) in enumerate(pick):
    path=glob.glob(sim.SP+'/shadowml/fivek/%s.npz'%nm)[0]; d=sim.fk_load.load(path); r=byname[nm]; e=d['experts']['c']; hl=v['hl']
    Y=d['raw_y'] if e.get('align_flag')!='crop' else e['raw_y']
    xd,valid=ML.prep(Y,r['kst'],hl,ML.P); v2=valid&(e['y']>ML.P['efloor']); x=xd[v2]; ee=np.log(e['y'][v2].astype(float)); ee-=np.median(ee)
    s=v['labels']['c']['s']; dark=x<=np.median(x)
    ax=axs[0,j]
    for s_,col in ((0,'C3'),(s,'C2'),(1024,'C1')):
        gr=np.log(np.maximum(sim.render(x,s_,hl),1e-9)); gr-=np.median(gr)
        idx=np.argsort(x[::7]); xs=x[::7][idx]
        ax.plot(xs,np.convolve(gr[::7][idx],np.ones(25)/25,'same'),col,label='GR s=%d'%s_)
    ax.scatter(x[::13],ee[::13],s=1,c='gray',alpha=.4); ax.set_xscale('log'); ax.set_xlabel('x_dark (12-bit)'); ax.set_ylabel('ln(Y/median)'); ax.set_title('%s s*=%d (C)\n%s'%(nm[:18],s,r['camera'])); ax.legend(fontsize=7); ax.set_ylim(-4,3)
    axs[1,j].plot(ML.SGRID,v['labels']['c']['cost'],'k'); axs[1,j].axvline(s,c='C2'); axs[1,j].set_xlabel('s'); axs[1,j].set_ylabel('cost')
plt.tight_layout(); plt.savefig('label_examples.png',dpi=60)
