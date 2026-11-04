"""D. Apply the model to the 35 DPReview DNGs with their real planes, ISO index and HC flag; contact sheet sorted by prediction."""
import sys, os, json
sys.dont_write_bytecode=True; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, sim
from PIL import Image, ImageDraw, ImageFont
ref=sim.ref; SP=sim.SP
S=json.load(open(SP+'/grdng/ext/summary.json'))
blobC=open(sim.MODEL+'/model_final.bin','rb').read(); blobM=open(sim.MODEL+'/model_M.bin','rb').read()   # tC/sC = the shipped (final consensus) model, tM = the earlier interim M
out=[]
for r in S:
    d=np.load(f"{SP}/grdng/ext/{r['id']}.npz"); s=d['s']; hl=int(r['drx'][:2]=='01')
    pl=[s[i,1:63,:].ravel().astype(np.uint32) for i in range(4)]
    idx=sim.iso_index(r['iso']); F=ref.features(*pl,64,62,hl,idx,0)
    tC=ref.eval_model(blobC,F); tM=ref.eval_model(blobM,F)
    cap=min(tC,int(sim.SR.TC[min(idx,96)])); 
    N=ref.NAMES; out.append(dict(id=r['id'],iso=r['iso'],hl=hl,idx=idx,ec=r['ec'],tC=tC,tM=tM,sC=tC/2,sM=tM/2,d01=F[N.index('d01')]/256,d10=F[N.index('d10')]/256,q50=F[N.index('q50')]/256,nearclip=F[N.index('nearclip')]/4096,cvb=F[N.index('cvb')]/256))
out.sort(key=lambda o:o['tC'])
json.dump(out,open(sim.MODEL+'/dpreview_predictions.json','w'),indent=1)
print('id          ISO hl   ec   t_C  s_C   t_M  s_M   d01(stops) d10  nearclip')
for o in out: print('%s %5d %d %+.1f %5d %4d %5d %4d   %5.2f  %5.2f  %.3f'%(o['id'],o['iso'],o['hl'],o['ec'],o['tC'],o['sC'],o['tM'],o['sM'],o['d01'],o['d10'],o['nearclip']))
from scipy.stats import spearmanr
print('Spearman(t_C, d01) = %.2f ; (t_C, d10) = %.2f ; (t_C, nearclip) = %.2f ; (t_C, t_M) = %.2f'%(spearmanr([o['tC'] for o in out],[o['d01'] for o in out]).statistic,spearmanr([o['tC'] for o in out],[o['d10'] for o in out]).statistic,spearmanr([o['tC'] for o in out],[o['nearclip'] for o in out]).statistic,spearmanr([o['tC'] for o in out],[o['tM'] for o in out]).statistic))
print('t_C: min %d median %d max %d ; share with t_C<=100: %.0f%%'%(min(o['tC'] for o in out),np.median([o['tC'] for o in out]),max(o['tC'] for o in out),100*np.mean([o['tC']<=100 for o in out])))
# contact sheet
cols=7; rowsn=(len(out)+cols-1)//cols; W=300; H=225; lab=44
sheet=Image.new('RGB',(cols*W,rowsn*(H+lab)),(20,20,20)); dr=ImageDraw.Draw(sheet)
try: font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',13)
except Exception: font=ImageFont.load_default()
for i,o in enumerate(out):
    im=Image.open(f"{SP}/grdng/prev/{o['id']}.jpg").convert('RGB'); im.thumbnail((W,H)); x=(i%cols)*W; y=(i//cols)*(H+lab)
    sheet.paste(im,(x+(W-im.width)//2,y)); 
    dr.text((x+4,y+H+2),'#%d  t=%d (s=%d)'%(i+1,o['tC'],o['sC']),fill=(255,255,255),font=font)
    dr.text((x+4,y+H+22),'ISO %d %s  d01 %.1f  clip %.2f'%(o['iso'],'HC' if o['hl'] else '--',o['d01'],o['nearclip']),fill=(190,190,190),font=font)
sheet.save(sim.MODEL+'/sheet.jpg',quality=88); print('sheet',sheet.size)
