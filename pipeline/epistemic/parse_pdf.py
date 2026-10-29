"""PDF parser v1: PDF -> anchored datum candidates, same schema as parse.py (jats-parse v2.4).

Tables come from docling TableFormer, text from the PDF text layer (docling, no OCR).
Number rules are imported from parse.py (TOKEN, RANGE, SCI, CODE, WORD_RE, numbers_in), so both parsers agree by construction.
Anchors: {page (1-based), bbox [x0, y0, x1, y1] in original PDF page coordinates (PyMuPDF convention, top-left origin),
          table/row/col for table cells, section/para (+ start/end within the paragraph) for text}.
Pages whose text runs sideways (landscape tables) are derotated before docling; bboxes are mapped back to the original page.
v1.1: pages with two text directions (sideways table beside a text column) get one copy per direction; superscripts
  kept apart in the PyMuPDF read; OCR third read on symbol-font / unmapped-glyph boxes; mid-dot decimals; one candidate per
  table footnote; repeated headers on continuation pages flagged anchor.repeated_header; read_variants on disagreement.
v1.5: tables on scanned pages rebuilt from fresh OCR boxes (rows by y, columns by x); text layer is the dual read.
v1.4: plain-space thousands in table cells joined (join_thousands, shared with jats-parse v2.6).
v1.3: span rules and prelabels shared with jats-parse v2.5 (exponents, E-notation, P<0.001 qualifier, copy / ci_level_label prelabels).
v1.2: ranges broken across lines ('21–' newline '23') restored where docling joined them as hyphenation ('2123').
Dual read: every number is compared with an independent read of the same bbox:
  * PyMuPDF words whose centre lies in the bbox (always);
  * RapidOCR on a 300 dpi render of the page, boxes whose centre lies in the bbox (pages whose text layer is OCR, i.e. scans).
  numbers[i].read_agree = True only if every independent read has the same (value, qualifier) at the aligned position.
  A candidate with any disagreeing number gets needs_check = True; it never enters data/ until adjudicated against a crop.
"""
import sys, json, hashlib, re, difflib, collections, tempfile, os
import pymupdf
from epistemic.parse import numbers_in, SPAN_RE, CODE, WORD_RE, WORDS, prelabel, join_thousands

VERSION = "pdf-parse v1.5"
BACK = re.compile(r"^\s*(\d+\.?\s*)?(references|bibliography|acknowledg|funding|declarations?|author.?s?.? contributions?|conflicts? of interest|competing interests?|ethics approval|consent for publication|availability of data|data availability|abbreviations|publisher.?s note|supplementary (information|material)|electronic supplementary)", re.I)
CITE = re.compile(r"\[\s*\d{1,3}(?:\s*[,–—-]\s*\d{1,3})*\s*\]")
CONT = re.compile(r"\(?\s*cont(inued|\.|d)?\b", re.I)
SYMFONT = re.compile(r"Sym|Symbol|MT-Extra|Math|Pi\d|Dingbat|Wingding", re.I)
BADGLYPH = re.compile(r"[\x00-\x08\x0b-\x1f\ufffd]")
THOU = re.compile(r"(?<=(?<![\d.])\d) (?=\d{3}(?![\d.]))|(?<=(?<![\d.])\d\d) (?=\d{3}(?![\d.]))|(?<=(?<![\d.])\d\d\d) (?=\d{3}(?![\d.]))")
MIDDOT = re.compile(r"(?<=\d) ?[·•∙] ?(?=\d)")   # Lancet/BMJ style decimal point 0·001
TABLE_NO = re.compile(r"^\s*table\s+([0-9IVX]+)", re.I)
TEXT_RE = SPAN_RE   # same span rules as the JATS parser (v2.5: exponents, E-notation, qualifiers after letters)


# ---------- page geometry ----------
ROT = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}

def page_dirs(pdf):
    """Per page: text lines as (Rect, rotation, chars), rotation = what makes the line read left-to-right."""
    out = []
    for p in pdf:
        ls = []
        for b in p.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                ls.append((pymupdf.Rect(l["bbox"]), ROT.get(tuple(round(x) for x in l["dir"]), 0), sum(len(s["text"]) for s in l["spans"])))
        out.append(ls)
    return out

