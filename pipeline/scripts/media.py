"""Media layer pilot: news articles -> claims -> cited evidence -> scores against the graph.

  python scripts/media.py fetch  [N]     GDELT article list for the topic queries (work/media/articles.json)
  python scripts/media.py scrape         article text + outbound links (work/media/text/<id>.json)
  python scripts/media.py claims         Haiku: claims, cited sources, spin flags (work/media/claims/<id>.json)
  python scripts/media.py resolve        links/descriptions -> DOI/PMCID/OpenAlex; marks papers already in the graph
  python scripts/media.py score          traceability, fidelity, underlying strength, spin (work/media/scored.json)
  python scripts/media.py report         work/media/report.md + work/media/media.json

Topic-free: queries come from MEDIA_QUERIES (one per line) or the defaults below.
Scores are four separate axes, never one blended number:
  traceability  0 none | 1 vague ("a new study") | 2 identifiable description | 3 direct link to the paper
  fidelity      faithful | overstated | understated | misrepresented | unrelated | unverifiable (vs the paper's own records)
  strength      what the whole graph says about the exposure/outcome pair (studies, independent sources, direction split)
  spin          flags: causal_language_for_association, relative_without_absolute, animal_or_cell_as_human, single_study_as_consensus, ...
"""
import os, sys, re, json, time, hashlib, glob, concurrent.futures as cf
import requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from epistemic import llm

W = os.environ.get("MEDIA_DIR", "work/media"); os.makedirs(f"{W}/text", exist_ok=True); os.makedirs(f"{W}/claims", exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}
MODEL = os.environ.get("MEDIA_MODEL", "haiku")
DEFAULT_Q = ['coffee "heart disease"', 'coffee cardiovascular study', 'coffee stroke risk study', 'coffee "blood pressure" study',
             'coffee arrhythmia "atrial fibrillation"', 'coffee mortality study', 'caffeine heart study', 'coffee "heart failure"',
             'coffee diabetes study', 'coffee aging longevity study']
QUERIES = [q.strip() for q in os.environ.get("MEDIA_QUERIES", "").splitlines() if q.strip()] or DEFAULT_Q

def jload(p, d=None):
    try: return json.load(open(p))
    except Exception: return d
def jdump(o, p): json.dump(o, open(p + ".tmp", "w"), indent=1, ensure_ascii=False); os.replace(p + ".tmp", p)
def aid(url): return hashlib.sha1(url.encode()).hexdigest()[:12]
def ask(system, user, max_tokens=6000):
    out, _ = llm.chat(MODEL, system, user, max_tokens)
    return out if isinstance(out, dict) else llm._parse(out)

