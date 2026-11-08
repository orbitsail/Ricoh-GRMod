#!/bin/sh
# ONE COMMAND for the final pass (re-runnable any time on whatever FiveK npz exist):  sh run_final.sh
# labels (cached per image) -> domain shift -> candidate CV + holdout + export -> sensitivity -> DPReview sheet.  Writes *.log / *.txt next to the outputs.
cd "$(dirname "$0")" || exit 1
python3 -B make_labels2.py > make_labels2.log 2>&1 && \
python3 -B domain_shift.py > domain_shift.txt 2>&1 && \
python3 -B select_final.py > select_final.log 2>&1 && \
python3 -B write_blob.py model_final_trees.json model_final.bin >> select_final.log 2>&1 && \
python3 -B sens_final.py > sens_final.txt 2>&1 && \
python3 -B apply_dpreview.py > dpreview_predictions.txt 2>&1 && sha256sum model_final.bin > model_final.sha256 && echo "final pass done: see select_final.log sens_final.txt domain_shift.txt dpreview_predictions.txt sheet.jpg model_final.bin"
