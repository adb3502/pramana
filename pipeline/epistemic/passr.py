"""Pass R v4: label every parsed number (role per number) AND wire it to the structure pass ids
(variable, group, reference group, model, analysis). Works on any document unit: <doc>, <doc>_S (supplements), <doc>_F (figures).
Writes ext/<unit>.<side>.json in the brief-v3 shape, so validate.run(<unit>) builds data/<unit>.jsonl and flags disputes as before.
Usage: python -m epistemic.passr <side> <backend> UNIT...   backend: haiku | sonnet | qwen_local | deepseek"""
import os, sys, re, json, time, requests, collections, concurrent.futures as cf
from .context import describe, table_index
from .typed import ROLE_HELP
from .typecheck import REASONS
from . import store
CHUNK = int(os.environ.get("PASSR_CHUNK", "100"))
BACK = {"haiku": ("anthropic", "claude-haiku-5-5", 0.10, 0.50), "sonnet": ("anthropic", "claude-sonnet-5-5", 2.0, 10.0),
        "qwen_local": ("local", "nvidia/Qwen3.8-Flash-Next-FP4-Local", 0, 0), "deepseek": ("deepseek", "deepseek-flash", 0.30, 1.20)}
ROLES_TXT = "\n".join(f"{k}: {v}" for k, v in ROLE_HELP.items())
SYSTEM = f"""You label every number found by a parser in a scientific paper, and wire each datum to the study structure.
For each item decide whether its numbers are data (a value reported, measured, defined or used by this study or a cited study) or not data.
If data, give exactly one role per number, in the order of "n", using only these roles:
{ROLES_TXT}
and wire it with ids from the STRUCTURE block: "v" variable_id (what is measured or estimated; for estimates the outcome), "g" group_id (who or which exposure level), "ref" reference group_id (for contrasts, else null), "m" model_id (else null), "a" analysis_id (else null). Use null when no id fits; never invent ids.
If not data, give one reason from: {", ".join(sorted(REASONS))}.
Notes: the 95 of "95% CI" is not data (ci_level_label); citation numbers and table or figure numbers are not data; a number inside a name like "type 2 diabetes" is not data (prose_word).
Answer with JSON only: {{"items":[{{"id":"<id>","d":1,"r":["role",...],"v":..,"g":..,"ref":..,"m":..,"a":..}} or {{"id":"<id>","d":0,"why":"<reason>"}}]}} with one entry for every input item."""

def structure_block(parent):
    p = f"ext/{parent}.S4.json"
    if not os.path.exists(p): return "STRUCTURE: none available"
    S = json.load(open(p)); L = []
    for k, idk, lk in (("variables", "variable_id", "label"), ("groups", "group_id", "label"), ("models", "model_id", "label"), ("analyses", "analysis_id", "description")):
        L.append(k.upper() + ": " + "; ".join(f"{x.get(idk)}={str(x.get(lk) or '')[:90]}" for x in S.get(k) or []))
    return "STRUCTURE\n" + "\n".join(L)

BULK_ROWS = int(os.environ.get("PASSR_BULK_ROWS", "40"))

