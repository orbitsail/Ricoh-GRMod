# SPDX-License-Identifier: GPL-2.0-only
import struct, sys, re
import capstone
IMG = open(sys.argv[1], 'rb').read()
BASE = 0x53000000
lo, hi = int(sys.argv[2], 16), int(sys.argv[3], 16)
pats = sys.argv[4:]
cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
for a in range(lo, hi, 4):
    o = a - BASE
    v = struct.unpack_from('<I', IMG, o)[0]
    for i in cs.disasm(struct.pack('<I', v), a):
        txt = i.mnemonic + ' ' + i.op_str
        if any(re.search(p, txt) for p in pats):
            print('%08x: %s' % (a, txt))