def page_rotations(dirs, share=0.15):
    """Rotations each page needs: the dominant one first, plus any other direction holding >= share of its characters
    (a sideways table next to a normal text column needs both)."""
    out = []
    for ls in dirs:
        c = collections.Counter()
        for _, r, n in ls: c[r] += n
        tot = sum(c.values()) or 1
        rs = [r for r, n in c.most_common() if n >= share * tot] or [0]
        out.append(rs)
    return out

def dir_of(lines, bbox):
    """Majority text rotation of the lines whose centre lies in bbox (None if no text)."""
    R = pymupdf.Rect(bbox) + (-1, -1, 1, 1); c = collections.Counter()
    for r, rot, n in lines:
        if R.contains(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)): c[rot] += n
    return c.most_common(1)[0][0] if c else None

def ocr_pages(pdf):
    """Pages that are scans with an OCR text layer: one image covers most of the page and there is text."""
    out = set()
    for i, p in enumerate(pdf):
        area = p.rect.width * p.rect.height
        cov = max((r.width * r.height for img in p.get_images() for r in p.get_image_rects(img[0])), default=0)
        if cov > 0.6 * area and p.get_text().strip(): out.add(i)
    return out

class Geo:
    """Maps docling bboxes (derotated page, bottom-left origin) to original page coordinates (top-left origin)."""
    def __init__(self, norm_pdf):
        self.pdf = norm_pdf
    def to_orig(self, page_no, bb):
        p = self.pdf[page_no - 1]
        h = p.rect.height   # displayed (rotated) height
        if getattr(bb, "coord_origin", None) is not None and str(bb.coord_origin).endswith("TOPLEFT"):
            r = pymupdf.Rect(bb.l, bb.t, bb.r, bb.b)
        else:
            r = pymupdf.Rect(bb.l, h - bb.t, bb.r, h - bb.b)
        r = r * p.derotation_matrix
        r.normalize()
        return [round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2)]


