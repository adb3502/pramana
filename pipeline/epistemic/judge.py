"""Judging ladder v1 for one document unit (<doc>, <doc>_S, <doc>_F):
  1. extractor disputes -> Jev (typed judge); a Jev answer equal to A or B settles it (adjudicator jev)
  2. Jev sided with neither -> Sonnet with the item's context; Sonnet picking A or B settles it, else -> Opus (final)
  3. figure numbers whose vision read and OCR disagree (needs_check) -> a second vision read of that item by Sonnet;
     confirmed exactly -> check_resolved, otherwise the number stays out of data/
Writes ext/<unit>.adj.json (validate's format), re-runs validate, ledgers every step.
Usage: python -m epistemic.judge UNIT...   env LADDER_TOP=opus|sonnet"""
import os, sys, json
from . import verify, validate, store, llm
from .context import describe, table_index
TOP = os.environ.get("LADDER_TOP", "sonnet")
ASK = ('You settle a disagreement between two extractors about the role of one number in a scientific paper. '
       'Choose the correct role from the vocabulary (it may be A, B or another role), or "not_data". '
       'Return JSON: {"role": "<role or not_data>", "why": "<one sentence>"}')

ASKB = ('You settle disagreements between two extractors about the role of numbers in a scientific paper. For each item choose the correct role '
        '(it may be A, B or another role from the same vocabulary) or "not_data". Return JSON {"items": [{"i": <i>, "role": "...", "why": "<short>"}]}, one per item.')

def ctx_of(P, T, cid):
    c = next(x for x in P["candidates"] if x["id"] == cid); x = describe(P, c, T) if "row" in c["anchor"] else {}
    return {"text": c["text"], "numbers": [n.get("raw") for n in c["numbers"]], "anchor": c["anchor"], "context": (c.get("local_context") or "")[:800],
            "table_caption": x.get("table_caption"), "column_header": x.get("column_header"), "row_label": x.get("row_label")}

