"""Acquire full text, richest source first: PMC JATS XML (via NCBI eutils), with content hashes.
PDF route (publisher text-mining APIs / campus IP) is a later stage; this module records what was not obtainable."""
import sys, time, json, hashlib, pathlib, requests
S = requests.Session()
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

def pmid_to_pmcid(pmid):
    r = S.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
              params={"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "resultType": "lite"}, timeout=60).json()
    res = r["resultList"]["result"]
    return res[0].get("pmcid") if res else None

def fetch_jats(pmcid, outdir="raw"):
    out = pathlib.Path(outdir); out.mkdir(exist_ok=True)
    p = out / f"{pmcid}.xml"
    if not p.exists():
        r = S.get(f"{EUTILS}/efetch.fcgi", params={"db": "pmc", "id": pmcid.replace("PMC", "")}, timeout=90)
        r.raise_for_status(); p.write_bytes(r.content); time.sleep(0.4)
    b = p.read_bytes()
    ok = b"<table-wrap" in b or b"<body" in b
    return {"doc": pmcid, "path": str(p), "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b), "has_body": ok}

if __name__ == "__main__":
    ids = sys.argv[1:]
    for i in ids:
        pmc = i if i.startswith("PMC") else pmid_to_pmcid(i)
        print(json.dumps(fetch_jats(pmc) if pmc else {"input": i, "error": "no PMC full text; needs PDF route"}))
