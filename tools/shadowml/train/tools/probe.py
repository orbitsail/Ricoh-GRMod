import sys,json
sys.path.insert(0,(__import__('os').environ.get('GRIV_WORK', '.') + '/grdng'))
import tiff, tifffile, rawpy
dng,tif=sys.argv[1:3]
data,t,out=tiff.read_all(dng)
for n,o,r in out['_ifds']:
    print(n,{k:(v if not isinstance(v,(list,bytes)) or len(v)<20 else '...') for k,v in r.items() if k!='_raw'})
with tifffile.TiffFile(tif) as f:
    pg=f.pages[0]; print(pg.shape,pg.dtype,pg.compression,pg.photometric, [ (t.name) for t in pg.tags.values()])
    ic=pg.tags.get('InterColorProfile')
    if ic: b=ic.value; print('ICC len',len(b),bytes(b)[:128][12:24],bytes(b)[4:8]); 
    import re; s=bytes(b); i=s.find(b'desc'); print(s[i:i+80])
r=rawpy.imread(dng); print(r.sizes, r.white_level, r.black_level_per_channel, r.color_desc, r.camera_whitebalance)
