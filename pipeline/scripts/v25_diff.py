"""Parse every JATS doc with the current parser into work/v25/<doc>.v25.json and compare with the v2.4 parse
(work/v25/<doc>.v24.json). A doc needs re-extraction only if candidate ids or number counts change;
qualifier/value-only changes keep the extraction valid (same ids and indices) and need revalidation only."""
import sys, os, json, glob, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from epistemic import parse
out = {}
for p in sorted(glob.glob("work/v25/*.v24.json")):
    d = os.path.basename(p).split(".")[0]
    if not os.path.exists(f"raw/{d}.xml"): continue
    old = json.load(open(p))
    if old.get("source_format") == "pdf": continue
    new = parse.parse(f"raw/{d}.xml"); json.dump(new, open(f"work/v25/{d}.v25.json", "w"), indent=1)
    o = {c["id"]: c for c in old["candidates"]}; n = {c["id"]: c for c in new["candidates"]}
    shape = lambda c: (c["kind"], len(c["numbers"]))
    struct = sum(1 for i in set(o) | set(n) if i not in o or i not in n or shape(o[i]) != shape(n[i]))
    vals = sum(1 for i in set(o) & set(n) if shape(o[i]) == shape(n[i]) and [(x["value"], x["qualifier"]) for x in o[i]["numbers"]] != [(x["value"], x["qualifier"]) for x in n[i]["numbers"]])
    pre = collections.Counter(c["prelabel"]["not_data"] for c in new["candidates"] if c.get("prelabel"))
    mal = sum(1 for c in new["candidates"] if c.get("malformed"))
    out[d] = {"cands_old": len(o), "cands_new": len(n), "struct_changed": struct, "value_or_qualifier_changed": vals, "prelabel": dict(pre), "malformed": mal}
    print(d, out[d], flush=True)
json.dump(out, open("work/v25/diff.json", "w"), indent=1)
