"""List needs_check numbers of a parsed_pdf doc: docling text vs the independent reads."""
import sys, json, collections
D = json.load(open(f"parsed_pdf/{sys.argv[1]}.json")); lim = int(sys.argv[2]) if len(sys.argv) > 2 else 30
para = {}
for c in D["candidates"]:
    if "para_reads" in c: para[(c["anchor"]["section"], c["anchor"]["para"])] = c["para_reads"]
k = 0
for c in D["candidates"]:
    if not c.get("needs_check"): continue
    bad = [x["raw"] for x in c["numbers"] if not x["read_agree"]]
    r = c.get("reads") or para.get((c["anchor"].get("section"), c["anchor"].get("para")), {})
    if c["kind"] == "text_span":
        ctx = c["local_context"]; i = ctx.find(c["text"]); doc_t = ctx[max(0, i - 50):i + 50]
        rr = {s: (t[max(0, t.find(bad[0].split()[-1]) - 60):t.find(bad[0].split()[-1]) + 40] if bad[0].split()[-1] in t else "<not found> " + t[:60]) for s, t in r.items()}
    else:
        doc_t = c["text"][:100]; rr = {s: t[:100] for s, t in r.items()}
    print(c["id"], c["kind"], c["anchor"].get("page"), "BAD", bad, "| DOC:", repr(doc_t), "|", {s: repr(t) for s, t in rr.items()})
    k += 1
    if k >= lim: break
