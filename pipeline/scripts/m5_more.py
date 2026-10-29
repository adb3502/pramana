"""Top-up candidates toward 250 papers: (1) the studies the root itself pooled (its reference list), (2) Europe PMC open-access
primary studies on coffee/caffeine and cardiometabolic or mortality outcomes. Screened by local Qwen (primary human study? coffee or
caffeine exposure? health outcome?), reasons kept. Appends to work/m4_candidates.json as source m5_*. Usage: python scripts/m5_more.py W2137201442"""
import os, sys, json, time, requests
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm, store
root = sys.argv[1]
C = json.load(open("work/m4_candidates.json")); seen = {w.get("pmcid") for w in C["works"] if w.get("pmcid")} | {f[:-4] for f in os.listdir("raw") if f.endswith(".xml")}
cands = []
refs = requests.get(f"https://api.openalex.org/works/{root}", params={"select": "referenced_works"}, timeout=60).json().get("referenced_works", [])
for r in refs:
    wid = r.rsplit("/", 1)[-1]
    try:
        w = requests.get(f"https://api.openalex.org/works/{wid}", params={"select": "id,display_name,publication_year,ids,doi"}, timeout=60).json()
        pmid = ((w.get("ids") or {}).get("pmid") or "").rsplit("/", 1)[-1]
        q = f"EXT_ID:{pmid} AND SRC:MED" if pmid else (f'DOI:"{(w.get("doi") or "").replace("https://doi.org/", "")}"' if w.get("doi") else None)
        x = ((requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": q, "format": "json", "resultType": "lite"}, timeout=60).json().get("resultList") or {}).get("result") or [{}])[0] if q else {}
        cands.append({"id": w.get("id"), "title": w.get("display_name"), "year": w.get("publication_year"), "pmcid": x.get("pmcid"), "abstract": "", "source": "m5_root_refs"})
    except Exception: pass
    time.sleep(0.2)
Q = ('(TITLE_ABS:"coffee" OR TITLE_ABS:"caffeine") AND (TITLE_ABS:cardiovascular OR TITLE_ABS:coronary OR TITLE_ABS:stroke OR TITLE_ABS:"heart failure" OR TITLE_ABS:mortality '
     'OR TITLE_ABS:hypertension OR TITLE_ABS:"blood pressure" OR TITLE_ABS:arrhythmia OR TITLE_ABS:"atrial fibrillation" OR TITLE_ABS:diabetes) AND (TITLE_ABS:cohort OR TITLE_ABS:prospective '
     'OR TITLE_ABS:randomized OR TITLE_ABS:randomised OR TITLE_ABS:"case-control" OR TITLE_ABS:"Mendelian") AND OPEN_ACCESS:Y AND IN_EPMC:Y AND SRC:MED AND PUB_TYPE:"research-article"')
cur = "*"
while cur and len([c for c in cands if c["source"] == "m5_epmc"]) < 1000:
    d = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": Q, "format": "json", "resultType": "core", "pageSize": 1000, "cursorMark": cur}, timeout=120).json()
    for x in (d.get("resultList") or {}).get("result") or []:
        cands.append({"id": x.get("id"), "title": x.get("title"), "year": x.get("pubYear"), "pmcid": x.get("pmcid"), "abstract": (x.get("abstractText") or "")[:900], "source": "m5_epmc"})
    nxt = d.get("nextCursorMark"); cur = nxt if nxt and nxt != cur else None
cands = [c for c in cands if c.get("pmcid") and c["pmcid"] not in seen]
uniq = {}; [uniq.setdefault(c["pmcid"], c) for c in cands]; cands = list(uniq.values())
SYS = ('Screen each paper for a corpus on coffee or caffeine and human health. keep=true only if it reports NEW data from humans (cohort, trial, case-control, cross-sectional, '
       'Mendelian randomization) with coffee or caffeine intake as an exposure and a cardiovascular, metabolic or mortality outcome. Return JSON {"items":[{"i":<i>,"keep":true|false,"reason":"<short>"}]}.')
for k in range(0, len(cands), 30):
    part = cands[k:k + 30]
    try:
        out, _ = llm.chat("qwen_local", SYS, json.dumps([{"i": n, "title": c["title"], "abstract": c["abstract"]} for n, c in enumerate(part)], ensure_ascii=False), 6000)
        for x in out.get("items", []):
            c = part[int(x["i"])]; c["keep"] = bool(x.get("keep")); c["reason"] = x.get("reason")
    except Exception as e: print("screen", k, str(e)[:100])
keep = [c for c in cands if c.get("keep") or c["source"] == "m5_root_refs"]
for c in keep: C["works"].append({"id": c["id"], "title": c["title"], "year": c["year"], "role": "new_evidence", "coffee_main": True, "pmcid": c["pmcid"], "in_store": False, "source": c["source"], "screen_reason": c.get("reason")})
json.dump(C, open("work/m4_candidates.json", "w"), indent=1)
json.dump(cands, open("work/m5_screen.json", "w"), indent=1)
store.append("m5_candidates", {"root_refs_with_pmc": sum(1 for c in cands if c["source"] == "m5_root_refs"), "epmc_screened": sum(1 for c in cands if c["source"] == "m5_epmc"), "kept": len(keep)})
print(json.dumps({"root_refs_new_pmc": sum(1 for c in cands if c["source"] == "m5_root_refs"), "epmc_new": sum(1 for c in cands if c["source"] == "m5_epmc"),
                  "epmc_kept": sum(1 for c in cands if c["source"] == "m5_epmc" and c.get("keep")), "added": len(keep)}))
