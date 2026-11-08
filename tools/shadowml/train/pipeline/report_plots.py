from common import *
from tfit import Tcurve
import json, csv
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
TF=json.load(open('T_final_lo560.json')); R=json.load(open('shadow_results.json'))
T=Tcurve(TF['lx'],TF['lj']); Tn=Tcurve(TF['T_nonHC']['lx'],TF['T_nonHC']['lj']); Th=Tcurve(TF['T_HC']['lx'],TF['T_HC']['lj'])
x=np.concatenate([np.arange(0,512,32),np.arange(512,4096,64),[4095]])
with open('T_table.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['x_12bit','J_linear','srgb_code8','nonHC_only','HC_only','supported(>=579)'])
    for v in x:
        vv=max(v,1e-3); w.writerow([int(v),'%.5f'%T(vv),'%.1f'%(255*lin2srgb(T(vv))),'%.5f'%Tn(vv),'%.5f'%Th(vv),int(v>=579)])
xs=np.geomspace(20,4095,300)
fig,ax=plt.subplots(1,2,figsize=(12,4.5))
ax[0].loglog(xs,T(xs),'k',lw=2,label='T (all 35, per-channel, matrixed RGB)');ax[0].loglog(xs,Tn(xs),'C0--',label='non-HC only');ax[0].loglog(xs,Th(xs),'C1--',label='HC only (HLTAB gain before T)')
ax[0].axvline(579,color='gray',ls=':');ax[0].text(600,0.03,'data support starts (index>=140)\nbelow: power-law extrapolation',fontsize=7)
ax[0].set_xlabel('x: linear 12-bit after WB, matrix, shading, HC gain');ax[0].set_ylabel('JPEG linear value');ax[0].legend(fontsize=7)
ax[1].semilogx(xs,255*lin2srgb(T(xs)),'k');ax[1].set_xlabel('x');ax[1].set_ylabel('JPEG sRGB 8-bit code');ax[1].grid(alpha=.3)
plt.tight_layout();plt.savefig('T_curve.png',dpi=90)
# shading
u=np.linspace(0,1,50);p=json.load(open('vp_final.json'))['0112655676']
plt.figure(figsize=(5,3.5));plt.plot(np.sqrt(2*u),np.exp(p[0]*u+p[1]*u*u));plt.xlabel('radius (corner=1.41, edge-mid=1)');plt.ylabel('JPEG/raw gain V');plt.title('inferred lens-shading gain');plt.tight_layout();plt.savefig('shading_gain.png',dpi=90)
# shadow cost curves
SG=[0,64,128,256,384,512,768,1024,1536]
fig,ax=plt.subplots(1,4,figsize=(16,3.8),sharey=True)
for a,m in zip(ax,('A_slope1.0','A_slope0.7','A_slope1.4','C_empirical')):
    for n,i in R.items():
        c=np.array(i[m]['cost']); a.plot(SG,np.sqrt(c),'-',color='C1' if i['hc'] else 'C0',lw=.7)
    a.set_title(m);a.set_xlabel('assumed strength s');a.set_xticks([0,256,512,1024,1536])
ax[0].set_ylabel('rms log(pred/JPEG), shadow blocks');ax[0].set_ylim(0,1.5)
plt.tight_layout();plt.savefig('shadow_cost_vs_s.png',dpi=90)
with open('best_s_per_image.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['id','HC','iso','n_shadow_blocks']+[f'{m}_{k}' for m in ('A_slope1.0','A_slope0.7','A_slope1.4','C_empirical') for k in ('s_best_grid','s_cont','P_s0','s_ci5','s_ci95','bias_log_at_s0')])
    for n,i in R.items():
        row=[n,i['hc'],i['iso'],i['n_blocks']]
        for m in ('A_slope1.0','A_slope0.7','A_slope1.4','C_empirical'):
            d=i[m]; row+= [d['s_grid_best'],round(d['s_cont']),d['boot_p_s0'],d['boot_lo'],d['boot_hi'],round(d['bias_s0'],3)]
        w.writerow(row)
