"""Claim model v1 (briefs/CLAIM_MODEL.md): turn extracted claims into assertions + propositions.
  python scripts/claims.py run [--media DIR ...] [--limit N]     one pass (sync, or queued when LLM_BATCH=collect)
  python scripts/claims.py loop [--media DIR ...]                collect -> Message Batches -> repeat until nothing is deferred
  python scripts/claims.py stats
Paper claims come from ext/<doc>.S4.json (claims with supported_by anchors) for finished papers; media claims from <DIR>/claims/*.json.
Writes work/claims/<source_id>.json: {"source":..., "assertions":[...], "propositions":[...]}; proposition ids are content hashes of
their normalized fields, so the same proposition asserted by a paper and a tweet gets the same id once concepts are resolved."""
import os, sys, json, glob, hashlib, subprocess, concurrent.futures as cf
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import llm
OUT = "work/claims"; os.makedirs(OUT, exist_ok=True)
MODEL = os.environ.get("CLAIMS_MODEL", "haiku")
FIELDS = ["subject", "object", "object_measure", "relation", "direction", "magnitude", "population", "conditions", "modality"]
SYS = """You convert claims into the claim model. Each input claim is an ASSERTION (someone said it). Split it into atomic PROPOSITIONS:
one subject, one object, one relation, one population each ("X lowers A, B and C" -> three propositions). Normative claims ("people should...")
become an empirical premise proposition plus "normative": "<the value judgment>" on the assertion.
Return JSON only:
{"assertions": [{"i": <input index>, "kind": "paper_abstract|paper_results|paper_discussion|paper_introduction|paper_methods|news|blog|press_release|social|report|other",
   "normative": null or "<value judgment>",
   "propositions": [{
     "subject": "exposure or intervention, plain canonical noun phrase (e.g. 'coffee consumption')",
     "object": "outcome as a plain canonical noun phrase (e.g. 'cognitive function')",
     "object_measure": "the instrument or metric actually used, or null (e.g. 'MoCA score', 'hazard of all-cause death')",
     "relation": "causal|associational|mechanistic|descriptive_quantity|predictive",
     "direction": "increase|decrease|no_effect|mixed|not_applicable",
     "magnitude": {"measure": "HR|OR|RR|beta|mean_difference|percent|count|...|null", "value": number or null, "lo": number or null, "hi": number or null, "unit": "...or null", "contrast": "e.g. Q4 vs Q1, per cup/day, or null", "qualitative": "words used when no number, or null"},
     "population": {"who": "...", "where": "... or null", "when": "... or null", "species": "human|mouse|rat|cell|...", "generality": "study_sample|subgroup|national|general_population|everyone"},
     "conditions": "dose, duration, subgroup, setting, or null",
     "modality": "hedged|plain|certain",
     "evidence_ids": ["ids from the claim's supported_by list that carry this proposition's number, or []"]}]}]}
Rules: use only what the claim and the record say; do not import outside knowledge; keep the author's population, do not widen it."""

def pid(p):
    key = json.dumps([str(p.get(k) or "").lower().strip() for k in ("subject", "object", "relation", "direction")] +
                     [str((p.get("population") or {}).get("who") or "").lower().strip()], ensure_ascii=False)
    return "P" + hashlib.sha256(key.encode()).hexdigest()[:16]
def aid(src, i, text): return "A" + hashlib.sha256(f"{src}|{i}|{text}".encode()).hexdigest()[:16]

def finished_papers():
    return sorted(os.path.basename(p)[:-len(".closure.json")] for p in glob.glob("validation/*.closure.json"))

def paper_one(doc):
    out = f"{OUT}/{doc}.json"
    if os.path.exists(out): return doc, "cached"
    s4 = f"ext/{doc}.S4.json"
    if not os.path.exists(s4): return doc, "no_S4"
    S = json.load(open(s4)); C = S.get("claims") or []
    if not C: json.dump({"source": doc, "kind": "paper", "assertions": [], "propositions": []}, open(out, "w")); return doc, "no_claims"
    from epistemic import records
    try: rec = records.render(doc)[:16000]
    except Exception: rec = json.dumps(S.get("study_card") or {})[:4000]
    claims = [{"i": i, "text": c.get("text_paraphrase") or c.get("text"), "relation": c.get("relation"), "hedging": c.get("hedging"), "scope": c.get("scope"),
               "location": c.get("location"), "numbers": c.get("numbers"), "supported_by": c.get("supported_by", [])[:30]} for i, c in enumerate(C)]
    try:
        r, _ = llm.chat(MODEL, SYS, f"SOURCE: research paper {doc}\n\nRECORD (study card, groups, models, variables, analyses):\n{rec}\n\nCLAIMS:\n{json.dumps(claims, ensure_ascii=False)}", 16000)
    except llm.Deferred: return doc, "deferred"
    except Exception as e: return doc, f"error {e!r}"[:100]
    return doc, write(doc, "paper", claims, r, speaker=f"authors of {doc}")

