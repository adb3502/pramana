"""Topic corpus from OpenAlex (any field, not just biomedicine): search, screen, fetch open-access full text.
  python scripts/oa_select.py <tag> "<screen description>" "<query 1>" "<query 2>" ...
Keeps primary research, evidence syntheses, technical/government/industry reports and datasets that measure or model the topic;
drops commentary and off-topic hits. Full text: PMC (JATS) when a PMCID exists, else an open-access PDF to raw_pdf/<W id>.pdf.
Writes work/<tag>_candidates.json in ingest format (pmcid works for --from, pdf works for --from --pdf)."""
import os, sys, json, time, hashlib, requests, collections
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm, store
tag, desc, queries = sys.argv[1], sys.argv[2], sys.argv[3:]
OA = "https://api.openalex.org/works"; M = {"mailto": "epistemic@example.org"}
def abstract(w):
    inv = w.get("abstract_inverted_index") or {}
    return " ".join(t for _, t in sorted((i, t) for t, ii in inv.items() for i in ii))
rows = {}
for q in queries:
    for page in (1, 2, 3):
        try: d = requests.get(OA, params={**M, "search": q, "filter": "is_oa:true", "per-page": 100, "page": page, "sort": "relevance_score:desc"}, timeout=60).json()
        except Exception: break
        for w in d.get("results", []):
            if w["id"] in rows: continue
            ids = w.get("ids", {})
            rows[w["id"]] = {"id": w["id"].rsplit("/", 1)[-1], "title": w.get("title"), "year": w.get("publication_year"), "type": w.get("type"),
                             "doi": (w.get("doi") or "").replace("https://doi.org/", ""), "pmcid": (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None,
                             "cited_by": w.get("cited_by_count"), "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
                             "abstract": abstract(w)[:1200], "query": q,
                             "pdf_urls": [l.get("pdf_url") for l in ([w.get("best_oa_location") or {}] + (w.get("locations") or [])) if l and l.get("pdf_url")]}
        if len(d.get("results", [])) < 100: break
        time.sleep(0.3)
    print(q, len(rows), flush=True)
R = [r for r in rows.values() if r["title"]]
SYS = (f"Screen documents for an evidence corpus on: {desc}. For each give kind: primary_measurement (new measurements or data), modelling (new model or estimate), "
       "evidence_synthesis (systematic review, meta-analysis), technical_report (government, industry, NGO report with data), narrative_review, commentary, other. "
       "keep=true for primary_measurement, modelling, evidence_synthesis or technical_report that directly measures or estimates the topic; keep=false otherwise. "
       'Return JSON {"items":[{"i":<i>,"kind":"...","keep":true|false,"reason":"<short>"}]}.')
for k in range(0, len(R), 30):
    part = R[k:k + 30]
    try:
        out, _ = llm.chat(os.environ.get("SCREEN_MODEL", "haiku"), SYS, json.dumps([{"i": n, "title": r["title"], "venue": r["venue"], "abstract": r["abstract"]} for n, r in enumerate(part)], ensure_ascii=False), 8000)
        for x in out.get("items", []): part[int(x["i"])].update(kind=x.get("kind"), keep=bool(x.get("keep")), reason=x.get("reason"))
    except Exception as e: print("screen", k, str(e)[:100])
keep = [r for r in R if r.get("keep")]
S = requests.Session(); S.headers["User-Agent"] = "epistemic-framework/0.4 (research use)"
for r in keep:
    if r["pmcid"]: continue
    dest = f"raw_pdf/{r['id']}.pdf"
    if os.path.exists(dest): r["pdf"] = dest; continue
    for u in dict.fromkeys(r["pdf_urls"]):
        try:
            x = S.get(u, timeout=90, allow_redirects=True)
            if x.ok and x.content[:5] == b"%PDF-":
                open(dest, "wb").write(x.content); r["pdf"] = dest; r["pdf_url"] = u
                store.append("raw_doc", {"doc": r["id"], "source": u, "sha256": hashlib.sha256(x.content).hexdigest(), "kind": "pdf"}); break
        except Exception: pass
        time.sleep(1)
works = [{"id": r["id"], "title": r["title"], "year": r["year"], "role": r.get("kind"), "kind": r.get("kind"), "pmcid": r["pmcid"], "pdf": r.get("pdf"),
          "doi": r["doi"], "venue": r["venue"], "cited_by": r["cited_by"], "in_store": False, "screen_reason": r.get("reason")} for r in keep]
out = {"thread": tag, "description": desc, "queries": queries, "date": time.strftime("%Y-%m-%d"), "hits": len(R), "kept": len(keep),
       "kinds": dict(collections.Counter(r.get("kind") for r in keep)), "with_pmcid": sum(1 for w in works if w["pmcid"]),
       "with_pdf": sum(1 for w in works if w["pdf"]), "works": works}
json.dump(out, open(f"work/{tag}_candidates.json", "w"), indent=1); json.dump(R, open(f"work/{tag}_screen.json", "w"), indent=1)
store.append(f"{tag}_candidates", {k: v for k, v in out.items() if k != "works"})
print(json.dumps({k: v for k, v in out.items() if k != "works"}))
