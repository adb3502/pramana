"""Open-access PDFs for mission 4 candidates without a PMC copy: OpenAlex best/any OA location pdf_url, plain GET only
(no browser, no retries past a block). Saves raw_pdf/<W id>.pdf when the response really is a PDF; records every outcome."""
import os, json, time, hashlib, requests
os.chdir(os.path.expanduser("~/epistemic"))
C = json.load(open("work/m4_candidates.json")); log = []
S = requests.Session(); S.headers["User-Agent"] = "epistemic-framework/0.4 (research use; contact via repository)"
import sys; sys.path.insert(0, os.path.expanduser("~/epistemic"))
for w in C["works"]:
    if w.get("pmcid"): continue
    wid = w["id"].rsplit("/", 1)[-1]; dest = f"raw_pdf/{wid}.pdf"
    if os.path.exists(dest): w["pdf"] = dest; continue
    try: rec = requests.get(f"https://api.openalex.org/works/{wid}", params={"select": "best_oa_location,locations"}, timeout=60).json()
    except Exception: rec = {}
    urls = [l.get("pdf_url") for l in ([rec.get("best_oa_location") or {}] + (rec.get("locations") or [])) if l and l.get("pdf_url")]
    got = None
    for u in dict.fromkeys(urls):
        try:
            r = S.get(u, timeout=90, allow_redirects=True)
            if r.ok and r.content[:5] == b"%PDF-":
                open(dest, "wb").write(r.content); got = u; break
            log.append({"id": wid, "url": u, "status": r.status_code, "ctype": r.headers.get("content-type", "")[:40]})
        except Exception as e: log.append({"id": wid, "url": u, "error": str(e)[:80]})
        time.sleep(1)
    if got:
        w["pdf"] = dest; w["pdf_url"] = got
        from epistemic import store
        store.append("raw_doc", {"doc": wid, "source": got, "sha256": hashlib.sha256(open(dest, "rb").read()).hexdigest(), "kind": "pdf"})
    w["pdf_tried"] = len(urls)
json.dump(C, open("work/m4_candidates.json", "w"), indent=1); json.dump(log, open("work/m4_pdf_failures.json", "w"), indent=1)
W = [w for w in C["works"] if not w.get("pmcid")]
print(json.dumps({"no_pmcid": len(W), "with_pdf_url": sum(1 for w in W if w.get("pdf_tried")), "downloaded": sum(1 for w in W if w.get("pdf")), "blocked_or_html": len(log)}))
