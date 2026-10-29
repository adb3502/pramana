"""Support and fidelity over the claim model (briefs/CLAIM_MODEL.md). No single score: profiles and distortion vectors.
  python scripts/support.py      -> work/claims_index/{support.json, fidelity.json, summary.json}
Support (evidence -> proposition core): papers, independent sources, designs, species, direction split, authors' relation language,
  counted only from result-bearing assertions (abstract/results), never from introductions or discussions.
Fidelity (media assertion -> its cited paper): field-by-field comparison with the cited paper's own propositions;
  when the cited paper is not in the graph, or makes no proposition on that core, the comparison is against the graph-wide support profile."""
import os, sys, json, glob, re, collections
os.chdir(os.path.expanduser("~/epistemic"))
OUT = "work/claims_index"; os.makedirs(OUT, exist_ok=True)
GEN = {"study_sample": 0, "subgroup": 0, "national": 1, "health_system": 1, "general_population": 2, "everyone": 3}
EVIDENCE_KINDS = {"paper_abstract", "paper_results", "paper_conclusion"}
def design_of(s):
    s = (s or "").lower()
    for k, ws in (("meta_analysis", ["meta-analys", "meta analys", "systematic review", "pooled analysis"]), ("mendelian_randomization", ["mendelian"]),
                  ("animal", ["mice", "mouse", "rat ", "rats", "murine", "zebrafish", "animal", "rodent", "piglet", "sheep", "drosophila"]),
                  ("cell", ["in vitro", "cell line", "cells", "cultured"]), ("rct", ["randomi", "trial", "crossover", "cross-over"]), ("cohort", ["cohort", "prospective", "longitudinal", "follow-up"]),
                  ("case_control", ["case-control", "case control"]), ("cross_sectional", ["cross-sectional", "cross sectional", "survey"]),
                  ("modelling", ["model", "simulation", "estimate", "scenario"])):
        if any(w in s for w in ws): return k
    return "other"
def norm(s): return re.sub(r"\s+", " ", str(s or "").lower()).strip()

E = json.load(open("work/graph/explorer.json"))
STUDY = {}
for s in E["studies"]:
    src = norm(s[3]); STUDY[s[0]] = {"design": design_of(s[2]), "design_text": s[2], "source": src if src and "not reported" not in src and "not named" not in src else s[0]}
FILES = {os.path.basename(f)[:-5]: json.load(open(f)) for f in glob.glob("work/claims/*.json")}
NONHUMAN = {"mouse", "mice", "rat", "rats", "animal", "zebrafish", "pig", "dog", "rabbit", "sheep", "drosophila", "worm", "c. elegans", "rodent", "primate"}
for src, d in FILES.items():                      # species override: a "randomised" mouse study is an animal study, not an RCT
    if d["kind"] != "paper" or src not in STUDY: continue
    sp = collections.Counter(norm((p.get("population") or {}).get("species")) for p in d["propositions"])
    top = sp.most_common(1)[0][0] if sp else ""
    if top in NONHUMAN or any(w in top for w in ("mouse", "rat", "animal")): STUDY[src]["design"] = "animal"
    elif "cell" in top or "in vitro" in top: STUDY[src]["design"] = "cell"
PROP = {}; BYDOC = collections.defaultdict(list); support = collections.defaultdict(lambda: {"papers": set(), "sources": set(), "design": collections.Counter(),
        "species": collections.Counter(), "direction": collections.Counter(), "relation_language": collections.Counter(), "magnitudes": [], "labels": collections.Counter()})
for src, d in FILES.items():
    P = {p["id"]: p for p in d["propositions"]}; PROP.update({(src, k): v for k, v in P.items()})
    if d["kind"] != "paper": continue
    for a in d["assertions"]:
        if a.get("kind") not in EVIDENCE_KINDS: continue
        for pid in a["propositions"]:
            p = P.get(pid)
            if not p or "core_id" not in p: continue
            BYDOC[src].append(p)
            S = support[p["core_id"]]; st = STUDY.get(src, {"design": "other", "source": src})
            if src not in S["papers"]:
                S["papers"].add(src); S["sources"].add(st["source"]); S["design"][st["design"]] += 1
            S["species"][(p.get("population") or {}).get("species") or "unknown"] += 1
            S["direction"][p.get("direction")] += 1; S["relation_language"][p.get("relation")] += 1
            S["labels"][f"{p.get('subject')} -> {p.get('object')}"] += 1
            m = p.get("magnitude") or {}
            if m.get("value") is not None and len(S["magnitudes"]) < 40: S["magnitudes"].append({"doc": src, "measure": m.get("measure"), "value": m.get("value"), "lo": m.get("lo"), "hi": m.get("hi"), "contrast": m.get("contrast")})
SUP = {k: {"papers": len(v["papers"]), "independent_sources": len(v["sources"]), "design": dict(v["design"]), "species": dict(v["species"]),
           "direction": dict(v["direction"]), "relation_language": dict(v["relation_language"]), "label": v["labels"].most_common(1)[0][0],
           "magnitudes": v["magnitudes"], "docs": sorted(v["papers"])[:60]} for k, v in support.items()}

