#!/usr/bin/env bash
# fetch -> parse (sequential, polite to NCBI) then extractor A (sonnet) 4 docs at a time. Ledger events for each step.
# Usage: scripts/batch_A.sh PMC... PMC...
set -uo pipefail
cd "$(dirname "$0")/.."; source .venv/bin/activate; mkdir -p raw parsed ext logs
OK=()
for DOC in "$@"; do
  if python -m epistemic.fetch "$DOC" && python -m epistemic.parse "raw/${DOC}.xml" "parsed/${DOC}.json"; then
    python -c "import sys; from epistemic import store; d=sys.argv[1]; store.append('parse_event', {'doc': d, 'parser': 'jats-parse v2', 'raw_sha256': store.file_hash(f'raw/{d}.xml'), 'parsed_sha256': store.file_hash(f'parsed/{d}.json')})" "$DOC"
    OK+=("$DOC")
  else echo "FAIL fetch/parse $DOC"; fi
done
extract_A () {
  SIDES="A:sonnet" scripts/extract.sh "$1" && python -c "import sys; from epistemic import store; d=sys.argv[1]; store.append('extraction_event', {'doc': d, 'extractor': 'sonnet', 'side': 'A', 'brief': 'EXTRACT_BRIEF v2', 'output_sha256': store.file_hash(f'ext/{d}.A.json')})" "$1" || echo "FAIL extract A $1"
}
export -f extract_A
printf "%s\n" "${OK[@]}" | xargs -P 4 -I{} bash -c 'extract_A {}'
echo "batch_A done"