# ---------- independent reads ----------
class Reader:
    def __init__(self, orig_pdf, rotations, ocr):
        self.pdf, self.rot, self.ocr_set = orig_pdf, rotations, ocr
        self._words, self._ocr, self._eng, self._sym = {}, {}, None, {}
    def _ordered(self, pi, items):
        """OCR boxes: order by reading order on the upright page (lines by y, then x)."""
        m = {0: pymupdf.Matrix(1, 0, 0, 1, 0, 0), 90: pymupdf.Matrix(0, 1, -1, 0, 0, 0),
             180: pymupdf.Matrix(-1, 0, 0, -1, 0, 0), 270: pymupdf.Matrix(0, -1, 1, 0, 0, 0)}[self.rot[pi]]
        def key(it):
            r = it[0] * m; r.normalize(); return (round(r.y0 / 3), r.x0)
        return [t for _, t in sorted(items, key=key)]
    def words(self, pi):
        """Word pieces from the text layer in native order, split at span boundaries so superscripts stay separate.
        Superscript pieces (flag bit 0, or font < 75% of the line's largest) are prefixed with '^'."""
        if pi not in self._words:
            out = []
            for b in self.pdf[pi].get_text("rawdict")["blocks"]:
                for l in b.get("lines", []):
                    big = max((sp["size"] for sp in l["spans"]), default=0)
                    spans = l["spans"]
                    for si_, sp in enumerate(spans):
                        # v1.4: a lone digit/punctuation glyph whose font differs from both neighbours is a likely encoding swap
                        # (AdvPS fonts print ± as '6', > as '.'): its box gets the OCR read too
                        t1 = "".join(ch["c"] for ch in sp["chars"]).strip()
                        txt_ = lambda x: "".join(ch["c"] for ch in x["chars"]).strip()
                        left = next((spans[k] for k in range(si_ - 1, -1, -1) if txt_(spans[k])), None)
                        right = next((spans[k] for k in range(si_ + 1, len(spans)) if txt_(spans[k])), None)
                        nb = [x for x in (left, right) if x is not None]
                        if len(t1) == 1 and t1.isdigit() and len(nb) == 2 and all(x["font"] != sp["font"] and re.search(r"\d", "".join(ch["c"] for ch in x["chars"])) for x in nb):
                            self._sym.setdefault(pi, []).append(pymupdf.Rect(sp["bbox"]))
                        sup = bool(sp["flags"] & 1) or sp["size"] < 0.75 * big
                        sym = bool(SYMFONT.search(sp["font"]))
                        cur, rect = "", None
                        for ch in sp["chars"] + [None]:
                            if ch is None or ch["c"].isspace():
                                if cur:
                                    if not sup and out and not out[-1][2] and out[-1][3] and abs(out[-1][0].x1 - rect.x0) < 0.6 and abs(out[-1][0].y1 - rect.y1) < 1:
                                        out[-1] = (out[-1][0] | rect, out[-1][1] + cur, False, True)   # same word split across spans
                                    else:
                                        out.append((rect, ("^" if sup else "") + cur, sup, True))
                                    if sym or BADGLYPH.search(cur): self._sym.setdefault(pi, []).append(rect)
                                if ch is not None and out: out[-1] = out[-1][:3] + (False,)
                                cur, rect = "", None
                            else:
                                cur += ch["c"]; r = pymupdf.Rect(ch["bbox"]); rect = r if rect is None else rect | r
                        if out: out[-1] = out[-1][:3] + (out[-1][3] and not sup,)
            self._words[pi] = [(r, t) for r, t, _, _ in out]
        return self._words[pi]
    def ocr_boxes(self, pi):
        if pi not in self._ocr:
            import numpy as np
            if self._eng is None:
                import logging; logging.getLogger("RapidOCR").setLevel(logging.ERROR)
                from rapidocr import RapidOCR
                self._eng = RapidOCR()
            dpi = 300; pix = self.pdf[pi].get_pixmap(dpi=dpi)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3]
            res = self._eng(img); s = 72 / dpi; boxes = []
            for box, txt in zip(res.boxes if res.boxes is not None else [], res.txts or []):
                xs = [pt[0] * s for pt in box]; ys = [pt[1] * s for pt in box]
                boxes.append((pymupdf.Rect(min(xs), min(ys), max(xs), max(ys)), txt))
            self._ocr[pi] = boxes
        return self._ocr[pi]
    @staticmethod
    def _inside(items, bbox, pad=0.5):
        R = pymupdf.Rect(bbox) + (-pad, -pad, pad, pad)
        return [(r, t) for r, t in items if R.contains(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))]
    def read(self, pi, bbox):
        """{'pymupdf': text, 'ocr': text (scan pages only)} for the bbox."""
        out = {"pymupdf": " ".join(t for _, t in self._inside(self.words(pi), bbox))}
        R = pymupdf.Rect(bbox)
        symbox = any(R.intersects(r) for r in self._sym.get(pi, []))
        if pi in self.ocr_set or symbox:   # scans, and boxes that use a symbol font or unmapped glyphs
            out["ocr"] = " ".join(self._ordered(pi, self._inside(self.ocr_boxes(pi), bbox)))
        return out

def _key(n):
    return (None if n["value"] is None else round(n["value"], 10), n.get("qualifier"))

def dual_read(nums, reads):
    """Set read_agree on each number in nums; return True if all agree."""
    agree = [True] * len(nums)
    for src, txt in reads.items():
        mine = [_key(x) for x in nums]
        ok = [False] * len(nums)
        txt = fix(_ocr_norm(txt) if src == "ocr" else txt)
        for variant in (txt, THOU.sub("", txt)):   # "10 155" read as one number or two
          other = read_numbers(variant)
          for a, b, size in difflib.SequenceMatcher(None, mine, [k for k, _ in other], autojunk=False).get_matching_blocks():
            for k in range(size):
                ok[a + k] = True
                if other[b + k][1]: nums[a + k]["superscript"] = True
        agree = [x and y for x, y in zip(agree, ok)]
    for n, a in zip(nums, agree): n["read_agree"] = a
    return all(agree)

