"""Closure test v1: can an agent answer the standard questions about a study from our records alone?
For each paper: (1) answers from the paper text (reference), (2) answers from records only (records.render),
(3) a grader compares them per question. completeness = matched / answerable-from-paper (partial counts half).
Every miss names a gap (missing value, missing wiring, missing card field) for the extraction framework to close.
Usage: python -m epistemic.closure PMC... [--model M] ; writes validation/<doc>.closure.json + ledger."""
import sys, os, json, time, requests
from . import records, store
QUESTIONS = [
 ("design", "What is the study design (e.g. prospective cohort, case-control, RCT, Mendelian randomization)?"),
 ("setting", "Where and in which data source or cohort was it done?"),
 ("years", "In which years were participants recruited, and when did follow-up end?"),
 ("population", "Who was studied (sex, age range, key eligibility criteria)?"),
 ("n_analysed", "How many participants were in the main analysis?"),
 ("exclusions", "What exclusions were applied, with how many people excluded for each?"),
 ("exposure", "How was the main exposure or intervention measured or assigned (instrument, timing, repeated or not)?"),
 ("categories", "What exposure levels or arms were compared, and which was the reference?"),
 ("outcome", "What was the primary outcome and how was it ascertained?"),
 ("followup", "How long was follow-up (mean or median, and person-years if reported)?"),
 ("events", "How many outcome events/cases were there in total?"),
 ("main_estimate", "What is the main fully adjusted effect estimate (measure, value and 95% CI) for the primary contrast (highest vs reference level, or intervention vs control) on the primary outcome?"),
 ("adjustment", "Which covariates were adjusted for in the main (fully adjusted) model?"),
 ("trend", "Was a dose-response or trend test reported, and what was its result (P for trend or per-cup estimate)?"),
 ("subgroups", "Which subgroup or effect-modification analyses were reported, and was any interaction significant?"),
 ("sensitivity", "Which sensitivity analyses were reported, and did they change the main result?"),
 ("missing", "How were missing data and losses to follow-up handled, and how many were lost?"),
 ("model_type", "What statistical model produced the main estimate (e.g. Cox, logistic, IVW)?"),
 ("secondary", "What secondary outcomes were analysed, with their main estimates?"),
 ("funding", "Who funded the study and were conflicts of interest declared?")]
from . import llm
MODEL = os.environ.get("CLOSURE_MODEL", "haiku")
spent = 0.0

def call(system, user, max_tokens=6000):
    global spent
    out, usd = llm.chat(MODEL, system, user, max_tokens); spent += usd; return out

ASK = ("Answer each question about the study using ONLY the material given. Be specific and include numbers exactly as given. "
       "If the material does not contain the answer, reply exactly \"NOT IN MATERIAL\". Do not use outside knowledge. "
       'Return JSON: {"answers": {"<qid>": "<answer>", ...}}')
GRADE = ("You compare two answers to the same question about a study. REFERENCE comes from the full paper; RECORDS comes from a "
         "structured database built from it. For each qid return one verdict: match (same facts and numbers), partial (some facts or "
         "numbers missing or less specific), mismatch (contradicts the reference), records_missing (reference has an answer, records say "
         "NOT IN MATERIAL), not_in_paper (reference says NOT IN MATERIAL). Also name the gap in a few words when not a match "
         '(e.g. "per-cup estimate not extracted", "follow-up not in card"). Return JSON: {"grades": {"<qid>": {"verdict": ..., "gap": ...}}}')

def run(doc):
    qs = "\n".join(f"{k}: {q}" for k, q in QUESTIONS)
    pr = f"validation/{doc}.closure_ref.json"   # the paper does not change: build its reference answers once, so runs differ only in the records
    import hashlib
    qh = hashlib.sha256(qs.encode()).hexdigest()[:12]
    if os.path.exists(pr) and json.load(open(pr)).get("questions_sha", qh) == qh: ref = json.load(open(pr))["answers"]
    else:
        ref = call(ASK, f"QUESTIONS\n{qs}\n\nMATERIAL (full paper)\n{records.paper_text(doc)[:400000]}")["answers"]
        os.makedirs("validation", exist_ok=True); json.dump({"doc": doc, "model": MODEL, "questions_sha": qh, "answers": ref}, open(pr, "w"), indent=1)
    rec_text = records.render(doc)
    got = call(ASK, f"QUESTIONS\n{qs}\n\nMATERIAL (database records)\n{rec_text[:400000]}")["answers"]
    pairs = "\n\n".join(f"{k}: {q}\nREFERENCE: {ref.get(k)}\nRECORDS: {got.get(k)}" for k, q in QUESTIONS)
    gr = call(GRADE, pairs)["grades"]
    W = {"match": 1, "partial": 0.5}
    ans = [k for k, _ in QUESTIONS if gr.get(k, {}).get("verdict") != "not_in_paper"]
    score = sum(W.get(gr.get(k, {}).get("verdict"), 0) for k in ans) / max(1, len(ans))
    out = {"doc": doc, "model": MODEL, "completeness": round(score, 3), "answerable": len(ans), "records_chars": len(rec_text),
           "grades": gr, "reference": ref, "records_answers": got}
    os.makedirs("validation", exist_ok=True); p = f"validation/{doc}.closure.json"; json.dump(out, open(p, "w"), indent=1)
    store.append("closure_test", {"doc": doc, "model": MODEL, "completeness": out["completeness"], "answerable": len(ans), "out_sha256": store.file_hash(p)})
    return out

if __name__ == "__main__":
    for d in [a for a in sys.argv[1:] if not a.startswith("--")]:
        o = run(d); v = {}
        for g in o["grades"].values(): v[g.get("verdict")] = v.get(g.get("verdict"), 0) + 1
        print(json.dumps({"doc": d, "completeness": o["completeness"], "verdicts": v, "gaps": {k: g.get("gap") for k, g in o["grades"].items() if g.get("verdict") not in ("match", "not_in_paper")}, "usd_total": round(spent, 4)}), flush=True)
