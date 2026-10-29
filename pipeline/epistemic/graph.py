"""Graph layer v2 (topic-free). Concepts are things (MeSH descriptors where verified, else free terms); every role
(exposure, outcome, covariate, stratifier...) lives on a study's edge, never on the concept.
Nodes: study, source, concept, variable (a study's measurement of a concept), level (a group defined as a range of a variable),
       population, model, analysis, estimate, claim, assumption, bias_flag.
Edges: study-USES->source; variable-MEASURES->concept {role, unit}; variable-IN->study; level-OF->variable {low, high, unit};
       model-ADJUSTS_FOR->variable|concept; estimate-IN->study, -EXPOSURE->variable, -OUTCOME->variable, -LEVEL->level, -REFERENCE->level,
       -MODEL->model; claim-MADE_IN->study, -SUPPORTED_BY->estimate; assumption-IN->study; bias_flag-ON->study; analysis-IN->study;
       derived concept-EVIDENCE->concept {estimates, studies, sources, direction of each study's headline estimate}.
An estimate = one effect value with its CI (and p) from the same candidate, the same table-row segment or the adjacent text span.
Outputs graph.duckdb (node, edge, estimate tables) and work/graph/{estimates,graph}.json. Usage: python -m epistemic.graph"""
import os, re, json, glob, math, pathlib, collections
import duckdb
from . import records, store
EST = {"estimate_hr": "HR", "estimate_rr": "RR", "estimate_or": "OR", "estimate_irr": "IRR", "estimate_beta": "beta", "estimate_difference": "difference"}
RATIO = {"HR", "RR", "OR", "IRR"}

def ci_lookup(rows):
    byc, byrow, bysec = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for r in rows:
        if not r.get("role"): continue
        a = r.get("anchor") or {}; byc[r["candidate"]].append(r)
        if "row" in a: byrow[(a.get("supp"), a.get("figure"), a["table"], a["row"])].append(r)
        elif "start" in a: bysec[(a.get("supp"), a.get("section"))].append(r)
    return byc, byrow, bysec

def attach(r, byc, byrow, bysec):
    a = r.get("anchor") or {}; i = int(r["datum_id"].rsplit("#", 1)[1])
    def pick(cands):
        lo = hi = p = None
        for x in cands:
            if x is r: continue
            if x["role"] == "ci_low" and lo is None: lo = x
            elif x["role"] == "ci_high" and hi is None: hi = x
            elif x["role"] == "p_value" and p is None: p = x
        return lo, hi, p
    lo, hi, p = pick([x for x in byc[r["candidate"]] if int(x["datum_id"].rsplit("#", 1)[1]) > i])
    def segment(seq):
        out = []
        for x in seq:
            if x["role"] in EST and x is not r: break
            out.append(x)
        return out
    if (lo is None or hi is None) and "row" in a:
        row = sorted([x for x in byrow[(a.get("supp"), a.get("figure"), a["table"], a["row"])] if (x.get("anchor") or {}).get("col", -1) > a.get("col", -1)], key=lambda x: (x["anchor"]["col"], x["datum_id"]))
        l2, h2, p2 = pick(segment(row)); lo, hi, p = lo or l2, hi or h2, p or p2
    if (lo is None or hi is None) and "start" in a:
        near = sorted([x for x in bysec[(a.get("supp"), a.get("section"))] if 0 <= x["anchor"]["start"] - a["end"] < 60], key=lambda x: x["anchor"]["start"])
        l2, h2, p2 = pick(segment(near)); lo, hi, p = lo or l2, hi or h2, p or p2
    return lo, hi, p

def wire(r, k):
    return (r.get(k) or r.get(k + "_A") or r.get(k + "_B")) if r else None

def low(x): return (str(x) if x is not None else "").lower() or None

