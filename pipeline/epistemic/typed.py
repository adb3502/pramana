"""Typed judges: an independent, cheap check of every datum's classification and roles.
Backends share one interface: ask(state, questions) -> {qid: {"answer": label_or_bool, "p": confidence}}
  jev    TypeSafe Jev hosted API (needs JEV_API_KEY; $0.042 per million input tokens)
  ollama a local open model on the Spark, constrained to the same label sets by JSON schema
  laya   ConvAI Laya, open-source local typed-decision model (adapter filled in after inspecting the package)
Judges never see the extractors' answers. Their job is to disagree when the extractors are wrong."""
import os, json, time, concurrent.futures as cf
import requests
from .context import describe, table_index
from .typecheck import ROLES

ROLE_HELP = {
 "estimate_hr": "hazard ratio estimate", "estimate_rr": "relative risk or rate ratio estimate", "estimate_or": "odds ratio estimate",
 "estimate_irr": "incidence rate ratio estimate", "estimate_beta": "regression coefficient", "estimate_difference": "difference between groups",
 "ci_low": "lower confidence limit", "ci_high": "upper confidence limit", "ci_level": "confidence level used as a value",
 "se": "standard error", "p_value": "p value", "p_trend": "p value for trend", "p_interaction": "p value for interaction",
 "p_heterogeneity": "p value for heterogeneity", "mean": "mean", "sd": "standard deviation", "median": "median",
 "iqr_low": "lower quartile", "iqr_high": "upper quartile", "range_low": "lower end of a range", "range_high": "upper end of a range",
 "percent": "percentage", "count": "count of people or items", "count_events": "number of outcome events or cases",
 "n_participants": "number of participants in a population", "person_years": "person-years of follow-up", "rate": "incidence or event rate",
 "rate_denominator": "denominator of a rate (per 10,000)", "correlation": "correlation coefficient", "power": "statistical power",
 "alpha": "significance level", "category_bound_low": "lower bound of an exposure or covariate category",
 "category_bound_high": "upper bound of a category", "category_value": "single-value category such as 2 cups",
 "cutpoint": "threshold dividing groups", "dose": "dose or intake amount", "age_bound_low": "lower age limit",
 "age_bound_high": "upper age limit", "year": "calendar year", "date_part": "day or month", "duration_years": "a duration in years",
 "followup_years": "length of follow-up", "serving_size": "serving or cup size", "content_per_serving": "content per serving such as mg caffeine per cup",
 "questionnaire_cycle": "questionnaire cycle interval", "version_number": "version number", "code": "classification code such as ICD",
 "hypothetical_effect": "effect size assumed in a power calculation", "degrees_of_freedom": "degrees of freedom",
 "sidedness": "1- or 2-sided test", "items_count": "number of questionnaire items", "other": "none of the above"}
assert set(ROLE_HELP) == ROLES

class Jev:
    name = "jev"
    def __init__(self, model="jev-latest"):
        self.key = os.environ["JEV_API_KEY"]; self.model = model; self.input_tokens = 0
    def ask(self, state, questions):
        q = {}
        for k, v in questions.items():
            if v["type"] == "noul": q[k] = {"type": "noul", "instructions": v["instructions"]}
            else: q[k] = {"type": "choice", "instructions": v["instructions"], "criteria": v["criteria"]}
        for a in range(6):
            r = requests.post("https://api.typesafe.ai/v1/systemone", headers={"Authorization": f"Bearer {self.key}"},
                              json={"model": self.model, "state": state, "questions": q}, timeout=60)
            if r.status_code in (429, 529, 500, 502, 503): time.sleep(min(30, 2 ** a)); continue
            r.raise_for_status(); d = r.json()
            self.input_tokens += d.get("usage", {}).get("input_tokens", 0)
            out = {}
            for k, ans in d["answers"].items():
                if ans["type"] == "noul": out[k] = {"answer": ans["noul"] >= 0.5, "p": ans["noul"]}
                else: out[k] = {"answer": ans["choice"], "p": ans.get("confidence")}
            return out
        raise RuntimeError("jev: retries exhausted")