def media_one(path):
    c = json.load(open(path)); src = c["id"]; out = f"{OUT}/media_{src}.json"
    if os.path.exists(out): return src, "cached"
    t = json.load(open(os.path.join(os.path.dirname(os.path.dirname(path)), "text", f"{src}.json")))
    claims = [{"i": i, "text": x.get("text"), "quote": x.get("quote"), "language": x.get("language"), "magnitude": x.get("magnitude"), "population": x.get("population"),
               "design_stated": x.get("study_design_stated"), "cites": [{"description": y.get("description"), "resolved": (y.get("resolved") or {}).get("pmcid") or (y.get("resolved") or {}).get("doi")} for y in x.get("cites", [])]}
              for i, x in enumerate(c.get("claims", []))]
    if not claims: return src, "no_claims"
    try:
        r, _ = llm.chat(MODEL, SYS, f"SOURCE: {c.get('item_type') or 'media'} item from {t.get('domain')} ({t.get('published')}): {t.get('title')}\n\nCLAIMS:\n{json.dumps(claims, ensure_ascii=False)}", 12000)
    except llm.Deferred: return src, "deferred"
    except Exception as e: return src, f"error {e!r}"[:100]
    return src, write(f"media_{src}", c.get("item_type") or "media", claims, r, speaker=t.get("domain"), url=t.get("url"), date=t.get("published"))

def write(src, kind, claims, r, speaker=None, url=None, date=None):
    A, P = [], {}
    for a in r.get("assertions", []):
        i = a.get("i")
        if not isinstance(i, int) or i >= len(claims): continue
        cl = claims[i]; ps = []
        for p in a.get("propositions") or []:
            p = {k: p.get(k) for k in FIELDS + ["evidence_ids"]}; p["id"] = pid(p); P.setdefault(p["id"], {**p, "evidence_ids": []})
            P[p["id"]]["evidence_ids"] = sorted(set(P[p["id"]]["evidence_ids"]) | set(p.get("evidence_ids") or []))
            ps.append(p["id"])
        A.append({"id": aid(src, i, cl.get("text")), "source": src, "source_kind": kind, "speaker": speaker, "url": url, "date": date,
                  "kind": a.get("kind"), "text": cl.get("text"), "quote": cl.get("quote"), "location": cl.get("location"),
                  "cites": cl.get("cites") or cl.get("supported_by"), "normative": a.get("normative"), "propositions": ps})
    json.dump({"source": src, "kind": kind, "assertions": A, "propositions": list(P.values())}, open(f"{OUT}/{src}.json", "w"), indent=1, ensure_ascii=False)
    return f"{len(A)} assertions {len(P)} propositions"

def run(args):
    media = [args[i + 1] for i, a in enumerate(args) if a == "--media"]
    lim = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    docs = finished_papers()[:lim]; mp = [p for d in media for p in sorted(glob.glob(f"{d}/claims/*.json"))][:lim]
    st = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for _, s in list(ex.map(paper_one, docs)) + list(ex.map(media_one, mp)):
            k = s.split()[0] if s and s[0].isalpha() else "done"; st[k] = st.get(k, 0) + 1
    print(json.dumps(st), flush=True); return st.get("deferred", 0)

def loop(args):
    q = "work/batchq/queue_claims.jsonl"; env = {**os.environ, "LLM_BATCH_QUEUE": q}
    for rnd in range(6):
        if os.path.exists(q): os.remove(q)
        r = subprocess.run([sys.executable, __file__, "run", *args], env={**env, "LLM_BATCH": "collect"})
        if not os.path.exists(q) or os.path.getsize(q) == 0: break
        subprocess.run([sys.executable, "-m", "epistemic.batch", "submit"], env=env)
        subprocess.run([sys.executable, "-m", "epistemic.batch", "wait"], env=env)
    subprocess.run([sys.executable, __file__, "stats"])

def stats():
    from collections import Counter
    A = P = 0; rel = Counter(); kind = Counter(); n = 0; multi = 0; gen = Counter()
    for f in glob.glob(f"{OUT}/*.json"):
        d = json.load(open(f)); n += 1; A += len(d["assertions"]); P += len(d["propositions"])
        for a in d["assertions"]: kind[a.get("kind")] += 1; multi += len(a["propositions"]) > 1
        for p in d["propositions"]: rel[p.get("relation")] += 1; gen[(p.get("population") or {}).get("generality")] += 1
    print(json.dumps({"sources": n, "assertions": A, "propositions": P, "assertions_split": multi, "relation": rel, "assertion_kind": kind, "population_generality": gen}, default=dict))

if __name__ == "__main__":
    cmd, rest = sys.argv[1], sys.argv[2:]
    {"run": lambda: run(rest), "loop": lambda: loop(rest), "stats": stats}[cmd]()
