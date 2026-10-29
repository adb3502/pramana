"""Parse every raw_pdf/*.pdf (or the given doc ids) with parse_pdf into parsed_pdf/, one converter for all."""
import sys, os, glob, json, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from epistemic import parse_pdf
docs = sys.argv[1:] or sorted(os.path.basename(p)[:-4] for p in glob.glob("raw_pdf/*.pdf"))
for d in docs:
    try:
        D = parse_pdf.parse(f"raw_pdf/{d}.pdf")
        json.dump(D, open(f"parsed_pdf/{d}.json", "w"), indent=1)
        print(json.dumps(parse_pdf.summary(D)), flush=True)
    except Exception:
        print(d, "FAILED", traceback.format_exc()[-800:], flush=True)
