"""Supplement parser v1: every retrieved supplementary file -> anchored candidates, same schema as parse.py.
Output parsed/<doc>_S.json, a pseudo-document (parent = doc), so extraction, adjudication and validation run unchanged.
Formats: docx (tables + paragraphs), doc/rtf/odt (-> docx via LibreOffice), xlsx/xls/ods/csv (each sheet a table),
pdf (pdf-parse, incl. dual read), zip (unpacked, recursed). Images are left for the vision route (figs.py) and listed.
Anchors: {supp: file, table, row, col} for cells, {supp: file, section, start, end} for text. Merged cells -> span_copy_of.
Every source file is recorded with sha256 and a status (parsed / image / skipped:<why> / failed:<why>)."""
import sys, os, re, json, glob, zipfile, hashlib, pathlib, subprocess, tempfile, shutil
from .parse import numbers_in, SPAN_RE, CODE, prelabel, join_thousands
from . import store, bundle
VERSION = "supp-parse v1.1"
IMG = {"jpg", "jpeg", "png", "gif", "tif", "tiff", "bmp", "eps"}
SKIP = {"mp4", "avi", "mov", "mp3", "wav", "xml", "nxml", "html", "htm", "css", "js"}
BULK = 20000   # numbers in one source file above which it is flagged bulk (parsed, but routed to rules/Laya, not LLM extraction)

def soffice(src, fmt, outdir):
    subprocess.run(["soffice", "--headless", "--convert-to", fmt, "--outdir", outdir, src], capture_output=True, timeout=300)
    p = pathlib.Path(outdir) / (pathlib.Path(src).stem + "." + fmt.split(":")[0])
    return str(p) if p.exists() else None

def norm(s): return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()

def docx_read(path):
    import docx
    d = docx.Document(path); tables, paras = [], [norm(p.text) for p in d.paragraphs if norm(p.text)]
    for tb in d.tables:
        rows, seen = [], {}
        for ri, r in enumerate(tb.rows):
            cells, cp = [], []
            for ci, c in enumerate(r.cells):
                k = id(c._tc)
                cells.append(norm(c.text)); cp.append(seen.get(k)); seen.setdefault(k, [ri, ci])
            rows.append({"cells": cells, "copy_of": cp, "is_head": ri == 0})
        tables.append({"caption": "", "rows": rows})
    return tables, paras

def sheet_read(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=False, data_only=True); tables = []
    for ws in wb.worksheets:
        merged = {}
        for mr in ws.merged_cells.ranges:
            for r in range(mr.min_row, mr.max_row + 1):
                for c in range(mr.min_col, mr.max_col + 1):
                    if (r, c) != (mr.min_row, mr.min_col): merged[(r, c)] = [mr.min_row - 1, mr.min_col - 1]
        rows = []
        for ri, r in enumerate(ws.iter_rows(values_only=True), 1):
            vals = ["" if v is None else (repr(v) if isinstance(v, float) and v != v else str(v)) for v in r]
            if not any(vals): continue
            rows.append({"cells": [norm(v) for v in vals], "copy_of": [merged.get((ri, ci)) for ci in range(1, len(vals) + 1)], "is_head": not rows})
        if rows: tables.append({"caption": f"sheet {ws.title}", "rows": rows})
    return tables, []

def csv_read(path):
    import csv
    rows = [{"cells": [norm(x) for x in r], "copy_of": [None] * len(r), "is_head": i == 0} for i, r in enumerate(csv.reader(open(path, errors="replace")))]
    return [{"caption": "", "rows": rows}], []

class Doc:
    def __init__(s, doc):
        s.D = {"doc": doc + "_S", "parent": doc, "parser": VERSION, "title": "", "sections": [], "tables": [], "figures": [],
               "supplements": [], "candidates": [], "sources": [], "images": []}; s.n = 0
    def add(s, kind, text, anchor, ctx=None, nums=None):
        nums = nums if nums is not None else numbers_in(text)
        if not nums: return 0
        s.n += 1
        s.D["candidates"].append({"id": f"{s.D['parent']}:x{s.n}", "kind": kind, "text": text, "anchor": anchor, "numbers": nums, "local_context": ctx})
        return len(nums)
    def tables(s, f, tables):
        k = 0
        for tb in tables:
            tid = f"sT{len(s.D['tables']) + 1}"
            s.D["tables"].append({"id": tid, "supp": f, "caption": tb["caption"], "footnotes": "", "rows": tb["rows"]})
            if tb["caption"]: k += s.add("table_caption", tb["caption"], {"supp": f, "table": tid, "part": "caption"})
            for ri, r in enumerate(tb["rows"]):
                for ci, cell in enumerate(r["cells"]):
                    if not cell: continue
                    kind = "table_header" if r["is_head"] else ("row_label" if ci == 0 else "table_cell")
                    anc = {"supp": f, "table": tid, "row": ri, "col": ci}
                    if r["copy_of"][ci]: anc["span_copy_of"] = r["copy_of"][ci]
                    k += s.add(kind, join_thousands(cell), anc)
        return k
    def text(s, f, paras):
        k = 0
        sid = f"sS{len(s.D['sections']) + 1}"; body = " ".join(paras)
        s.D["sections"].append({"id": sid, "supp": f, "title": f, "text": body})
        for m in SPAN_RE.finditer(body):
            if not re.search(r"\d", m.group(0)) or any(c.start() <= m.start() < c.end() for c in CODE.finditer(body)): continue
            k += s.add("text_span", m.group(0), {"supp": f, "section": sid, "start": m.start(), "end": m.end()}, body[max(0, m.start() - 180):m.end() + 180])
        return k
    def pdf(s, f, path):
        from .parse_pdf import parse as pparse
        P = pparse(path); k = 0; tmap = {}
        for t in P["tables"]:
            tid = f"sT{len(s.D['tables']) + 1}"; tmap[t["id"]] = tid; s.D["tables"].append(dict(t, id=tid, supp=f))
        for c in P["candidates"]:
            s.n += 1; a = dict(c["anchor"], supp=f)
            if "table" in a: a["table"] = tmap.get(a["table"], a["table"])
            s.D["candidates"].append(dict(c, id=f"{s.D['parent']}:x{s.n}", anchor=a)); k += len(c["numbers"])
        return k

