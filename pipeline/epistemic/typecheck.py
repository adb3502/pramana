"""Deterministic type checks on an extraction (brief v2 format). No model involved.
Schema: every record well-formed, roles from the controlled vocabulary, ids resolvable.
Value plausibility per role: percents 0..100, p 0..1, ratios > 0, SD >= 0, counts whole and >= 0,
years 1900..2030, interval bounds ordered and bracketing their estimate.
Returns a list of findings; each finding is either an extraction error or an error in the paper."""
import json, sys, math
from collections import defaultdict

ROLES = set("""estimate_hr estimate_rr estimate_or estimate_irr estimate_beta estimate_difference ci_low ci_high ci_level se
p_value p_trend p_interaction p_heterogeneity mean sd median iqr_low iqr_high range_low range_high percent count count_events
n_participants person_years rate rate_denominator correlation power alpha category_bound_low category_bound_high category_value
cutpoint dose age_bound_low age_bound_high year date_part duration_years followup_years serving_size content_per_serving
questionnaire_cycle version_number code hypothetical_effect degrees_of_freedom sidedness items_count other""".split())
REASONS = {"citation_number", "table_or_figure_number", "section_number", "ci_level_label", "unit_denominator",
           "software_version", "grant_number", "page_or_volume", "prose_word", "parse_artifact",
           "copy"}   # brief v3 prelabel reason (span/nested copies, repeated PDF headers)
RATIO = {"estimate_hr", "estimate_rr", "estimate_or", "estimate_irr"}

EST = RATIO | {"mean", "estimate_beta", "estimate_difference", "median"}

def half_unit(raw):
    """Half of the last printed decimal place, e.g. '0.83' -> 0.005, '12' -> 0.5."""
    raw = str(raw or "").lstrip("<>=~≤≥ ").replace(",", "")
    return 0.5 * 10 ** -len(raw.split(".")[1]) if "." in raw else 0.5

def log_centre(est, lo, hi, raws=(None, None, None)):
    """(offset, tolerance): how far a ratio sits from the log-midpoint of its CI, and the most rounding alone can explain (+0.01 slack)."""
    # mission 2: a value printed at one unit of its last decimal (0.01 with 2 decimals) is censored by rounding (the true value can be
    # far smaller), so its log distance is unknowable: report no offset rather than a false finding (PMC12517802 "0.01 (0.01-21.49)")
    if any(v is not None and r is not None and v <= 2 * half_unit(r) + 1e-12 for v, r in ((est, raws[0]), (lo, raws[1]))):
        return 0.0, 1.0
    off = abs(math.log(est) - (math.log(lo) + math.log(hi)) / 2)
    tol = half_unit(raws[0]) / est + (half_unit(raws[1]) / lo + half_unit(raws[2]) / hi) / 2 + 0.01
    return off, tol

def triplets(roles, numbers):
    """Walk the roles in order; each ci_low..ci_high pair binds to the nearest preceding estimate (if any)."""
    out, est, ratio, lo, raws = [], None, False, None, [None, None]
    for role, n in zip(roles, numbers):
        v = n.get("value")
        if v is None: continue
        if role in EST: est, ratio, lo, raws = v, role in RATIO, None, [n.get("raw"), None]
        elif role == "ci_low": lo, raws[1] = v, n.get("raw")
        elif role == "ci_high" and lo is not None:
            out.append((est, lo, v, ratio, (raws[0], raws[1], n.get("raw")))); est, lo = None, None
    return out

def check(P, E):
    F = []
    cands = {c["id"]: c for c in P["candidates"]}
    ids = {"variable_id": {v["variable_id"] for v in E.get("variables", [])},
           "group_id": {g["group_id"] for g in E.get("groups", [])},
           "model_id": {m["model_id"] for m in E.get("models", [])}}
    ids["reference_group_id"] = ids["group_id"]
    seen = defaultdict(int)
    for r in E.get("data", []): seen[r["id"]] += 1
    for r in E.get("not_data", []): seen[r["id"]] += 1
    for cid in cands:
        if seen[cid] != 1: F.append({"kind": "schema", "id": cid, "msg": f"classified {seen[cid]} times"})
    for r in E.get("not_data", []):
        if r.get("reason") not in REASONS: F.append({"kind": "schema", "id": r["id"], "msg": f"bad reason {r.get('reason')}"})
    for r in E.get("data", []):
        c = cands.get(r["id"])
        if not c: F.append({"kind": "schema", "id": r["id"], "msg": "unknown candidate"}); continue
        roles = r.get("roles") or []
        if len(roles) != len(c["numbers"]):
            F.append({"kind": "schema", "id": r["id"], "msg": f"{len(roles)} roles for {len(c['numbers'])} numbers"}); continue
        for k, allowed in ids.items():
            v = r.get(k)
            if v is not None and allowed and v not in allowed:
                F.append({"kind": "schema", "id": r["id"], "msg": f"{k} {v} not defined"})
        # multi-number candidates (a row of RR (CI) triplets, several p values in one sentence) repeat roles legitimately;
        # what must hold is that CI bounds pair up
        if len(roles) > 1 and roles.count("ci_low") != roles.count("ci_high"): F.append({"kind": "schema", "id": r["id"], "msg": f"unpaired CI bound in {roles}"})
        vals = {}
        for role, n in zip(roles, c["numbers"]):
            if role not in ROLES: F.append({"kind": "schema", "id": r["id"], "msg": f"role {role} not in vocabulary"}); continue
            v = n.get("value"); q = n.get("qualifier")
            if v is None: continue
            vals[role] = v
            bad = None
            if role == "percent" and not (0 <= v <= 100): bad = "percent outside 0-100"
            elif role.startswith("p_") and role != "p_trend" and not (0 <= v <= 1): bad = "p outside 0-1"
            elif role == "p_trend" and not (0 <= v <= 1): bad = "p outside 0-1"
            elif role in RATIO and v <= 0: bad = "ratio not positive"
            elif role in ("sd", "se", "person_years") and v < 0: bad = "negative spread or time"
            elif role in ("count", "count_events", "n_participants") and (v < 0 or v != int(v)): bad = "count not a whole non-negative number"
            elif role == "year" and not (1900 <= v <= 2030): bad = "implausible year"
            elif role == "correlation" and not (-1 <= v <= 1): bad = "correlation outside -1..1"
            if bad: F.append({"kind": "value", "id": r["id"], "msg": bad, "value": v, "qualifier": q})
        for est, lo, hi, ratio, raws in triplets(roles, c["numbers"]):
            if lo > hi: F.append({"kind": "value", "id": r["id"], "msg": "CI bounds reversed", "value": [lo, hi]})
            if est is not None and not (lo <= est <= hi):
                F.append({"kind": "value", "id": r["id"], "msg": "estimate outside its CI", "value": [est, lo, hi]})
            if ratio and lo > 0 and est and est > 0 and hi > 0:
                off, tol = log_centre(est, lo, hi, raws)
                if off > tol: F.append({"kind": "value", "id": r["id"], "msg": "ratio not centred in CI on log scale beyond rounding", "value": [est, lo, hi], "off": round(off, 3), "tol": round(tol, 3)})
        if "count" in vals and "percent" in vals and vals["count"] > 0 and "n" in r:
            pass
    return F

if __name__ == "__main__":
    P = json.load(open(sys.argv[1])); E = json.load(open(sys.argv[2]))
    F = check(P, E)
    print(json.dumps({"findings": len(F), "by_kind": {k: sum(1 for f in F if f["kind"] == k) for k in ("schema", "value")}, "sample": F[:10]}, indent=1))
