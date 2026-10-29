#!/bin/bash
# cancel the slow batch, then run Claude models synchronously (full price), cheapest first
cd ~/epistemic; source .venv/bin/activate; set -a; . ./.env; set +a
pkill -f bake_collect.py
curl -s -m 30 -X POST https://api.anthropic.com/v1/messages/batches/msgbatch_01CEgSqk26ag1rfR5bA9KE73/cancel -H "x-api-key: $ANTHROPIC_API_KEY" -H "anthropic-version: 2023-06-01" | head -c 300; echo
for m in haiku sonnet opus; do echo "== $m $(date +%H:%M)"; python scripts/bakeoff.py run $m | tail -1; done
python scripts/bake_score.py
echo "== done $(date +%H:%M)"
