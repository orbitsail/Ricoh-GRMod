# SPDX-License-Identifier: GPL-2.0-only
import sys, struct, re
data = open(sys.argv[1], 'rb').read()
BASE = 0x53000000
def find_u16(s):
    needle = s.encode('utf-16le')
    return [m.start() for m in re.finditer(re.escape(needle), data)]
def refs(off):
    pat = struct.pack('<I', BASE + off)
    out, i = [], data.find(pat)
    while i != -1:
        out.append(i); i = data.find(pat, i + 1)
    return out
def dump(off, before=0x40, after=0x60):
    lo = off - before
    for a in range(lo, off + after, 16):
        words = struct.unpack('<4I', data[a:a+16])
        print(f"{BASE+a:08x}: " + ' '.join(f"{w:08x}" for w in words))
for name in sys.argv[2:]:
    for so in find_u16(name):
        r = refs(so)
        print(f"## '{name}' text at {hex(so)}; refs {[hex(x) for x in r]}")
        for x in r:
            print("-- context of ref", hex(x))
            dump(x)
