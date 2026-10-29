#!/usr/bin/env bash
# Full cheap pipeline per doc: fetch -> parse (sequential, polite) -> A (sonnet) + B (sonnet, order seed) in parallel -> finish_doc.sh.
# Docs run 3 at a time (6 headless Claude sessions). Usage: scripts/batch_full.sh PMC... PMC...
cd "$(dirname "$0")/.."; source .venv/bin/activate; mkdir -p raw parsed ext logs
OK=()
for DOC in "$@"; do
  [ -s "parsed/${DOC}.json" ] && { OK+=("$DOC"); continue; }
  if python -m epistemic.fetch "$DOC" && python -m epistemic.parse "raw/${DOC}.xml" "parsed/${DOC}.json"; then
    python -c "import sys; from epistemic import store; d=sys.argv[1]; store.append('parse_event', {'doc': d, 'parser': 'jats-parse v2.6', 'raw_sha256': store.file_hash(f'raw/{d}.xml'), 'parsed_sha256': store.file_hash(f'parsed/{d}.json')})" "$DOC"
    OK+=("$DOC")
  else echo "FAIL fetch/parse $DOC"; fi
done
one () {
  D=$1
  if ! SIDES="A:sonnet B:sonnet" scripts/extract.sh "$D"; then
    MISS=""; for S in A B; do [ -s "ext/${D}.${S}.json" ] || MISS="$MISS $S:sonnet"; done
    echo "retry $D:$MISS"; SIDES="${MISS# }" scripts/extract.sh "$D" || { echo "FAIL extract $D"; return; }
  fi
  python -c "import sys; from epistemic import store; d=sys.argv[1]; store.append('extraction_event', {'doc': d, 'extractor': 'sonnet', 'side': 'A', 'brief': 'EXTRACT_BRIEF v3', 'output_sha256': store.file_hash(f'ext/{d}.A.json')})" "$D"
  scripts/finish_doc.sh "$D" || echo "FAIL finish $D"
}
export -f one
printf "%s\n" "${OK[@]}" | xargs -P 3 -I{} bash -c 'one {}'
python -m epistemic.store; python -m epistemic.store verify; echo "batch_full done"
