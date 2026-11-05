# SPDX-License-Identifier: GPL-2.0-only
import sys, re
data = open(sys.argv[1], 'rb').read()
kw = re.compile(sys.argv[2])
# any UTF-16LE run of printable (incl CJK) chars, length >= 3
seen = set()
i = 0
n = len(data)
res = []
for start in (0, 1):
    pass
pat = re.compile(rb'(?:[\x20-\x7e]\x00|[\x00-\xff][\x30-\x9f]|[\x00-\xff][\xa0-\xff]){3,}', re.S)
for m in pat.finditer(data):
    if m.start() % 2: continue
    try:
        s = m.group().decode('utf-16le')
    except Exception:
        continue
    if kw.search(s) and s not in seen:
        seen.add(s)
        res.append((m.start(), s))
for off, s in res[:int(sys.argv[3])]:
    print(hex(off), repr(s))
