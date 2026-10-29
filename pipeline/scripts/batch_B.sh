#!/usr/bin/env bash
# Extractor B (sonnet, order seed) 4 docs at a time; each doc goes straight to finish_doc.sh when its B is ready.
cd "$(dirname "$0")/.."
one () { SIDES="B:sonnet" scripts/extract.sh "$1" && scripts/finish_doc.sh "$1" || echo "FAIL B/finish $1"; }
export -f one
printf "%s\n" "$@" | xargs -P 4 -I{} bash -c 'one {}'
source .venv/bin/activate; python -m epistemic.store; python -m epistemic.store verify; echo "batch_B done"
