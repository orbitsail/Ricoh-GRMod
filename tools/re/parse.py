import os
import sys, struct, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from mn import load_mn
# usage: parse.py file.dng [stats_out.npz]   (a user-supplied GR IV DNG)
path = sys.argv[1]
data, t, out, mt, ents, vpos, cnt = load_mn(path)
ifd0 = out['_ifds'][0][2]
exif = [r for (n_, o, r) in out['_ifds'] if n_.endswith('exif')][0]
def mv(tag): return mt.value(ents[tag]) if tag in ents else None
def mb(tag):
    if tag not in ents: return b''
    typ, n, pos = ents[tag]
    return data[vpos+pos:vpos+pos+n] if n > 4 else mt.value(ents[tag])
b405 = mb(0x0405)
w, h = struct.unpack('<HH', b405[:4])
Y = np.frombuffer(b405[4:4+0x2000], dtype='<u2').reshape(64, 64)
pl = np.frombuffer(b405[0x2004:0x2004+0x10000], dtype='<u4').reshape(4, 64, 64)
print('Software', ifd0.get('Software'), 'AsShotNeutral', ifd0.get('AsShotNeutral'))
print('WB levels 0x0201', mv(0x0201), ' mnWB 0x0019', mv(0x0019), ' exifWB', exif.get('WhiteBalance'))
print('t', exif.get('ExposureTime'), 'N', exif.get('FNumber'), 'ISO', exif.get('ISO'), 'EC', exif.get('ExposureCompensation'))
print('picture mode 0x0033', mv(0x0033), ' shadow 0x0079', mv(0x0079), ' drx 0x0069', mb(0x0069).hex() if isinstance(mb(0x0069), bytes) else mb(0x0069))
print('AWBInfo 0x0068', mv(0x0068), ' 0x0221 len', len(mb(0x0221)))
print('grid', w, h)
for k, nm in enumerate(['R', 'Gr', 'B', 'cnt']):
    a = pl[k][:h, :w].astype(float)
    print(nm, 'mean %.1f median %.1f max %d' % (a.mean(), np.median(a), a.max()))
R, G, B = (pl[k][:h, :w].astype(float) for k in range(3))
m = pl[3][:h, :w] > 0
print('scene mean ratios R/G %.3f B/G %.3f' % (R[m].sum() / G[m].sum(), B[m].sum() / G[m].sum()))
np.savez(sys.argv[2] if len(sys.argv) > 2 else 'stats.npz', pl=pl, w=w, h=h)
# all makernote tags present, small ones
for tag in sorted(ents):
    typ, n, pos = ents[tag]
    if n <= 32:
        try: v = mt.value(ents[tag])
        except Exception as e: v = '?'
        print(hex(tag), v)
