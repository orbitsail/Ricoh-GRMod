# tools/re/ae: AE accuracy study

The scripts behind `docs/griv-re/ae-accuracy.md` (is the stock auto exposure as good as five expert retouchers?). Reference code: they produced
the numbers in that file and rerun to the same output; they are not a test suite.

Inputs are in the private pack (`docs/griv-re/testing.md` section 4), `$GRIV_DATA/ae`: `fivek/*.npz`, `gr/*.npz`, `ae_private.json`.
User file names are only in `ae_private.json`, never in this directory. `_paths.py` sets the paths (`GRIV_DATA`, `GRIV_AE_FIVEK`, `GRIV_AE_PRIVATE`).

```
mkdir -p OUT && cd OUT && ln -s "$GRIV_DATA/ae/gr" gr
python3 -I ../tools/re/ae/fk_table.py fk_table.json   # FiveK table (about 20 s)
python3 -I ../tools/re/ae/gr_table.py                 # needs mnscan.json (mnscan.py, from a list of DNG paths in grfiles.txt)
python3 -I ../tools/re/ae/analysis1.py                # -> cv_results.json   (then analysis2..4, robust1, report_assets)
```

`gr_extract.py OUTDIR file.dng ...` makes `gr/*.npz` from DNGs. `checks/` holds the side checks quoted in ae-accuracy.md (alignment, saturation,
nearest neighbours, white level, rederived anchors).

Rerun on 2026-11-04 after moving the scripts here: fk_table, cv_results, gr_gap, gap_by_expert and
anchor_variants came out identical to the tables of the original run.
