"""Measure how much of extraction can be done locally: header rules (tier 0) and Laya (tier 1), against the gold data layer.
Usage: python route_measure.py [n_laya_docs]   Writes work/route_measure.json"""
import json, glob, os, re, sys, random, collections
sys.path.insert(0, os.path.expanduser("~/epistemic"))
os.chdir(os.path.expanduser("~/epistemic"))
from epistemic.context import describe, table_index

EX = {"PMC2737446", "PMC1025516", "PMC3071630"}
TYPES = [(r"hazard ratio|\bHRs?\b", "estimate_hr"), (r"relative risk|risk ratio|\bRRs?\b", "estimate_rr"),
         (r"odds ratio|\bORs?\b", "estimate_or"), (r"incidence rate ratio|\bIRRs?\b", "estimate_irr")]
NUM = r"[<>≤≥]?\s*-?\d[\d.,]*"
TRIP = re.compile(r"^\s*" + NUM + r"\s*\(\s*" + NUM + r"\s*(?:-|–|—|to|,|;)\s*" + NUM + r"\s*\)\s*[*†‡§a-z]{0,3}\s*$")
PAIR = re.compile(r"^\s*" + NUM + r"\s*(?:\(\s*" + NUM + r"\s*%?\s*\)|±\s*" + NUM + r")\s*[*†‡a-z]{0,3}\s*$")
ONE = re.compile(r"^\s*" + NUM + r"\s*%?\s*[*†‡§a-z]{0,3}\s*$")
FAM = {"estimate_hr": "est", "estimate_rr": "est", "estimate_or": "est", "estimate_irr": "est",
       "count": "cnt", "n_participants": "cnt", "count_events": "cnt"}

def etype(text):
    for pat, est in TYPES:
        phrase, *abbr = pat.split("|")
        if re.search(phrase, text, re.I) or any(re.search(a, text) for a in abbr): return est
    return None

def rule_roles(c, ctx):
    n = len(c["numbers"])
    if "row" not in c["anchor"]: return None
    hdr = ctx.get("column_header") or ""; h = hdr.lower()
    rl = ((ctx.get("row_label") or "") + " " + (ctx.get("row_section") or "")).lower()
    cap = ctx.get("table_caption") or ""
    t = c["text"]
    if TRIP.match(t) and n == 3:
        if "ci" in h or "ci" in cap.lower() or "confidence" in (h + cap.lower()):
            return [etype(hdr) or etype(cap) or "estimate?", "ci_low", "ci_high"]
        if "median" in h and ("iqr" in h or "interquartile" in h): return ["median", "iqr_low", "iqr_high"]
        if "range" in h: return [None, "range_low", "range_high"]
        return None
    if PAIR.match(t) and n == 2:
        if "mean" in h and ("sd" in h or "±" in h or "standard deviation" in h): return ["mean", "sd"]
        if re.search(r"(\bn\b|\bno\.?|number)\s*\(%\)", h) or (h.strip().endswith("(%)") and "mean" not in h): return ["count", "percent"]
        return None
    if ONE.match(t) and n == 1:
        for txt in (h, rl):
            if re.search(r"p\s*(for|-)?\s*trend|ptrend", txt): return ["p_trend"]
            if re.search(r"p\s*(for|-)?\s*interaction", txt): return ["p_interaction"]
            if re.search(r"person[- ]years?", txt): return ["person_years"]
        if re.search(r"(^|\s)p(\s*value|-value)?\s*$", h.strip()): return ["p_value"]
        if re.search(r"(no\.?|number) of (cases|deaths|events)|^\s*(cases|deaths|events)\s*$", rl): return ["count_events"]
        if h.strip() in ("%", "(%)", "percent"): return ["percent"]
    return None

def gold_for(doc):
    g = collections.defaultdict(dict); copies = set()
    for l in open(f"data/{doc}.jsonl"):
        r = json.loads(l)
        i = int(r["datum_id"].rsplit("#", 1)[1])
        if r.get("span_copy") or r.get("nested_copy"): copies.add(r["candidate"]); continue
        g[r["candidate"]][i] = r.get("role")
    return g, copies

