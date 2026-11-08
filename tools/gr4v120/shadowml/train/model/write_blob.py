#!/usr/bin/env python3
"""Write the model blob for the camera module from the exported trees:  python3 -B write_blob.py [model_C_trees.json] [out.bin]
Uses the module's own writer (tools/gr4v120/shadowml/ref.py build_blob, imported read-only), so the format is whatever the module expects."""
import sys, json, os
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ.get('SHADOWML_REF_DIR', '/home/claude/grmod-shadow/tools/shadowml'))
import ref
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'model_C_trees.json')
dst = sys.argv[2] if len(sys.argv) > 2 else src.replace('_trees.json', '.bin')
m = json.load(open(src))
def tup(t): return ('leaf', t[1]) if t[0] == 'leaf' else ('split', t[1], t[2], tup(t[3]), tup(t[4]))
assert ref.NAMES == m['features'], 'feature list of ref.py changed since training: retrain'
blob = ref.build_blob([tup(t) for t in m['trees']], mul=m['mul'], off=m['off'], lo=m['lo'], hi=m['hi'])
assert ref.parse_blob(blob) is not None
open(dst, 'wb').write(blob); print('wrote', dst, len(blob), 'bytes')
