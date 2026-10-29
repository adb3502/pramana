"""Extractor B: a transparent rule-based drift coder over every Semantic Scholar citing context.
It is deliberately crude; its job is to be independent of extractor A (the model), so disagreements are visible."""
import json, re
from collections import Counter
S = json.load(open("s2_citations.json"))
CARD = re.compile(r"cardio|cvd|heart|coronary|chd|cad\b|stroke|myocardial|vascular", re.I)
COFF = re.compile(r"coffee|caffein", re.I)
ASSOC = re.compile(r"associat|link|correlat|related to|relationship|inverse|risk ratio|relative risk|\bRR\b|hazard", re.I)
CAUSAL = re.compile(r"\b(reduc\w*|lower(s|ed)? (the )?risk|decreas\w*|protect\w*|cardioprotect\w*|prevent\w*|benefi\w*|improv\w*)", re.I)
DOSE = re.compile(r"(\b3\b|three)\s*(to|-|–)\s*(\b5\b|five)|3\.5|non-?linear|[UJ][- ]shaped|lowest (cvd |cardiovascular )?risk|dose", re.I)
GUIDE = re.compile(r"recommend|guideline", re.I)
OTHER = re.compile(r"diabet|parkinson|cancer|dementia|alzheimer|liver|chlorogenic|depress|obes", re.I)
def code(t):
    if len(re.findall(r"[A-Za-z]", t)) < 40 or re.match(r"^\s*\d{4};", t): return "unusable"
    if not (CARD.search(t) or COFF.search(t)): return "unusable"
    m = re.search(r"(\d+)\s+(prospective|cohort|observational)\s+(cohort\s+)?studies", t, re.I)
    if m and m.group(1) not in ("36",): return "distortion"
    if re.search(r"strong(ly)? associat", t, re.I): return "distortion"
    if re.search(r"(increas\w*|higher|elevat\w*)\s+(the\s+)?(cvd\s+|cardiovascular\s+)?risk", t, re.I) and re.search(r"heavy|high(er)? (intake|consumption)|more than", t, re.I) and not re.search(r"\bnot\b|\bno\b|neither|neutral", t, re.I): return "distortion"
    if GUIDE.search(t): return "guideline_relay"
    if OTHER.search(t) and not CARD.search(t): return "misattribution"
    if CAUSAL.search(t) and not ASSOC.search(t): return "causal_upgrade"
    if DOSE.search(t) and CARD.search(t): return "faithful"
    if CARD.search(t): return "stripped"
    return "unusable"
rows = []
for c in S:
    p = c.get("citingPaper", {})
    for t in c.get("contexts") or []:
        rows.append({"paper": p.get("paperId"), "year": p.get("year"), "ids": p.get("externalIds") or {}, "text": t,
                     "intents": c.get("intents"), "code_B": code(t)})
json.dump(rows, open("s2_coded.json", "w"), indent=1)
cnt = Counter(r["code_B"] for r in rows); print(cnt)
# per-paper code: worst-case across a paper's contexts, excluding unusable
rank = ["misattribution", "distortion", "causal_upgrade", "guideline_relay", "stripped", "faithful"]
per = {}
for r in rows:
    if r["code_B"] == "unusable": continue
    k = r["paper"]; cur = per.get(k)
    if cur is None or rank.index(r["code_B"]) < rank.index(cur): per[k] = r["code_B"]
print("papers with usable contexts", len(per), Counter(per.values()))
# agreement with extractor A on overlapping papers
up = json.load(open("up_contexts.json")); A = json.load(open("up_coding.json"))["items"]
a_by = {}
for i, r in enumerate(up):
    c = A.get(str(i))
    if c and c[0] != "unusable": a_by[(r.get("pmid") or "")] = c[0]
pairs = []
for k, codeb in per.items():
    pm = next((r["ids"].get("PubMed") for r in rows if r["paper"] == k), None)
    if pm and pm in a_by: pairs.append((a_by[pm], codeb))
agree = sum(a == b for a, b in pairs)
print("overlap", len(pairs), "agree", agree, pairs)
json.dump({"counts_contexts": cnt, "per_paper": Counter(per.values()), "overlap": pairs}, open("s2_summary.json", "w"), indent=1)
