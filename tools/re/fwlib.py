import struct, os
D = os.path.dirname(os.path.abspath(__file__))
# The stock RTOS.bin (decoded RTOS section of the official fw 1.11; never committed) is found through $GRIV_RTOS.
RT = open(os.environ.get('GRIV_RTOS') or os.path.join(D, 'RTOS.bin'), 'rb').read()
BASE = 0x53000000
RAM_SRC, RAM_DST, RAM_LEN = 0x5437b640, 0x55000000, 0x57480
NAMES = {11:'Standard',12:'Vivid',13:'Monotone',14:'SoftMono',15:'HardMono',16:'HiConBW',17:'PosFilm',18:'CinemaY',19:'CinemaG',20:'Bleach',21:'Retro',22:'HDRTone',23:'CrossProc',24:'NegFilm',25:'M-Std',26:'M-Soft',27:'M-HiCon',28:'M-Grainy',29:'M-Solid',30:'M-HDR'}
def off(a):
    if RAM_DST <= a < RAM_DST + RAM_LEN: return RAM_SRC - BASE + (a - RAM_DST)
    if BASE <= a < BASE + len(RT): return a - BASE
    return None
def rd(a, n):
    o = off(a)
    if o is None: return None
    return RT[o:o+n]
def w(a):
    b = rd(a, 4)
    return None if b is None else struct.unpack('<I', b)[0]
def h(a):
    b = rd(a, 2); return struct.unpack('<h', b)[0]
def H(a):
    b = rd(a, 2); return struct.unpack('<H', b)[0]
def words(a, n):
    return list(struct.unpack('<%dI' % n, rd(a, 4*n)))
def i16s(a, n):
    return list(struct.unpack('<%dh' % n, rd(a, 2*n)))
def u16s(a, n):
    return list(struct.unpack('<%dH' % n, rd(a, 2*n)))
def isptr(v):
    return off(v) is not None
TONES, VARIANTS = 34, 3
TONE_TABLE, MA_TABLE, YCC_TABLE, GAMMA_TABLE = 0x55053780, 0x55053504, 0x55052cf4, 0x55053138
def tw(table, v, s): return w(table + 4*(v*TONES + s))
def name(s): return NAMES.get(s, 's%d' % s)
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
_md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
def dis(a, n=40, show=True):
    out = []
    code = rd(a, 4*n)
    for ins in _md.disasm(code, a):
        out.append((ins.address, ins.mnemonic, ins.op_str))
    if show:
        for x in out: print('%08x: %-8s %s' % x)
    return out
import re as _re
def find_word(val, lo=BASE, hi=None):
    """all 4-aligned offsets in RTOS image holding val"""
    b = struct.pack('<I', val)
    res = []
    i = RT.find(b)
    while i >= 0:
        if i % 4 == 0: res.append(BASE + i)
        i = RT.find(b, i+1)
    return res
import numpy as _np
_W = _np.frombuffer(RT[:len(RT)//4*4], dtype='<u4')
_CODE_END_W = (0x54000000 - BASE)//4
def callers(target, kinds=('bl','b')):
    ws = _W[:_CODE_END_W]
    idx = _np.arange(len(ws), dtype=_np.int64)
    pc = BASE + idx*4
    cond_ok = (ws >> 28) != 0xF
    isb = ((ws >> 25) & 7) == 5
    link = (ws >> 24) & 1
    off = (ws & 0xFFFFFF).astype(_np.int64)
    off = _np.where(off & 0x800000, off - 0x1000000, off)
    tgt = pc + 8 + off*4
    m = cond_ok & isb & (tgt == target)
    res = []
    for i in _np.nonzero(m)[0]:
        res.append((int(pc[i]), 'bl' if link[i] else 'b'))
    return res
def func_start(a, maxback=4000):
    """walk back to 'mov ip, sp' (e1a0c00d) prologue"""
    x = a
    for _ in range(maxback):
        if w(x) == 0xe1a0c00d: return x
        x -= 4
    return None
def movw_enc(rd_, imm):
    return 0xe3000000 | ((imm >> 12) & 0xf) << 16 | (rd_ << 12) | (imm & 0xfff)
def movt_enc(rd_, imm):
    return 0xe3400000 | ((imm >> 12) & 0xf) << 16 | (rd_ << 12) | (imm & 0xfff)
def xrefs(val, window=8):
    """code sites building `val` with movw/movt (any cond=AL, any reg) or literal pool"""
    lo, hi = val & 0xffff, val >> 16
    ws = _W[:_CODE_END_W]
    res = []
    for r in range(16):
        e1 = movw_enc(r, lo)
        idx = _np.nonzero(ws == e1)[0]
        e2 = movt_enc(r, hi)
        for i in idx:
            seg = ws[i+1:i+1+window]
            if (seg == e2).any():
                res.append(BASE + int(i)*4)
    for a in find_word(val):
        if a < 0x54000000: res.append(('lit', a))
    return res
