"""Pass S (structure brief v4): one call per paper -> study card, flow, groups, variables, models and the analyses register
(every analysis the methods promise, with where its results are, or status not_reported = silence).
Numbers are typed as printed and then auto-anchored to parser candidates (paper, supplements, figures); any number that
anchors nowhere is listed in `unanchored` and is not trusted. Output ext/<doc>.S4.json + ledger.
Usage: python -m epistemic.structure PMC... [--force]   env STRUCT_MODEL (default claude-haiku-5-5)"""
import sys, os, re, json, time, requests
from . import records, store
from .parse import numbers_in
from . import llm
MODEL = {"claude-haiku-5-5": "haiku", "claude-sonnet-5-5": "sonnet"}.get(os.environ.get("STRUCT_MODEL", "haiku"), os.environ.get("STRUCT_MODEL", "haiku"))
BRIEF = open(os.path.join(os.path.dirname(__file__), "..", "briefs", "STRUCTURE_BRIEF.md")).read()
SYSTEM = BRIEF + """

Implementation note for this run: type every number exactly as printed in the material (e.g. "3,507", "0.81 (0.65, 0.99)")
instead of candidate references; the pipeline anchors each typed number to the parser's candidates afterwards and rejects
numbers it cannot find. Also fill:
 "claims": [{"text_paraphrase", "relation": "association|causal|null|mechanistic", "hedging": "<the authors' own hedge words>", "scope", "location": "abstract|results|discussion|conclusion", "numbers": ["<the numbers the claim rests on, typed exactly as printed>"]}]  (every claim the authors make about their own results, abstract and conclusion first)
 "bias_flags": [{"stage": "agenda|construct|sampling|random_error|systematic_measurement|design|distribution_and_modeling|analytic_flexibility|spin_and_scope|file_drawer|transmission|echo|herding|incentives", "observation", "severity": "low|moderate|high", "kind": "measured|judged"}]
 "warrants": [{"assumption": "<an assumption the conclusions depend on>", "status": "tested|validation_cited|assumed|acknowledged_unverified"}]
Return the JSON object only."""

def material(doc):
    parts = [records.paper_text(doc)]
    if os.path.exists(f"parsed/{doc}_F.json"):
        F = json.load(open(f"parsed/{doc}_F.json")); byfig = {}
        for c in F["candidates"]:
            if c["kind"] == "figure_point": continue
            a = c["anchor"]; byfig.setdefault(a.get("figure"), []).append(" / ".join(x for x in (a.get("row_label"), a.get("column_label"), a.get("series")) if x) + ": " + c["text"])
        for f in F["figures"]:
            parts.append(f"## Figure reading {f['id']} ({f['type']}): {f['caption'][:400]}\n" + "\n".join(byfig.get(f["id"], [])[:400]))
    if os.path.exists(f"parsed/{doc}_S.json"):
        S = json.load(open(f"parsed/{doc}_S.json"))
        for t in S["tables"][:60]:
            rows = t["rows"][:40]
            parts.append(f"## Supplement {t.get('supp')} table {t['id']} {t.get('caption', '')} ({len(t['rows'])} rows; first {len(rows)} shown)\n" + "\n".join(" | ".join(r["cells"]) for r in rows))
        for s in S["sections"][:20]: parts.append(f"## Supplement text {s.get('supp')}\n{s['text'][:20000]}")
    return "\n\n".join(parts)

def call(user):
    out, usd = llm.chat(MODEL, SYSTEM, user, 32000); return out, usd, None

LOCATORS = {"reported_in", "promised_in", "analysis_id", "model_id", "group_id", "variable_id", "reference_group_id", "parent_group_id", "codes"}

def anchor(doc, obj):
    """Every number typed anywhere in obj must match a candidate number (value and, when given, qualifier)."""
    idx = {}
    for suf in ("", "_S", "_F"):
        p = f"parsed/{doc}{suf}.json"
        if not os.path.exists(p): continue
        for c in json.load(open(p))["candidates"]:
            for i, n in enumerate(c["numbers"]):
                if n.get("value") is not None: idx.setdefault(round(n["value"], 6), []).append(f"{c['id']}[{i}]")
    anchored, missing = {}, []
    def walk(x, path):
        if isinstance(x, dict): [walk(v, f"{path}.{k}") for k, v in x.items() if k not in LOCATORS]
        elif isinstance(x, list): [walk(v, f"{path}[{i}]") for i, v in enumerate(x)]
        elif isinstance(x, (int, float)) and not isinstance(x, bool): chk(str(x), path)
        elif isinstance(x, str): chk(x, path)
    def chk(s, path):
        for n in numbers_in(s):
            if n["value"] is None: continue
            refs = idx.get(round(n["value"], 6))
            if refs: anchored.setdefault(path, []).append({"raw": n["raw"], "refs": refs[:5]})
            else: missing.append({"path": path, "raw": n["raw"]})
    walk({k: obj.get(k) for k in ("study_card", "analyses", "claims")}, "")
    return anchored, missing

def run(doc, force=False):
    out = f"ext/{doc}.S4.json"
    if os.path.exists(out) and not force: return {"doc": doc, "skipped": True}
    S, usd, stop = call(f"Paper {doc}. Material follows.\n\n{material(doc)[:600000]}")
    anc, miss = anchor(doc, S)
    for i, c in enumerate(S.get("claims") or []):   # claims point at the candidates their numbers anchor to, as extractor claims always did
        c["supported_by"] = sorted({r.split("[")[0] for path, hits in anc.items() if path.startswith(f".claims[{i}]") for h in hits for r in h["refs"]})
    S.update({"doc": doc, "extractor": MODEL, "brief": "structure v4", "anchors": anc, "unanchored": miss, "usd": round(usd, 5), "stop": stop})
    json.dump(S, open(out, "w"), indent=1)
    an = S.get("analyses") or []
    rep = {"doc": doc, "usd": round(usd, 4), "analyses": len(an), "not_reported": sum(1 for a in an if a.get("status") == "not_reported"),
           "flow_steps": len((S.get("study_card") or {}).get("flow") or []), "unanchored": len(miss), "stop": stop}
    store.append("structure_pass", {**rep, "model": MODEL, "out_sha256": store.file_hash(out)})
    return rep

def reanchor(doc):
    p = f"ext/{doc}.S4.json"; S = json.load(open(p)); S["anchors"], S["unanchored"] = anchor(doc, S)
    # an unanchored number that is the sum or difference of two anchored numbers in the same card is labelled derived, not trusted as printed
    vals = sorted({float(re.sub(r"[,\u2009 ]", "", a["raw"])) for v in S["anchors"].values() for a in v if re.fullmatch(r"[\d,.\u2009 ]+", a["raw"])})
    vs = set(vals)
    for m in S["unanchored"]:
        try: x = float(re.sub(r"[,\u2009 ]", "", m["raw"]))
        except ValueError: continue
        if any((x + v) in vs or abs(x - v) in vs for v in vals): m["derived"] = True
    json.dump(S, open(p, "w"), indent=1); return {"doc": doc, "unanchored": len(S["unanchored"]), "derived": sum(1 for m in S["unanchored"] if m.get("derived"))}

if __name__ == "__main__":
    for d in [a for a in sys.argv[1:] if not a.startswith("--")]:
        print(json.dumps(reanchor(d) if "--reanchor" in sys.argv else run(d, "--force" in sys.argv)), flush=True)
