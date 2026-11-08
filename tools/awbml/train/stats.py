import json,sys,collections,numpy as np
G=sys.argv[1]
ix=json.load(open(G+'/index.json'))
print(len(ix), collections.Counter(e['split'] for e in ix), collections.Counter(e['camera'] for e in ix), collections.Counter(e['camera_flag'] for e in ix))
print('exif nan', sum(np.isnan(e['Av']) or np.isnan(e['Tv']) or np.isnan(e['Sv']) for e in ix))
for k in ['daytime','place','illumination','light_objects','shadows']:
    print(k, dict(collections.Counter(e[k] for e in ix)))
print('place x illum', collections.Counter((e['place'],e['illumination']) for e in ix))
gt=np.array([e['gt_gr'] for e in ix])
print('gt_gr R/G',np.percentile(gt[:,0],[0,5,50,95,100]).round(3),'B/G',np.percentile(gt[:,1],[0,5,50,95,100]).round(3))
ev=np.array([e['Av']+e['Tv']-e['Sv'] for e in ix])
print('Av+Tv-Sv pct',np.percentile(ev,[0,1,5,25,50,75,95,99,100]).round(2),'mean',ev.mean().round(2),'sd',ev.std().round(2))
for cam in ['Canon EOS 550D','Canon EOS 600D']:
    e2=np.array([a for a,e in zip(ev,ix) if e['camera']==cam]);print(cam,np.percentile(e2,[5,50,95]).round(2))
vf=np.array([e['valid_frac'] for e in ix]);print('valid frac',np.percentile(vf,[0,5,50,95,100]).round(3))
# examples: by K-ish: outdoor natural day vs indoor artificial lamp
def ex(f,n=3):
    c=[e for e in ix if f(e)][:n]
    for e in c: print(' ',e['image'],e['camera'],e['daytime'],e['place'],e['illumination'],e['light_objects'],'raw',np.round(e['gt_raw'],3),'gr',np.round(e['gt_gr'],3))
print('outdoor natural day sky'); ex(lambda e:e['place']=='outdoor' and e['illumination']=='natural' and e['daytime']=='day' and e['light_objects']=="['sky']")
print('indoor artificial lamp'); ex(lambda e:e['place']=='indoor' and e['illumination']=='artificial' and 'lamp' in e['light_objects'])
bl=sorted(ix,key=lambda e:e['gt_gr'][1]/e['gt_gr'][0])
print('lowest B/R',bl[0]['image'],np.round(bl[0]['gt_gr'],3),bl[0]['illumination'],' highest',bl[-1]['image'],np.round(bl[-1]['gt_gr'],3),bl[-1]['illumination'])
for lab,f in [('outdoor natural',lambda e:e['illumination']=='natural'),('artificial',lambda e:e['illumination']=='artificial')]:
    a=np.array([e['gt_gr'] for e in ix if f(e)]);print(lab,'median',np.median(a,0).round(3),'p5-p95 R/G',np.percentile(a[:,0],[5,95]).round(3),'B/G',np.percentile(a[:,1],[5,95]).round(3))
# stat sanity
d=np.load(G+'/'+ix[0]['image']+'.npz',allow_pickle=True);s=d['s'];print(ix[0]['image'],s.shape,s.dtype,s.max(axis=(1,2)),'rows0/63 zero',s[:,0].sum()+s[:,63].sum(),'zero-D blocks',(s[3,1:63,:]==0).sum(),'of',62*64, 'cols', {k:str(d[k]) for k in d.files if k not in ('s','gt_gr')})
sat=0;mx=0
for e in ix[::20]:
    s=np.load(G+'/'+e['image']+'.npz')['s'];mx=max(mx,s[:3].max());sat+=(s[:3]==4095).sum()
print('max stat',mx,'saturated cells in sample',sat)
