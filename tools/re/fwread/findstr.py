# SPDX-License-Identifier: GPL-2.0-only
import sys, re
path = sys.argv[1]
data = open(path, 'rb').read()
needle = "Auto EV Compensation".encode('utf-16le')
pos = [m.start() for m in re.finditer(re.escape(needle), data)]
print("occurrences:", [hex(p) for p in pos])
def strings_around(p, before=1600, after=2400):
    lo = max(0, p - before) & ~1
    chunk = data[lo:p + after]
    txt = chunk.decode('utf-16le', errors='replace')
    parts = [s for s in txt.split('\x00')]
    return lo, parts
for p in pos:
    lo, parts = strings_around(p)
    print("==== around", hex(p))
    for s in parts:
        s = s.strip()
        if len(s) >= 2 and all(ch.isprintable() for ch in s):
            print(repr(s))
