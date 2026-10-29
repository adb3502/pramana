"""Thread 2 corpus: coffee/caffeine and aging/longevity. Europe PMC open-access full texts, screened by DeepSeek (OpenRouter)
into kinds; keeps new human data, evidence syntheses and animal/cell aging studies. -> work/diabetes_candidates.json (ingest format)"""
import os, sys, json, time, requests
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm, store
Q = ('(TITLE_ABS:coffee OR TITLE_ABS:caffeine) AND (TITLE_ABS:diabetes OR TITLE_ABS:"type 2 diabetes" OR TITLE_ABS:"insulin resistance" OR TITLE_ABS:"insulin sensitivity" '
     'OR TITLE_ABS:glucose OR TITLE_ABS:glycemic OR TITLE_ABS:glycaemic OR TITLE_ABS:HbA1c OR TITLE_ABS:prediabetes OR TITLE_ABS:"metabolic syndrome" OR TITLE_ABS:"gestational diabetes") '
     'AND OPEN_ACCESS:Y AND IN_EPMC:Y')
have = {f[:-4] for f in os.listdir("raw") if f.endswith(".xml")}
for f in ("work/m4_candidates.json", "work/aging_candidates.json"):
    try: have |= {w.get("pmcid") for w in json.load(open(f))["works"] if w.get("pmcid")}
    except FileNotFoundError: pass
rows, cur = [], "*"
while cur:
    d = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": Q, "format": "json", "resultType": "core", "pageSize": 1000, "cursorMark": cur}, timeout=120).json()
    for x in (d.get("resultList") or {}).get("result") or []:
        if x.get("pmcid"): rows.append({"id": x.get("id"), "pmcid": x["pmcid"], "title": x.get("title"), "year": x.get("pubYear"), "pubtype": (x.get("pubTypeList") or {}).get("pubType"), "abstract": (x.get("abstractText") or "")[:900]})
    nxt = d.get("nextCursorMark"); cur = nxt if nxt and nxt != cur else None
rows = list({r["pmcid"]: r for r in rows}.values())
SYS = ('Screen papers for a corpus on coffee or caffeine intake and diabetes and glucose metabolism. For each give kind: human_primary (new human data: cohort, trial, '
       'case-control, cross-sectional, Mendelian randomization), evidence_synthesis (systematic review or meta-analysis), animal_or_cell, narrative_review, other. '
       'Coffee or caffeine intake must be a studied exposure. keep=true for human_primary or evidence_synthesis with an outcome of type 2 or gestational diabetes, prediabetes, '
       'insulin resistance or sensitivity, glucose or HbA1c, or metabolic syndrome; animal_or_cell only when glucose metabolism or insulin action is measured. '
       'Methods papers and work where caffeine is only a reagent are keep=false. Return JSON {"items":[{"i":<i>,"kind":"...","keep":true|false,"reason":"<short>"}]}.')
for k in range(0, len(rows), 30):
    part = rows[k:k + 30]
    try:
        out, _ = llm.chat(os.environ.get("SCREEN_MODEL", "qwen_local"), SYS, json.dumps([{"i": n, "title": r["title"], "abstract": r["abstract"]} for n, r in enumerate(part)], ensure_ascii=False), 8000)
        for x in out.get("items", []):
            r = part[int(x["i"])]; r.update(kind=x.get("kind"), keep=bool(x.get("keep")), reason=x.get("reason"))
    except Exception as e: print("screen", k, str(e)[:100])
keep = [r for r in rows if r.get("keep")]
out = {"thread": "coffee and diabetes", "query": Q, "date": time.strftime("%Y-%m-%d"), "hits_with_pmcid": len(rows),
       "works": [{"id": r["id"], "title": r["title"], "year": r["year"], "role": r.get("kind"), "coffee_main": True, "pmcid": r["pmcid"], "in_store": r["pmcid"] in have, "screen_reason": r.get("reason")} for r in keep]}
json.dump(out, open("work/diabetes_candidates.json", "w"), indent=1); json.dump(rows, open("work/diabetes_screen.json", "w"), indent=1)
import collections
store.append("diabetes_candidates", {"hits": len(rows), "kept": len(keep), "kinds": dict(collections.Counter(r.get("kind") for r in keep))})
print(json.dumps({"hits_with_pmcid": len(rows), "kept": len(keep), "kinds": dict(collections.Counter(r.get("kind") for r in keep)), "new": sum(1 for r in keep if r["pmcid"] not in have)}))
