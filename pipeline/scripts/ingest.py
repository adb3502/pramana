"""Mission 4 ingest: new PMC papers end to end through framework v4, several papers at a time.
fetch -> parse -> supplements -> figures -> structure (card, analyses, claims, bias, warrants) -> pass R (A haiku, B qwen_local) on
<doc>, <doc>_S, <doc>_F -> validate -> Laya gate -> judge ladder -> concepts -> closure. Each step is skipped when its output exists.
Usage: python scripts/ingest.py [--workers 4] PMC... | --from work/m4_candidates.json"""
import os, sys, json, subprocess, time, concurrent.futures as cf
os.chdir(os.path.expanduser("~/epistemic")); PY = ".venv/bin/python"
def sh(args, log):
    r = subprocess.run(args, capture_output=True, text=True); log.write(" ".join(args) + "\n" + (r.stdout[-2000:] or "") + (r.stderr[-1500:] if r.returncode else "") + "\n"); log.flush()
    return r.returncode == 0
def one(doc):
    os.makedirs("logs/ingest", exist_ok=True)
    pdf = doc.startswith("W")   # OpenAlex id: an open-access PDF with no PMC copy (raw_pdf/<id>.pdf, PDF parser, no JATS bundle)
    with open(f"logs/ingest/{doc}.log", "a") as log:
        if pdf:
            if not os.path.exists(f"raw_pdf/{doc}.pdf") and not os.path.exists(f"parsed/{doc}.json"): return doc, "no_pdf"
            if not os.path.exists(f"parsed/{doc}.json"):
                if not sh([PY, "-m", "epistemic.parse_pdf", f"raw_pdf/{doc}.pdf", f"parsed/{doc}.json"], log): return doc, "parse_pdf_failed"
                sh([PY, "-c", f"from epistemic import store; store.append('parse_event', {{'doc': '{doc}', 'parser': 'pdf-parse', 'raw_sha256': store.file_hash('raw_pdf/{doc}.pdf'), 'parsed_sha256': store.file_hash('parsed/{doc}.json')}})"], log)
            return rest(doc, log, pdf=True)
        if not os.path.exists(f"raw/{doc}.xml") and not sh([PY, "-m", "epistemic.fetch", doc], log): return doc, "fetch_failed"
        if not os.path.exists(f"raw/{doc}.xml") or b"<body" not in open(f"raw/{doc}.xml", "rb").read(): return doc, "no_full_text"
        if not os.path.exists(f"parsed/{doc}.json"):
            if not sh([PY, "-m", "epistemic.parse", f"raw/{doc}.xml", f"parsed/{doc}.json"], log): return doc, "parse_failed"
            sh([PY, "-c", f"from epistemic import store; store.append('parse_event', {{'doc': '{doc}', 'parser': 'jats-parse v2.8', 'raw_sha256': store.file_hash('raw/{doc}.xml'), 'parsed_sha256': store.file_hash('parsed/{doc}.json')}})"], log)
        return rest(doc, log)

def rest(doc, log, pdf=False):
    if True:
        if pdf: pass
        elif not os.path.exists(f"work/closure/{doc}.supp_done"):
            sh([PY, "-m", "epistemic.supp", doc], log); os.makedirs("work/closure", exist_ok=True); open(f"work/closure/{doc}.supp_done", "w").close()
        if not pdf and not os.path.exists(f"parsed/{doc}_F.json"): sh([PY, "-m", "epistemic.figs", doc], log)
        if not os.path.exists(f"ext/{doc}.S4.json") and not sh([PY, "-m", "epistemic.structure", doc], log): return doc, "structure_failed"
        defer = [x for x in os.environ.get("DEFER_UNITS", "").split(",") if x]   # e.g. _S: supplements labelled later, off-peak
        units = [u for u in (doc, doc + "_S", doc + "_F") if os.path.exists(f"parsed/{u}.json") and not any(u.endswith(x) for x in defer)]
        for x in defer:
            if os.path.exists(f"parsed/{doc}{x}.json"): os.makedirs("work/deferred", exist_ok=True); open(f"work/deferred/{doc}{x}", "w").close()
        for u in units:
            if not os.path.exists(f"ext/{u}.A.json"): sh([PY, "-m", "epistemic.passr", "A", "haiku", u], log)
            if not os.path.exists(f"ext/{u}.B.json"): sh([PY, "-m", "epistemic.passr", "B", os.environ.get("PASSR_B", "or_deepseek"), u], log)
            if not (os.path.exists(f"ext/{u}.A.json") and os.path.exists(f"ext/{u}.B.json")): continue   # an answer is still in a batch
            if not os.path.exists(f"work/closure/{u}.gated"):
                sh([PY, "-c", f"from epistemic import validate; validate.run('{u}', '.', None, write_data=True)"], log)
                if sh([PY, "-m", "epistemic.laya_gate", u], log) and sh([PY, "-m", "epistemic.judge", u], log): open(f"work/closure/{u}.gated", "w").close()
        if not os.path.exists(f"concepts/{doc}.json"): sh([PY, "-m", "epistemic.concepts", doc], log)
        if not all(os.path.exists(f"work/closure/{u}.gated") for u in units): return doc, "waiting"
        if not os.path.exists(f"validation/{doc}.closure.json") and not sh([PY, "-m", "epistemic.closure", doc], log): return doc, "waiting"
    return doc, "done"
if __name__ == "__main__":
    a = [x for i, x in enumerate(sys.argv[1:]) if x != "--corpus" and (i == 0 or sys.argv[i] != "--corpus")]; W = 4
    if "--workers" in a: i = a.index("--workers"); W = int(a[i + 1]); del a[i:i + 2]
    if a and a[0] == "--from":
        C = json.load(open(a[1]))["works"]; docs = [c["pmcid"] for c in C if c.get("pmcid") and not c.get("in_store")]
        if "--pdf" in a: docs = [c["id"].rsplit("/", 1)[-1] for c in C if c.get("pdf")]
    else: docs = a
    if "--corpus" in sys.argv:
        tag = sys.argv[sys.argv.index("--corpus") + 1]; os.makedirs("work/corpus", exist_ok=True)
        with open(f"work/corpus/{tag}.txt", "a") as f: f.write("\n".join(docs) + "\n")
    docs = list(dict.fromkeys(docs)); t0 = time.time()
    print(json.dumps({"start": time.strftime("%H:%M"), "docs": len(docs), "workers": W}), flush=True)
    with cf.ThreadPoolExecutor(W) as ex:
        for doc, st in ex.map(one, docs): print(json.dumps({"doc": doc, "status": st, "min": round((time.time() - t0) / 60, 1)}), flush=True)
    print("== done", time.strftime("%H:%M"), flush=True)