def read_numbers(txt):
    """[(key, is_superscript)] for an independent read; '^'-prefixed pieces are superscripts."""
    out = []
    for seg in re.split(r"(\^\S+)", txt):
        if seg: out += [(_key(x), seg.startswith("^")) for x in numbers_in(seg.lstrip("^"))]
    return out

LINEBREAK_RANGE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[–—-]\s*\n\s*(\d+(?:\.\d+)?)(?![\d.])")

def undehyphen(txt, raw):
    """Docling drops a dash at a line end as if it were hyphenation, joining '21–' + '23' into '2123'.
    For each range broken across lines in the raw text layer, restore the dash where docling joined the two parts (v1.2)."""
    for m in LINEBREAK_RANGE.finditer(raw):
        a, b = m.groups()
        txt = re.sub(r"(?<![\d.])" + re.escape(a) + r"\s?" + re.escape(b) + r"(?![\d.])", a + "–" + b, txt, count=1)
    return txt

def fix(t):
    """Docling text before number scanning: mid-dot decimals become '.' (0·001 -> 0.001)."""
    return MIDDOT.sub(".", t)

def _ocr_norm(t):
    # OCR engines emit look-alikes; map the common ones before reading numbers
    return t.replace("℃", "°C").replace("，", ",").replace("：", ":").replace("（", "(").replace("）", ")").replace("O.", "0.")


# ---------- scanned tables (v1.5) ----------
def _cluster(vals, tol):
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol: out[-1].append(v)
        else: out.append([v])
    return [(min(c), max(c)) for c in out]
def rebuild_scan_table(boxes, R, label_max_x=None):
    """boxes: [(Rect, text)] OCR boxes; R: table rect (orig coords). Returns rows [{cells:[(text, rect)], is_head}] and col starts."""
    B = [(r, t) for r, t in boxes if R.contains(pymupdf.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)) and t.strip()]
    if not B: return None
    ys = _cluster([r.y0 for r, _ in B], 3.5)
    rows = [[(r, t) for r, t in B if lo - 0.1 <= r.y0 <= hi + 0.1] for lo, hi in ys]
    numeric = lambda t: bool(re.fullmatch(r"[\d.,·()\-–—−<>≥≤%\s]+", t)) and bool(re.search(r"\d", t))
    lab_x = label_max_x or min((r.x0 for r, t in B if numeric(t)), default=R.x1) - 3
    xs = _cluster([r.x0 for r, t in B if r.x0 > lab_x], 12)
    cols = [lo for lo, hi in xs]
    out = []
    for row in rows:
        lab = " ".join(t for r, t in sorted(row, key=lambda b: b[0].x0) if r.x0 <= lab_x)
        cells = [""] * (len(cols) + 1); rects = [None] * (len(cols) + 1); cells[0] = lab
        for r, t in sorted(row, key=lambda b: b[0].x0):
            if r.x0 <= lab_x:
                rects[0] = r if rects[0] is None else rects[0] | r; continue
            k = max(i for i, c in enumerate(cols) if r.x0 >= c - 6) + 1
            cells[k] = (cells[k] + " " + t).strip(); rects[k] = r if rects[k] is None else rects[k] | r
        out.append({"cells": cells, "rects": rects})
    first_lab = next((i for i, r in enumerate(out) if r["cells"][0]), 0)
    for i, r in enumerate(out): r["is_head"] = i < first_lab
    return out


# ---------- main ----------
def normalize(path, rots):
    """A PDF with one copy of each page per needed rotation; pmap[k] = (original page index, rotation) of copy k."""
    src = pymupdf.open(path)
    pmap = [(i, r) for i, rs in enumerate(rots) for r in rs]
    if all(r == 0 for _, r in pmap): return path, pmap, None
    out = pymupdf.open()
    for i, r in pmap:
        out.insert_pdf(src, from_page=i, to_page=i)
        if r: out[-1].set_rotation(r)
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False); out.save(tmp.name)
    return tmp.name, pmap, tmp.name

