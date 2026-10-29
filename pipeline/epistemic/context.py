"""Build the human-readable context for one candidate: what a reader sees around the number.
Shared by the local extractor, the typed judges and adjudication."""

def table_index(P):
    return {t["id"]: t for t in P["tables"]}

def header_for(t, col):
    hs = [r["cells"][col] for r in t["rows"] if r["is_head"] and col < len(r["cells"]) and r["cells"][col]]
    out = []
    for h in hs:
        if h not in out: out.append(h)
    return " / ".join(out)

def section_label(rows, ri):
    """Nearest preceding row that has text only in column 0 (a section row such as 'Heart disease')."""
    for r in range(ri - 1, -1, -1):
        cells = rows[r]["cells"]
        if cells and cells[0] and all((c == cells[0] or not c) for c in cells[1:]):
            return cells[0]
    return ""

def describe(P, c, tables=None):
    tables = tables or table_index(P)
    a = c["anchor"]
    if "table" in a and "row" in a:
        t = tables[a["table"]]; rows = t["rows"]; r = rows[a["row"]]
        return {"where": f"table {a['table']} row {a['row']} col {a['col']}",
                "table_caption": t["caption"][:300],
                "column_header": header_for(t, a["col"]),
                "row_label": r["cells"][0] if r["cells"] else "",
                "row_section": section_label(rows, a["row"]),
                "cell_text": c["text"],
                "footnote_excerpt": t.get("footnotes", "")[:300]}
    if "table" in a:
        t = tables[a["table"]]
        return {"where": f"table {a['table']} {a.get('part')}", "text": c["text"][:600]}
    return {"where": a.get("section") or a.get("figure"), "text_around": c.get("local_context") or c["text"],
            "highlight": c["text"]}
