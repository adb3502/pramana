"""Item 4 (mission 2): confirm the PMC12178019 paper findings (JATS cells) in the typeset PDF.
For each finding cell (logs/paper_findings.jsonl + the malformed cell), find the PDF candidate in parsed_pdf/<doc>.json with the
same table number and the same numbers, record its page/bbox/read_agree, and render a crop sheet work/crops/<doc>_findings.png."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymupdf
from PIL import Image, ImageDraw, ImageFont
doc = sys.argv[1]
J = {c["id"]: c for c in json.load(open(f"parsed/{doc}.json"))["candidates"]}
P = json.load(open(f"parsed_pdf/{doc}.json"))["candidates"]
F = [json.loads(l) for l in open("logs/paper_findings.jsonl") if json.loads(l)["doc"] == doc]
F += [{"candidate": c["id"], "finding": "malformed cell"} for c in J.values() if c.get("malformed")]
tn = lambda t: re.sub(r"\D", "", t or "")
out = []
for f in F:
    j = J[f["candidate"].split("+")[0]]; key = [(x["value"], x["qualifier"]) for x in j["numbers"]]
    hits = [c for c in P if tn(c["anchor"].get("table")) == tn(j["anchor"].get("table")) and [(x["value"], x["qualifier"]) for x in c["numbers"]] == key]
    near = sorted(hits, key=lambda c: abs(c["anchor"]["row"] - j["anchor"]["row"]) + abs(c["anchor"]["col"] - j["anchor"]["col"]))
    h = near[0] if near else None
    out.append({"jats_candidate": j["id"], "jats_anchor": j["anchor"], "text": j["text"], "finding": f["finding"],
                "pdf_candidate": h and h["id"], "pdf_anchor": h and h["anchor"], "pdf_text": h and h["text"],
                "read_agree": h and all(x.get("read_agree") for x in h["numbers"]), "n_matches_in_table": len(hits)})
pdf = pymupdf.open(f"raw_pdf/{doc}.pdf"); tiles = []
from epistemic.parse_pdf import page_dirs, dir_of
dirs = page_dirs(pdf)
for k, o in enumerate(out):
    if not o["pdf_anchor"]: continue
    a = o["pdf_anchor"]; page = pdf[a["page"] - 1]; r = pymupdf.Rect(a["bbox"]) + (-30, -6, 30, 6)
    rot = dir_of(dirs[a["page"] - 1], pymupdf.Rect(a["bbox"])) or 0
    r = r * page.rotation_matrix; r.normalize(); r &= page.rect
    pix = page.get_pixmap(dpi=200, clip=r); im = Image.frombytes("RGB", (pix.w, pix.h), pix.samples)
    if (rot - page.rotation) % 360: im = im.rotate(-((rot - page.rotation) % 360), expand=True)
    tiles.append((k, im))
W = max(im.width for _, im in tiles) + 60; H = sum(im.height + 16 for _, im in tiles)
sh = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(sh); y = 0; font = ImageFont.load_default(size=22)
for k, im in tiles:
    d.text((4, y + 4), str(k), fill="red", font=font); sh.paste(im, (56, y)); y += im.height + 8; d.line([(0, y + 3), (W, y + 3)], fill="gray"); y += 8
sh.save(f"work/crops/{doc}_findings.png")
json.dump(out, open(f"validation/pdf/{doc}.findings_in_pdf.json", "w"), indent=1)
for k, o in enumerate(out): print(k, o["jats_anchor"].get("table"), o["jats_anchor"].get("row"), o["jats_anchor"].get("col"), repr(o["text"]), "->", o["pdf_candidate"], o["pdf_anchor"] and (o["pdf_anchor"]["page"], o["pdf_anchor"]["row"], o["pdf_anchor"]["col"]), "agree", o["read_agree"], o["finding"][:30])