def build():
    N, E, EST_ROWS = {}, [], []
    def node(i, t, label, doc=None, **props): N.setdefault(i, {"id": i, "type": t, "label": label, "doc": doc, "props": props}); return i
    def edge(s, d, t, **props): E.append({"src": s, "dst": d, "type": t, "props": props})
    docs = sorted({pathlib.Path(p).stem for p in glob.glob("raw/*.xml")} | {pathlib.Path(p).stem for p in glob.glob("parsed/W*.json") if "_" not in pathlib.Path(p).stem})
    if os.environ.get("GRAPH_FINISHED_ONLY", "1") == "1":   # only papers that completed the pipeline (closure written); in-progress papers stay out of the graph
        docs = [d for d in docs if os.path.exists(f"validation/{d}.closure.json")]
    gate = {g["doc"]: g for g in json.load(open("work/gate.json"))} if os.path.exists("work/gate.json") else {}
    for doc in docs:
        e = records.load_ext(doc); sc = e.get("study_card") or {}
        C = json.load(open(f"concepts/{doc}.json")) if os.path.exists(f"concepts/{doc}.json") else {}
        P = json.load(open(f"parsed/{doc}.json")) if os.path.exists(f"parsed/{doc}.json") else {}
        cl = json.load(open(f"validation/{doc}.closure.json"))["completeness"] if os.path.exists(f"validation/{doc}.closure.json") else None
        g = gate.get(doc) or {}
        sid = node(f"study:{doc}", "study", (P.get("title") or "")[:240], doc, design=sc.get("design"), setting=sc.get("setting"), closure=cl, gate=g.get("status"), silence=g.get("silence"))
        src = (C.get("source") or {}).get("canonical") or sc.get("cohort_name")
        if src: edge(sid, node(f"source:{re.sub(r'[^a-z0-9]+', ' ', src.lower()).strip()}", "source", src, country=(C.get("source") or {}).get("country")), "USES")
        cv = {low(k): v for k, v in (C.get("variables") or {}).items()}; cg = {low(k): v for k, v in (C.get("groups") or {}).items()}
        ca = {low(k): v for k, v in (C.get("adjusts_for") or {}).items()}
        vlab = {low(v.get("variable_id")): v for v in e.get("variables") or []}
        glab = {low(x.get("group_id")): x for x in e.get("groups") or []}
        mlab = {low(m.get("model_id")): m for m in e.get("models") or []}
        def vnode(vid):
            if not vid: return None
            vid = low(vid); v = vlab.get(vid) or {}; m = cv.get(vid) or {}
            n = node(f"var:{doc}:{vid}", "variable", v.get("label") or m.get("term") or vid, doc, role=m.get("role") or v.get("kind"), unit=m.get("unit") or v.get("unit"),
                     definition=v.get("definition"), term=m.get("term"))
            if m.get("concept") and n not in vnode.done:
                vnode.done.add(n)
                edge(n, node(f"concept:{m['concept']}", "concept", m.get("concept_label"), verified=m.get("verified")), "MEASURES", role=m.get("role"), unit=m.get("unit"), term=m.get("term"))
                edge(n, sid, "IN")
            return n
        vnode.done = set()
        for vid in vlab: vnode(vid)
        for gid, x in glab.items():
            m = cg.get(gid) or {}
            kind = "level" if m.get("kind") == "level" and m.get("defined_on") else "population"
            n = node(f"{kind}:{doc}:{gid}", kind, x.get("label"), doc, definition=x.get("definition"), low=m.get("low"), high=m.get("high"), unit=m.get("unit"),
                     status=[m.get("low_status"), m.get("high_status")], reference=m.get("reference"), conversion=m.get("conversion"))
            if kind == "level": edge(n, vnode(m["defined_on"]), "OF")
        for mid, mm in mlab.items():
            n = node(f"model:{doc}:{mid}", "model", mm.get("label"), doc, type=mm.get("type"), role=mm.get("role"), adjusted_for=mm.get("adjusted_for"))
            for a in ca.get(mid) or []:
                t = vnode(a) if low(a) in vlab or low(a) in cv else node(f"concept:term:{re.sub(r'[^a-z0-9]+', ' ', str(a).lower()).strip()}", "concept", a, verified=False)
                if t: edge(n, t, "ADJUSTS_FOR")
        for a in e.get("analyses") or []:
            edge(node(f"analysis:{doc}:{a.get('analysis_id')}", "analysis", a.get("description"), doc, kind=a.get("kind"), status=a.get("status"), conclusion=a.get("conclusion_as_stated")), sid, "IN")
        for k, w in enumerate(e.get("warrants") or []):
            edge(node(f"assumption:{doc}:{k}", "assumption", w.get("assumption"), doc, status=w.get("status")), sid, "IN")
        cand2est = collections.defaultdict(list)
        exposures = [k for k, v in cv.items() if v.get("role") == "exposure"]
        exposures = exposures if len({cv[k].get("concept") for k in exposures}) == 1 else []   # one exposure concept in the whole study
        exposures = exposures[:1]
        def concept_of(vn):
            if not vn: return None, None
            m = cv.get(vn.split(":", 2)[2]) or {}
            return m.get("concept"), m.get("concept_label")
        for suf in ("", "_S", "_F"):
            p = f"data/{doc}{suf}.jsonl"
            if not os.path.exists(p): continue
            rows = [json.loads(l) for l in open(p)]
            rows = [r for r in rows if not r.get("span_copy") and not r.get("nested_copy")]
            byc, byrow, bysec = ci_lookup(rows)
            for r in rows:
                meas = EST.get(r.get("role") or "")
                if not meas: continue
                lo, hi, pv = attach(r, byc, byrow, bysec)
                v = r["value"]; L = lo["value"] if lo else None; H = hi["value"] if hi else None
                var, grp, ref, mdl = (low(wire(r, k) or wire(lo, k)) for k in ("variable", "group", "reference_group", "model"))
                gl, gr = cg.get(grp or "") or {}, cg.get(ref or "") or {}
                xv = gl.get("defined_on") or gr.get("defined_on")
                inferred = False
                if not xv and len(exposures) == 1:
                    words = {w for w in re.findall(r"[a-z]{4,}", ((cv[exposures[0]].get("term") or "") + " " + (cv[exposures[0]].get("concept_label") or "")).lower())}
                    lab = ((glab.get(grp or "") or {}).get("label") or "") + " " + ((glab.get(ref or "") or {}).get("label") or "")
                    if words and any(w in lab.lower() for w in words): xv = exposures[0]; inferred = True   # the level names the study's one exposure
                on, xn = vnode(var), vnode(xv)
                oc, ocl = concept_of(on); xc, xcl = concept_of(xn)
                flags = []
                if L is not None and H is not None and not (L <= v <= H): flags.append("estimate_outside_ci")
                if not on: flags.append("no_outcome_wiring")
                if not xn: flags.append("no_exposure_wiring")
                if inferred: flags.append("exposure_inferred_single_exposure_study")
                is_ref = (v == 1.0 and meas in RATIO and grp and grp == ref and L is None)
                se = (math.log(H) - math.log(L)) / (2 * 1.959964) if (meas in RATIO and L and H and L > 0 and H > 0) else None
                eid = f"est:{doc}{suf}:{r['datum_id']}"
                covs = []
                for a in ca.get(mdl or "") or []:
                    mm = cv.get(low(a)) or {}; covs.append(mm.get("concept_label") or str(a))
                rec = {"id": eid, "doc": doc, "unit": doc + suf, "datum_id": r["datum_id"], "source_flag": wire(r, "source"), "measure": meas, "value": v, "ci_low": L, "ci_high": H,
                       "p": (pv or {}).get("raw"), "log_se_derived": se, "is_reference": is_ref,
                       "outcome_concept": oc, "outcome_concept_label": ocl, "outcome_term": (cv.get(var or "") or {}).get("term") or (vlab.get(var or "") or {}).get("label"),
                       "exposure_concept": xc, "exposure_concept_label": xcl, "exposure_term": (cv.get(low(xv) or "") or {}).get("term"),
                       "level_label": (glab.get(grp or "") or {}).get("label"), "level_low": gl.get("low"), "level_high": gl.get("high"), "level_unit": gl.get("unit"),
                       "ref_label": (glab.get(ref or "") or {}).get("label"), "ref_low": gr.get("low"), "ref_high": gr.get("high"),
                       "model_label": (mlab.get(mdl or "") or {}).get("label"), "model_role": (mlab.get(mdl or "") or {}).get("role"), "covariates": covs,
                       "source": src, "adjudicated": bool(r.get("adjudicated")), "where": {k: (r.get("anchor") or {}).get(k) for k in ("supp", "figure", "table", "row", "col", "section") if (r.get("anchor") or {}).get(k) is not None},
                       "flags": flags}
                EST_ROWS.append(rec); cand2est[r["candidate"]].append(eid)
                node(eid, "estimate", f"{meas} {v}" + (f" ({L} to {H})" if L is not None else ""), doc, **{k: rec[k] for k in ("measure", "value", "ci_low", "ci_high", "p", "is_reference", "flags")})
                edge(eid, sid, "IN")
                if on: edge(eid, on, "OUTCOME")
                if xn: edge(eid, xn, "EXPOSURE")
                gn = lambda g_: f"level:{doc}:{g_}" if f"level:{doc}:{g_}" in N else f"population:{doc}:{g_}"
                if grp: edge(eid, gn(grp), "LEVEL")
                if ref and ref != grp: edge(eid, gn(ref), "REFERENCE")
                if mdl: edge(eid, f"model:{doc}:{mdl}", "MODEL")
        for k, c in enumerate(e.get("claims") or []):
            cid = node(f"claim:{doc}:{k}", "claim", c.get("text_paraphrase"), doc, relation=c.get("relation"), hedging=c.get("hedging"), location=c.get("location"), scope=c.get("scope"))
            edge(cid, sid, "MADE_IN")
            for s_ in c.get("supported_by") or []:
                for eid in cand2est.get(str(s_).split("[")[0], []): edge(cid, eid, "SUPPORTED_BY")
        for k, b in enumerate(e.get("bias_flags") or []):
            edge(node(f"bias:{doc}:{k}", "bias_flag", b.get("observation"), doc, stage=b.get("stage"), severity=b.get("severity"), kind=b.get("kind")), sid, "ON")
    # derived concept-to-concept evidence: one headline per (study, exposure concept, outcome concept): widest contrast, most adjusted model
    pairs = collections.defaultdict(list)
    for r in EST_ROWS:
        if r["exposure_concept"] and r["outcome_concept"] and not r["is_reference"] and r["source_flag"] != "external": pairs[(r["exposure_concept"], r["outcome_concept"])].append(r)
    for (xc, oc), rs in pairs.items():
        by = collections.defaultdict(list)
        for r in rs: by[r["doc"]].append(r)
        dirs = collections.Counter()
        for d, rr in by.items():
            h = sorted(rr, key=lambda r: ((r["level_low"] if r["level_low"] is not None else -1), len(r["covariates"])), reverse=True)[0]
            if h["measure"] in RATIO and h["ci_low"] and h["ci_high"]: dirs["lower" if h["ci_high"] < 1 else "higher" if h["ci_low"] > 1 else "null"] += 1
            elif h["measure"] in ("beta", "difference") and h["ci_low"] is not None and h["ci_high"] is not None: dirs["lower" if h["ci_high"] < 0 else "higher" if h["ci_low"] > 0 else "null"] += 1
            else: dirs["no_ci"] += 1
        edge(f"concept:{xc}", f"concept:{oc}", "EVIDENCE", estimates=len(rs), studies=len(by), sources=len({r["source"] for r in rs if r["source"]}), directions=dict(dirs))
    E2 = [x for x in E if x["src"] in N and x["dst"] in N]
    os.makedirs("work/graph", exist_ok=True)
    json.dump(EST_ROWS, open("work/graph/estimates.json", "w"))
    json.dump({"nodes": list(N.values()), "edges": E2}, open("work/graph/graph.json", "w"))
    con = duckdb.connect("graph.duckdb")
    for name, rows in (("node", list(N.values())), ("edge", E2), ("estimate", EST_ROWS)):
        p = f"work/graph/{name}.jsonl"
        with open(p, "w") as f:
            for x in rows: f.write(json.dumps({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in x.items()}) + "\n")
        con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_json_auto('{p}', union_by_name=true, sample_size=-1)")
    rat = [r for r in EST_ROWS if not r["is_reference"]]
    rep = {"nodes": dict(collections.Counter(n["type"] for n in N.values())), "edges": dict(collections.Counter(x["type"] for x in E2)), "estimates": len(EST_ROWS),
           "with_ci": sum(1 for r in rat if r["ci_low"] is not None), "with_outcome": sum(1 for r in rat if r["outcome_concept"]), "with_exposure": sum(1 for r in rat if r["exposure_concept"]),
           "with_range": sum(1 for r in rat if r["level_low"] is not None), "outside_ci": sum(1 for r in rat if "estimate_outside_ci" in r["flags"]), "pairs": len(pairs), "dropped_edges": len(E) - len(E2)}
    store.append("graph_build", {**rep, "version": 2, "graph_sha256": store.file_hash("work/graph/graph.json")})
    return rep

if __name__ == "__main__":
    print(json.dumps(build(), indent=1))
