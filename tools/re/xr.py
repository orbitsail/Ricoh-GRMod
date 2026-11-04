"""My static cross-reference helpers for the official GR IV fw 1.11 RTOS (ARM32 LE, base 0x53000000). python3 -I -B.
fstart(a): function start (mov ip,sp + push{..lr}, or a bare push{..lr}); callers(fn): bl/b/blx-imm sites; lits(v): aligned words == v;
movwt(v): movw/movt pairs building v (same register, within 16 instructions); pr(a, n): print n instructions; cstr(a): C string."""
import struct, sys
import numpy as np
import capstone

BASE = 0x53000000
import os
# The stock RTOS.bin (decoded RTOS section of the official fw 1.11; never committed) is found through $GRIV_RTOS.
IMG = open(os.environ.get('GRIV_RTOS') or 'RTOS.bin', 'rb').read()
W = np.frombuffer(IMG[:len(IMG) // 4 * 4], dtype='<u4')
ADDR = BASE + 4 * np.arange(len(W), dtype=np.int64)
cs = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
cs.detail = True
CODE_END = 0x53EA0000          # strings / data start around here (code below)


def w(a):
    return struct.unpack_from('<I', IMG, a - BASE)[0]


class _Word:
    def __init__(self, a, v):
        self.address, self.bytes, self.mnemonic, self.op_str = a, struct.pack('<I', v), '.word', f'{v:#010x}'
        self.operands = []


def dis(a, n=1):
    out = []
    for k in range(n):
        x = a + 4 * k
        r = list(cs.disasm(IMG[x - BASE:x - BASE + 4], x))
        out.append(r[0] if r else _Word(x, w(x)))
    return out


def pr(a, n=1, mark=(), out=None):
    lines = []
    for i in dis(a, n):
        m = '>>' if i.address in mark else '  '
        lines.append(f'{m}{i.address:#010x}: {struct.unpack_from("<I", i.bytes)[0]:08x}  {i.mnemonic:8s} {i.op_str}')
    s = '\n'.join(lines)
    if out is None:
        print(s)
    else:
        out.write(s + '\n')
    return s


def _is_push_lr(v):
    return (v & 0xFFFF0000) == 0xE92D0000 and bool(v & 0x4000)


def _is_ret(v, a=None):
    if (v & 0x0FFF0000) in (0x08BD0000, 0x089D0000) and (v & 0x8000):      # ldm sp/ldmia sp!, {.., pc}
        return True
    if (v & 0x0FFFFFFF) == 0x012FFF1E or (v & 0x0FFFFFF0) == 0x012FFF10:     # bx lr / bx rX
        return True
    if (v >> 24) == 0xEA:                                                       # b (always)
        return True
    if a is not None and (v >> 24) == 0xEB:                                     # bl __stack_chk_fail (no return)
        o = v & 0xFFFFFF
        o = o - (1 << 24) if o & 0x800000 else o
        if (a + 8 + 4 * o) & 0xFFFFFFFF == 0x53A786C0:
            return True
    return False


def _prologue_like(v):
    return (v & 0x0E000000) in (0x04000000,) or (v & 0x0FF00000) in (0x03000000, 0x03400000) or (v & 0x0FEF0000) == 0x01A00000


def fstart(a, limit=0x4000):
    """start of the function containing a: the push{..lr} (or the mov ip,sp before it), moved back over at most two
    prologue-like instructions (ldr/str/mov/movw/movt) that follow a return / unconditional branch / stack-check call"""
    x = a
    while x > a - limit:
        v = w(x)
        if v == 0xE1A0C00D and _is_push_lr(w(x + 4)):
            break
        if _is_push_lr(v) and w(x - 4) != 0xE1A0C00D:
            break
        x -= 4
    else:
        return None
    s = x
    for k in (1, 2):
        if all(_prologue_like(w(x - 4 * j)) for j in range(1, k + 1)) and _is_ret(w(x - 4 * (k + 1)), x - 4 * (k + 1)):
            s = x - 4 * k
    return s


_cond = W >> 28
_isb = ((W >> 25) & 7) == 5
_off = (W & 0xFFFFFF).astype(np.int64)
_off = np.where(_off & 0x800000, _off - (1 << 24), _off)
_tgt = ADDR + 8 + 4 * _off
_blx_imm = _cond == 0xF          # blx imm (H bit ignored: ARM targets only matter here)


def callers(fn, kinds=('bl', 'b', 'blx')):
    m = _isb & (_tgt == fn)
    out = []
    for i in np.nonzero(m)[0]:
        v = int(W[i])
        k = 'blx' if (v >> 28) == 0xF else ('bl' if v & (1 << 24) else 'b')
        if k in kinds:
            out.append((int(ADDR[i]), k))
    return out


def lits(v):
    return [int(a) for a in ADDR[W == (v & 0xFFFFFFFF)]]


def movwt(v, lo=BASE, hi=CODE_END):
    """sites where movw rX,#lo16 ... movt rX,#hi16 builds v (movt within 16 instructions after movw)"""
    lo16, hi16 = v & 0xFFFF, v >> 16
    # movw: cond 0011 0000 imm4 Rd imm12 ; movt: cond 0011 0100 imm4 Rd imm12
    isw = ((W & 0x0FF00000) == 0x03000000) & ((((W >> 4) & 0xF000) | (W & 0xFFF)) == lo16)
    out = []
    for i in np.nonzero(isw)[0]:
        a = int(ADDR[i])
        if not (lo <= a < hi):
            continue
        rd = (int(W[i]) >> 12) & 0xF
        for j in range(i + 1, min(i + 17, len(W))):
            u = int(W[j])
            if (u & 0x0FF00000) == 0x03400000 and ((u >> 12) & 0xF) == rd:
                if (((u >> 4) & 0xF000) | (u & 0xFFF)) == hi16:
                    out.append(a)
                break
    return out


def cstr(a, n=96):
    o = a - BASE
    e = IMG.find(b'\0', o, o + n)
    return IMG[o:e if e > 0 else o + n].decode('latin1')


def find_str(s):
    out, i = [], 0
    b = s.encode() if isinstance(s, str) else s
    while True:
        i = IMG.find(b, i)
        if i < 0:
            return out
        out.append(BASE + i)
        i += 1


def bl_targets(fs, fe):
    """bl targets inside [fs, fe)"""
    out = []
    for a in range(fs, fe, 4):
        v = w(a)
        if ((v >> 25) & 7) == 5 and (v >> 28) != 0xF and (v & (1 << 24)):
            o = v & 0xFFFFFF
            o = o - (1 << 24) if o & 0x800000 else o
            out.append((a, (a + 8 + 4 * o) & 0xFFFFFFFF))
    return out


def fend(fs, limit=0x3000):
    """rough end: next function start after fs"""
    a = fs + 8
    while a < fs + limit:
        v = w(a)
        if v == 0xE1A0C00D and (w(a + 4) & 0xFFFF0000) == 0xE92D0000:
            return a
        a += 4
    return fs + limit


if __name__ == '__main__':
    cmd = sys.argv[1]
    a = int(sys.argv[2], 16)
    if cmd == 'pr':
        pr(a, int(sys.argv[3]) if len(sys.argv) > 3 else 32)
    elif cmd == 'fs':
        print(hex(fstart(a)))
    elif cmd == 'callers':
        print([(hex(x), k) for x, k in callers(a)])
    elif cmd == 'lits':
        print([hex(x) for x in lits(a)])
    elif cmd == 'movwt':
        print([hex(x) for x in movwt(a)])
