"""Parser v2: JATS XML -> anchored datum candidates.

Fixes over v1 (each was a failure seen in run 02):
  * ranges like 0.84-1.15 or 0.84–1.15 are two positive numbers, not a negative second number
  * comparison qualifiers (<, <=, >, >=, ~) are kept as a `qualifier`, so "<0.001" survives
  * in-text citations (xref ref-type=bibr) are removed before scanning, so "9,10" never becomes 910
  * table header rows and row-label cells are scanned too (kinds table_header, row_label)
  * number words (one..twenty, half, two thirds, ...) are captured as kind number_word
Every candidate carries: id, kind, text, anchor, numbers[{value, qualifier, raw}], local_context.
v2.1 (overnight 26 Oct 2026, found by typecheck):
  * scientific notation 2.4×10−19 (exponent in <sup>) is one number, not three
  * abbreviated year ranges 1984-87 expand the second year to 1987 (raw kept as written, expanded=True)
v2.4: tables/figures nested inside <p> are flagged anchor.nested_copy_of (their text repeats in the body; ids unchanged)
v2.3: thin / no-break spaces used as thousands separators (46 213) are one number, not two
v2.5 (mission 2, 26 Oct 2026):
  * mid-dot decimals (Lancet style 5·7, U+00B7/2022/2219 between digits) read as 5.7, not 5 and 7 (PMC9816653 kappa 0.389)
  * bare exponents 10<sup>-6</sup> (also after a qualifier, P<10^-6) and E-notation 2.8E-6 are one number
  * a qualifier glued to a letter keeps its number: P<0.001 -> qualifier "<" (was dropped)
  * malformed cells (two decimal points in one digit run, e.g. "0.64090.203-2.020)") flagged candidate.malformed=True,
    raw text kept; validate keeps them out of data/
  * prelabels (brief v3): span/nested copies and the lone 95 of "95% CI" get candidate.prelabel={"not_data": reason},
    so they never reach adjudication
v2.8: E-notation with spaces (2.9e + 40) is one number (PMC12517802)
v2.7: an en dash used as a minus sign (–0.339, not part of a range) is negative; found as 160 false 'estimate outside CI' in PMC13462672
v2.6: plain-space thousands in table cells (21 064) are one number (join_thousands); found when the adjudicator stored 21 and 64 as person_years
v2.2: row/colspan copies in table bodies are flagged anchor.span_copy_of=[row, col] (ids unchanged; validate dedups them)
"""
import re, sys, json, hashlib, copy
from lxml import etree

DASH = "–—−-"
QUAL = r"(?P<q>[<>]=?|≤|≥|~|≈)?\s*"
GSEP = "\u2009\u202f\u00a0"   # thin, narrow no-break, no-break space as digit-group separators (v2.3)
NUMBER = r"\d{1,3}(?:[," + GSEP + r"]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+"
TOKEN = re.compile(r"(?:(?<=[A-Za-z])(?P<q2>[<>]=?|≤|≥)\s*|(?<![A-Za-z0-9])" + QUAL + r")(?P<neg>(?<![A-Za-z0-9/])[−–-](?=\d))?(?<![A-Za-z])(?P<n>" + NUMBER + r")(?P<pct>\s?%)?")
RANGE = re.compile(r"(?<![A-Za-z0-9.])(" + NUMBER + r")\s*[" + DASH + r"]\s*(" + NUMBER + r")")
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
         "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "hundred": 100,
         "half": 0.5, "one third": 1 / 3, "two thirds": 2 / 3, "a quarter": 0.25, "three quarters": 0.75}
