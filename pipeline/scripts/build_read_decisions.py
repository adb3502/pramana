"""Rebuild read decisions for a PDF doc after a re-parse: rules (read_rules.py R1-R3, plus R4 split numbers, R5 misread ±,
R6 docling numbers found in order in the cell OCR) and earlier Opus decisions carried over only where the candidate text and
numbers are unchanged. Unresolved -> listed. usage: build_read_decisions.py DOC [OLD_PARSED]"""
import sys, json, re, os
d = sys.argv[1]; oldp = sys.argv[2] if len(sys.argv) > 2 else f"work/parsed_extracted/{d}.json"
D = json.load(open(f"parsed_pdf/{d}.json")); C = {c["id"]: c for c in D["candidates"]}
cv = json.load(open(f"work/crops/{d}.crop_variants.json"))
old = json.load(open(oldp)); O = {c["id"]: c for c in old["candidates"]}
prev = {}
for f in (f"work/read_adj/{d}.decisions.json",):
    if os.path.exists(f): prev = json.load(open(f))
key = lambda ns: [(round(x["value"], 9) if x["value"] is not None else None, x.get("qualifier")) for x in ns]
dig = lambda ns: "".join(re.sub(r"\D", "", x["raw"]) for x in ns)
src_nums = lambda c: c.get("numbers_docling") or c["numbers"]
dec, todo = {}, []
nc = [c for c in D["candidates"] if c.get("needs_check")]
for c in nc:
    i = c["id"]; oc = cv.get(i, {}).get("numbers", []); po = c["read_variants"].get("ocr", []); dn = c["numbers"]
    o = O.get(i)
    same = o is not None and o["text"] == c["text"] and key(src_nums(o)) == key(dn)
    if same and i in prev:   # unchanged candidate: keep the earlier decision (rule or Opus)
        dec[i] = prev[i]; continue
    if oc and key(oc) == key(dn): dec[i] = {"choice": "docling", "note": "R1 crop OCR equals docling", "adjudicator": "rule"}
    elif oc and po and key(oc) == key(po): dec[i] = {"choice": "ocr", "note": "R2 crop OCR equals page OCR", "adjudicator": "rule"}
    elif po and dig(po) == dig(dn) and (not oc or dig(oc) == dig(po)): dec[i] = {"choice": "ocr", "note": "R3 same digits, separator misread", "adjudicator": "rule"}
    else:
        drop6 = [x for k, x in enumerate(dn) if not (x["value"] == 6 and x.get("qualifier") is None and 0 < k)]
        kk = key(drop6); ko = key(oc)
        if oc and len(drop6) < len(dn) and kk == ko[:len(kk)]:
            dec[i] = {"choice": "picks", "picks": [["ocr_crop", k] for k in range(len(kk))], "note": "R5 '6' is a misread ± (font swap); crop OCR has the other numbers", "adjudicator": "rule"}
        elif oc and c["kind"] == "text_span" and all(x in ko for x in key(dn)) and dn and dn[0]["raw"][:1] != ".":
            dec[i] = {"choice": "docling", "note": "R6 docling numbers present in the line OCR", "adjudicator": "rule"}
        else: todo.append(i)
json.dump(dec, open(f"work/read_adj/{d}.decisions.json", "w"), indent=1); open(f"work/read_adj/{d}.todo.txt", "w").write("\n".join(todo))
print(d, "needs_check", len(nc), "decided", len(dec), "todo", todo)
