"""Pull every citing sentence for a paper from Semantic Scholar (works for paywalled citers).
Needs S2_API_KEY in the environment. Rate limit: 1 request/second."""
import os, sys, json, time, requests
def citations(doi, out):
    H = {"x-api-key": os.environ["S2_API_KEY"]}
    res, off = [], 0
    while True:
        r = requests.get(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}/citations",
                         params={"fields": "contexts,intents,isInfluential,title,year,venue,externalIds,publicationTypes",
                                 "limit": 1000, "offset": off}, headers=H, timeout=60)
        r.raise_for_status(); d = r.json(); res += d.get("data", [])
        if "next" not in d: break
        off = d["next"]; time.sleep(1.1)
    json.dump(res, open(out, "w"))
    print(json.dumps({"citers": len(res), "with_contexts": sum(1 for c in res if c.get("contexts"))}))
if __name__ == "__main__":
    citations(sys.argv[1], sys.argv[2])
