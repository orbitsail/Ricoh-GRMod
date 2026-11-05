# SPDX-License-Identifier: GPL-2.0-only
import sys, re
data = open(sys.argv[1], 'rb').read()
lo, hi = int(sys.argv[2], 16), int(sys.argv[3], 16)
pat = re.compile(rb'(?:[\x20-\x7e]\x00){4,}')
for m in pat.finditer(data, lo, hi):
    print(hex(m.start()), repr(m.group().decode('utf-16le')))
