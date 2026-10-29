"""Re-run validate for docs (all finished docs by default) after a validator change; ledger each; then collect arithmetic findings.
Usage: python scripts/revalidate.py "<reason>" [doc ...]"""
import json, glob, pathlib, sys, math
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from epistemic import validate, store, typecheck
reason = sys.argv[1]
docs = sys.argv[2:] or sorted(pathlib.Path(p).stem for p in glob.glob("validation/*.json") if pathlib.Path(p).stem.count(".") == 0)
for d in docs:
    if not (pathlib.Path(f"ext/{d}.A.json").exists() and pathlib.Path(f"ext/{d}.B.json").exists()): continue
    ref = json.load(open(f"reference/{d}.json")) if pathlib.Path(f"reference/{d}.json").exists() else None
    r = validate.run(d, ".", ref)
    P = json.load(open(f"parsed/{d}.json"))
    tc = {s: typecheck.check(P, json.load(open(f"ext/{d}.{s}.json"))) for s in ("A", "B")}
    json.dump(tc, open(f"validation/{d}.typecheck.json", "w"), indent=1)
    store.append("validation_event", {"doc": d, "report_sha256": store.file_hash(f"validation/{d}.json"), "data_sha256": store.file_hash(f"data/{d}.jsonl"),
                                      "typecheck_sha256": store.file_hash(f"validation/{d}.typecheck.json"), "role_agreement": r["role_agreement"],
                                      "adjudicated": r.get("adjudicated"), "stage": f"revalidate: {reason}"})
    print(d, "arith_fail", len(r["arithmetic_failures"]), "typecheck", len(tc["A"]), len(tc["B"]))
# paper findings: arithmetic failures on agreed/adjudicated triplets, from all current validation reports
out = []
for p in sorted(glob.glob("validation/*.json")):
    d = pathlib.Path(p).stem
    if d.count("."): continue
    v = json.load(open(p)); P = json.load(open(f"parsed/{d}.json")); C = {c["id"]: c for c in P["candidates"]}
    for f in v["arithmetic_failures"]:
        c = C[f["candidate"].split("+")[0]]; e, (lo, hi) = f["estimate"], f["ci"]
        out.append({"doc": d, "candidate": f["candidate"], "anchor": c["anchor"], "text": c["text"][:80], "estimate": e, "ci": [lo, hi],
                    "finding": "estimate outside its CI" if not (lo <= e <= hi) else "ratio off log-centre of CI beyond rounding"})
# mission 2: findings confirmed against the typeset PDF (validation/pdf/<doc>.findings_in_pdf.json, checked on crops by Opus)
conf = {}
for p in glob.glob("validation/pdf/*.findings_in_pdf.json"):
    for x in json.load(open(p)):
        if x.get("confirmed_in_pdf"): conf[x["jats_candidate"]] = x
for o in out:
    x = conf.get(o["candidate"].split("+")[0])
    if x: o.update(confirmed_in_pdf=True, pdf_anchor=x["pdf_anchor"])
with open("logs/paper_findings.jsonl", "w") as fh:
    for o in out: fh.write(json.dumps(o) + "\n")
print("paper findings", len(out)); print(store.verify())
