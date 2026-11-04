#!/bin/sh
# Final re-run on whatever FiveK npz exist (per-image results are cached; only new files cost time).
cd "$(dirname "$0")"
python3 -B build_T.py && python3 -B ae_calib.py > ae_calib.txt && python3 -B make_labels.py && python3 -B analyze_labels.py > labels_report.txt \
 && python3 -B synth_check.py > synth_check.txt && python3 -B final_fit.py > cv_final.txt && python3 -B apply_dpreview.py > dpreview_predictions.txt