WORD_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, WORDS), key=len, reverse=True)) + r")\b", re.I)
SCI = re.compile(r"(?:(?<=[A-Za-z])(?P<qs2>[<>]=?|≤|≥)\s*|(?<![A-Za-z0-9.])" + QUAL + r")(?P<m>\d+(?:\.\d+)?)\s*[×x·]\s*10\s*(?P<e>[−-]?\s?\d{1,3})(?![\d.])")
# v2.5: bare power of ten (10^-6, written 10<sup>-6</sup> in JATS; tx marks the exponent with ^) and E-notation (2.8E-6)
EXP = re.compile(r"(?:(?<=[A-Za-z])(?P<qx2>[<>]=?|≤|≥)\s*|(?<![A-Za-z0-9.])" + QUAL.replace("?P<q>", "?P<qx>") + r")(?:(?P<mx>\d+(?:\.\d+)?)\s*[×x·]\s*)?10\s*\^\s*(?P<ex>[−-]?\s?\d{1,3})(?![\d.])")
ENOT = re.compile(r"(?:(?<=[A-Za-z])(?P<qe2>[<>]=?|≤|≥)\s*|(?<![A-Za-z0-9.])" + QUAL.replace("?P<q>", "?P<qe>") + r")(?P<me>\d+(?:\.\d+)?)[eE](?P<ee>\s?[−+-]\s?\d{1,3}|\d{1,3})(?![\d.A-Za-z])")
MIDDOT = re.compile(r"(?<=\d)[·•∙](?=\d)(?!10[−-]?[1-9])")
MALFORMED = re.compile(r"\d\.\d+\.\d")
# v2.7: an en dash used as a minus sign is negative (see module docstring)
# v2.6: plain-space thousands in table cells ("21 064", "n = 81 248", "1484/19 593"). Conservative: the left group has 1-3 digits,
# does not start with 0 (a lost mid-dot "0 106") and is not itself preceded by a number ("1757 6 517" is mean ± SD with a misread ±).
THOU_CELL = re.compile(r"(?<![\d.,]\s)(?<![\d.,])\b([1-9]\d{0,2})((?: \d{3})+)(?![\d.]|\s?\d)")
def join_thousands(t):
    return THOU_CELL.sub(lambda m: m.group(1) + m.group(2).replace(" ", "\u2009"), t) if t else t

CODE = re.compile(r"\b[A-Z]\d{2}(?:\.\d{1,2})?\b")   # ICD-10 style codes, kept whole
QMAP = {"≤": "<=", "≥": ">=", "≈": "~"}

def _anon(p): return re.sub(r"\(\?P<\w+>", "(?:", p)
SPAN_RE = re.compile("|".join(_anon(x.pattern) for x in (EXP, ENOT, SCI, RANGE, TOKEN)))

def tx(el):
    el = mark_exponents(el)
    t = MIDDOT.sub(".", "".join(el.itertext()))
    t = re.sub(r"(?<=\d)[" + GSEP + r"](?=\d{3}(?!\d))", "\x00", t)   # protect digit-group separators (v2.3)
    return re.sub(r"\s+", " ", t).strip().replace("\x00", "\u2009")

def mark_exponents(el):
    """v2.5: <sup>-6</sup> right after '10' is an exponent; mark it '^-6' so 10^-6 reads as one number."""
    sups = el.xpath(".//sup")
    if not sups: return el
    el = copy.deepcopy(el)
    for sp in el.xpath(".//sup"):
        st = "".join(sp.itertext()).strip()
        prev = sp.getprevious()
        before = (prev.tail if prev is not None else sp.getparent().text) or ""
        if re.fullmatch(r"[−-]?\s?\d{1,3}", st) and re.search(r"(?<![\d.])10\s*$", before):
            for ch in list(sp): sp.remove(ch)
            sp.text = "^" + st
    return el

def num(raw):
    return float(re.sub(r"[," + GSEP + r"]", "", raw))

