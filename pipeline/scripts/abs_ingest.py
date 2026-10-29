"""Abstract-only tier for works with no open full text, plus title backfill for PDF-parsed works.
Usage: python scripts/abs_ingest.py work/water_candidates.json water
Writes parsed/<W>.json (source_format 'abstract') for works with no pmcid and no pdf, appends them to work/corpus/<tag>.txt,
and fills empty titles in parsed/<W>.json from the candidate list. Then run scripts/ingest.py on the ids it prints."""
import os, sys, json, time, hashlib, requests
os.chdir(os.path.expanduser("~/epistemic"))
cand, tag = sys.argv[1], sys.argv[2]
W = json.load(open(cand))["works"]
def wid(w): return w["id"].rsplit("/", 1)[-1]
# 1. title backfill
fixed = 0
for w in W:
    p = f"parsed/{wid(w)}.json"
    if os.path.exists(p) and w.get("title"):
        d = json.load(open(p))
        if not d.get("title"):
            d["title"] = w["title"]; json.dump(d, open(p, "w")); fixed += 1
print(json.dumps({"titles_fixed": fixed}))
# 2. abstracts
def oa_abstract(i):
    for k in range(4):
        r = requests.get(f"https://api.openalex.org/works/{i}", params={"select": "id,abstract_inverted_index,title"}, timeout=20)
        if r.status_code == 429: time.sleep(2 + 3 * k); continue
        if r.status_code != 200: return None
        inv = r.json().get("abstract_inverted_index") or {}
        pos = sorted((p, t) for t, ps in inv.items() for p in ps)
        return " ".join(t for _, t in pos) or None
    return None
def cr_abstract(doi):
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}", timeout=20)
        if r.status_code != 200: return None
        a = r.json()["message"].get("abstract")
        if not a: return None
        import re; return re.sub(r"<[^>]+>", " ", a).strip()
    except Exception: return None
ids, miss = [], []
for w in W:
    if w.get("pmcid") or w.get("pdf"): continue
    i = wid(w); p = f"parsed/{i}.json"
    if os.path.exists(p): ids.append(i); continue
    a = oa_abstract(i) or (cr_abstract(w["doi"]) if w.get("doi") else None)
    time.sleep(0.15)
    if not a or len(a) < 200: miss.append(i); continue
    d = {"doc": i, "sha256": hashlib.sha256(a.encode()).hexdigest(), "parser": "openalex-abstract v1", "source_format": "abstract",
         "title": w.get("title") or "", "pages": 0, "rotated_pages": [], "page_copies": {}, "ocr_pages": [],
         "sections": [{"id": "S0", "title": "Abstract", "text": a, "paras": [{"id": "P0", "page": 0, "bbox": None, "label": "text"}]}],
         "tables": [], "figures": [], "supplements": [], "candidates": [],
         "read_summary": {"note": "abstract only: no open full text"}, "meta": {"doi": w.get("doi"), "venue": w.get("venue"), "year": w.get("year")}}
    json.dump(d, open(p, "w")); ids.append(i)
with open(f"work/corpus/{tag}.txt", "a") as f: f.write("\n".join(ids) + "\n")
open(f"work/{tag}_abstract_ids.txt", "w").write("\n".join(ids) + "\n")
print(json.dumps({"abstract_docs": len(ids), "no_abstract": len(miss)}))
