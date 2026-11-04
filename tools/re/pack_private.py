#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Collects the private inputs of the test suites from a session scratchpad into one staging directory (see docs/griv-re/testing.md section 4):

  data/        GRIV_DATA: cubepp_gr/ learnawb/cube_eval_preds.npz grdng/ext/ grdng/v6_tables.npz studio/ fivek_gr/
  baselines/   GRIV_BASELINES: <name>/RTOS.bin of the earlier builds (v6 v7 v7b v8c final2 final4 final5 final5_ns fw9_pre fw9_base)
  official/    official.bin (the official 1.11 container the builder reads: core/testdata/private/official.bin), RTOS_1.11.bin (its decoded RTOS,
               GRIV_RTOS), official_1.20/ (the 1.20 container that was examined; labelled, not used by the tests)
  notes/       the scratch notes (*.md, *.txt, f_*.txt disassembly listings) with their relative paths

Data sets that can be downloaded again (cubepp_raw, photo, fk, the DNG caches) are left out. usage: pack_private.py SCRATCHPAD STAGING_DIR"""
import shutil
import sys
from pathlib import Path

DATA = ['cubepp_gr', 'learnawb/cube_eval_preds.npz', 'grdng/ext', 'grdng/v6_tables.npz', 'studio', 'fivek_gr']
BASE = {'v6': 'cpulut/fw8/v6', 'v7': 'cpulut/fw8/v7', 'v7b': 'cpulut/fw8/v7b', 'v8c': 'cpulut/fw8/v8c', 'final2': 'cpulut/final2', 'final4': 'cpulut/final4',
        'final5': 'cpulut/final5', 'final5_ns': 'cpulut/final5/ns', 'fw9_pre': 'cpulut/fw9/pre', 'fw9_base': 'cpulut/fw9/base'}
OFFICIAL = {'official/official.bin': 'fw/unz/fwdc248b.bin', 'official/RTOS_1.11.bin': 're/RTOS.bin', 'official/official_1.20/fwdc248b.bin': 'fw/unz120/fwdc248b.bin'}
NOTE_SKIP = ('node_modules', 'cubepp_raw', 'photo', 'fk', 'grmod_app')
NOTE_MAX = 2_000_000


def copy(src, dst, log):
    if src.is_dir():
        for f in sorted(src.rglob('*')):
            if f.is_file() and '__pycache__' not in f.parts:
                copy(f, dst / f.relative_to(src), log)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    log.append((str(dst), src.stat().st_size))


def main(sp, out):
    sp, out = Path(sp), Path(out)
    log, missing = [], []
    for d in DATA:
        (copy(sp / d, out / 'data' / d, log) if (sp / d).exists() else missing.append(d))
    for name, d in BASE.items():
        f = sp / d / 'RTOS.bin'
        (copy(f, out / 'baselines' / name / 'RTOS.bin', log) if f.exists() else missing.append(f'baseline {name} ({d}/RTOS.bin)'))
    for dst, src in OFFICIAL.items():
        (copy(sp / src, out / dst, log) if (sp / src).exists() else missing.append(dst))
    for f in sorted(sp.rglob('*')):
        if f.suffix in ('.md', '.txt') and f.is_file() and not any(p in NOTE_SKIP for p in f.relative_to(sp).parts) and f.stat().st_size <= NOTE_MAX:
            copy(f, out / 'notes' / f.relative_to(sp), log)
    groups = {}
    for p, n in log:
        g = '/'.join(Path(p).relative_to(out).parts[:2]) if Path(p).relative_to(out).parts[0] in ('baselines', 'official') else Path(p).relative_to(out).parts[0] + '/' + (Path(p).relative_to(out).parts[1] if Path(p).relative_to(out).parts[0] == 'data' else '')
        a = groups.setdefault(g, [0, 0]); a[0] += 1; a[1] += n
    for g, (n, s) in sorted(groups.items()):
        print(f'{g:44s} {n:5d} files {s / 1e6:9.1f} MB')
    print(f'TOTAL {len(log)} files {sum(n for _, n in log) / 1e6:.1f} MB')
    if missing:
        print('MISSING:', *missing, sep='\n  ')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(*sys.argv[1:])