def items(unit):
    """Per-number items, except big tables (> BULK_ROWS body rows): those become one item per column (header + sample cells);
    the column's answer is copied to every cell below it (labelled_by column_rule), so a 20,000-cell supplement costs a few calls."""
    P = json.load(open(f"parsed/{unit}.json")); T = table_index(P); caps, out = {}, []
    rows_in = collections.Counter((c["anchor"].get("supp"), c["anchor"].get("table")) for c in P["candidates"] if c["kind"] in ("table_cell", "row_label"))
    bulk = {k for k, n in rows_in.items() if n > BULK_ROWS * 3}
    cols = collections.defaultdict(list)
    figcap = {f["id"]: f.get("caption", "")[:300] for f in P.get("figures", [])}
    for c in P["candidates"]:
        if not c["numbers"] or (c.get("prelabel") or {}).get("not_data") or c["kind"] == "figure_point": continue
        a = c["anchor"]; it = {"id": c["id"], "n": [n.get("raw") for n in c["numbers"]]}
        if "row" in a and (a.get("supp"), a.get("table")) in bulk and c["kind"] in ("table_cell", "row_label"):
            cols[(a.get("supp"), a["table"], a["col"])].append(c); continue
        if "row" in a:
            x = describe(P, c, T); caps[a["table"]] = (x.get("table_caption") or "")[:250]
            it.update(t=a["table"], col=(x.get("column_header") or "")[:120], row=(x.get("row_label") or "")[:120], sec=(x.get("row_section") or "")[:80], cell=c["text"][:80])
        elif "figure" in a:
            it.update(fig=a["figure"], panel=a.get("panel", ""), row=a.get("row_label", ""), col=a.get("column_label", ""), series=a.get("series", ""), cell=c["text"][:80], cap=figcap.get(a["figure"], "")[:200])
        else:
            it.update(where=str(a.get("supp") or a.get("section") or "")[:60], ctx=(c.get("local_context") or c["text"])[:400], hl=c["text"][:120])
        out.append(it)
    colmap = {}
    for (sp, t, col), cs in cols.items():
        x = describe(P, cs[0], T); cid = f"col:{t}:{col}"; colmap[cid] = cs
        caps[t] = (x.get("table_caption") or "")[:250]
        out.append({"id": cid, "n": [n.get("raw") for n in cs[0]["numbers"]], "t": t, "col": (x.get("column_header") or "")[:120],
                    "column_of": len(cs), "samples": [c["text"][:60] for c in cs[:4]], "note": "a whole table column: answer for its typical cell"})
    items.colmap = colmap
    return P, caps, out

def call(backend, user):
    from . import llm
    out, usd = llm.chat(backend, SYSTEM, user, 16000); return out["items"], usd

def run(side, backend, unit):
    parent = unit.split("_")[0]
    P, caps, its = items(unit)
    head = f"Paper: {P.get('title') or parent}\n{structure_block(parent)}\n"
    jobs = []
    for i in range(0, len(its), CHUNK):
        part = its[i:i + CHUNK]; tabs = {t: caps[t] for t in {x.get("t") for x in part if x.get("t")}}
        jobs.append((part, head + "Table captions: " + json.dumps(tabs, ensure_ascii=False) + "\nItems:\n" + "\n".join(json.dumps(x, ensure_ascii=False) for x in part)))
    got, usd, fails = {}, 0.0, 0
    def one(j):
        try: return j[0], *call(backend, j[1])
        except Exception as e: return j[0], None, 0.0
    with cf.ThreadPoolExecutor(8 if backend == "qwen_local" else 4) as ex:
        for part, res, c in ex.map(one, jobs):
            usd += c
            if res is None: fails += 1; continue
            for x in res:
                if isinstance(x, dict): got[str(x.get("id"))] = x
    E = {"doc": unit, "extractor": __import__("epistemic.llm", fromlist=["B"]).B.get(backend, BACK.get(backend, (None, backend)))[1], "brief": "passR v4", "data": [], "not_data": [], "missed": []}
    nn = {c["id"]: len(c["numbers"]) for c in P["candidates"]}
    expanded = []
    for it in its:
        if it["id"].startswith("col:"):
            x = got.get(it["id"])
            for c in items.colmap.get(it["id"], []):
                if x is None: expanded.append({"id": c["id"]}); continue
                y = dict(x, id=c["id"], col_rule=True); got[c["id"]] = y; expanded.append({"id": c["id"]})
        else: expanded.append(it)
    its = expanded
    for it in its:
        x = got.get(it["id"])
        if x is None: E["missed"].append(it["id"]); continue
        roles = x.get("r") or []; dv = x.get("d")
        if roles and dv not in (0, False, "0"):
            roles = (list(roles) + [roles[-1]] * nn[it["id"]])[:nn[it["id"]]]
            E["data"].append({"id": it["id"], "roles": roles, "variable_id": x.get("v"), "group_id": x.get("g"), "reference_group_id": x.get("ref"),
                              "model_id": x.get("m"), "analysis_id": x.get("a"), "source": "this_study", **({"labelled_by": "column_rule"} if x.get("col_rule") else {})})
        else: E["not_data"].append({"id": it["id"], "reason": x.get("why") or "other"})
    p = f"ext/{unit}.{side}.json"; json.dump(E, open(p, "w"), indent=1)
    rep = {"unit": unit, "side": side, "backend": backend, "items": len(its), "data": len(E["data"]), "not_data": len(E["not_data"]), "missed": len(E["missed"]), "chunk_fail": fails, "usd": round(usd, 4)}
    store.append("passR", {**rep, "out_sha256": store.file_hash(p)})
    return rep

