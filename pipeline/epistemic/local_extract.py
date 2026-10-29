"""Extractor B on local hardware: an open model from a different family (default Qwen3) served by Ollama,
producing the same brief-v2 output as the Claude extractor, so validation is unchanged.
Stage 1 reads abstract, methods and table captions once and defines the study frame (groups, models, variables).
Stage 2 classifies candidates in small batches, constrained by JSON schema to the controlled vocabulary and the stage-1 ids.
Usage: python -m epistemic.local_extract parsed/<doc>.json ext/<doc>.B.json [model]"""
import json, sys, time, requests
from .context import describe, table_index
from .typecheck import ROLES, REASONS

HOST = "http://127.0.0.1:11434"

def gen(model, prompt, schema, think=False, num_ctx=32768):
    for a in range(4):
        try:
            r = requests.post(f"{HOST}/api/generate", json={"model": model, "prompt": prompt, "format": schema, "stream": False,
                              "think": think, "options": {"temperature": 0, "num_ctx": num_ctx}}, timeout=1800)
            r.raise_for_status(); return json.loads(r.json()["response"])
        except Exception as e:
            err = e; time.sleep(5)
    raise RuntimeError(f"ollama failed: {err}")

def stage1(P, model):
    secs = [s for s in P["sections"] if any(k in (s["title"] or "").lower() for k in ("abstract", "method", "subject", "design", "statistic", "population", "result"))]
    text = "\n\n".join(f"## {s['title']}\n{s['text']}" for s in secs)[:40000]
    caps = "\n".join(f"{t['id']}: {t['caption']} | footnotes: {t['footnotes'][:600]}" for t in P["tables"])
    header_rows = "\n".join(f"{t['id']} header: " + " || ".join(" | ".join(r["cells"]) for r in t["rows"] if r["is_head"])[:800] for t in P["tables"])
    obj = lambda props, req: {"type": "object", "properties": props, "required": req}
    arr = lambda item: {"type": "array", "items": item}
    s = lambda: {"type": "string"}
    schema = obj({
        "study_card": obj({"design": s(), "setting": s(), "cohort_name": s(), "population": s(), "exposure": s(),
                           "exposure_instrument": s(), "outcomes": s(), "followup": s(), "funding": s()}, ["design", "population", "exposure", "outcomes"]),
        "groups": arr(obj({"group_id": s(), "label": s(), "definition": s()}, ["group_id", "label"])),
        "models": arr(obj({"model_id": s(), "label": s(), "adjusted_for": arr(s()), "role": {"type": "string", "enum": ["main", "secondary", "sensitivity", "descriptive"]}}, ["model_id", "label", "role"])),
        "variables": arr(obj({"variable_id": s(), "label": s(), "kind": {"type": "string", "enum": ["exposure", "outcome", "covariate", "baseline", "design", "other"]}}, ["variable_id", "label", "kind"])),
        "claims": arr(obj({"text_paraphrase": s(), "relation": {"type": "string", "enum": ["association", "causal", "null", "mechanistic"]}, "location": s()}, ["text_paraphrase", "relation"])),
        "bias_flags": arr(obj({"stage": s(), "observation": s(), "severity": {"type": "string", "enum": ["low", "moderate", "high"]}}, ["stage", "observation", "severity"])),
        "warrants": arr(obj({"assumption": s(), "status": {"type": "string", "enum": ["tested", "validation_cited", "assumed"]}}, ["assumption", "status"]))},
        ["study_card", "groups", "models", "variables", "claims", "bias_flags", "warrants"])
    prompt = ("You are extracting the study frame from a scientific paper. Define every population group and exposure category "
              "(short ids like g_men, c_2_3cups), one model per distinct adjustment set (exactly one main model per outcome, the one the abstract reports), "
              "and every variable reported. Then list main claims, bias flags (stages: agenda, construct, sampling, random_error, systematic_measurement, "
              "design, distribution_and_modeling, analytic_flexibility, spin_and_scope, file_drawer, incentives) and warrants. Use only the text given.\n\n"
              f"TITLE: {P['title']}\n\n{text}\n\nTABLES:\n{caps}\n{header_rows}")
    return gen(model, prompt, schema, think=True)

def stage2(P, frame, model, batch=20):
    tables = table_index(P)
    gids = [g["group_id"] for g in frame["groups"]] + [None]
    mids = [m["model_id"] for m in frame["models"]] + [None]
    vids = [v["variable_id"] for v in frame["variables"]] + [None]
    enum = lambda xs: {"enum": xs}
    item = {"type": "object", "properties": {
        "id": {"type": "string"}, "is_data": {"type": "boolean"},
        "reason": enum(sorted(REASONS) + [None]), "roles": {"type": "array", "items": enum(sorted(ROLES))},
        "variable_id": enum(vids), "group_id": enum(gids), "reference_group_id": enum(gids), "model_id": enum(mids),
        "source": enum(["this_study", "external"])}, "required": ["id", "is_data", "roles"]}
    schema = {"type": "object", "properties": {"items": {"type": "array", "items": item}}, "required": ["items"]}
    frame_txt = json.dumps({k: frame[k] for k in ("groups", "models", "variables")}, ensure_ascii=False)[:12000]
    out = {}
    C = [c for c in P["candidates"]]
    for i in range(0, len(C), batch):
        chunk = C[i:i + batch]
        items = [{"id": c["id"], "numbers_in_order": [n.get("raw") for n in c["numbers"]], "context": describe(P, c, tables)} for c in chunk]
        prompt = ("Classify every number below from the paper titled '" + P["title"] + "'. For each candidate decide is_data "
                  "(a value reported, measured, defined or used by this study, or by a cited study) or not (give a reason). "
                  "If data, give one role per number in numbers_in_order, using the allowed roles exactly, and link to the frame ids. "
                  "Use source=external for values from other studies.\n\nFRAME:\n" + frame_txt + "\n\nCANDIDATES:\n" + json.dumps(items, ensure_ascii=False))
        res = gen(model, prompt, schema)
        for r in res.get("items", []): out[r["id"]] = r
        # retry singly for missing or malformed records
        for c in chunk:
            r = out.get(c["id"])
            if r is None or (r.get("is_data") and len(r.get("roles", [])) != len(c["numbers"])):
                one = gen(model, prompt.split("CANDIDATES:")[0] + "CANDIDATES:\n" + json.dumps([items[chunk.index(c)]], ensure_ascii=False), schema)
                if one.get("items"): out[c["id"]] = one["items"][0]
    return out

def run(parsed, outpath, model="qwen3:30b-a3b"):
    P = json.load(open(parsed))
    frame = stage1(P, model)
    recs = stage2(P, frame, model)
    data, not_data = [], []
    for c in P["candidates"]:
        r = recs.get(c["id"])
        if r and r.get("is_data") and len(r.get("roles", [])) == len(c["numbers"]):
            data.append({k: r.get(k) for k in ("id", "roles", "variable_id", "group_id", "reference_group_id", "model_id", "source")})
        else:
            not_data.append({"id": c["id"], "reason": (r or {}).get("reason") or "parse_artifact"})
    E = {"doc": P["doc"], "extractor": f"ollama:{model}", **frame, "data": data, "not_data": not_data, "missed_by_parser": [], "confidence": None}
    json.dump(E, open(outpath, "w"), indent=1)
    return {"doc": P["doc"], "data": len(data), "not_data": len(not_data)}

if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1], sys.argv[2], *(sys.argv[3:4] or []))))
