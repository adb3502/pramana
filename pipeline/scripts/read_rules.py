"""Deterministic read decisions for PDF needs_check candidates (before eye review of crops):
  R1 the tight cell-crop OCR equals the docling read            -> docling
  R2 the tight cell-crop OCR equals the page OCR (non-empty)     -> ocr   (two OCR passes, different clip and resolution)
  R3 (scans) same digits in text layer and both OCR passes, only separators differ (mid-dot read as hyphen) -> ocr
Everything else is listed for review against the crop. usage: read_rules.py DOC  -> work/read_adj/DOC.rules.json, DOC.review.txt"""
import sys, json, re
d = sys.argv[1]
D = json.load(open(f"parsed_pdf/{d}.json")); cv = json.load(open(f"work/crops/{d}.crop_variants.json"))
key = lambda ns: [(round(x["value"], 9) if x["value"] is not None else None, x.get("qualifier")) for x in ns]
dig = lambda ns: "".join(re.sub(r"\D", "", x["raw"]) for x in ns)
dec, review = {}, []
for c in D["candidates"]:
    if not c.get("needs_check") or c["id"] not in cv: continue
    oc = cv[c["id"]]["numbers"]; po = c.get("read_variants", {}).get("ocr", [])
    if oc and key(oc) == key(c["numbers"]): dec[c["id"]] = {"choice": "docling", "note": "R1 crop OCR equals docling", "adjudicator": "rule"}
    elif oc and po and key(oc) == key(po): dec[c["id"]] = {"choice": "ocr", "note": "R2 crop OCR equals page OCR", "adjudicator": "rule"}
    elif po and dig(po) == dig(c["numbers"]) and (not oc or dig(oc) == dig(po)): dec[c["id"]] = {"choice": "ocr", "note": "R3 same digits, separator misread in text layer", "adjudicator": "rule"}
    else: review.append(c["id"])
json.dump(dec, open(f"work/read_adj/{d}.rules.json", "w"), indent=1); open(f"work/read_adj/{d}.review.txt", "w").write("\n".join(review))
print(d, "rules", len(dec), {k: sum(1 for v in dec.values() if v["note"].startswith(k)) for k in ("R1", "R2", "R3")}, "review", len(review))
