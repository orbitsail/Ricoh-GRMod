# SPDX-License-Identifier: GPL-2.0-only
import sys, re
data = open(sys.argv[1], 'rb').read()
pat = re.compile(rb'(?:[\x20-\x7e]\x00){8,}')
seen = set()
kw = re.compile(sys.argv[2], re.I)
for m in pat.finditer(data):
    s = m.group().decode('utf-16le')
    if kw.search(s) and s not in seen:
        seen.add(s)
        print(hex(m.start()), repr(s))
