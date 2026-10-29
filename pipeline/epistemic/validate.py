"""Validator v2. Inputs: parsed/<doc>.json, ext/<doc>.<A|B>.json (brief v2 flat format).
Outputs: validation/<doc>.json and data/<doc>.jsonl (one row per number, the data layer).

v2.5: prelabelled candidates (brief v3) are excluded like copies; malformed and needs_check candidates are blocked from data.
Checks
  coverage   every candidate has exactly one record per extractor
  agreement  data vs not_data (kappa); role agreement per number;
             label agreement after aligning each extractor's private IDs (variable, group, model)
  arithmetic ratio estimates inside their CIs and log-centred; counts vs percents where both present
  external   optional reference values (e.g. a meta-analysis table) found at anchors
"""
import json, math, sys, pathlib
from .typecheck import log_centre
from collections import Counter, defaultdict

RATIO = {"estimate_hr", "estimate_rr", "estimate_or", "estimate_irr"}

def load(p): return json.load(open(p))

def index(ext):
    d = {r["id"]: r for r in ext.get("data", [])}
    nd = {r["id"]: r.get("reason") for r in ext.get("not_data", [])}
    return d, nd

def kappa(a, b):
    po = sum(x == y for x, y in zip(a, b)) / len(a)
    pa, pb = sum(a) / len(a), sum(b) / len(b); pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0, po

def align(pairs):
    """pairs: list of (labelA, labelB). Map each A label to its most frequent B partner; agreement = share consistent."""
    co = defaultdict(Counter)
    for a, b in pairs:
        if a is not None and b is not None: co[a][b] += 1
    mapping = {a: c.most_common(1)[0][0] for a, c in co.items()}
    ok = sum(1 for a, b in pairs if a is not None and b is not None and mapping.get(a) == b)
    n = sum(1 for a, b in pairs if a is not None and b is not None)
    return (ok / n if n else None), mapping

