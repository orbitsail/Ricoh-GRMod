import os
import sys, glob
# usage: dngwb.py 'DIR/*.dng'   (user-supplied GR IV DNGs; prints a few makernote tags per file)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mn import load_mn, PTAGS
import struct
want=[0x000C,0x0019,0x001A,0x001B,0x001C,0x0050,0x0068,0x0208,0x020D,0x0214,0x0221,0x004D,0x0034,0x0012,0x0014,0x0006,0x0007]
for f in sorted(glob.glob(sys.argv[1])):
    try:
        data,t,out,mt,ents,vpos,cnt=load_mn(f)
    except Exception as e:
        print(f,'ERR',e); continue
    row=[f.split('/')[-1]]
    for tag in want:
        if tag in ents:
            typ,n,pos=ents[tag]
            sz=n*{1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8}.get(typ,1)
            if sz<=40:
                v=mt.value(ents[tag])
                if isinstance(v,bytes): v=v.hex()
            else: v='<%dB>'%sz
            row.append('%04X=%s'%(tag,v))
    print(' '.join(str(x) for x in row))
