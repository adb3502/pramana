#!/bin/bash
cd ~/epistemic; source .venv/bin/activate; set -a; . ./.env; set +a
for m in haiku_none deepseek minimax glm qwen27b nemotron kimi; do
  [ "$m" = haiku_none ] && continue
  echo "== $m $(date +%H:%M)"; python scripts/bakeoff.py run $m smoke 2>&1 | tail -2
done
echo "== anthropic $(date +%H:%M)"; python scripts/bakeoff.py anthropic-batch smoke 2>&1 | tail -3
python scripts/bake_score.py 2>&1 | tail -15
echo SMOKE_DONE