_CONV = None
def converter():
    global _CONV
    if _CONV is None:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        po = PdfPipelineOptions(); po.do_ocr = False; po.do_table_structure = True
        po.table_structure_options.do_cell_matching = True
        _CONV = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=po)})
    return _CONV

def parse(path):
    raw = open(path, "rb").read(); sha = hashlib.sha256(raw).hexdigest()
    doc_id = os.path.basename(path).rsplit(".", 1)[0]
    orig = pymupdf.open(path); dirs = page_dirs(orig); rots = page_rotations(dirs)
    norm_path, pmap, tmp = normalize(path, rots)
    normpdf = pymupdf.open(norm_path)
    ocr = ocr_pages(orig)
    geo, rd = Geo(normpdf), Reader(orig, [rs[0] for rs in rots], ocr)
    P = lambda k: pmap[k - 1][0] + 1   # docling page number -> original page number
    def keep(item):
        """On pages with several text directions, keep an item only on the copy whose rotation matches its text."""
        if not item.prov: return True
        k = item.prov[0].page_no; oi, r = pmap[k - 1]
        if len(rots[oi]) == 1: return True
        d = dir_of(dirs[oi], geo.to_orig(k, item.prov[0].bbox))
        return d == r if d is not None else r == rots[oi][0]
    doc = converter().convert(norm_path).document
    if tmp: os.unlink(tmp)
    D = {"doc": doc_id, "sha256": sha, "parser": VERSION, "source_format": "pdf", "title": "",
         "pages": orig.page_count, "rotated_pages": [i + 1 for i, rs in enumerate(rots) if any(rs)],
         "page_copies": {str(i + 1): rs for i, rs in enumerate(rots) if len(rs) > 1},
         "ocr_pages": sorted(i + 1 for i in ocr),
         "sections": [], "tables": [], "figures": [], "supplements": [], "candidates": []}
    n = 0
    def rawtext(anchor):
        bx = [(anchor["page"], anchor["bbox"])] + [(x["page"], x["bbox"]) for x in anchor.get("more_boxes", [])]
        return "\n".join(orig[pg - 1].get_text("text", clip=pymupdf.Rect(bb)) for pg, bb in bx)
    def add(kind, text, anchor, ctx=None, nums=None, read_bbox=None):
        nonlocal n
        if nums is None and kind in ("table_cell", "row_label", "table_header", "table_caption", "table_footnote", "figure_caption"):
            text = undehyphen(text, rawtext(anchor))
            if kind in ("table_cell", "row_label", "table_header") and anchor["page"] - 1 not in ocr: text = join_thousands(text)   # not on scans: there "1 209" is a lost mid-dot
        nums = nums if nums is not None else numbers_in(text)
        if not nums: return
        n += 1
        c = {"id": f"{doc_id}:{n}", "kind": kind, "text": text, "anchor": anchor, "numbers": nums, "local_context": ctx}
        if kind != "code":
            boxes = [(anchor["page"], read_bbox or anchor["bbox"])] + [(x["page"], x["bbox"]) for x in anchor.get("more_boxes", [])]
            parts = [rd.read(pg - 1, bb) for pg, bb in boxes]
            reads = {k: " ".join(x[k] for x in parts if k in x) for k in parts[0]}
            ok = dual_read(nums, reads)
            c["reads"] = reads
            if not ok:
                c["needs_check"] = True
                c["read_variants"] = {k: numbers_in(fix(_ocr_norm(v) if k == "ocr" else v).replace("^", "")) for k, v in reads.items()}
        else:
            for x in nums: x["read_agree"] = True
        D["candidates"].append(c)
    def anc(item, **kw):
        pr = item.prov[0]
        a = {"page": P(pr.page_no), "bbox": geo.to_orig(pr.page_no, pr.bbox)}
        if len(item.prov) > 1:   # paragraph continues in another column or page
            a["more_boxes"] = [{"page": P(x.page_no), "bbox": geo.to_orig(x.page_no, x.bbox)} for x in item.prov[1:]]
        return dict(a, **kw)

    used_caps = set()
    # ---- tables (continuations merged: 'Table N (continued)', or no caption + same column count + next page) ----
    prev = None
    for t in doc.tables:
        if not keep(t): continue
        cap = t.caption_text(doc) if t.captions else ""
        for r in t.captions: used_caps.add(r.cref)
        for r in getattr(t, "footnotes", []) or []: used_caps.add(r.cref)
        pgn = t.prov[0].page_no; pg = P(pgn)
        m = TABLE_NO.match(cap)
        named = next((x for x in D["tables"] if m and x["id"] == f"T{m.group(1)}"), None)
        if named is not None and CONT.search(cap):   # "Table 5 (continued)"
            cont = True; prev = named
        else:
            cont = (not cap and prev is not None and prev["ncols"] == t.data.num_cols and pg == prev["last_page"] + 1)
        if cont:
            T = prev; row_off = T["nrows"]
        else:
            tid = f"T{m.group(1)}" if m else f"T{len(D['tables']) + 1}"
            if any(x["id"] == tid for x in D["tables"]): tid = f"{tid}_{len(D['tables']) + 1}"
            T = {"id": tid, "caption": cap, "footnotes": "", "rows": [], "nrows": 0, "ncols": t.data.num_cols, "pages": [], "last_page": pg}
            D["tables"].append(T); row_off = 0
            if cap: add("table_caption", fix(cap), anc(t.captions[0].resolve(doc), table=tid, part="caption"))
        T["pages"].append(pg); T["last_page"] = pg
        for fr in (getattr(t, "footnotes", []) or []):
            fi = fr.resolve(doc)
            T["footnotes"] = (T["footnotes"] + " " + fi.text).strip()
            add("table_footnote", fix(fi.text), anc(fi, table=T["id"], part="footnote"))
        if pg - 1 in ocr:
            # v1.5: on scans TableFormer can skew rows and merge neighbouring cells; rebuild the grid from fresh OCR boxes
            # (rows by y, columns by x, labels from the left column). The text layer (the scan's own OCR) is the dual read.
            Rt = pymupdf.Rect(anc(t)["bbox"]) + (-4, -4, 4, 4)
            srows = rebuild_scan_table(rd.ocr_boxes(pg - 1), Rt)
            if srows:
                T["scan_rebuilt"] = True
                for ri, r in enumerate(srows):
                    T["rows"].append({"cells": [fix(x) for x in r["cells"]], "is_head": r["is_head"], "page": pg})
                    for ci, (txt, rect) in enumerate(zip(r["cells"], r["rects"])):
                        if not txt or rect is None: continue
                        kind = "table_header" if r["is_head"] else ("row_label" if ci == 0 else "table_cell")
                        add(kind, fix(_ocr_norm(txt)), {"page": pg, "bbox": [round(v, 2) for v in rect], "table": T["id"], "row": row_off + ri, "col": ci, "source": "ocr_rebuild"})
                T["nrows"] = len(T["rows"]); prev = T
                continue
        grid = [[None] * t.data.num_cols for _ in range(t.data.num_rows)]
        for c in t.data.table_cells:
            for rr in range(c.start_row_offset_idx, c.end_row_offset_idx):
                for cc in range(c.start_col_offset_idx, c.end_col_offset_idx):
                    if rr < len(grid) and cc < len(grid[0]): grid[rr][cc] = c
        for ri, row in enumerate(grid):
            cells = [c.text if c else "" for c in row]
            is_head = all(c is None or c.column_header for c in row) and any(c is not None for c in row)
            norm = lambda cs: [re.sub(r"\W+", "", x).lower() for x in cs]
            first_heads = {x for h in T["rows"][:4] if h.get("page") == T["pages"][0] for x in norm(h["cells"]) if x}
            ne = [x for x in norm(cells) if x]
            rep_head = cont and ri < 4 and len(ne) >= 2 and sum(x in first_heads for x in ne) >= 0.75 * len(ne)
            lead_head = is_head and all(r_["is_head"] for r_ in T["rows"][len(T["rows"]) - ri:]) if ri else is_head
            T["rows"].append({"cells": cells, "is_head": is_head, "page": pg})
            for ci, c in enumerate(row):
                if c is None: continue
                if c.start_row_offset_idx != ri or c.start_col_offset_idx != ci: continue   # span copy: emit once at origin
                kind = "table_header" if (is_head or c.column_header) else ("row_label" if ci == 0 else "table_cell")
                bb = geo.to_orig(pgn, c.bbox) if c.bbox is not None else anc(t)["bbox"]
                a = {"page": pg, "bbox": bb, "table": T["id"], "row": row_off + ri, "col": ci}
                if c.row_span > 1 or c.col_span > 1: a["span"] = [c.row_span, c.col_span]
                if cont and (lead_head or rep_head): a["repeated_header"] = True   # header rows repeated on a continuation page
                add(kind, fix(c.text), a)
        T["nrows"] = len(T["rows"])
        prev = T
    for T in D["tables"]: T.pop("last_page", None)

    # ---- figures ----
    for fi, f in enumerate(p for p in doc.pictures if keep(p)):
        cap = f.caption_text(doc) if f.captions else ""
        for r in f.captions: used_caps.add(r.cref)
        fid = f"F{fi + 1}"
        D["figures"].append({"id": fid, "caption": cap, "page": P(f.prov[0].page_no) if f.prov else None, "digitized": False})
        if cap: add("figure_caption", fix(cap), anc(f.captions[0].resolve(doc), figure=fid, part="caption"))

    # ---- text (reading order, section/para) ----
    si, para, sec, back = -1, 0, None, False
    # front matter (affiliations, dates, correspondence) is outside the JATS body: skip text before an Abstract heading
    heads = [it for it in doc.texts if str(it.label).split(".")[-1].lower() == "section_header"]
    front = any(re.match(r"^\s*(abstract|summary)\b", h.text, re.I) for h in heads)
    def new_section(title):
        nonlocal si, para, sec
        si += 1; para = 0; sec = {"id": f"S{si}", "title": title, "text": "", "paras": []}; D["sections"].append(sec)
    for it in doc.texts:
        if it.self_ref in used_caps or not it.prov or not keep(it): continue
        if str(getattr(it, "content_layer", "body")).endswith("furniture"): continue
        lab = str(it.label).split(".")[-1].lower()
        if lab in ("page_header", "page_footer"): continue
        if lab == "title":
            D["title"] = D["title"] or it.text; continue
        if lab == "section_header":
            if front and not D["title"] and len(it.text.split()) >= 5: D["title"] = it.text   # first long heading before the abstract
            if front and re.match(r"^\s*(abstract|summary)\b", it.text, re.I): front = False
            back = bool(BACK.match(it.text))
            new_section(it.text)
            if back: sec["back_matter"] = True
            continue
        if back or front: continue
        if sec is None: new_section("")
        txt = fix(re.sub(r"\s+", " ", it.text).strip())
        if not txt: continue
        pid = f"P{para}"; para += 1
        base = anc(it, section=sec["id"], para=pid)
        txt = undehyphen(txt, rawtext(base))
        sec["paras"].append({"id": pid, "page": base["page"], "bbox": base["bbox"], "label": lab, **({"more_boxes": base["more_boxes"]} if "more_boxes" in base else {})})
        sec["text"] = (sec["text"] + " " + txt).strip()
        cites = [(m.start(), m.end()) for m in CITE.finditer(txt)]   # bracketed citation lists, stripped in JATS too
        codes = list(CODE.finditer(txt))
        for m in TEXT_RE.finditer(txt):
            s = m.group(0)
            if not re.search(r"\d", s): continue
            if any(cm.start() <= m.start() < cm.end() for cm in codes): continue
            if any(a_ <= m.start() < b_ for a_, b_ in cites): continue
            add("text_span", s, dict(base, start=m.start(), end=m.end()), txt[max(0, m.start() - 180):m.end() + 180])
            if D["candidates"] and D["candidates"][-1]["kind"] == "text_span": D["candidates"][-1]["_para_text"] = txt
        for cm in codes:
            add("code", cm.group(0), dict(base, start=cm.start(), end=cm.end()), txt[max(0, cm.start() - 80):cm.end() + 80],
                nums=[{"value": None, "qualifier": None, "raw": cm.group(0), "role_hint": "code"}])
        for wm in WORD_RE.finditer(txt):
            w = wm.group(1).lower()
            n += 1
            D["candidates"].append({"id": f"{doc_id}:{n}", "kind": "number_word", "text": wm.group(1),
                                    "anchor": dict(base, start=wm.start(), end=wm.end()),
                                    "numbers": [{"value": WORDS[w], "qualifier": None, "raw": wm.group(1), "role_hint": None, "read_agree": True}],
                                    "local_context": txt[max(0, wm.start() - 120):wm.end() + 120]})
    _tighten_text_reads(D, rd)
    D["read_summary"] = read_summary(D)
    return prelabel(D)

