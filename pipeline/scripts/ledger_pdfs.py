"""Append a raw_doc ledger event (source user_download) for every PDF in raw_pdf/ not yet ledgered. Idempotent."""
import sys, os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import glob, pathlib, json
from epistemic import store
done = {json.loads(l)["body"].get("sha256") for l in open("ledger.jsonl") if '"raw_doc"' in l}
for p in sorted(glob.glob("raw_pdf/*.pdf")):
    h = store.file_hash(p)
    if h in done: continue
    store.append("raw_doc", {"doc": pathlib.Path(p).stem, "path": p, "sha256": h, "bytes": pathlib.Path(p).stat().st_size, "format": "pdf", "source": "user_download"})
    print("ledgered", p)
print(store.verify())
