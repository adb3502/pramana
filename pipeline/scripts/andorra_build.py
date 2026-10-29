"""Build work/andorra_candidates.json from a reference list fetched elsewhere (OpenAlex budget on this IP is spent):
download open-access PDFs for the references, add PMC ids where known, seed added when raw_pdf/W7172483893.pdf exists."""
import os, sys, json, time, hashlib, requests
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import store
R = json.load(open(os.path.expanduser("~/andorra_refs.json")))
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) epistemic-framework/0.4 (research use)"
works = []
seed = R["seed"]["id"]
if os.path.exists(f"raw_pdf/{seed}.pdf"): works.append({"id": seed, "role": "seed", "doi": R["seed"]["doi"], "pdf": f"raw_pdf/{seed}.pdf", "pmcid": None, "in_store": False})
for wid, pmc in R["pmc"].items(): works.append({"id": wid, "role": "cited_by_seed", "pmcid": pmc, "pdf": None, "in_store": False})
for r in R["refs"]:
    if r["id"] in R["pmc"]: continue
    dest = f"raw_pdf/{r['id']}.pdf"
    if not os.path.exists(dest) and r.get("pdf_url"):
        try:
            x = S.get(r["pdf_url"], timeout=90, allow_redirects=True)
            if x.ok and x.content[:5] == b"%PDF-":
                open(dest, "wb").write(x.content)
                store.append("raw_doc", {"doc": r["id"], "source": r["pdf_url"], "sha256": hashlib.sha256(x.content).hexdigest(), "kind": "pdf"})
        except Exception: pass
        time.sleep(1)
    if os.path.exists(dest): works.append({"id": r["id"], "role": "cited_by_seed", "doi": r["doi"], "pdf": dest, "pmcid": None, "in_store": False})
json.dump({"thread": "andorra", "seed": seed, "works": works, "closed_refs": R["closed_refs"]}, open("work/andorra_candidates.json", "w"), indent=1)
print(json.dumps({"seed_pdf": os.path.exists(f"raw_pdf/{seed}.pdf"), "pdf_refs": sum(1 for w in works if w["pdf"] and w["role"] != "seed"), "pmc_refs": len(R["pmc"]),
                  "refs_with_oa_url": len(R["refs"]), "closed_refs": R["closed_refs"]}))
