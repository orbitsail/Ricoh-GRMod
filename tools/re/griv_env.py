# SPDX-License-Identifier: GPL-2.0-only
"""Where the tests find the inputs that are not in the repository (see docs/griv-re/testing.md section 4).

  GRIV_DATA       directory with the scene sets: cubepp_gr/, learnawb/cube_eval_preds.npz, grdng/ext/ (+ summary.json), studio/, fivek_gr/ (optional: dng/*.dng)
  GRIV_BASELINES  directory with baseline builds, <name>/RTOS.bin (v6 v7 v7b v8c final2 final4 final5 fw9_pre fw9_base)
  GRIV_RTOS       the stock RTOS.bin of the official fw 1.11 (tools/re, fwemu)

A missing variable or file stops the script with a message that names the variable.
"""
import os
from pathlib import Path

DOC = 'docs/griv-re/testing.md section 4'


def _fail(msg):
    raise SystemExit(f'{msg}\nSee {DOC} for the private input pack and its layout.')


def _root(var, what):
    v = os.environ.get(var)
    if not v:
        _fail(f'{var} is not set: it must point to {what}.')
    p = Path(v)
    if not p.is_dir():
        _fail(f'{var}={v} is not a directory ({what}).')
    return p


def data_root():
    return _root('GRIV_DATA', 'the directory with the scene sets (cubepp_gr/, learnawb/, grdng/ext/, studio/, fivek_gr/)')


def data(*parts, optional=False):
    """Path below $GRIV_DATA; a missing file is an error that names GRIV_DATA unless optional."""
    p = data_root().joinpath(*parts)
    if not optional and not p.exists():
        _fail(f'{"/".join(parts)} is missing in GRIV_DATA={os.environ["GRIV_DATA"]}.')
    return p


def baseline(name):
    """Path of $GRIV_BASELINES/<name>/RTOS.bin (a baseline build's decoded RTOS section)."""
    p = _root('GRIV_BASELINES', 'the directory with baseline builds as <name>/RTOS.bin').joinpath(name, 'RTOS.bin')
    if not p.exists():
        _fail(f'baseline {name}/RTOS.bin is missing in GRIV_BASELINES={os.environ["GRIV_BASELINES"]}.')
    return str(p)


def baseline_env(var, name):
    """$var if set (a path to an RTOS.bin), else the baseline <name>."""
    return os.environ.get(var) or baseline(name)
