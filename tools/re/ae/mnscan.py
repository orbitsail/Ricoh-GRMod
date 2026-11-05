# SPDX-License-Identifier: GPL-2.0-only
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sys, glob, struct, json, math
import _paths
import mn, tiff_min as tiff
import numpy as np
files=[l.strip() for l in open('grfiles.txt')]
rows=[]
for p in files:
    data,t,out,mt,ents,vpos,cnt = mn.load_mn(p)
    ae=bytes(mt.value(ents[0x206]))
    d,t2,o2=tiff.read_all(p); ifds={n:r for n,o,r in o2['_ifds']}; ex=ifds['ifd0.exif']; i0=ifds['ifd0']
    w=list(struct.unpack_from('<15H', ae, 81))
    hc=bytes(mt.value(ents[0x69]))[0]
    lv=mt.value(ents[0x2D])/1024.0
    N=ex['FNumber']; tt=ex['ExposureTime']; iso=ex['ISO']; ec=ex['ExposureCompensation']
    ev100=math.log2(N*N/tt)-math.log2(iso/100)
    name=p.split('/')[-1].replace('1793759','').split('_')[-1].split('.')[0]
    rows.append(dict(name=name,N=N,t=tt,iso=iso,ec=ec,prog=ex['ExposureProgram'],hc=hc,lv=lv,ev100=ev100,be=i0['BaselineExposure'],
      w0=struct.unpack_from('<H',ae,0)[0], words=w, isoauto=list(mt.value(ents[0x7A])), wb=mt.value(ents[0x19]), pm=list(bytes(mt.value(ents[0x33]))),
      met=mt.value(ents[0x17]), ael=mt.value(ents[0x48]), sw=i0['Software'].strip()[-5:], model=i0['Model'].strip()[-4:], date=ex['DateTimeOriginal'],
      ae=ae.hex()))
json.dump(rows,open('mnscan.json','w'))
print('%-10s %5s %6s %5s %5s %2s | %6s %6s %6s %5s | BE'%('name','N','t^-1','iso','ec','hc','LVmn','EV100','diff','w0'))
for r in rows:
    print('%-10s %5.1f %6.0f %5d %5.1f %2d | %6.2f %6.2f %6.2f %5d | %5.2f  isoauto %s wb %s pm %s ael %s %s'%(r['name'],r['N'],1/r['t'],r['iso'],r['ec'],r['hc'],r['lv'],r['ev100'],r['lv']-r['ev100']+r['ec'],r['w0'],r['be'],r['isoauto'],r['wb'],r['pm'],r['ael'],r['model']))
