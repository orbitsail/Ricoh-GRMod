# SPDX-License-Identifier: GPL-2.0-only
"""Build the FiveK table: raw-side features + per-expert display profiles.  usage: python3 -I fk_table.py OUT.json"""
import sys, os, json, glob, math
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__))); import _paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import fk_load
import features as F
from multiprocessing import Pool
SRC = _paths.FIVEK

def one(path):
    try:
        d = fk_load.load(path)
        m = d['meta']
        t = m.get('exposure_time'); N = m.get('f_number'); iso = m.get('iso')
        ev100 = math.log2(N * N / t) - math.log2(iso / 100.0) if (t and N and iso) else None
        row = {'name': m['name'], 'camera': m.get('dng_model') or m.get('model'), 'iso': iso, 't': t, 'N': N, 'ev100': ev100,
               'cat': m.get('categories'), 'be': m.get('baseline_exposure')}
        row.update(F.raw_features(d['raw_y'], d['blocks_clip']))
        ex = {}
        for l, e in d['experts'].items():
            if e.get('align_flag') in ('ok', 'orient_fixed') and e.get('y') is not None and e['y'].shape == d['raw_y'].shape:
                p = F.display_profile(e['y']); p['rho'] = e.get('rho'); ex[l] = p
        row['experts'] = ex
        return row
    except Exception as e:
        return {'name': os.path.basename(path), 'error': repr(e)}

if __name__ == '__main__':
    files = sorted(glob.glob(SRC + '/*.npz'))
    with Pool(2) as pool:
        rows = pool.map(one, files, chunksize=8)
    ok = [r for r in rows if 'error' not in r]
    print('files', len(files), 'ok', len(ok), 'errors', len(rows) - len(ok))
    json.dump(rows, open(sys.argv[1], 'w'))
