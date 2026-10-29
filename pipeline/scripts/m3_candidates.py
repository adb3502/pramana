"""Mission 3 (item 11): fetch the Europe PMC candidate list for OA full-text coffee + cardiovascular primary studies.
Writes work/m3_candidates.json {query, date, count, results:[{pmcid, pmid, doi, title, authors, journal, year, abstract}]}."""
import json, time, datetime, requests
Q = ('(TITLE_ABS:coffee) AND TITLE_ABS:(cardiovascular OR coronary OR heart OR stroke OR mortality OR hypertension OR atrial) '
     'AND TITLE_ABS:(cohort OR prospective OR randomized OR "case-control" OR mendelian) AND SRC:MED AND HAS_FT:Y AND OPEN_ACCESS:Y')
# 245 hits on 26 Oct 2026 (PM's count). Restricting to PUB_TYPE research-article gives 211; reviews are removed at screening instead.
U = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
out, cursor = [], "*"
while True:
    r = requests.get(U, params={"query": Q, "format": "json", "resultType": "core", "pageSize": 100, "cursorMark": cursor}, timeout=90).json()
    for x in r["resultList"]["result"]:
        out.append({"pmcid": x.get("pmcid"), "pmid": x.get("pmid"), "doi": x.get("doi"), "title": x.get("title"), "authors": x.get("authorString", "")[:200],
                    "journal": (x.get("journalInfo") or {}).get("journal", {}).get("title"), "year": x.get("pubYear"),
                    "pubtypes": (x.get("pubTypeList") or {}).get("pubType"), "abstract": (x.get("abstractText") or "")[:4000]})
    nxt = r.get("nextCursorMark")
    if not nxt or nxt == cursor or not r["resultList"]["result"]: break
    cursor = nxt; time.sleep(0.5)
json.dump({"query": Q, "date": datetime.date.today().isoformat(), "count_reported": r.get("hitCount"), "count": len(out), "results": out},
          open("work/m3_candidates.json", "w"), indent=1)
print(r.get("hitCount"), len(out))