def _tighten_text_reads(D, rd):
    """Text spans: the paragraph-level read has all numbers of the paragraph; re-check each span against its own
    position in the paragraph read, so a span agrees only if its numbers occur in the PyMuPDF read in the same order."""
    groups = collections.defaultdict(list)
    for c in D["candidates"]:
        if c["kind"] == "text_span": groups[(c["anchor"]["section"], c["anchor"]["para"])].append(c)
    for cs in groups.values():
        reads = cs[0]["reads"]
        allnums = [x for c in cs for x in c["numbers"]]
        for x in allnums: x.pop("read_agree", None)
        dual_read(allnums, reads)
        ptxt = cs[0]["_para_text"]
        for c in cs:
            c.pop("reads", None); c.pop("needs_check", None); c.pop("read_variants", None)
            if not all(x["read_agree"] for x in c["numbers"]):
                c["needs_check"] = True
                c["read_variants"] = {k: numbers_in(_map_span(ptxt, fix(_ocr_norm(v) if k == "ocr" else v).replace("^", ""), c["anchor"]["start"], c["anchor"]["end"]))
                                      for k, v in reads.items()}
        for c in cs: c.pop("_para_text", None)
        cs[0]["para_reads"] = reads

def _map_span(a, b, start, end):
    """Substring of b that corresponds to a[start:end] (character alignment), widened to whole tokens."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    def m(i):
        for x, y, n in sm.get_matching_blocks():
            if x <= i < x + n: return y + (i - x)
        best = min(sm.get_matching_blocks(), key=lambda t: min(abs(t[0] - i), abs(t[0] + t[2] - i)))
        return best[1] + (min(max(i - best[0], 0), best[2]))
    i, j = m(start), m(max(start, end - 1)) + 1
    while i > 0 and not b[i - 1].isspace(): i -= 1
    while j < len(b) and not b[j].isspace(): j += 1
    return b[i:j]

def read_summary(D):
    k = collections.Counter()
    for c in D["candidates"]:
        for x in c["numbers"]:
            k[(c["kind"], x.get("read_agree"))] += 1
    tot = sum(k.values()); ag = sum(v for (kk, a), v in k.items() if a)
    return {"numbers": tot, "read_agree": ag, "needs_check_candidates": sum(1 for c in D["candidates"] if c.get("needs_check")),
            "by_kind": {f"{kk}|{a}": v for (kk, a), v in sorted(k.items(), key=str)}}

def summary(D):
    k = collections.Counter(c["kind"] for c in D["candidates"])
    return {"doc": D["doc"], "parser": D["parser"], "tables": len(D["tables"]), "figures": len(D["figures"]),
            "candidates": dict(k), "numbers": sum(len(c["numbers"]) for c in D["candidates"]),
            "read_agree": D["read_summary"]["read_agree"], "needs_check": D["read_summary"]["needs_check_candidates"],
            "rotated_pages": D["rotated_pages"], "ocr_pages": D["ocr_pages"]}

if __name__ == "__main__":
    D = parse(sys.argv[1]); json.dump(D, open(sys.argv[2], "w"), indent=1); print(json.dumps(summary(D)))
