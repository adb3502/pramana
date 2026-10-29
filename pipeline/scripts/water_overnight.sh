#!/bin/bash
# OpenAlex free budget for this IP was exhausted on 2026-10-28; it resets at 00:00 UTC (05:30 IST). Run the water corpus after that.
cd ~/epistemic; set -a; . ./.env; set +a; unset LLM_BATCH
now=$(date -u +%s); tgt=$(date -u -d "tomorrow 00:05" +%s); sleep $((tgt-now))
.venv/bin/python scripts/oa_select.py water "water consumption, water footprint and water stress of data centers and artificial intelligence (cooling water, water use effectiveness WUE, electricity-generation water, AI model training and inference water use, local water impacts)" "data center water consumption" "data centre water footprint" "artificial intelligence water footprint" "AI water consumption training inference" "data center cooling water use effectiveness" "data center water stress drought" "hyperscale data center water" "machine learning carbon and water footprint"
python3 -c "
import json,glob
for p in glob.glob(\"work/media_water/claims/*.json\"):
    c=json.load(open(p)); c.pop(\"resolved\",None); json.dump(c,open(p,\"w\"))"
MEDIA_DIR=work/media_water .venv/bin/python scripts/media.py resolve
PDFFLAG=--pdf bash scripts/thread3.sh work/water_candidates.json water 12 &
bash scripts/thread2.sh work/water_candidates.json water 12
wait
