"""Step A: where does the GR IV AE put the scene?  Statistics of the G plane (x2 for HC) over the 35 DPReview DNGs."""
import json, numpy as np
SP=__import__('os').environ.get('GRIV_WORK', '.')
S=json.load(open(SP+'/grdng/ext/summary.json'))
def load(r):
    d=np.load(f"{SP}/grdng/ext/{r['id']}.npz"); s=d['s'].astype(np.float64)
    hl=int(r['drx'][:2]=='01'); G=s[1,1:63].ravel(); C=s[3,1:63].ravel(); return G,C,hl
YY,XX=np.divmod(np.arange(64*62),64)
CEN=(YY>=15)&(YY<47)&(XX>=16)&(XX<48)
def cw(L,m): # centre-weighted mean (centre half weight 3, rest 1)
    w=np.where(CEN,3.,1.)[m]; return np.log2((w*L[m]).sum()/w.sum())
STATS={
 'median':lambda L,m:np.log2(np.median(L[m])),
 'meanlog':lambda L,m:np.log2(np.maximum(L[m],1)).mean(),
 'mean_lin':lambda L,m:np.log2(L[m].mean()),
 'centre_w_mean':cw,
 'centre_mean':lambda L,m:np.log2(L[m&CEN].mean()),
 'q25':lambda L,m:np.log2(np.percentile(L[m],25)),
 'q75':lambda L,m:np.log2(np.percentile(L[m],75)),
 'q60':lambda L,m:np.log2(np.percentile(L[m],60)),
 'trim_meanlog(10-90)':lambda L,m:np.log2(np.maximum(np.sort(L[m])[int(.1*m.sum()):int(.9*m.sum())],1)).mean(),
}
if __name__=='__main__':
    rows=[]
    for r in S:
        G,C,hl=load(r); m=C>0; L=G*(2**hl); rows.append((r,L,m,hl))
    nall=len(rows); rows=[x for x in rows if x[0]['iso']<3200]   # ISO 6400/8000 = AE ran out of shutter/ISO range: exposure not metered, excluded
    print('using',len(rows),'of',nall,'(ISO<3200)')
    res={}
    for name,f in STATS.items():
        v=np.array([f(L,m) for r,L,m,hl in rows]); ec=np.array([r['ec'] for r,*_ in rows]); iso=np.array([r['iso'] for r,*_ in rows])
        z=ec==0; adj=v-ec
        slope=float(np.polyfit(ec,v,1)[0]); res[name]=dict(ec_slope=slope,n0=int(z.sum()),mean0=float(v[z].mean()),sd0=float(v[z].std(ddof=1)),sd_all_ecadj=float(adj.std(ddof=1)),mean_all=float(adj.mean()),
                       sd0_hl=float(v[z&(iso>=200)].std(ddof=1)),sd0_nohl=float(v[z&(iso<200)].std(ddof=1)), robust_sd0=float(1.4826*np.median(np.abs(v[z]-np.median(v[z])))))
        print('ec slope %.2f'%slope,end=' ');print('%-22s ec=0 n=%d  mean %.3f  sd %.3f stops (rob %.3f) | all ec-adj sd %.3f | hl sd %.3f noHL sd %.3f'%(name,z.sum(),res[name]['mean0'],res[name]['sd0'],res[name]['robust_sd0'],res[name]['sd_all_ecadj'],res[name]['sd0_hl'],res[name]['sd0_nohl']))
    print('per image (ec=0): iso hl median meanlog q25 q75 q90 frac>2048')
    for r,L,m,hl in rows:
        if r['ec']==0: print(r['id'],r['iso'],hl,'%.2f %.2f %.2f %.2f %.2f %.3f'%(np.log2(np.median(L[m])),np.log2(np.maximum(L[m],1)).mean(),np.log2(np.percentile(L[m],25)),np.log2(np.percentile(L[m],75)),np.log2(np.percentile(L[m],90)),(L[m]>2048).mean()))
    json.dump(res,open('ae_calib.json','w'),indent=1)
