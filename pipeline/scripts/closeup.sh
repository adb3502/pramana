#!/bin/bash
# Closure data run: supplements then figures, every paper. Idempotent (skips finished outputs).
cd ~/epistemic; set -a; . ./.env; set +a
for x in raw/*.xml; do d=$(basename $x .xml)
  [ -f parsed/${d}_S.json ] || [ -f work/closure/${d}.supp_done ] || { .venv/bin/python -m epistemic.supp $d 2>/dev/null | grep "^{" >> logs/supp.log; mkdir -p work/closure; touch work/closure/${d}.supp_done; }
  [ -f parsed/${d}_F.json ] || .venv/bin/python -m epistemic.figs $d 2>/dev/null | grep "^{" >> logs/figs.log
done
echo "== done $(date +%H:%M)" >> logs/figs.log
