#!/bin/bash
# Batch-mode thread: run every paper's pipeline with Anthropic calls queued (LLM_BATCH=collect), submit the queue as Message Batches
# (50% off), wait, and repeat until a round queues nothing new. Usage: scripts/thread.sh <candidates.json> <corpus_tag> [workers]
cd ~/epistemic; set -a; . ./.env; set +a; PY=.venv/bin/python; W=${3:-32}; export PASSR_B=${PASSR_B:-laya} LLM_LOCAL_SLOTS=${LLM_LOCAL_SLOTS:-6} LLM_BATCH_QUEUE=work/batchq/queue_$2${PDFFLAG:+_pdf}.jsonl
$PY -m epistemic.batch wait | tail -1   # finish batches a previous run left in flight
for round in $(seq 1 40); do
  echo "== round $round $(date +%H:%M)"
  rm -f $LLM_BATCH_QUEUE
  LLM_BATCH=collect $PY scripts/ingest.py --workers $W --from "$1" --corpus "$2" $PDFFLAG | grep -c '"done"' | sed 's/^/papers done: /'
  n=$( [ -f $LLM_BATCH_QUEUE ] && wc -l < $LLM_BATCH_QUEUE || echo 0 ); echo "queued $n"
  [ "$n" -eq 0 ] && break
  $PY -m epistemic.batch submit && $PY -m epistemic.batch wait | tail -1
done
echo "== thread done $(date +%H:%M)"