def run(doc, root=".", reference=None, sides=("A", "B"), write_data=None):
    """sides: which two extractions to compare (e.g. ("A", "L") for sonnet vs local). Only the default pair (or write_data=True)
    writes the data layer; other pairs write validation/<doc>.<X>-<Y>.json only.
    If ext/<doc>.adj.json exists, its verdicts fill the role of disputed numbers (adjudicated=True)."""
    root = pathlib.Path(root)
    P = load(root / "parsed" / f"{doc}.json")
    A = load(root / "ext" / f"{doc}.{sides[0]}.json"); B = load(root / "ext" / f"{doc}.{sides[1]}.json")
    if write_data is None: write_data = tuple(sides) == ("A", "B")
    adj = {}
    if write_data and (root / "ext" / f"{doc}.adj.json").exists():
        adj = {d["datum_id"]: d for d in load(root / "ext" / f"{doc}.adj.json").get("decisions", [])}
    Ad, An = index(A); Bd, Bn = index(B)
    C = P["candidates"]
    cov = {s: {"missing": [c["id"] for c in C if c["id"] not in d and c["id"] not in nd],
               "double": [c["id"] for c in C if c["id"] in d and c["id"] in nd]}
           for s, d, nd in (("A", Ad, An), ("B", Bd, Bn))}
    # v2.2: rowspan copies repeat the origin cell; they are not independent decisions or data
    copy = {c["id"] for c in C if "span_copy_of" in c["anchor"] or "nested_copy_of" in c["anchor"]}   # v2.4: table/fig text repeated in body
    # v2.5 (brief v3): prelabelled not_data (copies, lone 95 of "95% CI", repeated PDF headers) are decided by rule, not by A/B;
    # malformed cells and unverified PDF reads (needs_check) never become data.
    copy |= {c["id"] for c in C if c.get("prelabel") or c["anchor"].get("repeated_header")}
    blocked = {c["id"]: ("malformed" if c.get("malformed") else "needs_check") for c in C if c.get("malformed") or c.get("needs_check")}
    Cu = [c for c in C if c["id"] not in copy]
    Cu = [c for c in Cu if c["id"] not in blocked]
    k, po = kappa([c["id"] in Ad for c in Cu], [c["id"] in Bd for c in Cu])
    role_pairs, var_pairs, grp_pairs, mdl_pairs, rows = [], [], [], [], []
    conf = Counter()
    for c in C:
        ra, rb = Ad.get(c["id"]), Bd.get(c["id"])
        if ra and rb and c["id"] not in copy:
            var_pairs.append((ra.get("variable_id"), rb.get("variable_id")))
            grp_pairs.append((ra.get("group_id"), rb.get("group_id")))
            mdl_pairs.append((ra.get("model_id"), rb.get("model_id")))
        for i, num in enumerate(c["numbers"]):
            x = (ra or {}).get("roles", [None] * 99)[i] if ra and i < len(ra.get("roles", [])) else None
            y = (rb or {}).get("roles", [None] * 99)[i] if rb and i < len(rb.get("roles", [])) else None
            if c["id"] in copy:
                rows.append({"doc": doc, "datum_id": f"{c['id']}#{i}", "candidate": c["id"], "kind": c["kind"], "anchor": c["anchor"],
                             "value": num["value"], "qualifier": num.get("qualifier"), "raw": num.get("raw"), "role_A": x, "role_B": y,
                             "role": None, "agreed": False, "span_copy": True, "needs_adjudication": False, "data_dispute": False,
                             "prelabel": (c.get("prelabel") or {}).get("not_data")})
                continue
            if c["id"] in blocked:
                rows.append({"doc": doc, "datum_id": f"{c['id']}#{i}", "candidate": c["id"], "kind": c["kind"], "anchor": c["anchor"],
                             "value": num["value"], "qualifier": num.get("qualifier"), "raw": num.get("raw"), "role_A": x, "role_B": y,
                             "role": None, "agreed": False, "blocked": blocked[c["id"]], "needs_adjudication": False, "data_dispute": False})
                continue
            if x and y:
                role_pairs.append(x == y)
                if x != y: conf[(x, y)] += 1
            rows.append({"doc": doc, "datum_id": f"{c['id']}#{i}", "candidate": c["id"], "kind": c["kind"],
                         "anchor": c["anchor"], "value": num["value"], "qualifier": num.get("qualifier"), "raw": num.get("raw"),
                         "role_A": x, "role_B": y, "role": x if x == y else None, "agreed": bool(x and x == y),
                         "variable_A": (ra or {}).get("variable_id"), "variable_B": (rb or {}).get("variable_id"),
                         "group_A": (ra or {}).get("group_id"), "group_B": (rb or {}).get("group_id"),
                         "model_A": (ra or {}).get("model_id"), "model_B": (rb or {}).get("model_id"),
                         "reference_group_A": (ra or {}).get("reference_group_id"),
                         "source_A": (ra or {}).get("source"), "source_B": (rb or {}).get("source"),
                         "needs_adjudication": bool(x and y and x != y), "data_dispute": bool(x) != bool(y)})
            a = adj.get(f"{c['id']}#{i}")
            if a and (a.get("role") or a.get("not_data")):
                rows[-1].update({"role": a.get("role"), "adjudicated": True, "adj_not_data": bool(a.get("not_data")),
                                 "adjudicator": a.get("adjudicator"), "adj_choice": a.get("choice")})
    var_ag, var_map = align(var_pairs); grp_ag, _ = align(grp_pairs); mdl_ag, _ = align(mdl_pairs)
    # arithmetic on agreed ratio triplets
    by_c = defaultdict(list)
    for r in rows: by_c[r["candidate"]].append(r)
    trip, fails = 0, []
    for cid, rs in by_c.items():
        roles = [r["role"] for r in rs]
        if any(x in RATIO for x in roles) and "ci_low" in roles and "ci_high" in roles:
            k0 = next(k for k, r in enumerate(rs) if r["role"] in RATIO); re_ = rs[k0]
            # v2.5c: the CI must follow its estimate (merged cells can start with the previous column's CI)
            rl = next((r for r in rs[k0:] if r["role"] == "ci_low"), None); rh = next((r for r in rs[k0:] if r["role"] == "ci_high"), None)
            if rl is None or rh is None: continue
            e, lo, hi = re_["value"], rl["value"], rh["value"]
            trip += 1
            bad = not (lo <= e <= hi) or (lo > 0 and e > 0 and log_centre(e, lo, hi, (re_["raw"], rl["raw"], rh["raw"]))[0] > log_centre(e, lo, hi, (re_["raw"], rl["raw"], rh["raw"]))[1])
            if bad: fails.append({"candidate": cid, "estimate": e, "ci": [lo, hi]})
    # estimates and CIs split across adjacent text candidates (e.g. "RR 0.84, 0.74-0.94")
    text = [c for c in C if c["kind"] == "text_span"]
    def near(x, y):
        a1, a2 = x["anchor"], y["anchor"]
        return a1.get("section") == a2.get("section") and a1.get("para") == a2.get("para") and 0 <= a2["start"] - a1["end"] <= 40
    text_trips = []   # (estimate row, ci_low row, ci_high row, candidate ids)
    for ti, c1 in enumerate(text[:-1]):   # (not k: k holds the kappa)
        r1 = by_c[c1["id"]]
        if len(r1) != 1 or r1[0]["role"] not in RATIO or not near(c1, text[ti + 1]): continue
        r2 = by_c[text[ti + 1]["id"]]
        if [r["role"] for r in r2] == ["ci_low", "ci_high"]:
            text_trips.append((r1[0], r2[0], r2[1], [c1["id"], text[ti + 1]["id"]]))
        elif [r["role"] for r in r2] == ["ci_low"] and ti + 2 < len(text) and near(text[ti + 1], text[ti + 2]):
            # v2.5d: comma CI "0.68 (0.42, 1.10)" is three spans: estimate, ci_low, ci_high
            r3 = by_c[text[ti + 2]["id"]]
            if [r["role"] for r in r3] == ["ci_high"]:
                text_trips.append((r1[0], r2[0], r3[0], [c1["id"], text[ti + 1]["id"], text[ti + 2]["id"]]))
    for re1, rl, rh, ids in text_trips:
        e, lo, hi = re1["value"], rl["value"], rh["value"]; trip += 1
        o, t = log_centre(e, lo, hi, (re1["raw"], rl["raw"], rh["raw"])) if min(e, lo, hi) > 0 else (0, 1)
        if not (lo <= e <= hi) or o > t:
            fails.append({"candidate": "+".join(ids), "estimate": e, "ci": [lo, hi]})
    # v2.5: estimate and CI in separate table cells of the same row (HR | 95% CI, or HR | low | high), common in PDF tables
    cells = defaultdict(list)
    for c in C:
        a = c["anchor"]
        if c["kind"] == "table_cell" and c["id"] not in copy and "row" in a: cells[(a["table"], a["row"])].append(c)
    seen = set(by_c)  # candidates already used by in-cell triplets are skipped below
    in_cell = {cid for cid, rs in by_c.items() if any(r["role"] in RATIO for r in rs) and {"ci_low", "ci_high"} <= {r["role"] for r in rs}}
    for key, cs in cells.items():
        cs.sort(key=lambda c: c["anchor"]["col"])
        R = [[r for r in by_c[c["id"]]] for c in cs]
        for i in range(len(cs)):
            if cs[i]["id"] in in_cell: continue
            ro = [r["role"] for r in R[i]]
            if len(ro) != 1 or ro[0] not in RATIO: continue
            nxt = [r for c, rr in zip(cs[i + 1:i + 3], R[i + 1:i + 3]) for r in rr]
            lo = next((r for r in nxt[:2] if r["role"] == "ci_low"), None); hi = next((r for r in nxt[:2] if r["role"] == "ci_high"), None)
            if not (lo and hi) or any(r["candidate"] in in_cell for r in (lo, hi)): continue
            e, l, h = R[i][0]["value"], lo["value"], hi["value"]; trip += 1
            o, t = log_centre(e, l, h, (R[i][0]["raw"], lo["raw"], hi["raw"])) if min(e, l, h) > 0 else (0, 1)
            if not (l <= e <= h) or o > t:
                fails.append({"candidate": cs[i]["id"] + "+" + lo["candidate"] + ("" if hi["candidate"] == lo["candidate"] else "+" + hi["candidate"]), "estimate": e, "ci": [l, h], "split_cells": True})
    # v2.5d: estimate cell with its CI in the cell directly below (rows "Relative risk" / "(95% CI)", common in older tables)
    at = {(c["anchor"]["table"], c["anchor"]["row"], c["anchor"]["col"]): c for cs in cells.values() for c in cs}
    vert = []
    for (tb, r, col), c in at.items():
        rs = by_c[c["id"]]
        if c["id"] in in_cell or len(rs) != 1 or rs[0]["role"] not in RATIO: continue
        b = at.get((tb, r + 1, col))
        if not b or b["id"] in in_cell: continue
        rb = by_c[b["id"]]
        if [x["role"] for x in rb] != ["ci_low", "ci_high"]: continue
        vert.append((rs[0], rb[0], rb[1], [c["id"], b["id"]]))
        e, l, h = rs[0]["value"], rb[0]["value"], rb[1]["value"]; trip += 1
        o, t = log_centre(e, l, h, (rs[0]["raw"], rb[0]["raw"], rb[1]["raw"])) if min(e, l, h) > 0 else (0, 1)
        if not (l <= e <= h) or o > t:
            fails.append({"candidate": c["id"] + "+" + b["id"], "estimate": e, "ci": [l, h], "vertical": True})
    ext_found = None
    if reference:
        vals = {}
        for cid, rs in by_c.items():
            v = tuple(round(r["value"], 2) for r in rs if r["role"] in RATIO | {"ci_low", "ci_high"})
            if len(v) == 3: vals[v] = cid
        for re1, rl, rh, ids in text_trips + vert:   # text and vertical triplets (adjacent spans) count for external matching too
            vals.setdefault((round(re1["value"], 2), round(rl["value"], 2), round(rh["value"], 2)), ids[0])
        for key, cs in cells.items():   # split-cell triplets count for external matching too
            rs = [r for c in cs for r in by_c[c["id"]] if r["role"] in RATIO | {"ci_low", "ci_high"}]
            for i, r in enumerate(rs):
                if r["role"] in RATIO and [x["role"] for x in rs[i + 1:i + 3]] == ["ci_low", "ci_high"]:
                    vals.setdefault((round(r["value"], 2), round(rs[i + 1]["value"], 2), round(rs[i + 2]["value"], 2)), r["candidate"])
        hits = [{"ref": t, "candidate": vals.get(tuple(t))} for t in reference]
        ext_found = {"found": sum(1 for h in hits if h["candidate"]), "total": len(hits), "hits": hits}
    rep = {"doc": doc, "parser": P.get("parser"), "candidates": len(C), "numbers": len(rows), "span_copies": len(copy),
           "prelabelled": sum(1 for c in C if c.get("prelabel")), "blocked": dict(Counter(blocked.values())), "source_format": P.get("source_format", "jats"),
           "coverage": {s: {k2: len(v2) for k2, v2 in d.items()} for s, d in cov.items()},
           "data_vs_not_kappa": round(k, 3), "data_vs_not_agreement": round(po, 3),
           "role_agreement": round(sum(role_pairs) / len(role_pairs), 3) if role_pairs else None,
           "roles_compared": len(role_pairs), "needs_adjudication": sum(r["needs_adjudication"] for r in rows),
           "data_disputes": sum(r["data_dispute"] for r in rows), "adjudicated": sum(1 for r in rows if r.get("adjudicated")),
           "sides": list(sides),
           "top_role_confusions": [[list(k3), v3] for k3, v3 in conf.most_common(8)],
           "variable_alignment": var_ag, "group_alignment": grp_ag, "model_alignment": mdl_ag,
           "ratio_triplets": trip, "arithmetic_failures": fails, "external": ext_found,
           "missed_by_parser": {"A": len(A.get("missed_by_parser", [])), "B": len(B.get("missed_by_parser", []))}}
    (root / "validation").mkdir(exist_ok=True); (root / "data").mkdir(exist_ok=True)
    if not write_data:
        json.dump(rep, open(root / "validation" / f"{doc}.{sides[0]}-{sides[1]}.json", "w"), indent=1); return rep
    json.dump(rep, open(root / "validation" / f"{doc}.json", "w"), indent=1)
    with open(root / "data" / f"{doc}.jsonl", "w") as f:
        for r in rows: f.write(json.dumps(r) + "\n")
    return rep

if __name__ == "__main__":
    ref = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else None
    print(json.dumps(run(sys.argv[1], ".", ref), indent=1))
