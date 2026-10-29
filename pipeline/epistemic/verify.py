"""Third, independent check of every datum with a typed judge (Jev by default), after the two extractors.
Writes verification/<doc>.json and appends a ledger entry with tokens spent.
Usage: python -m epistemic.verify <doc> [jev|ollama] [--only-disputed]"""
import json, sys, pathlib
from . import typed, store

def run(doc, backend="jev", only_disputed=False):
    P = json.load(open(f"parsed/{doc}.json"))
    rows = [json.loads(l) for l in open(f"data/{doc}.jsonl")]
    if only_disputed:
        ids = {r["candidate"] for r in rows if r.get("needs_adjudication") or r.get("data_dispute")}
    else:
        ids = {r["candidate"] for r in rows if r.get("role_A") or r.get("role_B")}
    B = {"jev": typed.Jev, "ollama": typed.Ollama, "laya": getattr(typed, "Laya", None)}[backend]()
    judged = typed.judge(P, B, ids=ids, workers=6 if backend in ("jev", "laya") else 2)
    cmp = typed.compare(P, judged, rows)
    # where extractors disagreed, record what the judge sided with
    tie = []
    for r in rows:
        if not r.get("needs_adjudication"): continue
        i = int(r["datum_id"].rsplit("#", 1)[1]); j = (judged.get(r["candidate"], {}).get(f"role_{i}") or {}).get("answer")
        tie.append({"datum": r["datum_id"], "A": r["role_A"], "B": r["role_B"], "judge": j,
                    "verdict": "A" if j == r["role_A"] else "B" if j == r["role_B"] else "neither"})
    errors = sum(1 for v in judged.values() if "error" in v)
    rep = {"doc": doc, "backend": B.name, "candidates_judged": len(judged), "errors": errors,
           "agreement_with_extractor_consensus": cmp["agreement"], "family_agreement": cmp["family_agreement"], "compared": cmp["compared"],
           "disagreements": cmp["disagreements"], "tie_breaks": tie, "input_tokens": B.input_tokens,
           "cost_usd": round(B.input_tokens * 0.042 / 1e6, 4) if B.name == "jev" else 0.0}
    pathlib.Path("verification").mkdir(exist_ok=True)
    json.dump({"report": rep, "judged": judged}, open(f"verification/{doc}.{B.name}.json", "w"), indent=1)
    store.append("verification_event", {"doc": doc, "backend": B.name, "agreement": cmp["agreement"],
                                        "input_tokens": B.input_tokens, "report_sha256": store.file_hash(f"verification/{doc}.{B.name}.json")})
    return {k: rep[k] for k in ("doc", "backend", "candidates_judged", "errors", "agreement_with_extractor_consensus", "family_agreement", "compared", "input_tokens", "cost_usd")} | {"n_disagreements": len(rep["disagreements"]), "tie_breaks": len(tie)}

if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    print(json.dumps(run(a[0], a[1] if len(a) > 1 else "jev", "--only-disputed" in sys.argv)))