def run(unit):
    if not os.path.exists(f"ext/{unit}.A.json"): return {"unit": unit, "skipped": "not labelled"}
    rows = [json.loads(l) for l in open(f"data/{unit}.jsonl")] if os.path.exists(f"data/{unit}.jsonl") else []
    disp = [r for r in rows if r.get("needs_adjudication") and not r.get("adjudicated")]
    old = json.load(open(f"ext/{unit}.adj.json")) if os.path.exists(f"ext/{unit}.adj.json") else {"doc": unit, "decisions": []}
    have = {d["datum_id"] for d in old["decisions"]}; dec = list(old["decisions"]); usd = 0.0; esc = []
    if disp and os.path.exists("work/no_jev"):   # Jev is paid from personal credit: reserved for benchmarking Laya, not the live ladder
        esc = [(r, None) for r in disp if r["datum_id"] not in have]
    elif disp:
        verify.run(unit, "jev", only_disputed=True)
        V = json.load(open(f"verification/{unit}.jev.json")); tb = {t["datum"]: t for t in V["report"]["tie_breaks"]}
        for r in disp:
            if r["datum_id"] in have: continue
            t = tb.get(r["datum_id"], {})
            if t.get("verdict") in ("A", "B"):
                dec.append({"datum_id": r["datum_id"], "A": r["role_A"], "B": r["role_B"], "jev": t.get("judge"), "choice": t["verdict"], "role": t["judge"], "not_data": False, "adjudicator": "jev"})
            else: esc.append((r, t.get("judge")))
    if esc:   # batched: up to 30 disputes per call; Sonnet first, the top model only for items Sonnet resolved to neither extractor
        P = json.load(open(f"parsed/{unit}.json")); T = table_index(P)
        items = []
        for r, j in esc:
            item = ctx_of(P, T, r["candidate"]); i = int(r["datum_id"].rsplit("#", 1)[1])
            items.append((r, j, {"number_index": i, "number": item["numbers"][i] if i < len(item["numbers"]) else None, "A": r["role_A"], "B": r["role_B"], "third_opinion": j,
                                 "text": item["text"][:200], "context": (item["context"] or "")[:500], "table_caption": (item.get("table_caption") or "")[:200],
                                 "column_header": item.get("column_header"), "row_label": item.get("row_label")}))
        levels = ["sonnet"] + ([TOP] if TOP not in ("sonnet", "none") else [])
        pending = items
        for lvl in levels:
            nxt = []
            for k in range(0, len(pending), 30):
                part = pending[k:k + 30]
                q = json.dumps([dict(x[2], i=n) for n, x in enumerate(part)], ensure_ascii=False)
                try: out, c = llm.chat(lvl, ASKB, q, 6000); usd += c
                except Exception: out = {}
                got = {int(x.get("i", -1)): x for x in (out.get("items") or []) if isinstance(x, dict)}
                for n, (r, j, _) in enumerate(part):
                    role = (got.get(n) or {}).get("role")
                    if role is None or (role not in (r["role_A"], r["role_B"]) and lvl != levels[-1]): nxt.append(part[n]); continue
                    dec.append({"datum_id": r["datum_id"], "A": r["role_A"], "B": r["role_B"], "jev": j, "choice": "A" if role == r["role_A"] else "B" if role == r["role_B"] else "other",
                                "role": None if role == "not_data" else role, "not_data": role == "not_data", "why": (got.get(n) or {}).get("why"), "adjudicator": f"claude:{lvl}"})
            pending = nxt
    gated = gate_flags(unit, dec, have)
    usd += gated.pop("usd", 0.0)
    json.dump({"doc": unit, "adjudicator": "ladder v1", "n": len(dec), "decisions": dec}, open(f"ext/{unit}.adj.json", "w"), indent=1)
    checks = resolve_reads(unit) if unit.endswith("_F") else resolve_pdf_reads(unit) if unit.endswith("_S") else {}
    try: validate.run(unit, ".", None, write_data=True)
    except ZeroDivisionError: pass   # unit with no labelled numbers
    rep = {"unit": unit, **gated, "disputes": len(disp), "by_jev": sum(1 for d in dec if d.get("adjudicator") == "jev"), "escalated": len(esc), "usd_claude": round(usd, 4), **checks}
    store.append("judge_ladder", rep)
    return rep

def resolve_reads(unit):
    from .figs import img_b64, best
    P = json.load(open(f"parsed/{unit}.json")); parent = unit[:-2]; usd = 0.0; ok = bad = 0
    src = {s["id"]: s.get("file") for s in P.get("sources", []) if s.get("status") == "read"}
    for c in P["candidates"]:
        if not c.get("needs_check") or c.get("check_resolved"): continue
        f = src.get(c["anchor"].get("figure"))
        if not f: continue
        data, _ = img_b64(f"bundles/{parent}/{f}")
        a = c["anchor"]; label = " / ".join(x for x in (a.get("panel"), a.get("row_label"), a.get("column_label"), a.get("series")) if x)
        out, u = llm.chat("sonnet", 'Read one value from the figure. Return JSON {"printed": "<exact characters printed, or NONE>"}',
                          f"Find the value printed for: {label or c['text']}. A previous read said: {c['text']}", 1000, image_png_b64=data); usd += u
        if str(out.get("printed", "")).replace(" ", "") == c["text"].replace(" ", ""): c["check_resolved"] = True; c["needs_check"] = False; ok += 1
        else: c["read_variants"] = [c["text"], out.get("printed")]; bad += 1
    json.dump(P, open(f"parsed/{unit}.json", "w"))
    return {"reads_confirmed": ok, "reads_still_open": bad, "usd_reads": round(usd, 4)}