class Ollama:
    name = "ollama"
    def __init__(self, model="qwen3:30b-a3b", host="http://127.0.0.1:11434"):
        self.model, self.host, self.input_tokens = model, host, 0
    def ask(self, state, questions):
        props = {}
        for k, v in questions.items():
            props[k] = {"type": "boolean"} if v["type"] == "noul" else {"type": "string", "enum": list(v["criteria"])}
        schema = {"type": "object", "properties": props, "required": list(props)}
        lines = [f"- {k}: {v['instructions']}" + ("" if v["type"] == "noul" else " Options: " + "; ".join(f"{a} = {b}" for a, b in v["criteria"].items()))
                 for k, v in questions.items()]
        prompt = ("You check data extracted from a scientific paper. Answer every question about the CONTEXT. "
                  "Return JSON only.\n\nCONTEXT:\n" + json.dumps(state, ensure_ascii=False) + "\n\nQUESTIONS:\n" + "\n".join(lines))
        r = requests.post(f"{self.host}/api/generate", json={"model": self.model, "prompt": prompt, "format": schema, "stream": False,
                                                            "think": False, "options": {"temperature": 0}}, timeout=300)
        r.raise_for_status(); d = r.json(); self.input_tokens += d.get("prompt_eval_count", 0)
        ans = json.loads(d["response"])
        return {k: {"answer": ans.get(k), "p": None} for k in questions}

def questions_for(c):
    q = {"is_datum": {"type": "noul", "instructions": "Is the highlighted number a value reported, measured, defined or used by this study "
                       "(a statistic, sample size, category bound, date, dose or setting) rather than a citation number, a table or figure number, "
                       "the '95' of '95% CI', a per-10,000 unit, a software version, a grant number, or part of a name like 'type 2 diabetes'?"},
         "external": {"type": "noul", "instructions": "Does the highlighted number come from a different study that this paper is citing?"}}
    for i, n in enumerate(c["numbers"]):
        q[f"role_{i}"] = {"type": "choice", "instructions": f"Number {i + 1} of {len(c['numbers'])} in the highlighted text is {n.get('raw')}. What is it?",
                          "criteria": ROLE_HELP}
    return q

def judge(P, backend, ids=None, workers=4):
    tables = table_index(P)
    C = [c for c in P["candidates"] if (ids is None or c["id"] in ids) and c["numbers"] and c["numbers"][0].get("value") is not None]
    def one(c):
        st = describe(P, c, tables); st["numbers_in_order"] = [n.get("raw") for n in c["numbers"]]
        try: return c["id"], backend.ask(st, questions_for(c))
        except Exception as e: return c["id"], {"error": str(e)[:200]}
    out = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        for cid, a in ex.map(one, C): out[cid] = a
    return out

FAMILY = {}
for fam, rs in {"category": "category_bound_low category_bound_high category_value cutpoint dose age_bound_low age_bound_high serving_size content_per_serving",
                "count": "count count_events n_participants items_count", "ratio": "estimate_hr estimate_rr estimate_or estimate_irr",
                "p": "p_value p_trend p_interaction p_heterogeneity", "time": "year date_part duration_years followup_years questionnaire_cycle",
                "label": "version_number code other"}.items():
    for r in rs.split(): FAMILY[r] = fam
fam = lambda r: FAMILY.get(r, r)

def compare(P, judged, data_rows):
    """data_rows: the validated data layer for this doc (agreed roles). Returns agreement stats and disagreements."""
    agreed = {}
    for r in data_rows:
        if r.get("agreed"): agreed.setdefault(r["candidate"], {})[int(r["datum_id"].rsplit("#", 1)[1])] = r["role"]
    hit = miss = 0; dis = []
    for cid, roles in agreed.items():
        a = judged.get(cid, {})
        for i, role in roles.items():
            j = (a.get(f"role_{i}") or {}).get("answer")
            if j is None: continue
            if j == role: hit += 1
            else: miss += 1; dis.append({"candidate": cid, "index": i, "extractors": role, "judge": j})
    fam_miss = sum(1 for d in dis if fam(d["extractors"]) != fam(d["judge"]))
    return {"compared": hit + miss, "agreement": round(hit / (hit + miss), 3) if hit + miss else None,
            "family_agreement": round(1 - fam_miss / (hit + miss), 3) if hit + miss else None, "disagreements": dis}

try:
    from .laya_judge import Laya  # noqa
except ImportError:
    pass
