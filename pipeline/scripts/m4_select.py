"""Mission 4 selection: works citing the root that report new human data or pool studies, with coffee as the main subject.
Resolves PMCIDs via OpenAlex (single-work lookups), marks which are already in the store. -> work/m4_candidates.json"""
import os, sys, json, time, requests
os.chdir(os.path.expanduser("~/epistemic"))
root = sys.argv[1]
R = json.load(open(f"work/crawl/{root}_roles.json"))
keep = [r for r in R if r["role"] in ("new_evidence", "evidence_synthesis") and r["coffee_main"]]
have = {f[:-4] for f in os.listdir("raw") if f.endswith(".xml")} | {f[:-4] for f in os.listdir("raw_pdf") if f.endswith(".pdf")}
out = []
for r in keep:
    wid = r["id"].rsplit("/", 1)[-1]
    try:
        w = requests.get(f"https://api.openalex.org/works/{wid}", params={"select": "ids,doi,open_access,best_oa_location"}, timeout=60).json()
    except Exception: w = {}
    ids = w.get("ids") or {}; pmc = (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None
    if pmc and not pmc.startswith("PMC"): pmc = "PMC" + pmc
    out.append({**r, "pmcid": pmc, "pmid": (ids.get("pmid") or "").rsplit("/", 1)[-1] or None, "doi": w.get("doi"),
                "is_oa": (w.get("open_access") or {}).get("is_oa"), "oa_url": (w.get("best_oa_location") or {}).get("pdf_url"), "in_store": bool(pmc and pmc in have)})
    time.sleep(0.15)
json.dump({"root": root, "selected": len(keep), "works": out}, open("work/m4_candidates.json", "w"), indent=1)
n_pmc = sum(1 for x in out if x["pmcid"]); n_new = sum(1 for x in out if x["pmcid"] and not x["in_store"])
print(json.dumps({"selected": len(keep), "with_pmcid": n_pmc, "already_in_store": sum(x["in_store"] for x in out), "new_with_pmcid": n_new,
                  "no_pmcid_but_oa": sum(1 for x in out if not x["pmcid"] and x["is_oa"]), "closed_no_pmcid": sum(1 for x in out if not x["pmcid"] and not x["is_oa"])}))
