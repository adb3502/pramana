"""Compact, topic-free export of the graph for the explorer page: work/graph/explorer.json."""
import os, json, collections

def run():
    E = json.load(open("work/graph/estimates.json")); G = json.load(open("work/graph/graph.json"))
    N = {n["id"]: n for n in G["nodes"]}
    S, strs = {}, []
    def s(x):
        x = "" if x is None else str(x)
        if x not in S: S[x] = len(strs); strs.append(x)
        return S[x]
    studies = [n for n in G["nodes"] if n["type"] == "study"]; sidx = {n["doc"]: i for i, n in enumerate(studies)}
    src_of = {}; srcdocs = collections.defaultdict(set)
    for ed in G["edges"]:
        if ed["type"] == "USES": src_of[N[ed["src"]]["doc"]] = N[ed["dst"]]["label"]; srcdocs[N[ed["dst"]]["label"]].add(N[ed["src"]]["doc"])
    # concept profile: roles, studies, distinct study-level terms and units (construct heterogeneity)
    prof = collections.defaultdict(lambda: {"roles": collections.Counter(), "docs": set(), "terms": collections.Counter(), "units": collections.Counter(), "adjusted_in": 0})
    for ed in G["edges"]:
        if ed["type"] == "MEASURES":
            p = prof[ed["dst"]]; v = N[ed["src"]]; p["roles"][ed["props"].get("role") or "other"] += 1; p["docs"].add(v["doc"])
            if ed["props"].get("term"): p["terms"][ed["props"]["term"]] += 1
            if ed["props"].get("unit"): p["units"][ed["props"]["unit"]] += 1
        elif ed["type"] == "ADJUSTS_FOR":
            t = ed["dst"]
            if t.startswith("var:"):
                for e2 in G["edges"]:
                    pass
    adj = collections.Counter()
    m2c = {}
    for ed in G["edges"]:
        if ed["type"] == "MEASURES": m2c[ed["src"]] = ed["dst"]
    for ed in G["edges"]:
        if ed["type"] == "ADJUSTS_FOR":
            c = m2c.get(ed["dst"]) or (ed["dst"] if ed["dst"].startswith("concept:") else None)
            if c: adj[c] += 1
    concepts = []; cidx = {}
    for n in G["nodes"]:
        if n["type"] != "concept": continue
        p = prof.get(n["id"])
        if not p and not adj.get(n["id"]): continue
        cidx[n["id"]] = len(concepts)
        concepts.append([n["id"].split(":", 1)[1], n["label"], int(bool(n["props"].get("verified"))), len(p["docs"]) if p else 0,
                         dict(p["roles"]) if p else {}, [t for t, _ in p["terms"].most_common(6)] if p else [], [u for u, _ in p["units"].most_common(3)] if p else [], adj.get(n["id"], 0)])
    pairs = []
    for ed in G["edges"]:
        if ed["type"] == "EVIDENCE" and ed["src"] in cidx and ed["dst"] in cidx:
            pr = ed["props"]; d = pr.get("directions") or {}
            pairs.append([cidx[ed["src"]], cidx[ed["dst"]], pr["estimates"], pr["studies"], pr["sources"], d.get("lower", 0), d.get("null", 0), d.get("higher", 0), d.get("no_ci", 0)])
    claims = collections.defaultdict(list)
    for ed in G["edges"]:
        if ed["type"] == "SUPPORTED_BY": claims[ed["dst"]].append(ed["src"])
    rows = []
    for r in E:
        if r["is_reference"] or r.get("source_flag") == "external" or not (r["exposure_concept"] and r["outcome_concept"]): continue
        x, o = f"concept:{r['exposure_concept']}", f"concept:{r['outcome_concept']}"
        if x not in cidx or o not in cidx: continue
        cl = claims.get(r["id"], [])
        rows.append([sidx.get(r["doc"], -1), cidx[x], cidx[o], s(r["measure"]), r["value"], r["ci_low"], r["ci_high"], r["level_low"], r["level_high"], s(r["level_unit"]),
                     r["ref_low"], r["ref_high"], s(r["exposure_term"]), s(r["outcome_term"]), s(r["level_label"]), s(r["ref_label"]), s(r["model_label"]),
                     len(r["covariates"]), s(", ".join(r["covariates"][:30])), s(r["p"]), int(r["adjudicated"]), s(r["unit"][len(r["doc"]):] or "main"),
                     s(json.dumps(r["where"])), s(";".join(r["flags"])), s(" | ".join((N[c]["props"].get("relation") or "") + ": " + (N[c]["label"] or "")[:220] for c in cl[:2]))])
    per = collections.defaultdict(lambda: {"claims": [], "silent": [], "bias": [], "assume": []})
    for n in G["nodes"]:
        d = n.get("doc")
        if n["type"] == "claim": per[d]["claims"].append([n["props"].get("relation"), n["props"].get("location"), (n["label"] or "")[:260]])
        elif n["type"] == "analysis" and n["props"].get("status") in ("not_reported", "reported_without_numbers"): per[d]["silent"].append([n["props"]["status"], n["props"].get("kind"), (n["label"] or "")[:200]])
        elif n["type"] == "bias_flag": per[d]["bias"].append([n["props"].get("stage"), n["props"].get("severity"), (n["label"] or "")[:220]])
        elif n["type"] == "assumption": per[d]["assume"].append([n["props"].get("status"), (n["label"] or "")[:200]])
    ST = []
    for n in studies:
        pr = n["props"]; q = per[n["doc"]]
        ST.append([n["doc"], n["label"], pr.get("design"), src_of.get(n["doc"]), pr.get("closure"), pr.get("gate"), q["claims"][:12], q["silent"][:12], q["bias"][:12], q["assume"][:8]])
    cols = ["study", "x", "y", "measure", "value", "lo", "hi", "lvl_lo", "lvl_hi", "lvl_unit", "ref_lo", "ref_hi", "x_term", "y_term", "level", "ref", "model", "ncov",
            "covariates", "p", "adjudicated", "part", "where", "flags", "claims"]
    counts = dict(collections.Counter(n["type"] for n in G["nodes"]))
    out = {"corpus": os.environ.get("CORPUS_LABEL", "Corpus 1: coffee and cardiovascular outcomes"), "cols": cols, "strings": strs, "rows": rows, "concepts": concepts,
           "pairs": pairs, "studies": ST, "sources": {k: sorted(v) for k, v in srcdocs.items()}, "counts": counts}
    json.dump(out, open("work/graph/explorer.json", "w"), separators=(",", ":"))
    return {"rows": len(rows), "concepts": len(concepts), "pairs": len(pairs), "bytes": os.path.getsize("work/graph/explorer.json")}

if __name__ == "__main__":
    print(json.dumps(run()))