# ---------- fetch ----------
def fetch(n=100):
    arts = {a["url"]: a for a in jload(f"{W}/articles.json", [])}
    per = max(10, int(n * 1.6) // len(QUERIES))
    import html as _h, urllib.parse as _u
    for q in QUERIES:
        for first in range(1, 61, 10):
            try: t = requests.get("https://www.bing.com/news/search", params={"q": q.replace(chr(34), ""), "format": "rss", "count": 50, "first": first}, headers=UA, timeout=30).text
            except Exception: continue
            for blk in re.findall(r"<item>(.*?)</item>", t, re.S):
                lk = re.search(r"<link>(.*?)</link>", blk); ti = re.search(r"<title>(.*?)</title>", blk); dt = re.search(r"<pubDate>(.*?)</pubDate>", blk)
                if not lk: continue
                u = _u.parse_qs(_u.urlparse(_h.unescape(lk.group(1))).query).get("url", [_h.unescape(lk.group(1))])[0]
                if u not in arts: arts[u] = {"id": aid(u), "url": u, "title": _h.unescape(ti.group(1)) if ti else None, "domain": _u.urlparse(u).netloc.replace("www.", ""),
                                             "seendate": dt.group(1) if dt else None, "query": q, "kind": "news", "via": "bing"}
            time.sleep(1.5)
        print("bing", q, "total", len(arts), flush=True)
    for q in (QUERIES if os.environ.get("MEDIA_GDELT") == "1" else []):
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        prm = {"query": f"{q} sourcelang:english", "mode": "artlist", "maxrecords": min(250, per), "format": "json",
               "startdatetime": "20170101000000", "sort": "hybridrel"}
        js = {}
        for attempt in range(5):
            try:
                r = requests.get(url, params=prm, timeout=60); time.sleep(8)
                if r.text.strip().startswith("{"): js = r.json(); break
                print("  gdelt says:", r.text.strip()[:60], flush=True); time.sleep(25 * (attempt + 1))
            except Exception: time.sleep(20)
        for a in js.get("articles", []):
            if a.get("url") and a["url"] not in arts:
                arts[a["url"]] = {"id": aid(a["url"]), "url": a["url"], "title": a.get("title"), "domain": a.get("domain"),
                                  "seendate": a.get("seendate"), "query": q, "kind": "news"}
        print(q, len(js.get("articles", [])), "total", len(arts), flush=True)
    jdump(list(arts.values()), f"{W}/articles.json")
    return len(arts)

# ---------- scrape ----------
DROP = ["script", "style", "nav", "footer", "aside", "header", "form", "noscript", "figure", "iframe"]
def scrape_one(a):
    p = f"{W}/text/{a['id']}.json"
    if os.path.exists(p): return a["id"], "cached"
    from bs4 import BeautifulSoup
    try:
        r = requests.get(a["url"], headers=UA, timeout=30)
        if r.status_code != 200: jdump({"id": a["id"], "error": r.status_code}, p); return a["id"], f"http {r.status_code}"
        s = BeautifulSoup(r.text, "lxml")
        for t in s(DROP): t.decompose()
        root = s.find("article") or s.find("main") or s.body or s
        paras = [x.get_text(" ", strip=True) for x in root.find_all(["p", "li", "h2", "h3", "blockquote"])]
        paras = [x for x in paras if len(x) > 40]
        links = []
        for x in root.find_all("a", href=True):
            h = x["href"]
            if h.startswith("http") and a["domain"] not in h: links.append({"i": len(links), "href": h, "text": x.get_text(" ", strip=True)[:120]})
        meta = {m.get("property") or m.get("name"): m.get("content") for m in s.find_all("meta") if m.get("content")}
        jdump({"id": a["id"], "url": a["url"], "title": a.get("title"), "domain": a.get("domain"),
               "published": meta.get("article:published_time") or a.get("seendate"), "author": meta.get("author"),
               "text": "\n\n".join(paras)[:40000], "links": links[:150]}, p)
        return a["id"], f"{len(paras)} paras {len(links)} links"
    except Exception as e:
        jdump({"id": a["id"], "error": repr(e)[:200]}, p); return a["id"], "error"
def scrape():
    arts = jload(f"{W}/articles.json", [])
    with cf.ThreadPoolExecutor(12) as ex:
        for i, (k, st) in enumerate(ex.map(scrape_one, arts)): print(i, k, st, flush=True)

# ---------- claims ----------
CLAIM_SYS = """You read a media item (news, blog, post) about health or science and list every factual claim it makes about evidence: what affects what, by how much, in whom, and on whose authority.
Return JSON only:
{"item_type": "news|blog|press_release|opinion|social|other",
 "about_research": true|false,
 "claims": [{
   "text": "the claim restated in one plain sentence",
   "quote": "the shortest verbatim span from the item that makes the claim",
   "exposure": "what is said to act (e.g. coffee, 3-4 cups/day)", "outcome": "what is affected (e.g. heart failure)",
   "direction": "lower|higher|no_effect|mixed|unclear",
   "language": "causal|associational|hedged|mechanistic|advice",
   "magnitude": "number exactly as stated, or null", "absolute_risk_given": true|false,
   "population": "who, as stated, or null", "study_design_stated": "cohort|rct|meta-analysis|mendelian_randomization|animal|cell|review|unstated|...",
   "cites": [{"link": <index from LINKS or null>, "description": "how the item describes the source (journal, authors, institution, year, n)"}],
   "spin": ["causal_language_for_association", "relative_without_absolute", "animal_or_cell_as_human", "single_study_as_consensus",
            "extrapolated_dose", "headline_overstates_body", "claim_beyond_cited_source", "conflict_of_interest_unmentioned", "expert_quote_only"]  (only those present)
 }]}
Rules: when the item cites or shows a source, flag claim_beyond_cited_source on any claim that leans on that source but asserts something it does not study (other exposure, outcome or population). Never invent a citation; if the item gives none, cites is []. Use only flags you can point to in the text."""
def claims_one(t):
    p = f"{W}/claims/{t['id']}.json"
    if os.path.exists(p) or t.get("error") or len(t.get("text", "")) < 600: return t["id"], "skip"
    links = "\n".join(f"[{l['i']}] {l['text']} -> {l['href']}" for l in t["links"])
    user = f"TITLE: {t.get('title')}\nOUTLET: {t.get('domain')}\nPUBLISHED: {t.get('published')}\n\nTEXT:\n{t['text'][:24000]}\n\nLINKS:\n{links or '(none)'}"
    try:
        out = ask(CLAIM_SYS, user); out["id"] = t["id"]; jdump(out, p); return t["id"], len(out.get("claims", []))
    except llm.Deferred: return t["id"], "deferred"
    except Exception as e: return t["id"], f"error {e!r}"[:120]
def claims():
    ts = [jload(p) for p in glob.glob(f"{W}/text/*.json")]
    with cf.ThreadPoolExecutor(8) as ex:
        for i, (k, st) in enumerate(ex.map(claims_one, [t for t in ts if t])): print(i, k, st, flush=True)

# ---------- resolve ----------
DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>?#]+", re.I)
def in_graph(pmcid): return bool(pmcid) and os.path.exists(f"parsed/{pmcid}.json")
def epmc(q):
    try:
        r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": q, "format": "json", "resultType": "lite", "pageSize": 3}, timeout=30)
        return r.json().get("resultList", {}).get("result", [])
    except Exception: return []
def oa_search(desc):
    try:
        r = requests.get("https://api.openalex.org/works", params={"search": desc[:300], "per-page": 3, "mailto": "epistemic@example.org"}, timeout=30)
        return r.json().get("results", [])
    except Exception: return []
def norm_hit(src, doi=None, pmid=None, pmcid=None, title=None, year=None, oa=None, conf="link"):
    return {"via": src, "doi": doi, "pmid": pmid, "pmcid": pmcid, "title": title, "year": year, "openalex": oa, "confidence": conf, "in_graph": in_graph(pmcid)}
def resolve_link(href):
    m = DOI_RE.search(href.replace("%2F", "/"))
    q = None
    if m: q = f'DOI:"{m.group(0).rstrip(".)")}"'
    elif (mm := re.search(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)|ncbi\.nlm\.nih\.gov/pubmed/(\d+)", href)): q = f"EXT_ID:{mm.group(1) or mm.group(2)} AND SRC:MED"
    elif (mm := re.search(r"(PMC\d+)", href)): q = f"PMCID:{mm.group(1)}"
    if not q: return None
    h = epmc(q)
    if not h: return norm_hit("link", doi=m.group(0) if m else None, conf="link_unresolved")
    x = h[0]; return norm_hit("link", x.get("doi"), x.get("pmid"), x.get("pmcid"), x.get("title"), x.get("pubYear"))
VSYS = """A media item describes a research source. Decide whether the candidate paper is that source.
Return JSON {"same": true|false, "why": "<short>"}. Say true only when topic, finding and any stated details (journal, year, authors, institution, numbers) are consistent; a paper on a different topic is false."""
def verified(desc, w):
    try:
        out = ask(VSYS, f"DESCRIPTION IN THE MEDIA ITEM: {desc}\n\nCANDIDATE: {w.get('title')} ({w.get('publication_year')}; {((w.get('primary_location') or {}).get('source') or {}).get('display_name')})\n{abstract_of(w)[:1500]}", 300)
        return bool(out.get("same"))
    except Exception: return False
def abstract_of(w):
    inv = w.get("abstract_inverted_index") or {}
    return " ".join(t for _, t in sorted((i, t) for t, ii in inv.items() for i in ii))
def resolve_desc(desc):
    if not desc or len(desc) < 25: return None
    for w in [w for w in oa_search(desc) if verified(desc, w)][:1]:
        ids = w.get("ids", {}); pmcid = (ids.get("pmcid") or "").rsplit("/", 1)[-1] or None
        doi = (w.get("doi") or "").replace("https://doi.org/", "") or None
        if not pmcid and doi:
            h = epmc(f'DOI:"{doi}"'); pmcid = h[0].get("pmcid") if h else None
        return norm_hit("description", doi, (ids.get("pmid") or "").rsplit("/", 1)[-1] or None, pmcid, w.get("title"), w.get("publication_year"), w.get("id"), conf="search_top_hit")
    return None
def resolve():
    for p in sorted(glob.glob(f"{W}/claims/*.json")):
        c = jload(p); t = jload(f"{W}/text/{c['id']}.json", {})
        if c.get("resolved"): continue
        links = {l["i"]: l["href"] for l in t.get("links", [])}
        for cl in c.get("claims", []):
            for ct in cl.get("cites", []):
                hit = None
                if isinstance(ct.get("link"), int) and ct["link"] in links: hit = resolve_link(links[ct["link"]]); ct["href"] = links[ct["link"]]
                if not hit: hit = resolve_desc(ct.get("description"))
                ct["resolved"] = hit
        c["resolved"] = True; jdump(c, p); print("resolved", c["id"], flush=True)

# ---------- score ----------
def graph_index():
    d = jload("work/graph/explorer.json")
    K = [{"i": i, "label": (c[1] or c[0].replace("term:", "")), "terms": [x.lower() for x in (c[5] or [])]} for i, c in enumerate(d["concepts"])]
    P = [{"x": p[0], "y": p[1], "studies": p[3], "sources": p[4], "lower": p[5], "null": p[6], "higher": p[7], "noci": p[8]} for p in d["pairs"]]
    return K, P
def match(K, phrase):
    s = (phrase or "").lower()
    if not s: return []
    hits = [k for k in K if k["label"].lower() in s or any(t and (t == s or (len(t) > 4 and t in s)) for t in k["terms"])]
    return sorted(hits, key=lambda k: -len(k["label"]))[:4]
def strength(K, P, cl):
    xs, ys = match(K, cl.get("exposure")), match(K, cl.get("outcome"))
    best = None
    for x in xs:
        for y in ys:
            for p in P:
                if p["x"] == x["i"] and p["y"] == y["i"] and (not best or p["studies"] > best["studies"]):
                    best = dict(p, exposure=x["label"], outcome=y["label"])
    if not best: return {"graph": "pair not in graph", "exposure_matches": [k["label"] for k in xs], "outcome_matches": [k["label"] for k in ys]}
    n = best["lower"] + best["null"] + best["higher"] or 1
    agree = {"lower": best["lower"], "no_effect": best["null"], "higher": best["higher"]}.get(cl.get("direction"))
    return {"graph": "pair found", "exposure": best["exposure"], "outcome": best["outcome"], "studies": best["studies"], "independent_sources": best["sources"],
            "split": {"lower": best["lower"], "null": best["null"], "higher": best["higher"], "no_ci": best["noci"]},
            "share_agreeing_with_claim": None if agree is None else round(agree / n, 2)}
FID_SYS = """You check whether a media claim faithfully represents the research paper it cites. You get the claim (with its verbatim quote) and the paper's own extracted record (design, population, estimates, the authors' claims, limitations).
Return JSON only: {"fidelity": "faithful|overstated|understated|misrepresented|unrelated",
 "what_the_paper_found": "one sentence, with the key number",
 "gaps": ["specific mismatches, e.g. 'paper is observational; article says coffee protects'"],
 "causal_language_unsupported": true|false}
Judge only against the record; do not use outside knowledge."""
def paper_record(pmcid):
    try:
        from epistemic import records
        return records.render(pmcid)[:30000]
    except Exception: return None
def abstract(oa_id):
    try:
        w = requests.get(f"https://api.openalex.org/works/{oa_id.rsplit('/', 1)[-1]}", timeout=30).json(); inv = w.get("abstract_inverted_index") or {}
        pos = sorted((i, t) for t, ii in inv.items() for i in ii); return " ".join(t for _, t in pos)
    except Exception: return None
def fidelity(cl, hit):
    if not hit: return {"fidelity": "unverifiable", "basis": "no source cited or found"}
    rec, basis = (paper_record(hit["pmcid"]), "graph record") if hit.get("in_graph") else (None, None)
    if not rec and hit.get("openalex"): rec, basis = abstract(hit["openalex"]), "abstract only"
    if not rec and hit.get("doi"):
        h = epmc(f'DOI:"{hit["doi"]}"')
        if h and h[0].get("id"):
            try:
                r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={"query": f'DOI:"{hit["doi"]}"', "resultType": "core", "format": "json"}, timeout=30).json()
                rec, basis = r["resultList"]["result"][0].get("abstractText"), "abstract only"
            except Exception: pass
    if not rec: return {"fidelity": "unverifiable", "basis": "source found but no text"}
    try:
        out = ask(FID_SYS, f"CLAIM: {cl['text']}\nQUOTE: {cl.get('quote')}\nLANGUAGE: {cl.get('language')}\nMAGNITUDE AS STATED: {cl.get('magnitude')}\n\nPAPER ({basis}): {hit.get('title')}\n{rec}", 3000)
        out["basis"] = basis; return out
    except Exception as e: return {"fidelity": "unverifiable", "basis": f"error {e!r}"[:100]}
def trace(cl):
    cs = cl.get("cites") or []
    if not cs: return 0
    if any(c.get("href") and (c.get("resolved") or {}).get("confidence") == "link" for c in cs): return 3
    if any(c.get("resolved") for c in cs): return 2
    return 1
def score():
    K, P = graph_index(); out = []
    items = [jload(p) for p in sorted(glob.glob(f"{W}/claims/*.json"))]
    def one(c):
        t = jload(f"{W}/text/{c['id']}.json", {}); rows = []
        for cl in c.get("claims", []):
            hit = next((x["resolved"] for x in cl.get("cites", []) if x.get("resolved")), None)
            rows.append({"claim": cl["text"], "quote": cl.get("quote"), "exposure": cl.get("exposure"), "outcome": cl.get("outcome"),
                         "direction": cl.get("direction"), "language": cl.get("language"), "magnitude": cl.get("magnitude"),
                         "design_stated": cl.get("study_design_stated"), "source": hit, "cites": cl.get("cites"),
                         "traceability": trace(cl), "fidelity": fidelity(cl, hit), "strength": strength(K, P, cl), "spin": cl.get("spin") or []})
        return {"id": c["id"], "url": t.get("url"), "title": t.get("title"), "outlet": t.get("domain"), "published": t.get("published"),
                "item_type": c.get("item_type"), "claims": rows}
    with cf.ThreadPoolExecutor(6) as ex: out = list(ex.map(one, [c for c in items if c and c.get("about_research")]))
    jdump(out, f"{W}/scored.json"); print("scored", len(out), "items", sum(len(x["claims"]) for x in out), "claims")

# ---------- report ----------
def report():
    S = jload(f"{W}/scored.json", []); C = [dict(cl, outlet=it["outlet"], title=it["title"], url=it["url"]) for it in S for cl in it["claims"]]
    from collections import Counter
    n = len(C) or 1
    tr = Counter(c["traceability"] for c in C); fi = Counter(c["fidelity"].get("fidelity") for c in C); sp = Counter(f for c in C for f in c["spin"])
    lang = Counter(c["language"] for c in C); ing = sum(1 for c in C if (c["source"] or {}).get("in_graph"))
    pair = sum(1 for c in C if c["strength"].get("graph") == "pair found")
    L = [f"# Media evidence pilot", "", f"{len(S)} media items, {len(C)} claims about research.", "",
         "| Traceability | Claims |", "|---|---|"] + [f"| {k} {['none','vague','identifiable','direct link'][k]} | {tr[k]} ({tr[k]*100//n}%) |" for k in range(4)] + \
        ["", "| Fidelity to cited paper | Claims |", "|---|---|"] + [f"| {k} | {v} |" for k, v in fi.most_common()] + \
        ["", "| Spin flag | Claims |", "|---|---|"] + [f"| {k} | {v} |" for k, v in sp.most_common()] + \
        ["", "| Language | Claims |", "|---|---|"] + [f"| {k} | {v} |" for k, v in lang.most_common()] + \
        ["", f"Cited paper already in the graph: {ing}. Exposure/outcome pair found in the graph: {pair}.", "", "## Worst offenders (overstated or misrepresented, most spin)", ""]
    bad = sorted([c for c in C if c["fidelity"].get("fidelity") in ("overstated", "misrepresented")], key=lambda c: -len(c["spin"]))[:15]
    for c in bad:
        st = c["strength"]; g = f"graph: {st.get('studies')} studies, {st.get('independent_sources')} sources, split {st.get('split')}" if st.get("graph") == "pair found" else "graph: pair not covered"
        L += [f"**{c['outlet']}**: \"{(c['quote'] or c['claim'])[:220]}\"  ", f"Paper found: {c['fidelity'].get('what_the_paper_found')}  ", f"Gaps: {'; '.join(c['fidelity'].get('gaps') or [])}  ", f"Spin: {', '.join(c['spin']) or 'none'}. {g}", ""]
    open(f"{W}/report.md", "w").write("\n".join(L)); jdump(C, f"{W}/media.json"); print("\n".join(L[:40]))

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "fetch": print(fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 100))
    elif cmd == "scrape": scrape()
    elif cmd == "claims": claims()
    elif cmd == "resolve": resolve()
    elif cmd == "score": score()
    elif cmd == "report": report()
    elif cmd == "all":
        fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 100); scrape(); claims(); resolve(); score(); report()
