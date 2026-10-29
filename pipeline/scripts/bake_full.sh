#!/bin/bash
cd ~/epistemic; source .venv/bin/activate; set -a; . ./.env; set +a
for m in deepseek glm minimax qwen27b kimi; do echo "== $m $(TZ=Asia/Kolkata date +%H:%M)"; python scripts/bakeoff.py run $m 2>&1 | tail -1 | cut -c1-300; done
echo "== anthropic $(TZ=Asia/Kolkata date +%H:%M)"; python scripts/bakeoff.py anthropic-batch 2>&1 | tail -2
python scripts/bake_score.py > logs/bake_scores.txt 2>&1; tail -20 logs/bake_scores.txt
echo FULL_DONE $(TZ=Asia/Kolkata date +%H:%M)
