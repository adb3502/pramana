"""Thread 2 corpus: coffee/caffeine and aging/longevity. Europe PMC open-access full texts, screened by DeepSeek (OpenRouter)
into kinds; keeps new human data, evidence syntheses and animal/cell aging studies. -> work/aging_candidates.json (ingest format)"""
import os, sys, json, time, requests
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm, store
Q = ('(TITLE_ABS:coffee OR TITLE_ABS:caffeine) AND (TITLE_ABS:aging OR TITLE_ABS:ageing OR TITLE_ABS:longevity OR TITLE_ABS:lifespan OR TITLE_ABS:healthspan '
     'OR TITLE_ABS:"biological age" OR TITLE_ABS:"epigenetic age" OR TITLE_ABS:"epigenetic clock" OR TITLE_ABS:telomere OR TITLE_ABS:frailty OR TITLE_ABS:sarcopenia '
     'OR TITLE_ABS:"cognitive decline" OR TITLE_ABS:"cognitive function" OR TITLE_ABS:dementia OR TITLE_ABS:alzheimer OR TITLE_ABS:parkinson OR TITLE_ABS:neurodegenerat* '
     'OR TITLE_ABS:senescence OR TITLE_ABS:"healthy aging" OR TITLE_ABS:centenarian OR TITLE_ABS:"older adults" OR TITLE_ABS:elderly OR TITLE_ABS:"all-cause mortality" '
     'OR TITLE_ABS:inflammaging OR TITLE_ABS:"physical function" OR TITLE_ABS:"bone mineral density" OR TITLE_ABS:osteoporosis OR TITLE_ABS:autophagy) '
     'AND OPEN_ACCESS:Y AND IN_EPMC:Y')
have = {f[:-4] for f in os.listdir("raw") if f.endswith(".xml")}
try: have |= {w.get("pmcid") for w in json.load(open("work/m4_candidates.json"))["works"] if w.get("pmcid")}
except FileNotFoundError: pass
rows, cur = [], "*"
while cur:
    d = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": Q, "format": "json", "resultType": "core", "pageSize": 1000, "cursorMark": cur}, timeout=120).json()
    for x in (d.get("resultList") or {}).get("result") or []:
        if x.get("pmcid"): rows.append({"id": x.get("id"), "pmcid": x["pmcid"], "title": x.get("title"), "year": x.get("pubYear"), "pubtype": (x.get("pubTypeList") or {}).get("pubType"), "abstract": (x.get("abstractText") or "")[:900]})
    nxt = d.get("nextCursorMark"); cur = nxt if nxt and nxt != cur else None
rows = list({r["pmcid"]: r for r in rows}.values())
SYS = ('Screen papers for a corpus on coffee or caffeine intake and aging and longevity. For each give kind: human_primary (new human data: cohort, trial, case-control, '
       'cross-sectional, Mendelian randomization), evidence_synthesis (systematic review or meta-analysis), animal_or_cell (experimental work in animals, cells or other organisms), '
       'narrative_review, other. Coffee or caffeine intake must be a studied exposure. keep=true for: human_primary or evidence_synthesis with EITHER an aging-related outcome '
       '(mortality or survival, longevity, biological or epigenetic age, telomeres, frailty, sarcopenia, physical function, bone loss, cognitive decline, dementia, Alzheimer, '
       'Parkinson or other neurodegeneration, healthy aging) OR a population of older adults (roughly 60+) with any health outcome; animal_or_cell ONLY when lifespan, healthspan '
       'or a recognized hallmark of aging (senescence, autophagy, telomere attrition, mitochondrial or proteostasis decline, stem cell exhaustion, neurodegeneration) is measured. '
       'Methods papers, insecticide or pest studies, and work where caffeine is only a reagent are keep=false. '
       'Return JSON {"items":[{"i":<i>,"kind":"...","keep":true|false,"reason":"<short>"}]}.')
for k in range(0, len(rows), 30):
    part = rows[k:k + 30]
    try:
        out, _ = llm.chat("or_deepseek", SYS, json.dumps([{"i": n, "title": r["title"], "abstract": r["abstract"]} for n, r in enumerate(part)], ensure_ascii=False), 8000)
        for x in out.get("items", []):
            r = part[int(x["i"])]; r.update(kind=x.get("kind"), keep=bool(x.get("keep")), reason=x.get("reason"))
    except Exception as e: print("screen", k, str(e)[:100])
keep = [r for r in rows if r.get("keep")]
out = {"thread": "coffee and aging v2", "query": Q, "date": time.strftime("%Y-%m-%d"), "hits_with_pmcid": len(rows),
       "works": [{"id": r["id"], "title": r["title"], "year": r["year"], "role": r.get("kind"), "coffee_main": True, "pmcid": r["pmcid"], "in_store": r["pmcid"] in have, "screen_reason": r.get("reason")} for r in keep]}
json.dump(out, open("work/aging_candidates.json", "w"), indent=1); json.dump(rows, open("work/aging_screen.json", "w"), indent=1)
import collections
store.append("aging_candidates", {"hits": len(rows), "kept": len(keep), "kinds": dict(collections.Counter(r.get("kind") for r in keep))})
print(json.dumps({"hits_with_pmcid": len(rows), "kept": len(keep), "kinds": dict(collections.Counter(r.get("kind") for r in keep)), "new": sum(1 for r in keep if r["pmcid"] not in have)}))
