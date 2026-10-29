"""Render what the store knows about a paper, without the paper: study card, groups, models, variables and every datum
with its wiring (variable, group, reference, model, stratum, timepoint). This is the view an outside agent gets.
Usage: python -m epistemic.records PMC... [> file]"""
import sys, os, re, json, glob
REF = re.compile(r"(PMC\d+:[a-z]?\d+)\[(\d+)\]")

def resolver(doc):
    """Card fields cite candidate numbers as <id>[i]; an outside reader needs the value. Map each to 'raw (id[i])'."""
    vals = {}
    for suf in ("", "_S", "_F"):
        p = f"parsed/{doc}{suf}.json"
        if not os.path.exists(p): continue
        for c in json.load(open(p))["candidates"]:
            for i, n in enumerate(c["numbers"]): vals[f"{c['id']}[{i}]"] = n.get("raw") if n.get("raw") is not None else n.get("value")
    return lambda t: REF.sub(lambda m: f"{vals.get(m.group(0), '?')}", t)

def load_ext(doc):
    """Structure pass v4 (ext/<doc>.S4.json) wins for card, groups, variables, models and analyses; older extractor files fill in."""
    base = {}
    for side in ("adj", "A", "B"):
        p = f"ext/{doc}.{side}.json"
        if os.path.exists(p):
            e = json.load(open(p))
            if e.get("study_card") or e.get("groups"): base = e; break
    p4 = f"ext/{doc}.S4.json"
    if os.path.exists(p4):
        s4 = json.load(open(p4)); base = dict(base)
        for k in ("study_card", "groups", "variables", "models", "analyses", "claims", "bias_flags", "warrants"):
            if not s4.get(k): continue
            if k in ("claims", "bias_flags", "warrants"): base[k] = base.get(k) or s4[k]   # extractor-made lists win; S4 fills papers that have none
            elif k in ("study_card", "analyses") or not base.get(k): base[k] = s4[k]
            else: base[k] = s4[k] + [x for x in base.get(k, []) or [] if x not in s4[k]]
    return base

def _old_load_ext(doc):
    for side in ("adj", "A", "B"):
        p = f"ext/{doc}.{side}.json"
        if os.path.exists(p):
            e = json.load(open(p))
            if e.get("study_card") or e.get("groups"): return e
    return {}

class _SafeLab(dict):
    """Label lookup that tolerates list-valued ids (a datum tied to several groups)."""
    def get(self, k, d=None):
        if isinstance(k, list): return ", ".join(str(dict.get(self, x, x)) for x in k)
        try: return dict.get(self, k, d)
        except TypeError: return d

def render(doc, include=("", "_S", "_F")):
    e = load_ext(doc); out = [f"# Records for {doc}"]; res = resolver(doc)
    lab = _SafeLab()
    for k, idk in (("groups", "group_id"), ("models", "model_id"), ("variables", "variable_id")):
        for x in e.get(k, []) or []: lab[x.get(idk)] = x.get("label") or x.get(idk)
    out.append("## Study card\n" + json.dumps(e.get("study_card", {}), ensure_ascii=False))
    out.append("## Groups\n" + "\n".join(f"{g.get('group_id')}: {g.get('label')} :: {g.get('definition')} (parent {g.get('parent_group_id')})" for g in e.get("groups", []) or []))
    out.append("## Models\n" + "\n".join(f"{m.get('model_id')}: {m.get('label')} [{m.get('type')}; role {m.get('role')}] adjusted for {m.get('adjusted_for')}; stratified by {m.get('stratified_by')}" for m in e.get("models", []) or []))
    out.append("## Variables\n" + "\n".join(f"{v.get('variable_id')}: {v.get('label')} ({v.get('kind')}, {v.get('unit')}) :: {v.get('definition')}" for v in e.get("variables", []) or []))
    out.append("## Analyses register (status: reported / reported_without_numbers / not_reported)\n" + "\n".join(
        f"{a.get('analysis_id')}: [{a.get('kind')}] {a.get('description')} | model {a.get('model_id')} | outcome {a.get('outcome') or a.get('outcome_variable_id')} | stratifier {a.get('stratifier')} | status {a.get('status')} | reported in {a.get('reported_in')} | conclusion as stated: {a.get('conclusion_as_stated')}"
        for a in e.get("analyses", []) or []))
    for suf in include:
        p = f"data/{doc}{suf}.jsonl"
        if not os.path.exists(p): continue
        rows = [json.loads(l) for l in open(p)]
        rows = [r for r in rows if r.get("role") and not r.get("span_copy") and not r.get("nested_copy")]
        out.append(f"## Data{(' from ' + {'_S': 'supplements', '_F': 'figures'}[suf]) if suf else ''} ({len(rows)} values)\nvalue | role | variable | group | vs reference | model | stratum | timepoint")
        for r in rows:
            g = lambda k: r.get(k) or r.get(k + "_A") or ""
            out.append(" | ".join(str(x) for x in (r.get("raw") or r.get("value"), r["role"], lab.get(g("variable"), g("variable")), lab.get(g("group"), g("group")),
                                                     lab.get(g("reference_group"), g("reference_group")), lab.get(g("model"), g("model")), g("stratum"), g("timepoint"))))
    pf = f"parsed/{doc}_F.json"
    if os.path.exists(pf):
        F = json.load(open(pf)); pts = [c for c in F["candidates"] if c["kind"] == "figure_point"]
        typ = {f["id"]: f"{f.get('type')}: {f.get('caption', '')[:120]}" for f in F["figures"]}
        if F["figures"]: out.append("## Figures (type: caption)\n" + "\n".join(f"{k} {v}" for k, v in typ.items()))
        if pts:
            out.append(f"## Digitized points read off figure axes (estimates, not printed values; {len(pts)})\nfigure | panel | series | x | y | y_low | y_high")
            for c in pts:
                q = json.loads(c["text"]); out.append(" | ".join(str(x) for x in (c["anchor"]["figure"], q.get("panel", ""), q.get("series", ""), q.get("x"), q.get("y"), q.get("y_low"), q.get("y_high"))))
    return res("\n".join(out))

def paper_text(doc):
    """The paper as the parser sees it (sections + tables), for building reference answers."""
    P = json.load(open(f"parsed/{doc}.json")); out = [P.get("title", "")]
    for s in P["sections"]: out.append(f"## {s['title']}\n{s['text']}")
    for t in P["tables"]:
        out.append(f"## Table {t['id']}: {t['caption']}\n" + "\n".join(" | ".join(r["cells"]) for r in t["rows"]) + (f"\nFootnotes: {t['footnotes']}" if t.get("footnotes") else ""))
    for f in P.get("figures", []): out.append(f"## Figure {f['id']}: {f['caption']}")
    return "\n\n".join(out)

if __name__ == "__main__":
    for d in sys.argv[1:]: print(render(d))
