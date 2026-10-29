#!/bin/bash
cd ~/epistemic; set -a; . ./.env; set +a; unset LLM_BATCH; export PASSR_B=laya DEFER_UNITS=_S
.venv/bin/python scripts/ingest.py --workers 8 $(cat work/stragglers2.txt) > logs/stragglers2.log 2>&1
.venv/bin/python -m epistemic.gate --all > logs/rebuild_gate.log 2>&1
.venv/bin/python -m epistemic.graph > logs/rebuild_graph.log 2>&1
CORPUS_LABEL="Coffee and caffeine (cardiovascular, diabetes, aging, mechanism), repetitive negative thinking, AI and data center water" .venv/bin/python -m epistemic.graph_export > logs/rebuild_export.log 2>&1
echo EXPORT_DONE >> logs/rebuild_export.log
.venv/bin/python scripts/claims.py loop --media work/media --media work/media_water > logs/claims_loop2.log 2>&1
.venv/bin/python scripts/concepts_wd.py search > logs/claims_wd2.log 2>&1 && .venv/bin/python scripts/concepts_wd.py pick >> logs/claims_wd2.log 2>&1 && .venv/bin/python scripts/concepts_wd.py apply >> logs/claims_wd2.log 2>&1
.venv/bin/python scripts/support.py > logs/support_run.log 2>&1
echo CHAIN_DONE >> logs/support_run.log