docs = sorted(os.path.basename(f)[:-6] for f in glob.glob("data/*.jsonl"))
docs = [d for d in docs if d not in EX and os.path.exists(f"parsed/{d}.json")]
S = collections.Counter(); per_role = collections.defaultdict(lambda: [0, 0]); wrong = []
for d in docs:
    P = json.load(open(f"parsed/{d}.json")); T = table_index(P); g, copies = gold_for(d)
    for c in P["candidates"]:
        if c["id"] in copies or not c["numbers"]: continue
        gold = g.get(c["id"], {})
        nn = len(c["numbers"]); S["numbers"] += nn
        gr = [gold.get(i) for i in range(nn)]
        S["gold_data_numbers"] += sum(1 for x in gr if x)
        pl = c.get("prelabel")
        if pl and pl.get("not_data"):
            S["prelabel_numbers"] += nn; S["prelabel_correct"] += sum(1 for x in gr if not x); continue
        try: ctx = describe(P, c, T)
        except Exception: continue
        rr = rule_roles(c, ctx)
        if rr:
            S["rule_numbers"] += nn
            for i, role in enumerate(rr):
                if role is None: continue
                S["rule_labels"] += 1
                if role == "estimate?":
                    S["rule_est_untyped"] += 1; ok = (gr[i] or "").startswith("estimate_"); S["rule_correct_family"] += ok; per_role[role][0] += 1; per_role[role][1] += ok; continue
                ok = gr[i] == role
                S["rule_correct"] += ok; S["rule_correct_family"] += bool(ok or (FAM.get(role) and FAM.get(role) == FAM.get(gr[i])))
                per_role[role][0] += 1; per_role[role][1] += ok
                if not ok and len(wrong) < 40: wrong.append({"doc": d, "cand": c["id"], "header": ctx.get("column_header"), "text": c["text"][:60], "rule": role, "gold": gr[i]})
out = {"docs": len(docs), **S,
       "rule_precision_exact": round(S["rule_correct"] / max(1, S["rule_labels"] - S["rule_est_untyped"]), 4),
       "rule_precision_family": round(S["rule_correct_family"] / max(1, S["rule_labels"]), 4),
       "rule_coverage_of_all_numbers": round(S["rule_labels"] / max(1, S["numbers"]), 4),
       "rule_coverage_of_data_numbers": round(S["rule_labels"] / max(1, S["gold_data_numbers"]), 4),
       "prelabel_precision": round(S["prelabel_correct"] / max(1, S["prelabel_numbers"]), 4),
       "per_role": {k: {"n": v[0], "precision": round(v[1] / v[0], 4)} for k, v in sorted(per_role.items(), key=lambda kv: -kv[1][0])},
       "rule_errors_sample": wrong}
json.dump(out, open("work/route_measure.json", "w"), indent=1)
print(json.dumps({k: out[k] for k in out if k not in ("per_role", "rule_errors_sample")}))
print(json.dumps(out["per_role"]))

# ---- tier 1: Laya ckpt2 on held-out docs, numbers the rules did not label
nl = int(sys.argv[1]) if len(sys.argv) > 1 else 0
if nl:
    from epistemic import typed
    from epistemic.laya_judge import Laya
    train = set(open("/tmp/laya_train_docs.txt").read().split())
    held = [d for d in docs if d not in train]
    random.seed(7); random.shuffle(held); held = held[:nl]
    L = Laya(host="http://127.0.0.1:8766", model="epi2", head_max_len=576, max_len=1024)
    recs = []
    for d in held:
        P = json.load(open(f"parsed/{d}.json")); T = table_index(P); g, copies = gold_for(d)
        ids = set()
        for c in P["candidates"]:
            if c["id"] in copies or not c["numbers"] or (c.get("prelabel") or {}).get("not_data"): continue
            if rule_roles(c, describe(P, c, T)): continue
            ids.add(c["id"])
        J = typed.judge(P, L, ids=ids, workers=4)
        for cid, a in J.items():
            if "error" in a: recs.append({"doc": d, "err": a["error"][:80]}); continue
            gold = g.get(cid, {})
            isd = a.get("is_datum") or {}
            for k, v in a.items():
                if not k.startswith("role_"): continue
                i = int(k[5:]); gr = gold.get(i)
                recs.append({"doc": d, "cand": cid, "i": i, "pred": v.get("answer"), "p": v.get("p"), "gold": gr,
                             "isd_p": isd.get("p")})
        print(d, len(J), flush=True)
    json.dump(recs, open("work/route_laya.json", "w"))
    R = [r for r in recs if "pred" in r]
    print("laya numbers", len(R), "errors", sum(1 for r in recs if "err" in r))
    data_R = [r for r in R if r["gold"]]
    for t in [0.0, 0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 0.99]:
        acc = [r for r in data_R if (r["p"] or 0) >= t]
        prec = sum(r["pred"] == r["gold"] for r in acc) / max(1, len(acc))
        print(f"role p>={t}: coverage {len(acc)/max(1,len(data_R)):.3f} precision {prec:.4f}")
    nd = [r for r in R if r.get("isd_p") is not None]
    for t in [0.5, 0.9, 0.98]:
        hi = [r for r in nd if r["isd_p"] >= t or r["isd_p"] <= 1 - t]
        ok = sum((r["isd_p"] >= 0.5) == bool(r["gold"]) for r in hi)
        print(f"is_datum confident@{t}: coverage {len(hi)/max(1,len(nd)):.3f} precision {ok/max(1,len(hi)):.4f}")
