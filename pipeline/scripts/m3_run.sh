#!/usr/bin/env bash
# Mission 3: run the JATS pipeline on every kept paper not yet finished, batches of 6, STATUS checkpoint after each batch.
cd "$(dirname "$0")/.."; source .venv/bin/activate
mapfile -t TODO < <(python - <<'PY'
import json, os
S = json.load(open("work/m3_screen.json"))
for r in S["records"]:
    d = r["pmcid"]
    if r["decision"] == "keep" and not os.path.exists(f"ext/{d}.adj.json"): print(d)
PY
)
echo "todo ${#TODO[@]}"
for ((i=0; i<${#TODO[@]}; i+=6)); do
  B=("${TODO[@]:i:6}"); echo "batch $((i/6+1)): ${B[*]} $(TZ=Asia/Kolkata date +%H:%M)"
  scripts/batch_full.sh "${B[@]}"
  python scripts/m3_checkpoint.py
done
echo m3_run_done
