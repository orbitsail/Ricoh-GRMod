# SPDX-License-Identifier: GPL-2.0-only
import sys, struct, re
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s, capstone
cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
def ins(a):
    v = s.w(a)
    r = list(cs.disasm(struct.pack('<I', v), a))
    return r[0] if r else None
def inner_of(g):
    for k in range(24):
        i = ins(g + 4*k)
        if i and i.mnemonic == 'ldr' and '#0x518]' in i.op_str:
            j = ins(g + 4*k + 4)
            if j and j.mnemonic == 'bl':
                return int(j.op_str[1:], 16)
    return None
def p_offset(t):
    base = 0; kind = ''
    for k in range(6):
        i = ins(t + 4*k)
        if i is None: return None
        txt = i.mnemonic + ' ' + i.op_str
        m = re.match(r'add r3, r3, #(0x[0-9a-f]+)', txt)
        if m: base = int(m.group(1), 0); continue
        m = re.search(r'\[r3(?:, #(0x[0-9a-f]+))?\]', i.op_str)
        if m and (i.mnemonic.startswith('ldr') or i.mnemonic.startswith('vldr')) and 'r3, [r0]' not in txt:
            off = int(m.group(1), 16) if m.group(1) else 0
            return '%s P+0x%x' % (i.mnemonic, base + off)
        if i.mnemonic == 'bx': return None
    return None
def decode_set(t):
    base = 0
    for k in range(4):
        i = ins(t + 4*k)
        if i is None: return '?'
        txt = i.mnemonic + ' ' + i.op_str
        m = re.match(r'add r0, r0, #(0x[0-9a-f]+)', txt)
        if m: base = int(m.group(1), 0); continue
        m = re.search(r'\[r0(?:, #(0x[0-9a-f]+))?\]', i.op_str)
        if m and i.mnemonic.startswith(('str', 'vstr')):
            off = int(m.group(1), 16) if m.group(1) else 0
            return '%s I+0x%x' % (i.mnemonic, base + off)
        if i.mnemonic == 'movw' and 'r3' in i.op_str:
            mm = re.search(r'#(0x[0-9a-f]+)', i.op_str)
            nxt = ins(t + 4*k + 4)
            if mm and nxt and nxt.mnemonic.startswith('str'):
                return '%s I+0x%x' % (nxt.mnemonic, int(mm.group(1), 16))
    return '?'
lo, hi = int(sys.argv[1], 16), int(sys.argv[2], 16)
a = lo
while a < hi:
    i = ins(a)
    if i and i.mnemonic == 'bl' and i.op_str.startswith('#'):
        t = int(i.op_str[1:], 16)
        if 0x53750000 <= t < 0x53760000:
            inn = inner_of(t)
            po = p_offset(inn) if inn else None
            b = a + 4; setter = None
            while b < hi + 0x40:
                j = ins(b)
                if j is None: break
                if j.mnemonic == 'bl':
                    setter = int(j.op_str[1:], 16); break
                b += 4
            print('%08x getter %08x inner %s  %s  -> %s' % (a, t, hex(inn) if inn else None, po, decode_set(setter) if setter else None))
    a += 4
