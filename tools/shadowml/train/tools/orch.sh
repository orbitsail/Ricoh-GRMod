#!/bin/bash
R=${GRIV_WORK:-.}/shadowml
cd $R
while [ $(ls fivek | grep -vc '^\.') -lt 1000 ]; do
  pgrep -f "[f]k_run.py" >/dev/null || break
  sleep 10
done
touch STOP
while pgrep -f "[f]k_run.py" >/dev/null; do sleep 3; done
rm -f STOP
echo "phase1 stopped at $(ls fivek | grep -vc '^\.') files $(date)" >> progress2.log
python3 tools/fk_run2.py 7200 >> run2.out 2>&1
echo "orch done $(date)" >> progress2.log
