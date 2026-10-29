"""Compare the PDF parser against the JATS parser for a doc that has both (item 3, mission 2).
Table numbers: per table (JATS TabK <-> PDF TK), numbers in row-major order are aligned by value+qualifier
(difflib); recall = matched / JATS numbers, precision = matched / PDF numbers. Matched pairs are also checked
for the same column and the same row (after the repeated-header offset). Unmatched numbers are classified by cause.
Text numbers: multiset recall/precision of (value, qualifier) over all body/abstract text spans.
usage: python scripts/compare_pdf_jats.py DOC [--json out.json]
"""
import sys, os, json, re, difflib, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TABLE_KINDS = {"table_cell", "row_label", "table_header"}

def key(n): return (None if n["value"] is None else round(n["value"], 10), n.get("qualifier"))

def tnum(tid):
    m = re.search(r"(\d+)", tid or ""); return int(m.group(1)) if m else None

def table_numbers(D, pdf):
    out = collections.defaultdict(list)
    for c in D["candidates"]:
        a = c["anchor"]
        if c["kind"] not in TABLE_KINDS: continue
        if a.get("span_copy_of") or a.get("repeated_header"): continue
        if pdf and re.search(r"_\d+$", a["table"]): pass
        for i, n in enumerate(c["numbers"]):
            if n.get("superscript"): continue   # footnote marks and unit exponents (kg/m2): JATS keeps them inside words
            out[tnum(a["table"])].append({"key": key(n), "raw": n["raw"], "row": a["row"], "col": a["col"], "text": c["text"],
                                          "kind": c["kind"], "agree": n.get("read_agree")})
    for k in out: out[k].sort(key=lambda x: (x["row"], x["col"]))
    return out

def norm(t): return re.sub(r"[^a-z0-9]", "", (t or "").lower().replace("·", "."))

def row_labels(D):
    """{(table number, row): (row label, section label)}; section = the last label-only row above (e.g. 'Coffee (cups/d)')."""
    out = {}
    for T in D["tables"]:
        sec = ""
        for ri, r in enumerate(T["rows"]):
            cells = r["cells"]; lab = cells[0] if cells else ""
            if lab and all(not c.strip() or c == lab for c in cells[1:]) and not r.get("is_head"): sec = lab   # label-only row (JATS colspans repeat the label)
            out[(tnum(T["id"]), ri)] = (lab, sec)
    return out

def classify(op, J, P):
    if op == "delete": return "missing_in_pdf"
    if op == "insert": return "extra_in_pdf"
    if len(J) == len(P):
        if all(a["key"][0] == b["key"][0] for a, b in zip(J, P)): return "qualifier_differs"
        return "value_differs"
    return "split_or_merged"