def handle(S, path, rel, tmp):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    src = {"file": rel, "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(), "ext": ext}
    try:
        if ext in IMG: S.D["images"].append(rel); src["status"] = "image"
        elif ext in SKIP: src["status"] = f"skipped:{ext}"
        elif ext == "zip":
            zd = pathlib.Path(path).parent / ("_unzipped_" + pathlib.Path(rel.split("!")[-1]).stem); zipfile.ZipFile(path).extractall(zd); src["status"] = "unzipped"   # kept, so crops can be rendered later
            S.D["sources"].append(src)
            for p in sorted(zd.rglob("*")):
                if p.is_file(): handle(S, str(p), rel + "!" + str(p.relative_to(zd)), tmp)
            return
        else:
            if ext in ("doc", "rtf", "odt", "wpd"): path = soffice(path, "docx", tmp); ext = "docx"
            elif ext in ("xls", "ods"): path = soffice(path, "xlsx", tmp); ext = "xlsx"
            if not path: raise RuntimeError("conversion failed")
            if ext == "docx": t, p = docx_read(path); k = S.tables(rel, t) + (S.text(rel, p) if p else 0)
            elif ext in ("xlsx", "xlsm"): t, _ = sheet_read(path); k = S.tables(rel, t)
            elif ext in ("csv", "tsv", "txt"): t, _ = csv_read(path); k = S.tables(rel, t)
            elif ext == "pdf": k = S.pdf(rel, path)
            else: raise RuntimeError(f"unknown format {ext}")
            src["status"] = "parsed"; src["numbers"] = k; src["bulk"] = k > BULK
    except Exception as e:
        src["status"] = f"failed:{str(e)[:160]}"
    S.D["sources"].append(src)

def run(doc):
    M = bundle.fetch(doc); g = bundle.match(M)
    figfiles = {x for f in g["figures"] for x in f["files"]} | {x for t in g["image_tables"] for x in t["files"]}
    suppfiles = {x for s_ in g["supplements"] for x in s_["files"]}
    S = Doc(doc)
    with tempfile.TemporaryDirectory() as tmp:
        for f in M["files"]:
            if f["file"] in figfiles: continue   # figures and image tables belong to the vision route
            ext = f["file"].rsplit(".", 1)[-1].lower()
            if ext in IMG and f["file"] not in suppfiles:   # inline formulas, thumbnails, logos: not data objects
                S.D["sources"].append({"file": f["file"], "sha256": f["sha256"], "ext": ext, "status": "skipped:inline_or_unlisted_image"}); continue
            handle(S, f"bundles/{doc}/{f['file']}", f["file"], tmp)
    prelabel(S.D)
    out = f"parsed/{doc}_S.json"
    if not S.D["candidates"] and not S.D["images"]:
        rep = {"doc": doc, "sources": len(S.D["sources"]), "candidates": 0}
    else:
        json.dump(S.D, open(out, "w"))
        rep = {"doc": doc, "sources": len(S.D["sources"]), "candidates": len(S.D["candidates"]),
               "numbers": sum(len(c["numbers"]) for c in S.D["candidates"]), "images": len(S.D["images"]),
               "failed": [s["file"] for s in S.D["sources"] if s["status"].startswith("failed")],
               "bulk": [s["file"] for s in S.D["sources"] if s.get("bulk")]}
        store.append("parse_supp", {"doc": doc, "parser": VERSION, "out_sha256": store.file_hash(out), **{k: rep[k] for k in ("candidates", "numbers", "failed", "bulk")}})
    return rep

if __name__ == "__main__":
    docs = sorted(pathlib.Path(p).stem for p in glob.glob("raw/*.xml")) if sys.argv[1:] == ["--all"] else sys.argv[1:]
    for d in docs: print(json.dumps(run(d)), flush=True)
