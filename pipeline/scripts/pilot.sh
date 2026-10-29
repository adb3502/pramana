#!/usr/bin/env bash
# End-to-end pilot: fetch -> parse -> extract (A, B) -> validate -> store -> ledger.
# Usage: scripts/pilot.sh PMC3439152 PMC2729465 PMC2754877
set -euo pipefail
source .venv/bin/activate
mkdir -p raw parsed ext validation data
for DOC in "$@"; do
  python -m epistemic.fetch "$DOC"
  python -m epistemic.parse "raw/${DOC}.xml" "parsed/${DOC}.json"
  python - "$DOC" <<'PY'
import sys; from epistemic import store
d=sys.argv[1]; store.append("parse_event", {"doc": d, "parser": "jats-parse v2", "raw_sha256": store.file_hash(f"raw/{d}.xml"), "parsed_sha256": store.file_hash(f"parsed/{d}.json")})
PY
  scripts/extract.sh "$DOC"
  python - "$DOC" <<'PY'
import sys, json; from epistemic import store, validate
d=sys.argv[1]
for s,m in (("A","sonnet"),("B","opus")):
    store.append("extraction_event", {"doc": d, "extractor": m, "brief": "EXTRACT_BRIEF v2", "output_sha256": store.file_hash(f"ext/{d}.{s}.json")})
ref = None
try: ref = json.load(open(f"reference/{d}.json"))
except FileNotFoundError: pass
rep = validate.run(d, ".", ref)
store.append("validation_event", {"doc": d, "report_sha256": store.file_hash(f"validation/{d}.json"), "role_agreement": rep["role_agreement"]})
print(json.dumps({k: rep[k] for k in ("doc","numbers","data_vs_not_kappa","role_agreement","needs_adjudication","ratio_triplets","variable_alignment","model_alignment")}))
PY
done
python -m epistemic.store
python -m epistemic.store verify