def run_laya(side, unit):
    """Second reader = Laya (local fine-tuned typed classifier): a role per number and an is-it-data answer per number.
    No wiring: links come from extractor A alone and are checked by Jev where the two readers disagree on roles."""
    from .laya_judge import Laya
    from . import typed
    P = json.load(open(f"parsed/{unit}.json")); T = table_index(P)
    back = Laya(host=os.environ.get("LAYA_URL", "http://127.0.0.1:8768"), model=os.environ.get("LAYA_MODEL", "epi4"), head_max_len=576, max_len=1024)
    help_ = typed.questions_for({"numbers": []})["is_datum"]["instructions"]
    cands = [c for c in P["candidates"] if c["numbers"] and not (c.get("prelabel") or {}).get("not_data") and c["kind"] != "figure_point"]
    def one(c):
        st = describe(P, c, T); st["numbers_in_order"] = [n.get("raw") for n in c["numbers"]]
        qs = typed.questions_for(c); Q = {f"role_{i}": qs[f"role_{i}"] for i in range(len(c["numbers"])) if f"role_{i}" in qs}
        Q["is_datum_0"] = {"type": "noul", "instructions": f"Number 1 of {len(c['numbers'])} in the highlighted text is {c['numbers'][0].get('raw')}. " + help_}
        import fcntl, time as _t, random as _r
        os.makedirs("work/locks", exist_ok=True)
        for attempt in range(6):
            fh = None
            try:
                while fh is None:
                    for i in range(int(open("work/laya_slots").read()) if os.path.exists("work/laya_slots") else int(os.environ.get("LAYA_SLOTS", "16"))):
                        f = open(f"work/locks/laya_{i}", "w")
                        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); fh = f; break
                        except OSError: f.close()
                    if fh is None: _t.sleep(0.2 + _r.random() * 0.3)
                return c, back.ask(st, Q)
            except Exception:
                _t.sleep(2 * (attempt + 1))
            finally:
                if fh: fcntl.flock(fh, fcntl.LOCK_UN); fh.close()
        return c, None
    E = {"doc": unit, "extractor": "laya:" + back.model, "brief": "passR v4 (laya reader: roles only)", "data": [], "not_data": [], "missed": [], "abstained": 0}
    PMIN = float(os.environ.get("LAYA_READER_P", "0.6"))   # below this Laya abstains (takes A's role), so only confident disagreements reach the judges
    A = {}
    if os.path.exists(f"ext/{unit}.A.json"):
        ea = json.load(open(f"ext/{unit}.A.json")); A = {d["id"]: d["roles"] for d in ea.get("data", [])}
    with cf.ThreadPoolExecutor(int(os.environ.get("LAYA_THREADS", "8"))) as ex:
        for c, a in ex.map(one, cands):
            if a is None: E["missed"].append(c["id"]); continue
            isd = (a.get("is_datum_0") or {}).get("answer", True)
            if isd:
                roles = []
                for i in range(len(c["numbers"])):
                    x = a.get(f"role_{i}") or {}
                    if (x.get("p") or 0) < PMIN and c["id"] in A and i < len(A[c["id"]]): roles.append(A[c["id"]][i]); E["abstained"] += 1
                    else: roles.append(x.get("answer") or "other")
                E["data"].append({"id": c["id"], "roles": roles,
                                  "role_p": [round((a.get(f"role_{i}") or {}).get("p") or 0, 3) for i in range(len(c["numbers"]))], "source": "this_study"})
            else: E["not_data"].append({"id": c["id"], "reason": "laya_not_datum"})
    p = f"ext/{unit}.{side}.json"; json.dump(E, open(p, "w"), indent=1)
    rep = {"unit": unit, "side": side, "backend": "laya", "items": len(cands), "data": len(E["data"]), "not_data": len(E["not_data"]), "missed": len(E["missed"]), "usd": 0.0}
    store.append("passR", {**rep, "out_sha256": store.file_hash(p)})
    return rep

if __name__ == "__main__":
    side, backend = sys.argv[1], sys.argv[2]
    for u in sys.argv[3:]: print(json.dumps(run_laya(side, u) if backend == "laya" else run(side, backend, u)), flush=True)
