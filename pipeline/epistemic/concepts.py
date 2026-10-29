"""Concept layer v2 (topic-free): map each paper's own ids onto shared, externally anchored concepts.
A concept is just a thing in the world (a MeSH descriptor when one fits). Whether a study uses it as exposure, outcome,
covariate or stratifier is a ROLE on the study's edge, never a property of the concept.
Per paper, one LLM call proposes for every variable a MeSH preferred heading (plus a free canonical term), for every group
the variable it is defined on and the range it covers in a canonical unit, and for every model the variables it adjusts for.
Each proposed heading is then verified against NLM's MeSH lookup API (exact match on the preferred label); verified concepts
get the descriptor id (D......), the rest stay as unverified free terms (id term:<normalized>). Numbers in ranges are marked
as_reported only if they occur in the group's own label/definition, else converted (with the conversion written down).
Output concepts/<doc>.json; MeSH lookups cached in work/mesh_cache.json. Usage: python -m epistemic.concepts PMC... | --all [--force]"""
import os, sys, re, json, glob, time, pathlib, requests, fcntl
from . import llm, store, records
from .parse import numbers_in
MODEL = os.environ.get("CONCEPT_MODEL", "haiku")
ROLES = ["exposure", "outcome", "covariate", "stratifier", "mediator", "instrument", "baseline_characteristic", "design", "other"]
SYSTEM = """You normalise one scientific paper's own identifiers so its results can be joined with any other paper's, whatever the topic.
Return JSON only:
{"source": {"canonical": "<standard name of the cohort, trial, registry or dataset; 'meta-analysis of N studies' or 'GWAS consortium <name>' when that is what it is>", "country": "<country or multi>"},
 "variables": {"<variable_id>": {"mesh": "<the MeSH preferred heading that best names WHAT is measured, e.g. Heart Failure, Coffee, Body Mass Index, Smoking, Blood Pressure; null if none fits>",
                                  "term": "<short canonical English name, lower case, as specific as the paper is (e.g. 'heart failure hospitalization', 'decaffeinated coffee intake')>",
                                  "role": one of """ + json.dumps(ROLES) + """,
                                  "unit": "<canonical unit of the measured quantity (UCUM style: 'cups/d', 'mmHg', 'kg/m2', 'mg/d', '1' for counts or binary) or null>"}},
 "groups": {"<group_id>": {"kind": "level|population|subgroup|other",
                           "defined_on": "<variable_id this group is a level or range of, or null>",
                           "low": number or null, "high": number or null, "unit": "<unit of low/high, the same canonical unit as that variable when you can convert>",
                           "conversion": "none" or the conversion you applied (e.g. "cups per week / 7"), "reference": true|false}},
 "adjusts_for": {"<model_id>": ["<variable_id or, if the covariate has no variable_id, a short canonical term>"]}}
Rules: every input id must appear. Use real MeSH preferred headings only (you know MeSH; when unsure give null rather than inventing one).
Ranges: open bounds are null ('>=5' -> low 5, high null; '<1' -> low 0, high 1; 'none' -> 0, 0). Never guess a bound the label does not give."""

CACHE = "work/mesh_cache.json"
def mesh_lookup(label):
    if not label: return None
    os.makedirs("work", exist_ok=True)
    with open(CACHE + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        c = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    if label in c: return c[label]
    hit = None
    for match in ("exact",):
        try:
            r = requests.get("https://id.nlm.nih.gov/mesh/lookup/descriptor", params={"label": label, "match": match, "limit": 3}, timeout=30)
            js = r.json() if r.ok else []
            if js: hit = {"id": js[0]["resource"].rsplit("/", 1)[-1], "label": js[0]["label"]}
        except (requests.RequestException, ValueError): return None   # do not cache network failures
    time.sleep(0.2)
    with open(CACHE + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        c = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
        c[label] = hit; json.dump(c, open(CACHE, "w"))
    return hit

def norm_term(t): return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()

def payload(doc):
    e = records.load_ext(doc); sc = e.get("study_card") or {}
    return json.dumps({"cohort_name": sc.get("cohort_name"), "setting": sc.get("setting") or sc.get("data_source"), "design": sc.get("design"),
                       "variables": [{k: v.get(k) for k in ("variable_id", "label", "kind", "unit", "definition")} for v in e.get("variables") or []],
                       "groups": [{k: g.get(k) for k in ("group_id", "label", "definition", "parent_group_id")} for g in e.get("groups") or []],
                       "models": [{"model_id": m.get("model_id"), "adjusted_for": m.get("adjusted_for")} for m in e.get("models") or []]}, ensure_ascii=False), e

def run(doc, force=False):
    out = f"concepts/{doc}.json"
    if os.path.exists(out) and not force and json.load(open(out)).get("v") == 2: return {"doc": doc, "skipped": True}
    pl, e = payload(doc)
    C, usd = llm.chat(MODEL, SYSTEM, pl[:300000], 32000)
    nver = 0
    for vid, v in (C.get("variables") or {}).items():
        h = mesh_lookup(v.get("mesh"))
        v["concept"] = h["id"] if h else ("term:" + norm_term(v.get("term") or v.get("mesh") or vid))
        v["concept_label"] = h["label"] if h else (v.get("term") or v.get("mesh"))
        v["verified"] = bool(h); nver += bool(h)
    gl = {g.get("group_id"): f"{g.get('label')} {g.get('definition')}" for g in e.get("groups") or []}
    for gid, g in (C.get("groups") or {}).items():
        seen = {round(n["value"], 6) for n in numbers_in(gl.get(gid, "")) if n["value"] is not None}
        for k in ("low", "high"):
            x = g.get(k)
            if isinstance(x, (int, float)) and not isinstance(x, bool): g[k + "_status"] = "as_reported" if round(float(x), 6) in seen or x == 0 else "converted"
    C.update({"v": 2, "doc": doc, "model": MODEL, "usd": round(usd, 5)})
    os.makedirs("concepts", exist_ok=True); json.dump(C, open(out, "w"), indent=1)
    nv = len(C.get("variables") or {})
    rep = {"doc": doc, "source": (C.get("source") or {}).get("canonical"), "variables": nv, "mesh_verified": nver, "groups": len(C.get("groups") or {}), "usd": round(usd, 4)}
    store.append("concept_map", {**rep, "version": 2, "out_sha256": store.file_hash(out)}); return rep

if __name__ == "__main__":
    docs = sorted(pathlib.Path(p).stem for p in glob.glob("raw/*.xml")) if "--all" in sys.argv else [a for a in sys.argv[1:] if not a.startswith("--")]
    for d in docs:
        try: print(json.dumps(run(d, "--force" in sys.argv)), flush=True)
        except Exception as ex: print(json.dumps({"doc": d, "error": str(ex)[:200]}), flush=True)
