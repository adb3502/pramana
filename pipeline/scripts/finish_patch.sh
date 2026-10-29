#!/usr/bin/env bash
# After a patch merge (scripts/patch_extract.py): validate, typecheck, Jev on disputed only (budget-gated), Opus adjudication,
# re-validate with verdicts folded in, ledger, summary line to logs/batch_summary.jsonl.
# Usage: scripts/finish_doc.sh PMC...   (B_MODEL env names B's model for the ledger; default sonnet)
set -uo pipefail
cd "$(dirname "$0")/.."; source .venv/bin/activate; set -a; source .env; set +a
DOC=$1
python - "$DOC" "${B_MODEL:-sonnet}" <<'PY'
import sys, json, pathlib
from epistemic import store, validate, typecheck
d, bm = sys.argv[1], sys.argv[2]
P = json.load(open(f"parsed/{d}.json"))
tc = {s: typecheck.check(P, json.load(open(f"ext/{d}.{s}.json"))) for s in ("A", "B")}
json.dump(tc, open(f"validation/{d}.typecheck.json", "w"), indent=1)
ref = json.load(open(f"reference/{d}.json")) if pathlib.Path(f"reference/{d}.json").exists() else None
r = validate.run(d, ".", ref)
store.append("validation_event", {"doc": d, "report_sha256": store.file_hash(f"validation/{d}.json"), "role_agreement": r["role_agreement"], "stage": "pre-adjudication",
                                  "typecheck_sha256": store.file_hash(f"validation/{d}.typecheck.json")})
print(json.dumps({"doc": d, "stage": "validated", "kappa": r["data_vs_not_kappa"], "role": r["role_agreement"], "disputes": r["needs_adjudication"] + r["data_disputes"],
                  "typecheck": {s: len(v) for s, v in tc.items()}}))
PY
if python scripts/jev_spent.py 4.50 >/dev/null; then
  python -m epistemic.verify "$DOC" jev --only-disputed || echo "jev failed $DOC"
else echo "jev budget stop reached; skipping jev for $DOC"; fi
python scripts/adjudicate.py "$DOC" || echo "adjudication failed $DOC"
python - "$DOC" <<'PY'
import sys, json, pathlib
from epistemic import store, validate
d = sys.argv[1]
ref = json.load(open(f"reference/{d}.json")) if pathlib.Path(f"reference/{d}.json").exists() else None
r = validate.run(d, ".", ref)
store.append("validation_event", {"doc": d, "report_sha256": store.file_hash(f"validation/{d}.json"), "data_sha256": store.file_hash(f"data/{d}.jsonl"),
                                  "role_agreement": r["role_agreement"], "adjudicated": r["adjudicated"], "stage": "post-adjudication"})
tc = json.load(open(f"validation/{d}.typecheck.json"))
jv = json.load(open(f"verification/{d}.jev.json"))["report"] if pathlib.Path(f"verification/{d}.jev.json").exists() else {}
adj = json.load(open(f"ext/{d}.adj.json")) if pathlib.Path(f"ext/{d}.adj.json").exists() else {}
data_n = sum(1 for l in open(f"data/{d}.jsonl") if json.loads(l).get("role"))
s = {"doc": d, "candidates": r["candidates"], "numbers": r["numbers"], "data_numbers": data_n, "kappa": r["data_vs_not_kappa"], "role_agreement": r["role_agreement"],
     "disputes": r["needs_adjudication"] + r["data_disputes"], "adjudicated": r["adjudicated"], "ratio_triplets": r["ratio_triplets"],
     "arith_fail": len(r["arithmetic_failures"]), "external": r["external"] and f'{r["external"]["found"]}/{r["external"]["total"]}',
     "typecheck_A": len(tc["A"]), "typecheck_B": len(tc["B"]), "jev_compared": jv.get("compared"), "jev_tokens": jv.get("input_tokens"), "jev_usd": jv.get("cost_usd"),
     "jev_agrees_adj": sum(1 for x in adj.get("decisions", []) if x.get("jev") and x.get("jev") == x.get("role")), "adj_cost_equiv": adj.get("cost_usd_equiv")}
open("logs/batch_summary.jsonl", "a").write(json.dumps(s) + "\n"); print(json.dumps(s))
PY