def compare(mp, pp):
    """Distortion vector of a media proposition against one paper proposition."""
    v = {}
    v["subject"] = "same" if mp.get("subject_qid") == pp.get("subject_qid") else "different"
    v["object"] = "same" if mp.get("object_qid") == pp.get("object_qid") else ("measure_as_outcome" if norm(pp.get("object_measure")) and norm(mp.get("object")) != norm(pp.get("object")) else "different")
    mr, pr = mp.get("relation"), pp.get("relation")
    v["relation"] = "same" if mr == pr else ("upgraded_to_causal" if mr == "causal" and pr in ("associational", "association", "predictive") else f"{pr}->{mr}")
    md, pd_ = mp.get("direction"), pp.get("direction")
    v["direction"] = "same" if md == pd_ else ("reversed" if {md, pd_} == {"increase", "decrease"} else f"{pd_}->{md}")
    mg, pg = GEN.get((mp.get("population") or {}).get("generality"), 0), GEN.get((pp.get("population") or {}).get("generality"), 0)
    ms, ps = norm((mp.get("population") or {}).get("species")), norm((pp.get("population") or {}).get("species"))
    v["population"] = ("species_jump" if ps and ms and ps != ms and ps != "human" and ms == "human" else
                       "overgeneralized" if mg > pg else "narrowed" if mg < pg else "same")
    mm, pm = mp.get("magnitude") or {}, pp.get("magnitude") or {}
    if pm.get("value") is None: v["magnitude"] = "no_number_in_source"
    elif mm.get("value") is None: v["magnitude"] = "omitted"
    elif mm.get("measure") == pm.get("measure") and pm.get("value") not in (0, None) and abs(mm["value"] - pm["value"]) / abs(pm["value"]) > 0.2: v["magnitude"] = "changed"
    else: v["magnitude"] = "same_or_comparable"
    mo, po = mp.get("modality"), pp.get("modality")
    v["modality"] = "hedge_dropped" if po == "hedged" and mo == "certain" else ("strengthened" if po == "hedged" and mo == "plain" else "same" if mo == po else f"{po}->{mo}")
    bad = {"subject": {"different"}, "object": {"different", "measure_as_outcome"}, "relation": None, "direction": None, "population": {"overgeneralized", "species_jump"},
           "magnitude": {"changed", "omitted"}, "modality": {"hedge_dropped", "strengthened"}}
    v["distorted_fields"] = [k for k, s in bad.items() if (s is None and v[k] != "same") or (s and v[k] in s)]
    return v

sys.path.insert(0, os.path.expanduser("~/epistemic"))
from epistemic import llm
MC_PATH = f"{OUT}/judge_cache.json"; MC = json.load(open(MC_PATH)) if os.path.exists(MC_PATH) else {}
MSYS = """A media claim cites a research paper. You get the media proposition and the paper's own propositions (numbered).
1. Pick the paper proposition the media claim actually rests on: the most specific match, including subgroups (e.g. 'tea with milk' matches the milk subgroup, not overall tea). null if none is about the same subject or outcome.
2. Judge each field of the media proposition against that paper proposition, reading meaning, not wording. Polarity matters: 'destroys the brain' and 'lowers cognitive scores' point the same way.
Return JSON only:
{"index": <int or null>, "fields": {
 "subject": "same|broader|narrower|different",
 "object": "same|broader|narrower|measure_as_outcome|different",
 "relation": "same|upgraded_to_causal|downgraded|different",
 "direction": "same|reversed|effect_added|effect_dropped|unclear",
 "population": "same|overgeneralized|species_jump|narrowed|different",
 "magnitude": "same|inflated|deflated|omitted|no_number_in_source|unverifiable",
 "modality": "same|hedge_dropped|strengthened|weakened"},
 "note": "one sentence on the most important gap, or null"}
measure_as_outcome: the media names a broad outcome where the paper measured a specific score or instrument. effect_added: the paper found no effect, the media reports one.
inflated: the media's wording or number implies a larger effect than the paper reports, even without a number."""
OK = {"subject": {"same", "narrower"}, "object": {"same", "narrower"}, "relation": {"same", "downgraded"}, "direction": {"same", "unclear"},
      "population": {"same", "narrowed"}, "magnitude": {"same", "no_number_in_source", "unverifiable", "deflated"}, "modality": {"same", "weakened"}}
def judge(mp, doc):
    k = f"{mp['id']}|{doc}"
    if k in MC: return MC[k]
    pps = [{"i": i, **{f: p.get(f) for f in ("subject", "object", "object_measure", "relation", "direction", "magnitude", "population", "conditions", "modality")}} for i, p in enumerate(BYDOC[doc][:60])]
    try: out, _ = llm.chat(os.environ.get("MATCH_MODEL", "haiku"), MSYS, json.dumps({"media": {f: mp.get(f) for f in ("subject", "object", "relation", "direction", "magnitude", "population", "conditions", "modality")}, "paper": pps}, ensure_ascii=False), 1200)
    except Exception: out = None
    MC[k] = out; return out
