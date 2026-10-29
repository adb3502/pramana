"""Score bake-off outputs against the gold data layer. Usage: python scripts/bake_score.py -> work/bake/scores.json"""
import os, sys, json, glob, itertools, collections
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
B = "work/bake"
FAM = lambda r: "est" if (r or "").startswith("estimate_") else ("cnt" if r in ("count", "n_participants", "count_events") else ("cat" if r in ("category_bound_low", "category_bound_high", "category_value", "cutpoint", "dose") else r))
sl = json.load(open(f"{B}/slice.json"))
N = int(sys.argv[1]) if len(sys.argv) > 1 else None  # score only the first N docs (common subset)
if N: sl["docs"] = sl["docs"][:N]; sl["ding_docs"] = [d for d in sl["ding_docs"] if d in sl["docs"]]
def gold(doc):
    g = {}
    for l in open(f"data/{doc}.jsonl"):
        r = json.loads(l)
        if r.get("span_copy") or r.get("nested_copy"): continue
        g[(r["candidate"], int(r["datum_id"].rsplit("#", 1)[1]))] = r
    return g
G = {d: gold(d) for d in sl["docs"]}
P = {d: {c["id"]: c for c in json.load(open(f"parsed/{d}.json"))["candidates"]} for d in sl["docs"]}
def preds(name):
    out = {}; stats = collections.Counter()
    for f in glob.glob(f"{B}/{name}/*.json"):
        if f.endswith(".err.json"):
            if os.path.basename(f).split(".")[0] in P: stats["errors"] += 1
            continue
        x = json.load(open(f))
        if x["doc"] not in P: continue
        stats["chunks"] += 1; stats["in"] += x.get("in", 0); stats["out"] += x.get("out", 0); stats["usd"] += x.get("usd", 0)
        if not x.get("parsed"): stats["parse_fail"] += 1; continue
        got = {str(it.get("id")): it for it in x["items"] if isinstance(it, dict)}
        for cid in x["ids"]:
            it = got.get(cid); n = len(P[x["doc"]][cid]["numbers"])
            if it is None: stats["missing_items"] += 1; continue
            roles = it.get("r") or []
            dv = it.get("d")
            d = (bool(roles) and dv not in (0, False, "0")) or dv in (1, True, "1")
            if dv in (0, False, "0") and it.get("why"): d = False
            for i in range(n):
                out[(x["doc"], cid, i)] = (roles[i] if d and i < len(roles) else None) if d else None
    return out, stats
names = sorted(os.path.basename(p) for p in glob.glob(f"{B}/*") if os.path.isdir(p))
S, PR = {}, {}
for nm in names:
    pr, st = preds(nm); PR[nm] = pr
    tot = ex = fam = adjn = adjok = 0; dv = collections.Counter()
    for d in sl["docs"]:
        for (cid, i), r in G[d].items():
            k = (d, cid, i)
            if k not in pr: continue
            gr, p = r.get("role"), pr[k]
            dv[(bool(gr), bool(p))] += 1
            if gr:
                tot += 1; ex += p == gr; fam += FAM(p) == FAM(gr)
                if r.get("needs_adjudication") or (r.get("role_A") != r.get("role_B")): adjn += 1; adjok += p == gr
    n = sum(dv.values()); po = (dv[(True, True)] + dv[(False, False)]) / max(1, n)
    pa = ((dv[(True, True)] + dv[(True, False)]) * (dv[(True, True)] + dv[(False, True)]) + (dv[(False, False)] + dv[(False, True)]) * (dv[(False, False)] + dv[(True, False)])) / max(1, n * n)
    # Ding: candidates whose three numbers equal a reference triplet
    dhit = dok = 0
    have = {k[0] for k in pr}
    for d in sl["ding_docs"]:
        if d not in have: continue
        refs = []
        for f in (f"reference/{d}.json", f"reference/{d}.ding.json"):
            if os.path.exists(f): refs += [t for t in json.load(open(f)) if t not in refs]
        for trip in refs:
            for cid, c in P[d].items():
                vals = [x.get("value") for x in c["numbers"]]
                if len(vals) == 3 and all(v is not None and abs(v - t) < 1e-9 for v, t in zip(vals, trip)):
                    dhit += 1; rr = [pr.get((d, cid, i)) for i in range(3)]
                    dok += (rr[0] or "").startswith("estimate_") and rr[1] == "ci_low" and rr[2] == "ci_high"; break
    S[nm] = {"numbers_scored": tot, "role_exact": round(ex / max(1, tot), 4), "role_family": round(fam / max(1, tot), 4),
             "adjudicated_rows": adjn, "adjudicated_exact": round(adjok / max(1, adjn), 4),
             "data_kappa": round((po - pa) / (1 - pa), 4) if pa < 1 else None, "ding_found": dhit, "ding_correct": dok,
             "chunks": st["chunks"], "parse_fail": st["parse_fail"], "missing_items": st["missing_items"], "errors": st["errors"],
             "tokens_in": st["in"], "tokens_out": st["out"], "usd": round(st["usd"], 4), "usd_per_paper": round(st["usd"] / max(1, len({k[0] for k in pr})), 4)}
# pairwise dispute rate on gold-data numbers both labeled
pairs = {}
for a, b in itertools.combinations(names, 2):
    both = dis = 0
    for d in sl["docs"]:
        for (cid, i), r in G[d].items():
            if not r.get("role"): continue
            k = (d, cid, i)
            if k in PR[a] and k in PR[b]: both += 1; dis += PR[a][k] != PR[b][k]
    if both: pairs[f"{a}+{b}"] = round(dis / both, 4)
json.dump({"scores": S, "pair_dispute_rate": pairs}, open((f"{B}/scores_first{N}.json" if N else f"{B}/scores.json"), "w"), indent=1)
for nm, s in sorted(S.items(), key=lambda kv: -kv[1]["role_exact"]): print(nm, s)
print("pairs (lowest dispute):", sorted(pairs.items(), key=lambda kv: kv[1])[:10])
