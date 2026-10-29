"""Sort every work citing the root by what it does with it. Abstracts from OpenAlex, roles by Haiku in batches of 40.
Usage: python scripts/citer_roles.py W2137201442 -> work/crawl/<root>_roles.json"""
import sys, os, json, time, collections, requests
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm, store
root = sys.argv[1]; works = []; page = 1
while True:
    r = requests.get("https://api.openalex.org/works", params={"filter": f"cites:{root}", "select": "id,display_name,publication_year,type,abstract_inverted_index,primary_location", "per-page": 200, "page": page}, timeout=60)
    if r.status_code != 200: print("page", page, r.status_code); break
    d = r.json(); works += d["results"]; page += 1; time.sleep(1)
    if not d["results"] or len(works) >= d["meta"]["count"]: break
def abstract(inv):
    if not inv: return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps); return " ".join(w for _, w in pos)
ROLES = {"new_evidence": "reports new human data (cohort, trial, case-control, cross-sectional, Mendelian randomization) on coffee or caffeine and a health outcome",
         "evidence_synthesis": "systematic review, meta-analysis or umbrella review that pools studies",
         "narrative_review": "narrative or expert review summarising literature without pooling",
         "guideline_policy": "clinical guideline, dietary guideline, regulatory or position statement",
         "mechanism": "laboratory, animal, cell, chemistry or food-science work on coffee, caffeine or their compounds",
         "other_topic": "primary topic is something else; cites the root only as background",
         "commentary": "editorial, letter, comment or opinion"}
SYS = ("Classify each scientific work by what it does, using exactly one role from: " + json.dumps(ROLES) +
       '. Also say whether coffee or caffeine is the main subject (coffee_main true/false). Return JSON {"items": [{"i": <index>, "role": "...", "coffee_main": true|false}]}, one per input.')
out = {}
for k in range(0, len(works), 40):
    batch = works[k:k + 40]
    items = [{"i": k + j, "type": w["type"], "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"), "title": w["display_name"], "abstract": abstract(w.get("abstract_inverted_index"))[:900]} for j, w in enumerate(batch)]
    try:
        res, usd = llm.chat(os.environ.get("ROLE_MODEL","qwen_local"), SYS, json.dumps(items, ensure_ascii=False), 8000)
        for x in res.get("items", []): out[int(x["i"])] = x
    except Exception as e: print("batch", k, str(e)[:120])
rows = [{"id": w["id"], "title": w["display_name"], "year": w["publication_year"], "type": w["type"], "has_abstract": bool(w.get("abstract_inverted_index")),
         "role": (out.get(i) or {}).get("role"), "coffee_main": (out.get(i) or {}).get("coffee_main")} for i, w in enumerate(works)]
json.dump(rows, open(f"work/crawl/{root}_roles.json", "w"), indent=1)
c = collections.Counter(r["role"] for r in rows); cm = collections.Counter((r["role"], r["coffee_main"]) for r in rows)
print(json.dumps({"works": len(rows), "with_abstract": sum(r["has_abstract"] for r in rows), "roles": c.most_common(), "coffee_main": sum(1 for r in rows if r["coffee_main"])}))
for role in ROLES: print(role, cm.get((role, True), 0), cm.get((role, False), 0))
by = collections.defaultdict(list)
for r in rows: by[r["role"]].append(r)
for role, rs in by.items():
    for r in sorted(rs, key=lambda r: -(r["year"] or 0))[:2]: print("EX", role, r["year"], (r["title"] or "")[:100])
store.append("citer_roles", {"root": root, "works": len(rows), "roles": dict(c)})
