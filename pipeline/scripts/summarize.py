"""Per-doc table from current artifacts (validation/, verification/, ext/*.adj.json). Usage: python scripts/summarize.py [--md]"""
import json, glob, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

def row(d):
    v = json.load(open(f"validation/{d}.json"))
    tcp = pathlib.Path(f"validation/{d}.typecheck.json")
    if tcp.exists():
        tc = json.load(open(tcp)); tca, tcb = len(tc["A"]), len(tc["B"])
    else:
        from epistemic import typecheck
        P = json.load(open(f"parsed/{d}.json"))
        tca, tcb = (len(typecheck.check(P, json.load(open(f"ext/{d}.{s}.json")))) for s in ("A", "B"))
    jv = json.load(open(f"verification/{d}.jev.json"))["report"] if pathlib.Path(f"verification/{d}.jev.json").exists() else {}
    adj = json.load(open(f"ext/{d}.adj.json")) if pathlib.Path(f"ext/{d}.adj.json").exists() else {"decisions": []}
    dec = adj["decisions"]
    data = sum(1 for l in open(f"data/{d}.jsonl") if json.loads(l).get("role"))
    ext = v.get("external"); P = json.load(open(f"parsed/{d}.json"))
    jev_ok = sum(1 for x in dec if x.get("jev") and x["jev"] == x.get("role"))
    return {"doc": d, "parser": P.get("parser"), "title": P.get("title", "")[:70], "candidates": v["candidates"], "numbers": v["numbers"],
            "span_copies": v.get("span_copies", 0), "data": data, "kappa": v["data_vs_not_kappa"], "agree": v.get("data_vs_not_agreement"),
            "role": v["role_agreement"], "disputes": v["needs_adjudication"] + v.get("data_disputes", 0), "adjudicated": v.get("adjudicated", 0),
            "triplets": v["ratio_triplets"], "arith_fail": len(v["arithmetic_failures"]),
            "external": f'{ext["found"]}/{ext["total"]}' if ext else "-", "tc": f"{tca}/{tcb}",
            "jev_scope": "all" if jv.get("candidates_judged", 0) > 100 and d in ("PMC2754877", "PMC2729465", "PMC3439152") else ("disputed" if jv else "-"),
            "jev_agree_adj": f"{jev_ok}/{len(dec)}" if dec else "-", "jev_usd": jv.get("cost_usd", 0), "adj_equiv_usd": adj.get("cost_usd_equiv", 0)}

if __name__ == "__main__":
    docs = sorted(pathlib.Path(p).stem for p in glob.glob("validation/*.json") if pathlib.Path(p).stem.count(".") == 0)
    R = [row(d) for d in docs]
    if "--md" in sys.argv:
        cols = ["doc", "candidates", "numbers", "span_copies", "data", "kappa", "role", "disputes", "triplets", "arith_fail", "external", "tc", "jev_agree_adj", "jev_usd", "adj_equiv_usd"]
        print("| " + " | ".join(cols) + " |"); print("|" + "---|" * len(cols))
        for r in R: print("| " + " | ".join(str(r[c]) for c in cols) + " |")
        print(f"\nTotals: docs {len(R)}, numbers {sum(r['numbers'] for r in R)}, data {sum(r['data'] for r in R)}, disputes {sum(r['disputes'] for r in R)}, "
              f"jev ${sum(r['jev_usd'] or 0 for r in R):.3f}, adjudication equiv ${sum(r['adj_equiv_usd'] or 0 for r in R):.2f}")
    else:
        for r in R: print(json.dumps(r))
