#!/bin/bash
# Framework v4 rollout over every paper, after closeup.sh (supplements + figures). Needs local Qwen (B) and Laya ckpt4 (gate).
# Anthropic spend is capped by LLM_ANTHROPIC_CAP_USD (from .env).
cd ~/epistemic; set -a; . ./.env; set +a; PY=.venv/bin/python
until grep -q "== done" logs/figs.log; do sleep 300; done
until curl -s -m 3 127.0.0.1:8768/ > /dev/null; do (setsid nohup scripts/laya_server_epi4.sh >> logs/laya_epi4.log 2>&1 < /dev/null &); sleep 60; done
until curl -s -m 3 127.0.0.1:8000/v1/models > /dev/null; do sleep 60; done
curl -s -m 3 127.0.0.1:8768/ > /dev/null || { (setsid nohup scripts/laya_server_epi4.sh > logs/laya_epi4.log 2>&1 < /dev/null &); sleep 90; }
for x in raw/*.xml; do d=$(basename $x .xml)
  [ -f ext/$d.S4.json ] || $PY -m epistemic.structure $d
  for u in ${d}_S ${d}_F; do
    [ -f parsed/$u.json ] || continue
    [ -f ext/$u.A.json ] || $PY -m epistemic.passr A haiku $u
    [ -f ext/$u.B.json ] || $PY -m epistemic.passr B or_deepseek $u
    $PY -c "from epistemic import validate; validate.run('$u', '.', None, write_data=True)" 2>/dev/null
  done
  for u in $d ${d}_S ${d}_F; do
    [ -f data/$u.jsonl ] || continue
    [ -f work/closure/$u.gated ] && continue
    $PY -m epistemic.laya_gate $u && $PY -m epistemic.judge $u && touch work/closure/$u.gated
  done
  [ -f validation/$d.closure.json ] || $PY -m epistemic.closure $d
done 2>&1 | grep "^{" >> logs/rollout.log
$PY -m epistemic.gate --all > logs/gate.log 2>&1; tail -1 logs/gate.log >> logs/rollout.log; echo "== done $(date +%H:%M)" >> logs/rollout.log
