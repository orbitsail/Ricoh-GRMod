import struct, random
from fwemu import Emu
import awb_ref as R
FR0, FST = 0x6A70, 0x218
A_OBJ, C_OBJ = 0x60100000, 0x60200000

def make_objs(e):
    e.call(0x5395f248, A_OBJ)
    e.call(0x5396127c, C_OBJ)

def frame_addr(obj, i): return obj + FR0 + FST * i

def read_frames(e, obj, n=33):
    out = []
    for i in range(n):
        a = frame_addr(obj, i)
        raw = e.rb(a + 8, 16 * 24)
        f = [list(struct.unpack_from('<4I', raw, 16 * r)) for r in range(24)]
        h = list(struct.unpack('<24H', e.rb(a + 0x1e8, 48)))
        out.append((f, h))
    return out

def write_frame_fields(e, obj, i, f):
    a = frame_addr(obj, i)
    e.wb(a + 8, b''.join(struct.pack('<4I', *r) for r in f))

def set_mode_reset(e, obj, mode, reset_fn):
    e.wb(obj + 0xaf88, bytes([mode]))
    e.call(reset_fn, obj)

def sync_py_from_emu(e, obj, py):
    fr = read_frames(e, obj)
    for i, (f, h) in enumerate(fr):
        py.frames[i].f = [list(r) for r in f]
        py.frames[i].h = list(h)