def numbers_in(s):
    """Return [{value, qualifier, raw, role_hint}] for every number in s, ranges split correctly."""
    s = MIDDOT.sub(".", s)   # v2.5, same length, so positions are unchanged
    out, taken = [], []
    for m in EXP.finditer(s):
        q = m.group("qx") or m.group("qx2"); q = QMAP.get(q, q)
        v = float((m.group("mx") or "1") + "e" + m.group("ex").replace("−", "-").replace(" ", ""))
        out.append((m.start(), {"value": v, "qualifier": q, "raw": m.group(0).strip(), "role_hint": None}))
        taken.append((m.start(), m.end()))
    for m in ENOT.finditer(s):
        if any(a <= m.start() < b for a, b in taken): continue
        q = m.group("qe") or m.group("qe2"); q = QMAP.get(q, q)
        v = float(m.group("me") + "e" + m.group("ee").replace("−", "-").replace(" ", ""))
        out.append((m.start(), {"value": v, "qualifier": q, "raw": m.group(0).strip(), "role_hint": None}))
        taken.append((m.start(), m.end()))
    for m in SCI.finditer(s):
        if any(a <= m.start() < b for a, b in taken): continue
        q = m.group("q") or m.group("qs2"); q = QMAP.get(q, q)
        v = float(m.group("m") + "e" + m.group("e").replace("−", "-").replace(" ", ""))
        out.append((m.start(), {"value": v, "qualifier": q, "raw": m.group(0).strip(), "role_hint": None}))
        taken.append((m.start(), m.end()))
    for m in RANGE.finditer(s):
        if any(a <= m.start() < b for a, b in taken): continue
        if any(a <= m.start(2) < b for a, b in taken): continue   # v2.8: the range's upper end is an exponent number (0.01–2.9e + 40)
        a, b = m.group(1), m.group(2)
        bv = num(b)
        if re.fullmatch(r"(19|20)\d\d", a) and re.fullmatch(r"\d\d", b) and int(b) > int(a) % 100:
            out.append((m.start(1), {"value": float(a), "qualifier": None, "raw": a, "role_hint": "range_low"}))
            out.append((m.start(2), {"value": float(int(a) // 100 * 100 + int(b)), "qualifier": None, "raw": b, "role_hint": "range_high", "expanded": True}))
            taken.append((m.start(), m.end())); continue
        # a range must look like a range: second >= first, or a CI/interval context; dates like 1995-96 kept as two numbers too
        out.append((m.start(1), {"value": num(a), "qualifier": None, "raw": a, "role_hint": "range_low"}))
        out.append((m.start(2), {"value": bv, "qualifier": None, "raw": b, "role_hint": "range_high"}))
        taken.append((m.start(), m.end()))
    for m in TOKEN.finditer(s):
        if any(a <= m.start("n") < b for a, b in taken): continue
        raw = m.group("n"); v = num(raw)
        if m.group("neg"): v = -v
        q = m.group("q") or m.group("q2"); q = QMAP.get(q, q)
        out.append((m.start(), {"value": v, "qualifier": q, "raw": m.group(0).strip(), "role_hint": "percent" if m.group("pct") else None}))
    return [x for _, x in sorted(out, key=lambda t: t[0])]

def strip_citations(el):
    el = copy.deepcopy(el)
    for x in el.xpath(".//xref[@ref-type='bibr']"):
        parent = x.getparent(); tail = x.tail or ""
        prev = x.getprevious()
        # remove brackets/commas/dashes that only joined citations
        if prev is not None: prev.tail = (prev.tail or "") + re.sub(r"^[\s,–\-\]\)]*", " ", tail, count=1)
        else: parent.text = (parent.text or "") + re.sub(r"^[\s,–\-\]\)]*", " ", tail, count=1)
        parent.remove(x)
    t = tx(el)
    return re.sub(r"[\[\(]\s*[,–\-\s]*[\]\)]", "", t)   # empty brackets left behind

def grid(table):
    """Rows of cells with row/colspans expanded. copy_of[ci] = [row, col] of the origin cell when the cell is a span copy (v2.2)."""
    rows, spans = [], {}
    for ri, tr in enumerate(table.xpath(".//tr")):
        out, cp, ci = [], [], 0
        def fill():
            nonlocal ci
            while (ri, ci) in spans:
                t, o = spans.pop((ri, ci)); out.append(t); cp.append(o); ci += 1
        for c in tr.xpath("./th|./td"):
            fill()
            t = tx(c); rs = int(c.get("rowspan", 1) or 1); cs = int(c.get("colspan", 1) or 1)
            for k in range(cs):
                out.append(t); cp.append(None if k == 0 else [ri, ci])
                for r in range(1, rs): spans[(ri + r, ci + k)] = (t, [ri, ci])
            ci += cs
        fill()
        rows.append({"cells": out, "copy_of": cp, "is_head": bool(tr.xpath("ancestor::thead")) or (bool(tr.xpath("./th")) and not tr.xpath("./td"))})
    return rows

def parse(path):
    raw = open(path, "rb").read(); sha = hashlib.sha256(raw).hexdigest()
    t = etree.fromstring(raw)
    doc_id = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    title = tx(t.xpath("//article-title")[0]) if t.xpath("//article-title") else ""
    D = {"doc": doc_id, "sha256": sha, "parser": "jats-parse v2.8", "title": title,
         "sections": [], "tables": [], "figures": [], "supplements": [], "candidates": []}
    n = 0
    def add(kind, text, anchor, ctx=None, nums=None):
        nonlocal n
        nums = nums if nums is not None else numbers_in(text)
        if not nums: return
        n += 1
        D["candidates"].append({"id": f"{doc_id}:{n}", "kind": kind, "text": text, "anchor": anchor,
                                "numbers": nums, "local_context": ctx})
    for tw in t.xpath("//table-wrap"):
        tid = tw.get("id") or f"T{len(D['tables']) + 1}"
        cap = tx(tw.xpath(".//caption")[0]) if tw.xpath(".//caption") else ""
        foot = " ".join(tx(f) for f in tw.xpath(".//table-wrap-foot"))
        g = grid(tw.xpath(".//table")[0]) if tw.xpath(".//table") else []
        D["tables"].append({"id": tid, "caption": cap, "footnotes": foot, "rows": g})
        add("table_caption", cap, {"table": tid, "part": "caption"})
        add("table_footnote", foot, {"table": tid, "part": "footnote"})
        for ri, r in enumerate(g):
            for ci, cell in enumerate(r["cells"]):
                if ci > 0 and r["cells"][ci - 1] == cell and r["is_head"]: continue   # colspan duplicate in header
                kind = "table_header" if r["is_head"] else ("row_label" if ci == 0 else "table_cell")
                anc = {"table": tid, "row": ri, "col": ci}
                if r.get("copy_of") and ci < len(r["copy_of"]) and r["copy_of"][ci]: anc["span_copy_of"] = r["copy_of"][ci]
                add(kind, join_thousands(cell), anc)
    for si, sec in enumerate(t.xpath("//abstract | //body//sec[not(ancestor::sec)]")):
        title_s = tx(sec.xpath("./title")[0]) if sec.xpath("./title") else ("Abstract" if sec.tag == "abstract" else "")
        pels = sec.xpath(".//p[not(ancestor::table-wrap) and not(ancestor::fig)]")
        paras = [strip_citations(p) for p in pels]
        body = " ".join(paras)
        # v2.4: some publishers nest <table-wrap>/<fig> inside <p>; their text lands in the body a second time.
        # Find those character ranges so candidates inside them are flagged (ids unchanged), like rowspan copies.
        nested, off = [], 0
        for p_el, ptxt in zip(pels, paras):
            for el in p_el.xpath(".//table-wrap | .//fig"):
                if el.xpath("ancestor::table-wrap | ancestor::fig")[:1] and el.xpath("ancestor::table-wrap | ancestor::fig")[0] is not el and \
                   any(a in p_el.xpath(".//table-wrap | .//fig") for a in el.xpath("ancestor::table-wrap | ancestor::fig")): continue
                et = strip_citations(el); i = ptxt.find(et[:120]) if et else -1
                if i >= 0: nested.append((off + i, off + i + len(et), el.get("id") or el.tag))
            off += len(ptxt) + 1
        def nest_of(a):
            return next((t for x, y, t in nested if x <= a < y), None)
        D["sections"].append({"id": f"S{si}", "title": title_s, "text": body})
        for m in re.finditer(r"[^.;]*?(?:" + NUMBER + r")[^.;]*", body):
            pass
        # one candidate per number occurrence, with its char span
        for (start, item) in [(mm.start(), mm) for mm in SPAN_RE.finditer(body)]:
            s = item.group(0)
            if not re.search(r"\d", s): continue
            if any(cm.start() <= item.start() < cm.end() for cm in CODE.finditer(body)): continue
            add("text_span", s, dict({"section": f"S{si}", "start": item.start(), "end": item.end()}, **({"nested_copy_of": nest_of(item.start())} if nest_of(item.start()) else {})),
                body[max(0, item.start() - 180):item.end() + 180])
        for cm in CODE.finditer(body):
            add("code", cm.group(0), dict({"section": f"S{si}", "start": cm.start(), "end": cm.end()}, **({"nested_copy_of": nest_of(cm.start())} if nest_of(cm.start()) else {})),
                body[max(0, cm.start() - 80):cm.end() + 80],
                nums=[{"value": None, "qualifier": None, "raw": cm.group(0), "role_hint": "code"}])
        for wm in WORD_RE.finditer(body):
            w = wm.group(1).lower()
            add("number_word", wm.group(1), dict({"section": f"S{si}", "start": wm.start(), "end": wm.end()}, **({"nested_copy_of": nest_of(wm.start())} if nest_of(wm.start()) else {})),
                body[max(0, wm.start() - 120):wm.end() + 120],
                nums=[{"value": WORDS[w], "qualifier": None, "raw": wm.group(1), "role_hint": None}])
    for fi, f in enumerate(t.xpath("//fig")):
        fid = f.get("id") or f"F{fi + 1}"
        cap = tx(f)
        href = f.xpath(".//graphic/@*[local-name()='href']")
        D["figures"].append({"id": fid, "caption": cap, "graphic": href[0] if href else None, "digitized": False})
        add("figure_caption", cap, {"figure": fid, "part": "caption"})
    for s in t.xpath("//supplementary-material"):
        href = s.xpath(".//media/@*[local-name()='href']")
        D["supplements"].append({"label": tx(s)[:200], "href": href[0] if href else None, "retrieved": False})
    return prelabel(D)

CI95 = re.compile(r"^\s*%?\s*(CI|C\.I\.|confidence|credible|uncertainty)", re.I)

def prelabel(D, body_of=None):
    """v2.5 / brief v3: deterministic not_data labels, so these never reach the extractors' judgment or adjudication.
    copies (span_copy_of, nested_copy_of, repeated_header) -> 'copy'; the lone 95 of '95% CI' -> 'ci_level_label';
    malformed cells -> flagged, never data."""
    for c in D["candidates"]:
        a = c["anchor"]
        if c["kind"] in ("table_cell", "row_label", "table_header", "table_caption", "table_footnote", "text_span") and MALFORMED.search(c["text"] or ""):
            c["malformed"] = True
        if a.get("span_copy_of") or a.get("nested_copy_of") or a.get("repeated_header"):
            c["prelabel"] = {"not_data": "copy"}; continue
        ns = c["numbers"]
        if len(ns) == 1 and ns[0]["value"] == 95:
            if c["kind"] == "text_span":
                after = (c.get("local_context") or "")
                i = after.find(c["text"], max(0, len(after) // 2 - len(c["text"]) - 200))
                tail = after[i + len(c["text"]):] if i >= 0 else ""
                pct = ns[0].get("role_hint") == "percent" or c["text"].rstrip().endswith("%")
                if pct and CI95.match(tail) or (not pct and re.match(r"^\s*%\s*(CI|C\.I\.|confidence|credible)", tail, re.I)):
                    c["prelabel"] = {"not_data": "ci_level_label"}
            elif re.search(r"95\s?%\s*(CI|C\.I\.|confidence|credible|uncertainty)", c["text"], re.I):
                c["prelabel"] = {"not_data": "ci_level_label"}
    return D

def summary(D):
    k = {}
    for c in D["candidates"]: k[c["kind"]] = k.get(c["kind"], 0) + 1
    return {"doc": D["doc"], "tables": len(D["tables"]), "figures": len(D["figures"]),
            "supplements": len(D["supplements"]), "candidates": k,
            "numbers": sum(len(c["numbers"]) for c in D["candidates"])}

if __name__ == "__main__":
    D = parse(sys.argv[1]); json.dump(D, open(sys.argv[2], "w"), indent=1); print(json.dumps(summary(D)))
