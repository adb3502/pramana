"""Citation network around one seed paper, any field: seed + everything it cites + everything citing it (one level each way).
  python scripts/net_any.py <tag> <seed DOI or W id> [--depth2-refs]
Full text: PMC (JATS) when a PMCID exists, else an open-access PDF to raw_pdf/<W id>.pdf. Works with neither are listed as not_open.
Writes work/<tag>_candidates.json in ingest format (pmcid works for --from, pdf works for --from --pdf)."""
import os, sys, json, time, hashlib, requests
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import store
tag, seed = sys.argv[1], sys.argv[2]
OA = "https://api.openalex.org"; M = {"mailto": "epistemic@example.org"}
S = requests.Session(); S.headers["User-Agent"] = "epistemic-framework/0.4 (research use)"
def oa(path, **p):
    for a in range(4):
        r = S.get(f"{OA}/{path}", params={**M, **p}, timeout=60)
        if r.status_code == 429: time.sleep(10 * (a + 1)); continue
        return r.json()
    return {}
s = oa(f"works/{'doi:' + seed if seed.startswith('10.') else seed}")
net = [(s, "seed")]
def fetch_ids(ids, role):
    out = []
    for k in range(0, len(ids), 50):
        part = "|".join(i.rsplit("/", 1)[-1] for i in ids[k:k + 50])
        out += [(w, role) for w in oa("works", filter=f"openalex:{part}", **{"per-page": 50}).get("results", [])]
    return out
net += fetch_ids(s.get("referenced_works", []), "cited_by_seed")
page = 1
while True:
    d = oa("works", filter=f"cites:{s['id'].rsplit('/', 1)[-1]}", **{"per-page": 200, "page": page})
    net += [(w, "cites_seed") for w in d.get("results", [])]
    if len(d.get("results", [])) < 200: break
    page += 1
if "--depth2-refs" in sys.argv:
    for w, role in list(net):
        if role == "cited_by_seed": net += fetch_ids(w.get("referenced_works", [])[:60], "cited_by_ref")
works, seen, not_open = [], set(), []
for w, role in net:
    wid = w["id"].rsplit("/", 1)[-1]
    if wid in seen: continue
    seen.add(wid)
    ids = w.get("ids", {}); pmcid = (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None
    rec = {"id": wid, "title": w.get("title"), "year": w.get("publication_year"), "role": role, "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
           "type": w.get("type"), "pmcid": pmcid, "pdf": None, "in_store": False}
    if not pmcid:
        dest = f"raw_pdf/{wid}.pdf"
        if os.path.exists(dest): rec["pdf"] = dest
        else:
            urls = [l.get("pdf_url") for l in ([w.get("best_oa_location") or {}] + (w.get("locations") or [])) if l and l.get("pdf_url")]
            for u in dict.fromkeys(urls):
                try:
                    x = S.get(u, timeout=90, allow_redirects=True)
                    if x.ok and x.content[:5] == b"%PDF-":
                        open(dest, "wb").write(x.content); rec["pdf"] = dest; rec["pdf_url"] = u
                        store.append("raw_doc", {"doc": wid, "source": u, "sha256": hashlib.sha256(x.content).hexdigest(), "kind": "pdf"}); break
                except Exception: pass
                time.sleep(1)
    if rec["pmcid"] or rec["pdf"]: works.append(rec)
    else: not_open.append({"id": wid, "title": w.get("title"), "role": role, "type": w.get("type")})
out = {"thread": tag, "seed": s.get("id"), "seed_title": s.get("title"), "date": time.strftime("%Y-%m-%d"),
       "network": {"refs": len(s.get("referenced_works", [])), "citers": sum(1 for _, r in net if r == "cites_seed"), "total": len(seen),
                   "open_pmc": sum(1 for w in works if w["pmcid"]), "open_pdf": sum(1 for w in works if w["pdf"] and not w["pmcid"]), "not_open": len(not_open)},
       "not_open": not_open, "works": works}
json.dump(out, open(f"work/{tag}_candidates.json", "w"), indent=1)
store.append(f"{tag}_candidates", {k: v for k, v in out.items() if k not in ("works", "not_open")})
print(json.dumps(out["network"]), json.dumps([w for w in works if w["role"] == "seed"]))
