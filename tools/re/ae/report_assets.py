# SPDX-License-Identifier: GPL-2.0-only
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, csv, numpy as np
import _paths
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
for p in fm.findSystemFonts():
    if 'NotoSansCJK-Regular' in p: fm.fontManager.addfont(p)
plt.rcParams['font.family']='Noto Sans CJK SC'; plt.rcParams['axes.unicode_minus']=False
gr=json.load(open('gr_table.json')); gap=json.load(open('gap_by_expert.json'))
green=_paths.EXCLUDE
names=gap['names']; cons=np.array(gap['consensus']['stops']); gl=np.array(gap['consensus']['gap_L'])
# sign flip for presentation: camera minus expert (+ = camera brighter)
idx={n:i for i,n in enumerate(names)}
rows=[]
for r in gr:
    n=r['name']; src='你自己拍' if n.startswith('R000') else 'DPReview样张'
    row={'照片':n,'来源':src,'光圈':r['N'],'快门(秒)':round(r['t'],5),'ISO':r['iso'],'曝光补偿(档)':r['ec'],'高光校正':'开' if r['hc'] else '关',
         '相机出片：中间调亮度(0黑-100白)':round(r['disp']['L_p50'],1),'相机出片：整体平均亮度':round(r['disp']['L_mean'],1),
         'RAW里过曝像素(%)':round(100*r['lvl_clip_frac'],2)}
    if n in idx:
        i=idx[n]; row['修图师共识：中间调亮度']=round(r['disp']['L_p50']-(-gl[i]),1) if False else round(r['disp']['L_p50']+gl[i],1)
        row['相机比修图师亮(+)暗(-) 档']=round(-cons[i],2); row['是否纳入对比']='是'
    else:
        row['修图师共识：中间调亮度']=''; row['相机比修图师亮(+)暗(-) 档']=''
        row['是否纳入对比']='否：用了曝光补偿' if r['ec']!=0 else '否：直出JPEG偏绿(白平衡问题)，亮度不可信'
    rows.append(row)
with open('out/per_scene.csv','w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
# figure 1: per expert
labs=['修图师 A','修图师 B','修图师 C','修图师 D','修图师 E','五人共识']
vals=[-np.mean(gap[k]['stops']) for k in 'abcde']+[-np.mean(cons)]
sds=[np.std(gap[k]['stops'],ddof=1)/np.sqrt(len(cons)) for k in 'abcde']+[np.std(cons,ddof=1)/np.sqrt(len(cons))]
fig,ax=plt.subplots(figsize=(7.2,3.6),dpi=160)
cols=['#8da0cb']*5+['#e5793a']
ax.barh(labs[::-1],vals[::-1],xerr=sds[::-1],color=cols[::-1],ecolor='#555',capsize=3)
ax.axvline(0,color='k',lw=1); ax.set_xlabel('相机出片比这位修图师会调的亮度：亮(+) / 暗(−)，单位：档（24 张自动曝光照片的平均）')
ax.set_title('相机的亮度落在 5 位修图师的偏好之间',fontsize=11)
for y,v in zip(range(6),vals[::-1]): ax.text(0.92,y,'%+.2f 档'%v,va='center',ha='right',fontsize=9.5,fontweight='bold')
ax.set_xlim(-0.45,0.95); fig.tight_layout(); fig.savefig('out/fig1_experts.png'); plt.close(fig)
# figure 2: per scene consensus gap
o=np.argsort(-(-cons)); nm=[names[i] for i in o]; v=[-cons[i] for i in o]
fig,ax=plt.subplots(figsize=(7.2,6.2),dpi=160)
ax.barh(range(len(v)),v,color=['#e5793a' if x>0 else '#4c78a8' for x in v]); ax.set_yticks(range(len(v))); ax.set_yticklabels(nm,fontsize=7)
ax.axvspan(-0.46,0.46,color='#ddd',alpha=.5,zorder=0); ax.axvline(0,color='k',lw=1)
ax.set_xlabel('相机比修图师共识亮(+)/暗(−)，档；灰带 = 修图师彼此的分歧范围(±0.46 档)'); ax.set_title('逐张：相机亮度 vs 修图师共识（24 张）',fontsize=11)
fig.tight_layout(); fig.savefig('out/fig2_per_scene.png'); plt.close(fig)
print('ok', len(rows))
print('per expert (camera minus expert, stops):', dict(zip(labs,[round(x,2) for x in vals])))