def gate_flags(unit, dec, have):
    """Laya flags on agreed rows: Jev looks; Jev with the extractors -> agreed role stands; Jev with Laya -> Sonnet decides."""
    p = f"ext/{unit}.laya.json"
    if not os.path.exists(p): return {"laya_flags": 0}
    from . import typed
    F = [f for f in json.load(open(p))["flags"] if f["datum_id"] not in have]
    if not F: return {"laya_flags": 0}
    P = json.load(open(f"parsed/{unit}.json")); T = table_index(P)
    nojev = os.path.exists("work/no_jev")   # without Jev, only the most confident Laya flags go to Sonnet
    J = {} if nojev else typed.judge(P, typed.Jev(), ids={f["candidate"] for f in F}, workers=4)
    kept = overturned = 0; usd = 0.0
    for f in F:
        i = int(f["datum_id"].rsplit("#", 1)[1])
        j = (f["laya"] if f.get("p", 0) >= float(os.environ.get("LAYA_FLAG_P_NOJEV", "0.97")) else None) if nojev else (J.get(f["candidate"], {}).get(f"role_{i}") or {}).get("answer")
        if j != f["laya"]: kept += 1; continue
        item = ctx_of(P, T, f["candidate"])
        q = json.dumps({"number_index": i, "number": item["numbers"][i] if i < len(item["numbers"]) else None, "A": f["agreed"], "B": f["laya"],
                        "note": "two extractors agreed on A; two independent judges say B", **item}, ensure_ascii=False)
        out, c = llm.chat("sonnet", ASK, q, 2000); usd += c; role = out.get("role")
        if role != f["agreed"]:
            overturned += 1
            dec.append({"datum_id": f["datum_id"], "A": f["agreed"], "B": f["agreed"], "laya": f["laya"], "jev": j, "choice": "other",
                        "role": None if role == "not_data" else role, "not_data": role == "not_data", "why": out.get("why"), "adjudicator": "claude:sonnet (laya gate)"})
        else: kept += 1
    return {"laya_flags": len(F), "laya_kept": kept, "laya_overturned": overturned, "usd": usd}

def supp_path(parent, rel):
    parts = rel.split("!"); p = f"bundles/{parent}/{parts[0]}"
    for inner in parts[1:]: p = f"bundles/{parent}/_unzipped_{os.path.splitext(os.path.basename(parts[0]))[0]}/{inner}"
    return p

def resolve_pdf_reads(unit):
    """needs_check numbers in supplement PDFs: render the bbox (with margin) at 300 dpi and ask Sonnet to read it."""
    import base64, pymupdf
    P = json.load(open(f"parsed/{unit}.json")); parent = unit[:-2]; usd = 0.0; ok = bad = 0
    for c in P["candidates"]:
        a = c["anchor"]
        if not c.get("needs_check") or c.get("check_resolved") or "bbox" not in a: continue
        path = supp_path(parent, a["supp"])
        if not os.path.exists(path): continue
        doc = pymupdf.open(path); pg = doc[a["page"] - 1]; x0, y0, x1, y1 = a["bbox"]
        pix = pg.get_pixmap(dpi=300, clip=pymupdf.Rect(x0 - 40, y0 - 12, x1 + 40, y1 + 12))
        data = base64.b64encode(pix.tobytes("png")).decode()
        out, u = llm.chat("sonnet", 'Read the text in the centre of this crop of a table cell. Return JSON {"printed": "<exact characters>"}', f"Competing reads: {c.get('read_variants') or c['text']}", 500, image_png_b64=data); usd += u
        if str(out.get("printed", "")).replace(" ", "") == c["text"].replace(" ", ""): c["check_resolved"] = True; c["needs_check"] = False; ok += 1
        else: c["read_variants"] = (c.get("read_variants") or [c["text"]]) + [out.get("printed")]; bad += 1
    json.dump(P, open(f"parsed/{unit}.json", "w"))
    return {"reads_confirmed": ok, "reads_still_open": bad, "usd_reads": round(usd, 4)}

if __name__ == "__main__":
    for u in sys.argv[1:]: print(json.dumps(run(u)), flush=True)
