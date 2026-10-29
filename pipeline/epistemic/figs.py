"""Figure route v1: every figure, image table and image supplement -> typed reading with anchored candidates.
Output parsed/<doc>_F.json (pseudo-document, parent = doc), so extraction/adjudication/validation run unchanged.
Read 1: a vision model (default Haiku 5.5) types the figure and transcribes every printed number with its row/column/series
labels, transcribes image tables cell by cell, and digitizes plotted points of curves and bars (as estimates).
Read 2 (independent): RapidOCR over the same image. A printed number is read_agree only if OCR finds the same value;
otherwise needs_check=True and it stays out of data/ until adjudicated, like pdf-parse. Digitized points are never data
on their own: kind figure_point, trust 'digitized_estimate', for the weighting layer to treat as such.
Usage: python -m epistemic.figs PMC... | --all   [env FIG_MODEL]"""
import sys, os, io, re, json, glob, base64, time, hashlib, pathlib, requests
from PIL import Image
from .parse import numbers_in, prelabel, join_thousands
from . import store, bundle
VERSION = "fig-read v1.1"
MODEL = os.environ.get("FIG_MODEL", "claude-haiku-5-5"); PIN, POUT = (0.10, 0.50) if "haiku" in MODEL else (2.0, 10.0)
TYPES = ["forest_plot", "survival_curve", "dose_response_curve", "line_plot", "bar_chart", "scatter_plot", "box_plot",
         "flow_diagram", "table_image", "funnel_plot", "causal_diagram", "map", "photo_or_micrograph", "schematic", "other"]
PROMPT = """You are transcribing a figure from a scientific paper so that its data can be used without the image.
Caption (from the paper): {caption}

Return JSON only:
{{"type": one of {types},
 "panels": [{{"panel": "A" or "", "title": str, "x_axis": {{"label": str, "unit": str, "min": num, "max": num, "scale": "linear|log"}}, "y_axis": {{...same}}}}],
 "printed": [{{"text": the exact characters printed, "panel": str, "row_label": str, "column_label": str, "series": str}}],
 "table": [[cell text, ...], ...] (only when the image is a table: every row, every cell, header rows first, exactly as printed; "" for empty cells),
 "points": [{{"panel": str, "series": str, "x": num, "y": num, "y_low": num|null, "y_high": num|null}}],
 "notes": str}}

Rules: transcribe every number printed in the image (axis tick labels excluded, but numbers-at-risk tables, effect sizes, CIs, p values, n, counts in flow-diagram boxes, bar labels, legend numbers included), each as its own entry with the labels that tell what it is. Copy characters exactly; never compute or round.
"points": for curves, bars and point estimates whose values are NOT printed, read them off the axes (bars: top of the bar; survival curves: the curve at each labelled x tick; dose-response: each marker or, if none, every x tick). Leave points empty when every value is printed. Never invent a series that is not drawn."""

def img_b64(path, maxside=1568):
    im = Image.open(path); im.seek(0); im = im.convert("RGB")
    if max(im.size) > maxside: im.thumbnail((maxside, maxside))
    b = io.BytesIO(); im.save(b, "PNG"); return base64.b64encode(b.getvalue()).decode(), im.size

def ask(path, caption):
    from . import llm
    data, size = img_b64(path)
    out, usd = llm.chat({"claude-haiku-5-5": "haiku", "claude-sonnet-5-5": "sonnet"}.get(MODEL, "haiku"), "", PROMPT.format(caption=caption[:3000] or "(none)", types=TYPES), 16000, image_png_b64=data)
    return out, usd, None

_ocr = None
def ocr_values(path):
    """Read 2: every numeric token RapidOCR sees, as (value, qualifier) keys."""
    global _ocr
    if _ocr is None:
        from rapidocr import RapidOCR; _ocr = RapidOCR()
    im = Image.open(path); im.seek(0); im = im.convert("RGB")
    if max(im.size) < 1200: im = im.resize((im.size[0] * 2, im.size[1] * 2))
    p = f"/tmp/ocr_{os.getpid()}.png"; im.save(p)
    res = _ocr(p); txts = list(getattr(res, "txts", None) or [])
    keys = set()
    for t in txts:
        for n in numbers_in(t.replace("·", ".")): keys.add(round(n["value"], 6))
    return keys, txts

class Fig:
    def __init__(s, doc):
        s.D = {"doc": doc + "_F", "parent": doc, "parser": VERSION, "model": MODEL, "title": "", "sections": [], "tables": [],
               "figures": [], "supplements": [], "candidates": [], "sources": []}; s.n = 0
    def add(s, kind, text, anchor, ctx=None, nums=None, ocr=None, extra=None):
        nums = nums if nums is not None else numbers_in(join_thousands(text))
        if not nums: return
        if ocr is not None:
            for x in nums: x["read_agree"] = round(x["value"], 6) in ocr if x["value"] is not None else True
        s.n += 1
        c = {"id": f"{s.D['parent']}:f{s.n}", "kind": kind, "text": text, "anchor": anchor, "numbers": nums, "local_context": ctx}
        if ocr is not None and any(not x["read_agree"] for x in nums): c["needs_check"] = True
        if extra: c.update(extra)
        s.D["candidates"].append(c)

