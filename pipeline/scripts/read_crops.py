"""Adjudicate PDF dual-read disagreements against rendered crops.
  make DOC        render a crop for every needs_check candidate in parsed_pdf/DOC.json into work/crops/DOC_<k>.png
                  (up to 8 crops per sheet, numbered) with a sidecar .txt listing the competing reads.
  apply DOC FILE  FILE = {cid: {"choice": "docling"|"pymupdf"|"ocr"|"none", "note": ...}} written by the adjudicator.
                  The chosen read replaces the candidate's numbers (the docling read is kept as numbers_docling);
                  "none" keeps needs_check (no read is right; the number never enters data/).
                  Writes parsed/DOC.json (the version the extraction pipeline reads) and a ledger event.
No number is typed here: a choice selects one of the parser's own reads.
"""
import sys, os, json, re, pathlib, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymupdf
from PIL import Image, ImageDraw, ImageFont

def span_rect(page, c):
    """A strip around the text-span's line inside its paragraph boxes, else the anchor bbox."""
    a = c["anchor"]; boxes = [(a["page"], a["bbox"])] + [(x["page"], x["bbox"]) for x in a.get("more_boxes", [])]
    if c["kind"] != "text_span":
        return a["page"], pymupdf.Rect(a["bbox"]) + (-8, -8, 8, 8)
    raws = [next((x["raw"] for x in c["numbers"] if not x.get("read_agree")), c["numbers"][0]["raw"])]
    raws += [x["raw"] for v in c.get("read_variants", {}).values() for x in v[:1]]
    para = c.get("_ptxt") or ""
    nth = para[:a["start"]].count(core) if para else 0
    hits = []
    for raw in raws:
      core = re.sub(r"[^\d.]", "", raw.split()[-1]) or raw
      if hits: break
      for pg, bb in boxes:
        R = pymupdf.Rect(bb)
        for w in page.parent[pg - 1].get_text("words"):
            r = pymupdf.Rect(w[:4])
            if R.contains(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)) and core.split(".")[0] in re.sub(r"[-–·]", ".", w[4]):
                hits.append((pg, r, R))
    if not hits: return a["page"], pymupdf.Rect(a["bbox"]) + (-3, -3, 3, 3)
    pg, r, R = hits[min(nth, len(hits) - 1)]
    if r.height > r.width * 1.5:   # sideways text: the line runs vertically
        return pg, pymupdf.Rect(r.x0 - 4, R.y0 - 3, r.x1 + 4, R.y1 + 3)
    return pg, pymupdf.Rect(R.x0 - 3, r.y0 - 4, R.x1 + 3, r.y1 + 4)

