"""Level 1 of the citation tree: every work citing the root, with its reference count. Usage: python scripts/citers.py W2137201442"""
import sys, os, json, time, requests, statistics, collections
os.chdir(os.path.expanduser("~/epistemic"))
root = sys.argv[1]; out = []; page = 1
sel = "referenced_works,id,doi,display_name,publication_year,type,referenced_works_count,cited_by_count,ids,open_access,primary_location"
while True:
    r = requests.get("https://api.openalex.org/works", params={"filter": f"cites:{root}", "select": sel, "per-page": 200, "page": page}, timeout=60)
    if r.status_code != 200: print("page", page, r.status_code, r.text[:200]); break
    d = r.json(); out += d["results"]; page += 1; time.sleep(1)
    if not d["results"] or len(out) >= d["meta"]["count"]: break
os.makedirs("work/crawl", exist_ok=True)
json.dump({"root": root, "fetched_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "works": out}, open(f"work/crawl/{root}_citing.json", "w"))
refs = [w["referenced_works_count"] or 0 for w in out]
t = collections.Counter(w["type"] for w in out)
pmc = sum(1 for w in out if (w.get("ids") or {}).get("pmcid")); oa = sum(1 for w in out if (w.get("open_access") or {}).get("is_oa"))
bins = collections.Counter(("0" if x == 0 else "1-9" if x < 10 else "10-29" if x < 30 else "30-49" if x < 50 else "50-99" if x < 100 else "100-199" if x < 200 else "200+") for x in refs)
print(json.dumps({"citing": len(out), "types": dict(t), "refs_total": sum(refs), "refs_mean": round(statistics.mean(refs), 1), "refs_median": statistics.median(refs),
                  "refs_max": max(refs), "zero_refs": refs.count(0), "bins": dict(bins), "with_pmcid": pmc, "open_access": oa,
                  "by_type_median": {k: statistics.median([w["referenced_works_count"] or 0 for w in out if w["type"] == k]) for k in t}}))
for w in sorted(out, key=lambda w: -(w["referenced_works_count"] or 0))[:8]:
    print(w["referenced_works_count"], w["publication_year"], w["type"], (w["display_name"] or "")[:90])
