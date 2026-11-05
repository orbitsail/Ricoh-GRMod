# SPDX-License-Identifier: GPL-2.0-only
import sys, struct
data = open(sys.argv[1], 'rb').read()
BASE = 0x53000000
def refs(off):
    addr = BASE + off
    pat = struct.pack('<I', addr)
    out = []
    i = data.find(pat)
    while i != -1:
        out.append(i)
        i = data.find(pat, i + 1)
    return out
targets = {'Auto EV Compensation': 0xdedc74, 'EV Compensation': 0xded1cc, 'ISO Setting': 0xded430,
           'ISO Auto Upper Limit': 0xdecc18, 'ISO Auto Lower Limit': 0xdece98, 'Minimum Shutter Speed': 0xdf0900,
           'Exposure Setting': None}
for name, off in targets.items():
    if off is None: continue
    r = refs(off)
    print(name, hex(off), 'refs at', [hex(x) for x in r])
