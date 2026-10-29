"""External truth (item 5): match reference triplets [estimate, ci_low, ci_high] from a meta-analysis against the data layer
(data/<doc>.jsonl, same rule as validate.run: a candidate whose final roles hold one ratio estimate + ci_low + ci_high, values
rounded to 2 decimals). usage: external_check.py DOC REFFILE -> prints found/total, writes validation/external/<DOC>.<tag>.json"""
import sys, json, os, collections
RATIO = {"estimate_hr", "estimate_rr", "estimate_or", "estimate_irr"}
d, ref = sys.argv[1], sys.argv[2]
by = collections.defaultdict(list)
for l in open(f"data/{d}.jsonl"):
    r = json.loads(l); by[r["candidate"]].append(r)
vals = {}
for cid, rs in by.items():
    v = tuple(round(r["value"], 2) for r in rs if r["role"] in RATIO | {"ci_low", "ci_high"})
    if len(v) == 3: vals.setdefault(v, cid)
R = json.load(open(ref)); hits = [{"ref": t, "candidate": vals.get(tuple(round(x, 2) for x in t))} for t in R]
os.makedirs("validation/external", exist_ok=True)
tag = os.path.basename(ref)[len(d) + 1:-5] or "ref"
out = {"doc": d, "reference": ref, "found": sum(1 for h in hits if h["candidate"]), "total": len(hits), "hits": hits}
json.dump(out, open(f"validation/external/{d}.{tag}.json", "w"), indent=1)
print(d, tag, f'{out["found"]}/{out["total"]}', [h["ref"] for h in hits if not h["candidate"]])
