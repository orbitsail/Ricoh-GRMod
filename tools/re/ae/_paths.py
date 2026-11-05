# SPDX-License-Identifier: GPL-2.0-only
"""Paths and private inputs for the AE accuracy study (docs/griv-re/ae-accuracy.md).

Nothing private is in the repository. Set:
  GRIV_DATA         the private pack's data/ (testing.md section 4); the study's inputs are in $GRIV_DATA/ae:
                      fivek/*.npz   FiveK raw-side statistics and expert renditions (fk_table.py input)
                      gr/*.npz      one file per GR IV DNG made by gr_extract.py (gr_table.py, analysis2-4 input)
                      ae_private.json, see GRIV_AE_PRIVATE
  GRIV_AE_FIVEK     overrides the FiveK directory
  GRIV_AE_PRIVATE   JSON file kept in the private pack (default $GRIV_DATA/ae/ae_private.json) with
                    "exclude"      names of user-supplied frames left out of the comparison (bad WB),
                    "wb_override"  {name: [r, g, b]} neutral used for those frames,
                    "rederive_names", "wl_names"  frames printed by checks/rederive_a.py and checks/wl.py
The scripts read and write their tables (fk_table.json, gr_table.json, ...) in the current directory;
run them in an output directory with a link gr -> $GRIV_DATA/ae/gr (see README.md).
"""
import os, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
for p in (os.path.join(REPO, 'tools', 're'), os.path.join(REPO, 'tools', 'shadowml', 'train', 'tools')):
    if p not in sys.path:
        sys.path.insert(0, p)
DATA = os.environ.get('GRIV_DATA', '.')
FIVEK = os.environ.get('GRIV_AE_FIVEK') or os.path.join(DATA, 'ae', 'fivek')
_priv = os.environ.get('GRIV_AE_PRIVATE') or os.path.join(DATA, 'ae', 'ae_private.json')
PRIV = json.load(open(_priv)) if os.path.exists(_priv) else {'exclude': [], 'wb_override': {}, 'rederive_names': [], 'wl_names': []}
EXCLUDE = set(PRIV.get('exclude', []))
