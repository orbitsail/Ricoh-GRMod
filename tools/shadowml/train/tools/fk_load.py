"""Loader for SP/shadowml/fivek/*.npz.

    import sys; sys.path.insert(0, '<SP>/shadowml/tools'); import fk_load
    d = fk_load.load(path)
    d['meta']        dict (see below)
    d['raw_y']       float32 (H,W): linear Y, relative to sensor white level (NOT exposure normalised), as-shot WB,
                     oriented like the experts' output.  Y=1 ~ a neutral at the white level.
    d['blocks_y']    float32 (62,64): mean linear Y per block over the full active area, sensor orientation (unrotated)
    d['blocks_clip'] float32 (62,64): fraction of clipped raw samples per block
    d['experts']     {letter: dict(y=float32 (h,w) linear ProPhoto Y, plus per-expert meta keys: align_flag, rho, ...)}
                     'y' has the same shape as raw_y when align_flag in ('ok','orient_fixed').  For align_flag=='crop'
                     the expert has its own shape and d['experts'][l]['raw_y'] is the raw side re-cut to match it.
Y is stored as int16 2nd-order differences of log codes; code = round((log2 Y + 20) * 32), code 0 == floor (Y <= 2**-20);
fk_load decodes it (cumsum over rows then cols, Y = 2**(code/32 - 20)). Resolution 1/32 stop (~2.2% step).
"""
import json, os
import numpy as np
_HERE = os.path.dirname(os.path.abspath(__file__))

import sys
sys.path.insert(0, _HERE)
import fk_common as _C
_dec = _C.dec_logy   # int16 2nd-difference of round((log2 Y + 20) * 32) -> linear Y float32

def load(path):
    z = np.load(path, allow_pickle=False)
    meta = json.loads(str(z['meta_json']))
    d = dict(meta=meta, raw_y=_dec(z['raw_y']), blocks_y=z['blocks_y'].astype(np.float32),
             blocks_clip=z['blocks_clip'].astype(np.float32), experts={})
    for l, em in meta['experts'].items():
        e = dict(em)
        e['y'] = _dec(z['exp_' + l]) if ('exp_' + l) in z.files else None
        if 'rawcut_' + l in z.files:
            e['raw_y'] = _dec(z['rawcut_' + l])
        d['experts'][l] = e
    return d

def iter_dir(dirpath):
    for f in sorted(os.listdir(dirpath)):
        if f.endswith('.npz'):
            yield load(os.path.join(dirpath, f))
