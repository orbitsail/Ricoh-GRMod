# SPDX-License-Identifier: GPL-2.0-only
# annotated disassembler for the AE study (scratch)
import sys, struct, json, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s
from s import w, IMG, BASE
import capstone
cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
cs.detail = True
NAMEFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'names.json')
NAMES = {}
if os.path.exists(NAMEFILE):
    NAMES = {int(k, 16): v for k, v in json.load(open(NAMEFILE)).items()}
def name(a, n=None):
    NAMES[a] = n
    json.dump({hex(k): v for k, v in NAMES.items()}, open(NAMEFILE, 'w'), indent=0)

def inimg(a):
    return BASE <= a < BASE + len(IMG)
def cstring(a, maxn=80):
    if not inimg(a): return None
    o = a - BASE
    e = IMG.find(b'\0', o, o + maxn)
    if e < 0: return None
    b = IMG[o:e]
    if len(b) >= 3 and all(0x20 <= c < 0x7f or c in (9, 10) for c in b):
        return b.decode('latin1')
    return None
def f32(v):
    return struct.unpack('<f', struct.pack('<I', v & 0xFFFFFFFF))[0]

def dis(a, n=60, end=None, notes=True, quiet_calls=False):
    out = []
    regs = {}  # movw/movt tracking
    x = a
    cnt = 0
    while True:
        if end is not None and x >= end: break
        if end is None and cnt >= n: break
        v = w(x)
        ins = list(cs.disasm(struct.pack('<I', v), x))
        if not ins:
            out.append('%08x: %08x  .word' % (x, v)); x += 4; cnt += 1; continue
        i = ins[0]
        txt = '%08x: %08x  %-7s %s' % (x, v, i.mnemonic, i.op_str)
        note = ''
        m = i.mnemonic
        if m.startswith('ldr') and 'pc' in i.op_str and '[pc' in i.op_str:
            mm = re.search(r'\[pc, #(-?)(0x[0-9a-f]+|\d+)\]', i.op_str)
            if mm:
                imm = int(mm.group(2), 0) * (-1 if mm.group(1) else 1)
                la = x + 8 + imm
                lv = w(la) if inimg(la) else None
                if lv is not None:
                    note = '; =%#x' % lv
                    sc = cstring(lv)
                    if sc: note += ' "%s"' % sc
                    elif lv in NAMES: note += ' <%s>' % NAMES[lv]
                    rd = i.op_str.split(',')[0]
                    regs[rd] = lv
        elif m.startswith('vldr') and '[pc' in i.op_str:
            mm = re.search(r'\[pc, #(-?)(0x[0-9a-f]+|\d+)\]', i.op_str)
            if mm:
                imm = int(mm.group(2), 0) * (-1 if mm.group(1) else 1)
                la = x + 8 + imm
                if re.match(r'\s*d\d+', i.op_str):
                    dv = struct.unpack('<d', struct.pack('<II', w(la), w(la+4)))[0]
                    note = '; =%g (double %#x_%08x)' % (dv, w(la+4), w(la))
                else:
                    note = '; =%g (%#x)' % (f32(w(la)), w(la))
        elif m == 'movw':
            rd, imm = i.op_str.split(', ')
            regs[rd] = int(imm.lstrip('#'), 0)
        elif m == 'movt':
            rd, imm = i.op_str.split(', ')
            if rd in regs and regs[rd] is not None:
                val = (int(imm.lstrip('#'), 0) << 16) | (regs[rd] & 0xFFFF)
                regs[rd] = val
                note = '; =%#x' % val
                sc = cstring(val)
                if sc: note += ' "%s"' % sc
                elif val in NAMES: note += ' <%s>' % NAMES[val]
        elif m in ('bl', 'b', 'blx') and i.op_str.startswith('#'):
            t = int(i.op_str[1:], 0)
            if t in NAMES: note = '; <%s>' % NAMES[t]
        elif m == 'adr' or (m == 'add' and 'pc' in i.op_str.split(',')[1:2]):
            pass
        out.append(txt + ('   ' + note if note and notes else ''))
        x += 4; cnt += 1
    print('\n'.join(out))

if __name__ == '__main__':
    a = int(sys.argv[1], 16)
    n = int(sys.argv[2], 0) if len(sys.argv) > 2 else 60
    dis(a, n)