D2P_PATH = f"{OUT}/doi2pmc.json"; D2P = json.load(open(D2P_PATH)) if os.path.exists(D2P_PATH) else {}
LOCAL = {}
for f in glob.glob("raw/PMC*.xml"):
    try:
        head = open(f, errors="ignore").read(20000)
        m = re.search(r'pub-id-type="doi"[^>]*>([^<]+)<', head)
        if m: LOCAL[m.group(1).strip().lower()] = os.path.basename(f)[:-4]
    except Exception: pass
D2P = {k: v for k, v in D2P.items() if v}                      # never trust a cached miss: the lookup service may have been down
def to_pmc(x):
    x = str(x or "")
    if x.startswith("PMC"): return x
    if not x.startswith("10."): return None
    if x.lower() in LOCAL: return LOCAL[x.lower()]
    if x not in D2P:
        try:
            import requests
            r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": 'DOI:"%s"' % x, "format": "json", "pageSize": 1}, timeout=30).json()
            if "resultList" not in r: return None
            h = r["resultList"].get("result") or []; D2P[x] = h[0].get("pmcid") if h else None
        except Exception: return None
    return D2P.get(x)
FID = []
for src, d in FILES.items():
    if d["kind"] == "paper": continue
    P = {p["id"]: p for p in d["propositions"]}
    item_cites = sorted({to_pmc(c.get("resolved")) for a in d["assertions"] for c in (a.get("cites") or []) if isinstance(c, dict) and to_pmc(c.get("resolved"))})
    for a in d["assertions"]:
        cited = [to_pmc(c.get("resolved")) for c in (a.get("cites") or []) if isinstance(c, dict) and to_pmc(c.get("resolved"))] or item_cites   # an uncited sentence leans on the sources of its item
        for pid in a["propositions"]:
            mp = P.get(pid)
            if not mp or "core_id" not in mp: continue
            row = {"assertion": a["id"], "source": src, "speaker": a.get("speaker"), "url": a.get("url"), "text": a.get("text"), "quote": a.get("quote"),
                   "proposition": {k: mp.get(k) for k in ("subject", "object", "relation", "direction", "modality", "population", "magnitude")},
                   "core_id": mp["core_id"], "cited_in_graph": [c for c in cited if c in BYDOC], "cited_not_in_graph": [c for c in cited if c not in BYDOC]}
            best = None
            for doc in row["cited_in_graph"]:
                j = judge(mp, doc)
                if not j or j.get("index") is None or not (0 <= j["index"] < len(BYDOC[doc][:60])): continue
                F = j.get("fields") or {}
                bad = [f for f in ("subject", "object", "relation", "direction", "population", "magnitude", "modality") if F.get(f) and F[f] not in OK[f]]
                if not best or len(bad) < len(best[3]): best = (doc, BYDOC[doc][j["index"]], j, bad)
            if best:
                doc, pp, j, bad = best
                row["against"] = {"doc": doc, "proposition": {k: pp.get(k) for k in ("subject", "object", "object_measure", "relation", "direction", "modality", "population", "magnitude")}}
                row["distortion"] = {**(j.get("fields") or {}), "distorted_fields": bad, "note": j.get("note"),
                                     "claim_beyond_cited_source": (j.get("fields") or {}).get("subject") == "different" or (j.get("fields") or {}).get("object") == "different"}
            elif row["cited_in_graph"]:
                row["distortion"] = {"note": "cited paper makes no proposition on this subject or outcome", "claim_beyond_cited_source": True, "distorted_fields": []}
            row["support"] = SUP.get(mp["core_id"])
            FID.append(row)
json.dump(MC, open(MC_PATH, "w")); json.dump(D2P, open(D2P_PATH, "w"))
json.dump(SUP, open(f"{OUT}/support.json", "w"), ensure_ascii=False)
json.dump(FID, open(f"{OUT}/fidelity.json", "w"), ensure_ascii=False, indent=0)
C = collections.Counter
checked = [r for r in FID if isinstance(r.get("distortion"), dict) and "distorted_fields" in r["distortion"]]
summ = {"cores_with_evidence": len(SUP), "cores_multi_source": sum(1 for v in SUP.values() if v["independent_sources"] >= 2),
        "media_propositions": len(FID), "with_graph_support": sum(1 for r in FID if r.get("support")),
        "compared_to_cited_paper": len(checked), "beyond_cited_source": sum(1 for r in checked if r["distortion"].get("claim_beyond_cited_source")),
        "distorted_field_counts": dict(C(f for r in checked for f in r["distortion"]["distorted_fields"])),
        "n_distorted_fields": dict(C(len(r["distortion"]["distorted_fields"]) for r in checked)),
        "relation_upgrades": sum(1 for r in checked if r["distortion"].get("relation") == "upgraded_to_causal"), "effect_added": sum(1 for r in checked if r["distortion"].get("direction") == "effect_added"), "inflated": sum(1 for r in checked if r["distortion"].get("magnitude") == "inflated"),
        "overgeneralized": sum(1 for r in checked if r["distortion"].get("population") in ("overgeneralized", "species_jump"))}
json.dump(summ, open(f"{OUT}/summary.json", "w"), indent=1); print(json.dumps(summ, indent=1))
