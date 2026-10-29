"""Citation-network corpus around one seed paper, topic-free.
  python scripts/net_select.py <tag> <seed doi or W id> "<Europe PMC topic query or ''>" "<screen description>"
Collects: the seed, everything it cites, everything citing it (OpenAlex), plus an optional Europe PMC topic search,
resolves open-access PMCIDs, screens topic hits with Haiku, writes work/<tag>_candidates.json (ingest format)."""
import os, sys, json, time, requests, collections
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm, store
tag, seed, topicq, desc = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
OA = "https://api.openalex.org"; EP = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"; M = {"mailto": "epistemic@example.org"}
def oa(path, **p): return requests.get(f"{OA}/{path}", params={**M, **p}, timeout=60).json()
def ep(q, size=1000, cur="*"): return requests.get(EP, params={"query": q, "format": "json", "resultType": "core", "pageSize": size, "cursorMark": cur}, timeout=120).json()
s = oa(f"works/{'doi:' + seed if seed.startswith('10.') else seed}")
net = [(s, "seed")]
refs = s.get("referenced_works", [])
for k in range(0, len(refs), 50):
    ids = "|".join(r.rsplit("/", 1)[-1] for r in refs[k:k + 50])
    net += [(w, "cited_by_seed") for w in oa("works", filter=f"openalex:{ids}", **{"per-page": 50}).get("results", [])]
page = 1
while True:
    d = oa("works", filter=f"cites:{s['id'].rsplit('/', 1)[-1]}", **{"per-page": 200, "page": page})
    net += [(w, "cites_seed") for w in d.get("results", [])]
    if len(d.get("results", [])) < 200: break
    page += 1
rows = {}
for w, role in net:
    doi = (w.get("doi") or "").replace("https://doi.org/", ""); pmcid = (w.get("ids", {}).get("pmcid") or "").rsplit("/", 1)[-1] or None
    oa_ok = (w.get("open_access") or {}).get("is_oa")
    if not pmcid and doi:
        try:
            h = ep(f'DOI:"{doi}"', 3).get("resultList", {}).get("result", [])
            if h: pmcid = h[0].get("pmcid")
        except Exception: pass
    rows[w["id"]] = {"id": w["id"].rsplit("/", 1)[-1], "doi": doi, "pmcid": pmcid, "title": w.get("title"), "year": w.get("publication_year"),
                     "role": role, "is_oa": oa_ok, "keep": True, "kind": "network"}
    time.sleep(0.15)
topic = []
if topicq:
    cur = "*"
    while cur:
        d = ep(topicq + " AND OPEN_ACCESS:Y AND IN_EPMC:Y", 1000, cur)
        for x in (d.get("resultList") or {}).get("result") or []:
            if x.get("pmcid"): topic.append({"id": x.get("id"), "pmcid": x["pmcid"], "title": x.get("title"), "year": x.get("pubYear"), "abstract": (x.get("abstractText") or "")[:900], "role": "topic"})
        nxt = d.get("nextCursorMark"); cur = nxt if nxt and nxt != cur else None
    topic = list({r["pmcid"]: r for r in topic}.values())
    SYS = (f"Screen papers for a corpus on: {desc}. For each give kind: human_primary (new human data), evidence_synthesis (systematic review or meta-analysis), "
           "animal_or_cell, narrative_review, other. keep=true for human_primary, evidence_synthesis, or animal_or_cell work that directly studies the topic; "
           "keep=false for narrative reviews, methods papers and off-topic hits. Return JSON {\"items\":[{\"i\":<i>,\"kind\":\"...\",\"keep\":true|false,\"reason\":\"<short>\"}]}.")
    for k in range(0, len(topic), 30):
        part = topic[k:k + 30]
        try:
            out, _ = llm.chat(os.environ.get("SCREEN_MODEL", "haiku"), SYS, json.dumps([{"i": n, "title": r["title"], "abstract": r["abstract"]} for n, r in enumerate(part)], ensure_ascii=False), 8000)
            for x in out.get("items", []): part[int(x["i"])].update(kind=x.get("kind"), keep=bool(x.get("keep")), reason=x.get("reason"))
        except Exception as e: print("screen", k, str(e)[:100])
have_raw = {f[:-4] for f in os.listdir("raw") if f.endswith(".xml")}
works, seen = [], set()
for r in list(rows.values()) + [t for t in topic if t.get("keep")]:
    if not r.get("pmcid") or r["pmcid"] in seen: continue
    seen.add(r["pmcid"])
    works.append({"id": r["id"], "title": r["title"], "year": r["year"], "role": r.get("role"), "kind": r.get("kind"), "pmcid": r["pmcid"],
                  "in_store": False, "screen_reason": r.get("reason")})
works.sort(key=lambda w: {"seed": 0, "cited_by_seed": 1, "cites_seed": 1}.get(w["role"], 2))
out = {"thread": tag, "seed": s["id"], "seed_title": s.get("title"), "topic_query": topicq, "date": time.strftime("%Y-%m-%d"),
       "network": {"refs": len(refs), "citers": sum(1 for _, r in net if r == "cites_seed"),
                   "with_pmcid": sum(1 for r in rows.values() if r["pmcid"]), "not_open": [r["title"] for r in rows.values() if not r["pmcid"]][:80]},
       "topic_hits": len(topic), "topic_kept": sum(1 for t in topic if t.get("keep")), "works": works}
json.dump(out, open(f"work/{tag}_candidates.json", "w"), indent=1); json.dump(list(rows.values()) + topic, open(f"work/{tag}_screen.json", "w"), indent=1)
store.append(f"{tag}_candidates", {k: v for k, v in out.items() if k != "works"} | {"n_works": len(works)})
print(json.dumps({k: v for k, v in out.items() if k not in ("works",)} | {"n_works": len(works), "already_parsed": sum(1 for w in works if w["pmcid"] in have_raw)}, default=str)[:1500])
