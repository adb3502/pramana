"""Resolve PMCIDs for mission 4 candidates via Europe PMC (by PMID, else DOI); mark open-access full text and what is already stored."""
import os, json, time, requests
os.chdir(os.path.expanduser("~/epistemic"))
C = json.load(open("work/m4_candidates.json"))
have = {f[:-4] for f in os.listdir("raw") if f.endswith(".xml")}
for w in C["works"]:
    q = f"EXT_ID:{w['pmid']} AND SRC:MED" if w.get("pmid") else (f'DOI:"{w["doi"].replace("https://doi.org/", "")}"' if w.get("doi") else None)
    if not q: continue
    try:
        r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": q, "format": "json", "resultType": "lite"}, timeout=60).json()
        res = (r.get("resultList") or {}).get("result") or []
        if res:
            x = res[0]; w["pmcid"] = x.get("pmcid"); w["epmc_oa"] = x.get("isOpenAccess") == "Y"; w["has_ft"] = x.get("inPMC") == "Y" or x.get("hasTextMinedTerms") == "Y"
    except Exception: pass
    w["in_store"] = bool(w.get("pmcid") and w["pmcid"] in have); time.sleep(0.2)
json.dump(C, open("work/m4_candidates.json", "w"), indent=1)
W = C["works"]
print(json.dumps({"selected": len(W), "with_pmcid": sum(1 for w in W if w.get("pmcid")), "already_in_store": sum(1 for w in W if w["in_store"]),
                  "new_with_pmcid": sum(1 for w in W if w.get("pmcid") and not w["in_store"]), "new_oa_pmc": sum(1 for w in W if w.get("pmcid") and not w["in_store"] and w.get("epmc_oa")),
                  "no_pmcid": sum(1 for w in W if not w.get("pmcid"))}))