def make(doc):
    D = json.load(open(f"parsed_pdf/{doc}.json")); pdf = pymupdf.open(f"raw_pdf/{doc}.pdf")
    from epistemic.parse_pdf import page_dirs, dir_of
    dirs = page_dirs(pdf)
    paras = {}
    for c in D["candidates"]:
        if c["kind"] == "text_span": paras.setdefault((c["anchor"]["section"], c["anchor"]["para"]), []).append(c)
    nc = [c for c in D["candidates"] if c.get("needs_check")]
    if os.environ.get("ONLY"): keep = set(open(os.environ["ONLY"]).read().split()); nc = [c for c in nc if c["id"] in keep]
    out = pathlib.Path("work/crops"); out.mkdir(parents=True, exist_ok=True)
    for f in out.glob(f"{doc}_*.*"): f.unlink()
    font = ImageFont.load_default(size=22)
    import numpy as np, logging
    logging.getLogger("RapidOCR").setLevel(logging.ERROR)
    from rapidocr import RapidOCR
    from epistemic.parse_pdf import fix, _ocr_norm
    from epistemic.parse import numbers_in
    eng = RapidOCR(); crop_var = {}
    for s in range(0, len(nc), 8):
        tiles, lines = [], []
        for k, c in enumerate(nc[s:s + 8], start=s):
            pg, r = span_rect(pdf[0], c)
            page = pdf[pg - 1]
            rot = dir_of(dirs[pg - 1], r) or 0           # text direction in unrotated page space
            r = r * page.rotation_matrix; r.normalize()  # anchors are unrotated coords; clip wants display coords
            r = r & page.rect
            pix = page.get_pixmap(dpi=220, clip=r)
            im = Image.frombytes("RGB", (pix.w, pix.h), pix.samples)
            extra = (rot - page.rotation) % 360
            if extra: im = im.rotate(-extra, expand=True)   # derotate sideways pages (text reads bottom-to-top)
            if im.width > 1500: im = im.resize((1500, int(im.height * 1500 / im.width)))
            tiles.append((k, im))
            tight = (pymupdf.Rect(c["anchor"]["bbox"]) + (-4, -2, 4, 2)) if c["kind"] != "text_span" else None
            if tight is not None: tight = tight * page.rotation_matrix; tight.normalize(); tight = tight & page.rect
            big = page.get_pixmap(dpi=400, clip=tight if tight is not None else r); bim = Image.frombytes("RGB", (big.w, big.h), big.samples)
            if extra: bim = bim.rotate(-extra, expand=True)
            res = eng(np.asarray(bim)); otxt = " ".join(res.txts or [])
            crop_var[c["id"]] = {"text": otxt, "numbers": numbers_in(fix(_ocr_norm(otxt)))}
            v = {src: [x["raw"] for x in ns] for src, ns in c.get("read_variants", {}).items()}
            v["ocr_crop"] = [x["raw"] for x in crop_var[c["id"]]["numbers"]]
            lines.append(f"[{k}] {c['id']} {c['kind']} p{pg} docling={[x['raw'] for x in c['numbers']]} " +
                         " ".join(f"{src}={vv}" for src, vv in v.items()) + f" | text: {c['text'][:90]!r}")
        W = max(im.width for _, im in tiles) + 60; H = sum(im.height + 16 for _, im in tiles)
        sheet = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(sheet); y = 0
        for k, im in tiles:
            d.text((4, y + 4), str(k), fill="red", font=font); sheet.paste(im, (56, y)); y += im.height + 8
            d.line([(0, y + 3), (W, y + 3)], fill="gray"); y += 8
        n = s // 8
        sheet.save(out / f"{doc}_{n:02d}.png"); open(out / f"{doc}_{n:02d}.txt", "w").write("\n".join(lines) + "\n")
    old = json.load(open(out / f"{doc}.crop_variants.json")) if (out / f"{doc}.crop_variants.json").exists() else {}
    old.update(crop_var); json.dump(old, open(out / f"{doc}.crop_variants.json", "w"), indent=1)
    print(doc, "needs_check", len(nc), "sheets", (len(nc) + 7) // 8)

def apply(doc, fpath):
    from epistemic import store
    D = json.load(open(f"parsed_pdf/{doc}.json")); dec = json.load(open(fpath))
    cvp = pathlib.Path(f"work/crops/{doc}.crop_variants.json"); cv = json.load(open(cvp)) if cvp.exists() else {}
    stats = {}
    for c in D["candidates"]:
        if not c.get("needs_check"): continue
        d = dec.get(c["id"])
        if not d: stats["undecided"] = stats.get("undecided", 0) + 1; continue
        ch = d["choice"]; stats[ch] = stats.get(ch, 0) + 1
        c["read_adjudication"] = {"choice": ch, "note": d.get("note"), "adjudicator": d.get("adjudicator", "opus")}
        if ch == "none": c["read_unresolved"] = True; continue
        if ch == "picks":   # [[read, index], ...]: numbers chosen by index from the parser's reads, still no typing
            src = lambda r: cv.get(c["id"], {}).get("numbers", []) if r == "ocr_crop" else c["read_variants"].get(r, [])
            alt = [src(r)[i] for r, i in d["picks"]]
            c["numbers_docling"] = c["numbers"]; c["numbers"] = [dict(x, read_agree=True, read_source="picks") for x in alt]
            c.pop("needs_check"); continue
        if ch != "docling":
            alt = cv.get(c["id"], {}).get("numbers") if ch == "ocr_crop" else c["read_variants"].get(ch)
            if not alt: c["read_unresolved"] = True; stats["empty_variant"] = stats.get("empty_variant", 0) + 1; continue
            c["numbers_docling"] = c["numbers"]
            c["numbers"] = [dict(x, read_agree=True, read_source=ch) for x in alt]
        else:
            for x in c["numbers"]: x["read_agree"] = True
        c.pop("needs_check")
    D["read_adjudication"] = {"decisions_sha256": store.file_hash(fpath), "stats": stats}
    json.dump(D, open(f"parsed/{doc}.json", "w"), indent=1)
    store.append("read_adjudication_event", {"doc": doc, "parser": D["parser"], "decisions_file": fpath, "decisions_sha256": store.file_hash(fpath),
                                             "parsed_sha256": store.file_hash(f"parsed/{doc}.json"), "stats": stats})
    print(doc, stats)

if __name__ == "__main__":
    if sys.argv[1] == "make": [make(d) for d in sys.argv[2:]]
    elif sys.argv[1] == "apply": apply(sys.argv[2], sys.argv[3])