def read_one(F, obj_kind, oid, path, caption):
    out, usd, stop = ask(path, caption)
    ocr, txts = ocr_values(path)
    rec = {"id": oid, "object": obj_kind, "file": path.rsplit("/", 1)[-1], "caption": caption, "type": out.get("type"),
           "panels": out.get("panels"), "notes": out.get("notes"), "usd": round(usd, 5), "stop": stop, "ocr_tokens": len(txts)}
    F.D["figures"].append(rec)
    ctx = f"{obj_kind} {oid}: {caption[:600]}"
    for p in out.get("printed") or []:
        F.add("figure_text", str(p.get("text", "")), {"figure": oid, "panel": p.get("panel", ""), "row_label": p.get("row_label", ""),
              "column_label": p.get("column_label", ""), "series": p.get("series", "")}, ctx, ocr=ocr)
    tb = out.get("table") or []
    if tb:
        tid = f"fT{len(F.D['tables']) + 1}"
        rows = [{"cells": [str(c) for c in r], "copy_of": [None] * len(r), "is_head": i == 0} for i, r in enumerate(tb)]
        F.D["tables"].append({"id": tid, "figure": oid, "caption": caption, "footnotes": "", "rows": rows})
        for ri, r in enumerate(rows):
            for ci, cell in enumerate(r["cells"]):
                if not cell: continue
                kind = "table_header" if r["is_head"] else ("row_label" if ci == 0 else "table_cell")
                F.add(kind, cell, {"figure": oid, "table": tid, "row": ri, "col": ci}, ocr=ocr)
    plot = out.get("type") in ("survival_curve", "dose_response_curve", "line_plot", "bar_chart", "scatter_plot", "box_plot", "forest_plot", "funnel_plot", "other")
    for p in (out.get("points") or []) if plot else []:   # no digitizing of schematics, photos, maps, diagrams
        vals = [("x", p.get("x")), ("y", p.get("y")), ("y_low", p.get("y_low")), ("y_high", p.get("y_high"))]
        nums = [{"value": float(v), "qualifier": None, "raw": f"{k}={v}", "role_hint": k} for k, v in vals if isinstance(v, (int, float))]
        F.add("figure_point", json.dumps(p), {"figure": oid, "panel": p.get("panel", ""), "series": p.get("series", "")}, ctx, nums=nums,
              extra={"trust": "digitized_estimate", "prelabel_hint": "digitized"})
    return usd

def best(doc, files):
    """Highest-resolution file among the ones that match an object (Europe PMC ships jpg and gif copies)."""
    fs = [f"bundles/{doc}/{f}" for f in files if os.path.exists(f"bundles/{doc}/{f}")]
    def px(p):
        try: im = Image.open(p); return im.size[0] * im.size[1]
        except Exception: return -1
    fs = [p for p in fs if px(p) > 0]
    return max(fs, key=px) if fs else None

def run(doc, budget=None):
    M = bundle.fetch(doc); g = bundle.match(M)
    caps = {}
    try:
        P = json.load(open(f"parsed/{doc}.json"))
        caps = {f["id"]: f["caption"] for f in P.get("figures", [])} | {t["id"]: t["caption"] for t in P.get("tables", [])}
    except FileNotFoundError: pass
    jobs = [("figure", f["id"], f["files"]) for f in g["figures"]] + [("image_table", t["id"], t["files"]) for t in g["image_tables"]]
    try:
        S = json.load(open(f"parsed/{doc}_S.json")); jobs += [("supplement_image", f"simg{i + 1}", [im]) for i, im in enumerate(S.get("images", []))]
    except FileNotFoundError: pass
    F = Fig(doc); usd = 0.0
    for kind, oid, files in jobs:
        p = best(doc, [f.split("!")[-1] if "!" not in f else f for f in files])
        if not p: F.D["sources"].append({"object": kind, "id": oid, "status": "no_file"}); continue
        try:
            usd += read_one(F, kind, oid, p, caps.get(oid, "")); F.D["sources"].append({"object": kind, "id": oid, "file": p.rsplit("/", 1)[-1], "sha256": store.file_hash(p), "status": "read"})
        except Exception as e:
            F.D["sources"].append({"object": kind, "id": oid, "status": f"failed:{str(e)[:160]}"})
    prelabel(F.D)
    out = f"parsed/{doc}_F.json"; json.dump(F.D, open(out, "w"))
    nc = sum(1 for c in F.D["candidates"] if c.get("needs_check"))
    rep = {"doc": doc, "objects": len(jobs), "read": sum(1 for s in F.D["sources"] if s["status"] == "read"),
           "types": {}, "candidates": len(F.D["candidates"]), "needs_check": nc,
           "points": sum(1 for c in F.D["candidates"] if c["kind"] == "figure_point"), "usd": round(usd, 4),
           "failed": [s["id"] for s in F.D["sources"] if s["status"].startswith("failed") or s["status"] == "no_file"]}
    for f in F.D["figures"]: rep["types"][f["type"]] = rep["types"].get(f["type"], 0) + 1
    store.append("parse_fig", {"doc": doc, "parser": VERSION, "model": MODEL, "out_sha256": store.file_hash(out), **{k: rep[k] for k in ("objects", "read", "candidates", "needs_check", "usd", "failed")}})
    return rep

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    docs = sorted(pathlib.Path(p).stem for p in glob.glob("raw/*.xml")) if "--all" in sys.argv else args
    for d in docs:
        if os.path.exists(f"parsed/{d}_F.json") and "--force" not in sys.argv: continue
        print(json.dumps(run(d)), flush=True)