def compare(doc):
    J = json.load(open(f"parsed/{doc}.json")); P = json.load(open(f"parsed_pdf/{doc}.json"))
    jt, pt = table_numbers(J, False), table_numbers(P, True)
    jl, pl = row_labels(J), row_labels(P)
    lab = {"pairs": 0, "label_equal": 0, "section_equal": 0, "offset_pairs": 0, "offset_label_equal": 0, "offset_section_equal": 0, "label_mismatch_examples": []}
    res = {"doc": doc, "jats_parser": J["parser"], "pdf_parser": P["parser"], "tables": {}, "mismatches": []}
    TJ = TP = TM = TC = TR = 0
    for t in sorted(set(jt) | set(pt), key=lambda x: (x is None, x)):
        a, b = jt.get(t, []), pt.get(t, [])
        sm = difflib.SequenceMatcher(None, [x["key"] for x in a], [x["key"] for x in b], autojunk=False)
        m = col = row = 0; offs = collections.Counter()
        for i, j, size in sm.get_matching_blocks():
            for k in range(size):
                m += 1; col += a[i + k]["col"] == b[j + k]["col"]; offs[b[j + k]["row"] - a[i + k]["row"]] += 1
                x, y = a[i + k], b[j + k]
                if x["kind"] == "table_cell":
                    (la, sa), (lb, sb) = jl.get((t, x["row"]), ("", "")), pl.get((t, y["row"]), ("", ""))
                    eq, se = norm(la) == norm(lb), norm(sa) == norm(sb); off = x["row"] != y["row"]
                    lab["pairs"] += 1; lab["label_equal"] += eq; lab["section_equal"] += se
                    if off: lab["offset_pairs"] += 1; lab["offset_label_equal"] += eq; lab["offset_section_equal"] += se
                    if not (eq and se) and len(lab["label_mismatch_examples"]) < 15:
                        lab["label_mismatch_examples"].append({"table": t, "jats_row": x["row"], "pdf_row": y["row"], "col": x["col"], "raw": x["raw"],
                                                               "jats": [la, sa], "pdf": [lb, sb]})
        ops = [o for o in sm.get_opcodes() if o[0] != "equal"]
        # a delete and an insert of the same numbers next to each other = the cell landed in another row/col
        pend = {}
        for o in ops:
            if o[0] in ("delete", "insert"):
                ks = tuple(x["key"] for x in (a[o[1]:o[2]] if o[0] == "delete" else b[o[3]:o[4]]))
                other = "insert" if o[0] == "delete" else "delete"
                if (other, ks) in pend: pend[(other, ks)].append(o); pend[(o[0], ks, "pair")] = True
                else: pend.setdefault((o[0], ks), [])
        paired = {k[1] for k in pend if len(k) == 3}
        for tag, i1, i2, j1, j2 in ops:
            ks = tuple(x["key"] for x in (a[i1:i2] if tag == "delete" else b[j1:j2]))
            if tag in ("delete", "insert") and ks in paired:
                res["mismatches"].append({"table": t, "cause": "cell_in_other_row_or_col (counted unmatched)",
                                          "jats": [(x["raw"], x["row"], x["col"]) for x in a[i1:i2]][:6],
                                          "pdf": [(x["raw"], x["row"], x["col"]) for x in b[j1:j2]][:6], "n_jats": i2 - i1, "n_pdf": j2 - j1})
                continue
            res["mismatches"].append({"table": t, "cause": classify(tag, a[i1:i2], b[j1:j2]),
                                      "jats": [(x["raw"], x["row"], x["col"], x["text"][:60]) for x in a[i1:i2]][:6],
                                      "pdf": [(x["raw"], x["row"], x["col"], x["text"][:60]) for x in b[j1:j2]][:6],
                                      "n_jats": i2 - i1, "n_pdf": j2 - j1})
        # rows: most matched pairs share one offset per table segment; count pairs whose offset is a common one
        row = sum(v for o, v in offs.items() if v >= 0.05 * max(m, 1))
        res["tables"][str(t)] = {"jats": len(a), "pdf": len(b), "matched": m,
                                 "recall": round(m / len(a), 4) if a else None, "precision": round(m / len(b), 4) if b else None,
                                 "same_col": col, "row_offsets": dict(offs.most_common(4))}
        TJ += len(a); TP += len(b); TM += m; TC += col
    res["table_total"] = {"jats": TJ, "pdf": TP, "matched": TM, "recall": round(TM / TJ, 4) if TJ else None,
                          "precision": round(TM / TP, 4) if TP else None, "same_col_of_matched": round(TC / TM, 4) if TM else None}
    res["row_labels"] = lab
    res["mismatch_causes"] = dict(collections.Counter(x["cause"] for x in res["mismatches"]))
    res["mismatch_numbers_by_cause"] = {c: [sum(x["n_jats"] for x in res["mismatches"] if x["cause"] == c),
                                            sum(x["n_pdf"] for x in res["mismatches"] if x["cause"] == c)] for c in res["mismatch_causes"]}
    tj = collections.Counter(key(n) for c in J["candidates"] if c["kind"] == "text_span" and not c["anchor"].get("nested_copy_of") for n in c["numbers"])
    tp = collections.Counter(key(n) for c in P["candidates"] if c["kind"] == "text_span" for n in c["numbers"] if not n.get("superscript"))
    inter = sum((tj & tp).values())
    res["text_total"] = {"jats": sum(tj.values()), "pdf": sum(tp.values()), "matched_multiset": inter,
                         "recall": round(inter / max(1, sum(tj.values())), 4), "precision": round(inter / max(1, sum(tp.values())), 4)}
    return res

if __name__ == "__main__":
    r = compare(sys.argv[1])
    if "--json" in sys.argv: json.dump(r, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
    print(json.dumps({k: r[k] for k in ("doc", "pdf_parser", "table_total", "mismatch_causes", "mismatch_numbers_by_cause", "text_total", "row_labels")}, indent=0))
    for t, v in r["tables"].items(): print(t, v)
    if "-v" in sys.argv:
        for x in r["mismatches"][:40]: print(json.dumps(x, ensure_ascii=False))
