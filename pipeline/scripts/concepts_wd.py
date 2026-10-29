"""Wikidata concept anchoring for propositions (architecture decision 1).
  python scripts/concepts_wd.py search      Wikidata candidates for every unique subject/object phrase (cache work/wikidata_cache.json)
  python scripts/concepts_wd.py pick        Haiku chooses the QID (or a broader QID, or none) per phrase
  python scripts/concepts_wd.py apply       writes subject_qid/object_qid and core/specific ids into work/claims/*.json
Core id: (subject QID, object QID, relation family). Specific id: core + population (who, species) + object measure.
Phrases with no acceptable QID keep a term: id so nothing is dropped."""
import os, sys, json, glob, re, time, hashlib, requests, concurrent.futures as cf
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm
CACHE = "work/wikidata_cache.json"; C = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
H = {"User-Agent": "epistemic-framework/0.4 (research use; knowledge graph concept anchoring)"}
def save(): json.dump(C, open(CACHE + ".tmp", "w"), ensure_ascii=False); os.replace(CACHE + ".tmp", CACHE)
def norm(s): return re.sub(r"\s+", " ", str(s or "").lower().strip(" .;:,"))[:160]
def phrases():
    P = set()
    for f in glob.glob("work/claims/*.json"):
        for p in json.load(open(f))["propositions"]:
            for k in ("subject", "object"):
                if p.get(k): P.add(norm(p[k]))
    return sorted(x for x in P if x)
SPARQL = """SELECT ?item ?itemLabel ?itemDescription WHERE {
 SERVICE wikibase:mwapi { bd:serviceParam wikibase:endpoint "www.wikidata.org"; wikibase:api "EntitySearch"; mwapi:search "%s"; mwapi:language "en"; mwapi:limit "%d".
   ?item wikibase:apiOutputItem mwapi:item. ?num wikibase:apiOrdinal true. }
 SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } } ORDER BY ?num"""
def wd(q, n=10):
    """Entity search routed through the Wikidata Query Service (the action API rate-limits our addresses)."""
    q = q.replace("\\", " ").replace('"', " ")
    for a in range(6):
        try:
            r = requests.get("https://query.wikidata.org/sparql", params={"query": SPARQL % (q, n), "format": "json"}, headers=H, timeout=60)
            if r.status_code in (429, 503): time.sleep(int(r.headers.get("retry-after", "20")) + 2); continue
            r.raise_for_status()
            out = []
            for x in r.json()["results"]["bindings"]:
                qid = x["item"]["value"].rsplit("/", 1)[-1]; lab = (x.get("itemLabel") or {}).get("value")
                out.append({"qid": qid, "label": lab if lab != qid else None, "desc": (x.get("itemDescription") or {}).get("value")})
            return [o for o in out if o["label"]]
        except Exception: time.sleep(5)
    return None
def search():
    todo = [p for p in phrases() if p not in C or "cands" not in C[p]]
    print(len(todo), "phrases to search", flush=True)
    def one(p):
        c = wd(p)
        words = p.split()
        if c == [] and len(words) > 2: c = wd(" ".join(words[-2:]))          # head-noun fallback
        if c == [] and len(words) > 1: c = wd(words[-1])
        return p, c
    with cf.ThreadPoolExecutor(int(os.environ.get("WD_THREADS", "3"))) as ex:
        for i, (p, c) in enumerate(ex.map(one, todo)):
            if c is None: continue                                        # rate-limited: leave for the next run
            C.setdefault(p, {})["cands"] = c
            if i % 500 == 0: save(); print(i, time.strftime("%H:%M"), flush=True)
    save()
SYS = """You anchor phrases from scientific and media claims to Wikidata items. For each phrase choose the candidate QID that names the same concept.
If none is the same but one is a correct broader concept (e.g. phrase 'decaffeinated coffee intake' -> 'decaffeinated coffee' or 'coffee'), choose it and set match "broader".
If none fits, qid null. Never choose a candidate that is a different thing that happens to share words (a band, a film, a journal, a person, a place).
Return JSON {"items":[{"i":<i>,"qid":"Q..." or null,"match":"exact|broader|none"}]}."""
def pick():
    todo = [p for p, v in C.items() if "qid" not in v and v.get("cands")]
    for p, v in C.items():
        if "qid" not in v and not v.get("cands"): v.update(qid=None, match="none")
    print(len(todo), "phrases to pick", flush=True)
    parts = [todo[k:k + 25] for k in range(0, len(todo), 25)]
    def one(part):
        try:
            out, _ = llm.chat(os.environ.get("WD_MODEL", "haiku"), SYS, json.dumps([{"i": i, "phrase": p, "candidates": C[p]["cands"]} for i, p in enumerate(part)], ensure_ascii=False), 4000)
            return part, out.get("items", [])
        except Exception as e: return part, []
    with cf.ThreadPoolExecutor(8) as ex:
        for n, (part, items) in enumerate(ex.map(one, parts)):
            for x in items:
                try: p = part[int(x["i"])]
                except Exception: continue
                q = x.get("qid"); ok = q in {c["qid"] for c in C[p]["cands"]}
                C[p].update(qid=q if ok else None, match=x.get("match") if ok else "none",
                            label=next((c["label"] for c in C[p]["cands"] if c["qid"] == q), None) if ok else None)
            if n % 40 == 0: save(); print(n * 25, flush=True)
    save()
FAM = {"causal": "effect", "associational": "effect", "association": "effect", "predictive": "effect", "mechanistic": "mechanism", "descriptive_quantity": "quantity"}
def cid(p):
    s = C.get(norm(p.get("subject")), {}); o = C.get(norm(p.get("object")), {})
    sq = s.get("qid") or "term:" + norm(p.get("subject")); oq = o.get("qid") or "term:" + norm(p.get("object"))
    return sq, oq
def apply():
    n = q = 0
    for f in glob.glob("work/claims/*.json"):
        d = json.load(open(f))
        for p in d["propositions"]:
            sq, oq = cid(p); p["subject_qid"], p["object_qid"] = sq, oq
            fam = FAM.get(p.get("relation"), "other")
            p["core_id"] = "K" + hashlib.sha256(f"{sq}|{oq}|{fam}".encode()).hexdigest()[:14]
            pop = p.get("population") or {}
            p["specific_id"] = "S" + hashlib.sha256(f"{p['core_id']}|{norm(pop.get('who'))}|{norm(pop.get('species'))}|{norm(p.get('object_measure'))}".encode()).hexdigest()[:14]
            n += 1; q += sq.startswith("Q") and oq.startswith("Q")
        json.dump(d, open(f, "w"), indent=1, ensure_ascii=False)
    m = [v for v in C.values() if "qid" in v]
    print(json.dumps({"propositions": n, "both_anchored": q, "phrases": len(C), "anchored": sum(1 for v in m if v.get("qid")),
                      "exact": sum(1 for v in m if v.get("match") == "exact"), "broader": sum(1 for v in m if v.get("match") == "broader")}))
if __name__ == "__main__":
    {"search": search, "pick": pick, "apply": apply}[sys.argv[1]]()
