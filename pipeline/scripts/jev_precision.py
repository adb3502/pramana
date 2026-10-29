"""Jev as a flagger: precision of Jev flags on NON-disputed rows (both extractors agreed, Jev disagreed).
Samples flags from docs with all-candidate Jev runs, stratified into cross-family and within-family, and asks Opus
(blind to which answer is whose) which role is right. Writes verification/jev_flag_precision.json and a ledger event.
Usage: python scripts/jev_precision.py [n_cross] [n_within]"""
import json, random, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1])); sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from epistemic import typed, store
from epistemic.context import describe, table_index
from epistemic.typecheck import ROLES
from adjudicate import ask

DOCS = ["PMC2754877", "PMC2729465", "PMC3439152"]
PROMPT = """Each item is one number from a scientific paper on coffee and heart disease, with its context, and two candidate roles X and Y
from a controlled vocabulary. Decide which role is correct: "X", "Y", or "neither" (then give the right role).
Vocabulary: {roles}
Notes: category_bound_low/high bound an exposure or covariate category; category_value is a single-valued category; cutpoint divides groups;
n_participants is a population or group size; count is people with a characteristic; count_events is cases.
Return ONLY a JSON array: [{{"datum_id": ..., "pick": "X"|"Y"|"neither", "role": <correct role>, "why": <max 12 words>}}].
ITEMS:
{items}"""

def main(n_cross=40, n_within=20, seed=7):
    rnd = random.Random(seed); flags = []
    for d in DOCS:
        P = json.load(open(f"parsed/{d}.json")); T = table_index(P); C = {c["id"]: c for c in P["candidates"]}
        rows = [json.loads(l) for l in open(f"data/{d}.jsonl")]
        judged = json.load(open(f"verification/{d}.jev.json"))["judged"]
        for x in typed.compare(P, judged, [r for r in rows if r.get("agreed")])["disagreements"]:
            c = C[x["candidate"]]
            flags.append({"doc": d, "datum_id": f'{x["candidate"]}#{x["index"]}', "consensus": x["extractors"], "jev": x["judge"],
                          "cross": typed.fam(x["extractors"]) != typed.fam(x["judge"]),
                          "item": {"number": c["numbers"][x["index"]].get("raw"), "position": f'{x["index"] + 1} of {len(c["numbers"])}',
                                   "numbers_in_candidate": [n.get("raw") for n in c["numbers"]], "context": describe(P, c, T)}})
    cross = [f for f in flags if f["cross"]]; within = [f for f in flags if not f["cross"]]
    S = rnd.sample(cross, min(n_cross, len(cross))) + rnd.sample(within, min(n_within, len(within)))
    items = []
    for f in S:
        swap = rnd.random() < 0.5; f["X"], f["Y"] = (f["jev"], f["consensus"]) if swap else (f["consensus"], f["jev"])
        items.append({"datum_id": f["datum_id"], **f["item"], "X": f["X"], "Y": f["Y"]})
    res = []
    for k in range(0, len(items), 30):
        r, _ = ask(PROMPT.format(roles=" ".join(sorted(ROLES)), items=json.dumps(items[k:k + 30], ensure_ascii=False)), "opus"); res += r
    by = {x.get("datum_id"): x for x in res if isinstance(x, dict)}
    for f in S:
        x = by.get(f["datum_id"], {}); pick = x.get("pick")
        truth = f["X"] if pick == "X" else f["Y"] if pick == "Y" else x.get("role")
        f["verdict"] = "jev_right" if truth == f["jev"] else "consensus_right" if truth == f["consensus"] else "neither"
        f["why"] = x.get("why"); f.pop("item")
    def prec(fs): return {"n": len(fs), "jev_right": sum(f["verdict"] == "jev_right" for f in fs), "consensus_right": sum(f["verdict"] == "consensus_right" for f in fs),
                          "neither": sum(f["verdict"] == "neither" for f in fs)}
    out = {"flags_total": len(flags), "cross_family_flags": len(cross), "within_family_flags": len(within),
           "sample_cross": prec([f for f in S if f["cross"]]), "sample_within": prec([f for f in S if not f["cross"]]), "items": S}
    json.dump(out, open("verification/jev_flag_precision.json", "w"), indent=1)
    store.append("verification_event", {"doc": ",".join(DOCS), "backend": "opus-on-jev-flags", "input_tokens": 0,
                                        "report_sha256": store.file_hash("verification/jev_flag_precision.json")})
    print(json.dumps({k: v for k, v in out.items() if k != "items"}))

if __name__ == "__main__":
    a = [int(x) for x in sys.argv[1:3]]; main(*a)
