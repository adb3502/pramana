"""Adjudicate disputed data with Opus (headless Claude Code).
A dispute is a number where the two extractors gave different roles, or where one called the candidate data and the other not.
Opus sees the candidate's context, both answers and the Jev verdict (if verification/<doc>.jev.json exists) and picks.
It never types a number: it only picks A, B, or another role from the controlled vocabulary.
Writes ext/<doc>.adj.json and a ledger event. Re-run validate afterwards to fold the verdicts into data/<doc>.jsonl.
Usage: python scripts/adjudicate.py <doc> [--model opus] [--chunk 40]"""
import json, os, sys, subprocess, pathlib, re, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from epistemic import store
from epistemic.context import describe, table_index
from epistemic.typecheck import ROLES, REASONS

CLAUDE = os.environ.get("CLAUDE", os.path.expanduser("~/.local/bin/claude"))

def disputes(doc):
    P = json.load(open(f"parsed/{doc}.json")); T = table_index(P); C = {c["id"]: c for c in P["candidates"]}
    rows = [json.loads(l) for l in open(f"data/{doc}.jsonl")]
    jev = {}
    if pathlib.Path(f"verification/{doc}.jev.json").exists():
        jev = json.load(open(f"verification/{doc}.jev.json"))["judged"]
    out = []
    for r in rows:
        if not (r.get("needs_adjudication") or r.get("data_dispute")): continue
        c = C[r["candidate"]]; i = int(r["datum_id"].rsplit("#", 1)[1])
        j = jev.get(r["candidate"], {})
        out.append({"datum_id": r["datum_id"], "number": r["raw"], "position": f"{i + 1} of {len(c['numbers'])}",
                    "numbers_in_candidate": [n.get("raw") for n in c["numbers"]], "context": describe(P, c, T),
                    "A": r["role_A"] or "not_data", "B": r["role_B"] or "not_data",
                    "jev": {"role": (j.get(f"role_{i}") or {}).get("answer"), "is_datum": (j.get("is_datum") or {}).get("answer")} if j else None})
    return out

PROMPT = """You are the adjudicator for a data-extraction pipeline on the scientific paper "{title}".
Two blind extractors classified each number below and disagreed. A third cheap judge (jev) may also have an opinion; it is often
right on clear cases but confuses near-synonym roles. For each item choose the correct answer:
  choice "A" or "B" if one extractor is right, or "other" with a role you pick from the vocabulary if both are wrong.
  "not_data" is a legal answer (the number is a citation, table number, the 95 of 95% CI, a unit denominator, etc).
Role vocabulary (use exactly): {roles}
Brief rules you must apply (EXTRACT_BRIEF v2): not_data reasons are citation_number, table_or_figure_number, section_number,
ci_level_label (when the candidate is just the "95" of "95% CI" it is not_data; ci_level is only for that 95 inside a multi-number candidate such as a caption), unit_denominator (the 10,000 in "per 10,000"),
software_version, grant_number, page_or_volume, prose_word (part of a name or phrase, e.g. "type 2 diabetes"), parse_artifact.
Role notes: category_bound_low/high are the bounds of an exposure or covariate category (e.g. 2-3 cups); category_value is a
single-valued category (e.g. 1 cup); cutpoint is a threshold dividing groups; n_participants is the size of a population or group;
count is a count of people with a characteristic; count_events is cases/outcome events.
Return ONLY a JSON array, one object per item, in order: {{"datum_id": ..., "choice": "A"|"B"|"other", "role": <final role or "not_data">, "why": <max 15 words>}}.

ITEMS:
{items}"""

def ask(prompt, model):
    for a in range(3):
        p = subprocess.run([CLAUDE, "-p", prompt, "--model", model, "--output-format", "json"],
                           capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        try:
            env = json.loads(p.stdout); txt = env.get("result", "")
            m = re.search(r"\[.*\]", txt, re.S)
            return json.loads(m.group(0)), env.get("total_cost_usd")
        except Exception as e:
            err = f"{e}: {p.stderr[-300:]}"; time.sleep(10)
    raise RuntimeError(f"adjudication failed: {err}")

def run(doc, model="opus", chunk=40):
    P = json.load(open(f"parsed/{doc}.json")); D = disputes(doc)
    decisions, cost = [], 0.0
    # deterministic brief rule first: a lone "95" followed by "% CI"/"% confidence" is not_data (ci_level_label); no model call
    secs = {s["id"]: s["text"] for s in P["sections"]}; C = {c["id"]: c for c in P["candidates"]}
    def lone_ci95(d):
        c = C[d["datum_id"].rsplit("#", 1)[0]]; a = c["anchor"]
        if len(c["numbers"]) != 1 or c["numbers"][0].get("value") != 95 or "section" not in a: return False
        return bool(re.match(r"\s*%?\s*(CI\b|C\.I\.|confidence|credib)", secs.get(a["section"], "")[a["end"]:a["end"] + 20], re.I))
    for d in [d for d in D if lone_ci95(d)]:
        decisions.append({"datum_id": d["datum_id"], "A": d["A"], "B": d["B"], "jev": (d["jev"] or {}).get("role"),
                          "choice": "A" if d["A"] == "not_data" else "B", "role": None, "not_data": True,
                          "why": "brief rule: the 95 of 95% CI is ci_level_label", "adjudicator": "rule:ci_level_label"})
    D = [d for d in D if not lone_ci95(d)]
    for k in range(0, len(D), chunk):
        part = D[k:k + chunk]
        res, c = ask(PROMPT.format(title=P["title"], roles=" ".join(sorted(ROLES)), items=json.dumps(part, ensure_ascii=False)), model)
        cost += c or 0
        byid = {x.get("datum_id"): x for x in res if isinstance(x, dict)}
        for d in part:
            x = byid.get(d["datum_id"]) or {}
            role = x.get("role")
            if x.get("choice") == "A": role = d["A"]
            elif x.get("choice") == "B": role = d["B"]
            ok = role in ROLES or role == "not_data"
            decisions.append({"datum_id": d["datum_id"], "A": d["A"], "B": d["B"], "jev": (d["jev"] or {}).get("role"),
                              "choice": x.get("choice") if ok else None, "role": role if ok and role != "not_data" else None,
                              "not_data": role == "not_data", "why": x.get("why"), "adjudicator": f"claude:{model}"})
    out = {"doc": doc, "adjudicator": f"claude:{model}", "n": len(decisions), "decisions": decisions, "cost_usd_equiv": round(cost, 4)}
    json.dump(out, open(f"ext/{doc}.adj.json", "w"), indent=1)
    store.append("adjudication_event", {"doc": doc, "adjudicator": f"claude:{model}", "n": len(decisions),
                                        "output_sha256": store.file_hash(f"ext/{doc}.adj.json")})
    from collections import Counter
    jev_hit = sum(1 for d in decisions if d["jev"] and d["role"] == d["jev"])
    return {"doc": doc, "disputes": len(decisions), "choices": dict(Counter(d["choice"] for d in decisions)),
            "jev_agrees_with_adjudicator": jev_hit, "jev_available": sum(1 for d in decisions if d["jev"]), "cost_usd_equiv": round(cost, 4)}

if __name__ == "__main__":
    a = sys.argv[1:]; model = a[a.index("--model") + 1] if "--model" in a else "opus"
    chunk = int(a[a.index("--chunk") + 1]) if "--chunk" in a else 40
    print(json.dumps(run(a[0], model, chunk)))
