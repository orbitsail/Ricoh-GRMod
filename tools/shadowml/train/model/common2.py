"""Shared helpers for the selection / sensitivity / domain-shift scripts."""
import sys, os, json, hashlib
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, sim
ref = sim.ref; NAMES = ref.NAMES; SG = np.arange(0, 1025, 16); SP = sim.SP
EXCL = {'mode', 'rg', 'bg'}
FULL = [i for i, n in enumerate(NAMES) if n not in EXCL]
REL_NAMES = ['d01', 'd05', 'd10', 'u99', 'in1', 'in2', 'in3', 'in4', 'in5', 'nearclip', 'cvb', 'idx', 'hl']
REL = [NAMES.index(n) for n in REL_NAMES]
HOLD_SALT = 'shadowml-holdout-3'
def is_holdout(cam): return int(hashlib.md5((HOLD_SALT + cam).encode()).hexdigest(), 16) % 5 == 0
def load_rows():
    R = json.load(open(sim.MODEL + '/labels2.json')); rows = []
    for r in R:
        for v in r['variants']:
            L = v['labels']
            if 'c' not in L: continue
            costs = {l: np.array(L[l]['cost']) for l in L}
            rows.append(dict(name=r['name'], cam=r['camera'], off=v['off'], hl=v['hl'], iso=v['iso'], F=v['F'], stock_t=v['stock_t'], nexp=len(L),
                             s={l: L[l]['s'] for l in L}, costs=costs, costC=costs['c'],
                             sM=float(np.median([L[l]['s'] for l in L])) if len(L) == 5 else np.nan))
    return rows
def real_planes():
    S = json.load(open(SP + '/grdng/ext/summary.json')); out = []
    for r in S:
        d = np.load(f"{SP}/grdng/ext/{r['id']}.npz"); s = d['s']
        out.append(dict(id=r['id'], iso=r['iso'], hl=int(r['drx'][:2] == '01'), ec=r['ec'], pl=[s[i, 1:63, :].ravel().astype(np.int64) for i in range(4)]))
    return out
def real_feats(rp, scale_stops=0.0, cap=None):
    """features of a real-plane record; scale_stops scales R, G, B (AE uncertainty); cap clips the (pre-hl) planes at that value; zero-count blocks stay zero."""
    R, G, B, C = rp['pl']
    f = 2.0 ** scale_stops
    sc = lambda a: np.rint(a * f).astype(np.int64)
    R, G, B = sc(R), sc(G), sc(B)
    if cap is not None: R, G, B = np.minimum(R, cap), np.minimum(G, cap), np.minimum(B, cap)
    return ref.features(R.astype(np.uint32), G.astype(np.uint32), B.astype(np.uint32), C.astype(np.uint32), 64, 62, rp['hl'], sim.iso_index(rp['iso']), 0)
def cost_at(curve, s): return np.interp(s, SG, curve)
def cap_s(t, idx): return min(t, int(sim.SR.TC[min(int(idx), 0x60)])) / 2.0
