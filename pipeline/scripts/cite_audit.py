"""Citation audit: does a paper's own reference list support what the paper says it supports?
  python scripts/cite_audit.py <PMCID>
Reads raw/<PMCID>.xml (JATS). For every sentence that cites references, pairs the sentence with each cited work,
fetches that work's evidence (our graph record when the paper is in the graph, else its abstract from Europe PMC),
and asks the judge model whether the reference supports the sentence. Writes validation/<PMCID>.cite_audit.json.
Topic-free. Verdicts: supports | partially_supports | does_not_support | contradicts | not_evidence (review, guideline,
textbook, or methods citation used for a factual claim) | unverifiable (no text available)."""
import os, sys, re, json, requests, concurrent.futures as cf
from lxml import etree
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm
MODEL = os.environ.get("AUDIT_MODEL", "haiku")
EP = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

def refs_of(root):
    R = {}
    for ref in root.iter("ref"):
        rid = ref.get("id"); t = " ".join(ref.itertext()); t = re.sub(r"\s+", " ", t).strip()
        ids = {p.get("pub-id-type"): (p.text or "").strip() for p in ref.iter("pub-id")}
        title = ref.find(".//article-title"); src = ref.find(".//source"); yr = ref.find(".//year")
        R[rid] = {"rid": rid, "text": t[:400], "doi": ids.get("doi"), "pmid": ids.get("pmid"), "pmcid": ids.get("pmcid"),
                  "title": " ".join(title.itertext()).strip() if title is not None else None,
                  "source": (src.text or "").strip() if src is not None else None, "year": (yr.text or "").strip() if yr is not None else None}
    return R

def sentences(root):
    out = []
    body = root.find(".//body")
    if body is None: return out
    for sec in body.iter("sec"):
        stitle = sec.findtext("title") or ""
        for p in sec.findall("p"):
            # rebuild text with citation markers
            parts = []
            def walk(e):
                if e.tag == "xref" and e.get("ref-type") == "bibr":
                    parts.append("".join(f"[[{r}]]" for r in (e.get("rid") or "").split())); parts.append(e.tail or ""); return
                parts.append(e.text or "")
                for c in e: walk(c)
                if e is not p: parts.append(e.tail or "")
            walk(p)
            txt = re.sub(r"\s+", " ", "".join(parts))
            # expand ranges like [[B3]]-[[B6]] / [[B3]]–[[B6]]
            def rng(m):
                a, b = m.group(1), m.group(2); pa, na = re.match(r"(\D*)(\d+)", a).groups(); pb, nb = re.match(r"(\D*)(\d+)", b).groups()
                return "".join(f"[[{pa}{i}]]" for i in range(int(na), int(nb) + 1)) if pa == pb and int(nb) - int(na) < 30 else m.group(0)
            txt = re.sub(r"\[\[([^\[\]]+)\]\]\s*[-–]\s*\[\[([^\[\]]+)\]\]", rng, txt)
            for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", txt):
                rids = re.findall(r"\[\[([^\[\]]+)\]\]", s)
                if rids: out.append({"section": stitle, "sentence": re.sub(r"\[\[[^\]]+\]\]", "", s).strip(), "rids": list(dict.fromkeys(rids))})
    return out

def evidence(ref):
    pmcid = ref.get("pmcid")
    q = f'DOI:"{ref["doi"]}"' if ref.get("doi") else f"EXT_ID:{ref['pmid']} AND SRC:MED" if ref.get("pmid") else (f'TITLE:"{ref["title"][:200]}"' if ref.get("title") else None)
    meta = {}
    if q:
        try:
            r = requests.get(EP, params={"query": q, "format": "json", "resultType": "core", "pageSize": 1}, timeout=40).json()
            x = (r.get("resultList") or {}).get("result") or []
            if x: meta = x[0]; pmcid = pmcid or meta.get("pmcid")
        except Exception: pass
    if pmcid and os.path.exists(f"parsed/{pmcid}.json"):
        try:
            from epistemic import records
            return {"basis": "graph record", "pmcid": pmcid, "title": meta.get("title") or ref.get("title"), "text": records.render(pmcid)[:20000],
                    "pubtype": (meta.get("pubTypeList") or {}).get("pubType")}
        except Exception: pass
    if meta.get("abstractText"):
        return {"basis": "abstract", "pmcid": pmcid, "title": meta.get("title"), "text": re.sub("<[^>]+>", " ", meta["abstractText"])[:6000],
                "pubtype": (meta.get("pubTypeList") or {}).get("pubType")}
    return {"basis": None, "pmcid": pmcid, "title": meta.get("title") or ref.get("title"), "text": None}

SYS = """You audit a citation. A paper makes a statement and cites a reference for it. You get the statement and the reference's own evidence (its extracted record or its abstract).
Return JSON only: {"verdict": "supports|partially_supports|does_not_support|contradicts|not_evidence|unverifiable",
 "reference_found": "one sentence: what the reference actually reports, with design and key number if any",
 "gap": "what the statement claims that the reference does not show, or null",
 "reference_design": "rct|cohort|cross_sectional|case_control|meta_analysis|systematic_review|narrative_review|animal|cell|guideline|methods|other"}
Use not_evidence when the reference is a review, guideline, textbook or methods paper cited for an empirical claim it did not itself test.
Judge only from what you are given; never use your own memory of the reference. If the statement gives a number the record does not contain, the verdict is unverifiable, not does_not_support."""

def judge(item):
    s, ref, ev = item
    if not ev.get("text"): return {**s, "rid": ref["rid"], "ref": ref.get("title") or ref["text"][:120], "verdict": "unverifiable", "basis": None}
    try:
        out, _ = llm.chat(MODEL, SYS, f"STATEMENT ({s['section']}): {s['sentence']}\n\nREFERENCE ({ev['basis']}; {ev.get('pubtype')}): {ev.get('title')}\n{ev['text']}", 1500)
        return {**s, "rid": ref["rid"], "ref": ev.get("title") or ref.get("title"), "ref_pmcid": ev.get("pmcid"), "basis": ev["basis"], **out}
    except Exception as e:
        return {**s, "rid": ref["rid"], "ref": ev.get("title"), "verdict": "unverifiable", "basis": f"error {e!r}"[:80]}

def run(pmcid):
    root = etree.parse(f"raw/{pmcid}.xml").getroot()
    R = refs_of(root); S = sentences(root)
    used = {r for s in S for r in s["rids"] if r in R}
    with cf.ThreadPoolExecutor(6) as ex: E = dict(zip(used, ex.map(lambda r: evidence(R[r]), used)))
    items = [(s, R[r], E[r]) for s in S for r in s["rids"] if r in R]
    with cf.ThreadPoolExecutor(8) as ex: res = list(ex.map(judge, items))
    from collections import Counter
    summ = {"doc": pmcid, "references": len(R), "cited_in_text": len(used), "citing_sentences": len(S), "pairs": len(res),
            "verdicts": dict(Counter(r["verdict"] for r in res)), "basis": dict(Counter(str(E[r]["basis"]) for r in used)),
            "by_section": {sec: dict(Counter(r["verdict"] for r in res if r["section"] == sec)) for sec in dict.fromkeys(r["section"] for r in res)}}
    json.dump({"summary": summ, "pairs": res, "references": R}, open(f"validation/{pmcid}.cite_audit.json", "w"), indent=1, ensure_ascii=False)
    print(json.dumps(summ, indent=1))

if __name__ == "__main__":
    for d in sys.argv[1:]: run(d)
