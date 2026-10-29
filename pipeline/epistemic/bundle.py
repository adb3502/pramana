"""Fetch every file attached to a PMC article (figures, image tables, supplements) from Europe PMC, unpack, hash, ledger.
bundles/<doc>/<file>; bundles/<doc>/MANIFEST.json. Usage: python -m epistemic.bundle PMC... | --all"""
import sys, os, io, json, glob, time, zipfile, hashlib, pathlib, requests
from lxml import etree
from . import store
URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{}/supplementaryFiles"
PMC_BIN = "https://pmc.ncbi.nlm.nih.gov/articles/instance/{}/bin/{}"

def jats_inventory(doc):
    """What the JATS says should exist: table-wraps (real table or image), figures, supplements, with their hrefs."""
    try: t = etree.parse(f"raw/{doc}.xml", etree.XMLParser(recover=True, huge_tree=True))
    except (OSError, etree.XMLSyntaxError): return {"tables": [], "figures": [], "supplements": [], "error": "unparseable raw xml"}
    if t.getroot() is None: return {"tables": [], "figures": [], "supplements": [], "error": "empty raw xml"}
    href = lambda el: [h.rsplit("/", 1)[-1] for h in el.xpath(".//*[local-name()='graphic' or local-name()='media']/@*[local-name()='href']")]
    tabs = [{"id": tw.get("id"), "has_table": bool(tw.xpath(".//table")), "graphics": href(tw)} for tw in t.xpath("//table-wrap")]
    figs = [{"id": f.get("id"), "graphics": href(f)} for f in t.xpath("//fig")]
    supp = [{"id": s.get("id"), "files": href(s)} for s in t.xpath("//supplementary-material")]
    return {"tables": tabs, "figures": figs, "supplements": supp}

def fetch(doc, out="bundles"):
    d = pathlib.Path(out) / doc; d.mkdir(parents=True, exist_ok=True)
    man = d / "MANIFEST.json"
    if man.exists():
        M = json.load(open(man))
        if M.get("v", 1) >= 2: return M
    files_prev = None
    err = None
    for a in range(4):
        try:
            r = requests.get(URL.format(doc), timeout=120)
            if r.status_code == 404: err = "404"; break
            r.raise_for_status(); break
        except requests.RequestException as e: err = str(e)[:200]; time.sleep(10 * (a + 1))
    files = []
    if err is None:
        try:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            for zi in z.infolist():
                if zi.is_dir(): continue
                name = pathlib.Path(zi.filename).name; b = z.read(zi)
                (d / name).write_bytes(b); files.append({"file": name, "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
        except zipfile.BadZipFile: err = "not a zip"
    J = jats_inventory(doc)
    # fallback: any JATS-declared file Europe PMC did not ship (common for NIH manuscripts) from PMC's own file path
    have = {f["file"] for f in files} | {f["file"].rsplit(".", 1)[0] for f in files}
    want = [g for t in J["tables"] if not t["has_table"] for g in t["graphics"]] + [g for f in J["figures"] for g in f["graphics"]] + [g for s in J["supplements"] for g in s["files"]]
    for h in want:
        if h in have or h.rsplit(".", 1)[0] in have: continue
        for name in ([h] if "." in h else [h + ".jpg", h + ".gif"]):
            try:
                r2 = requests.get(PMC_BIN.format(doc[3:], name), timeout=120)
                if r2.ok and len(r2.content) > 500 and not r2.headers.get("content-type", "").startswith("text/html"):
                    (d / name).write_bytes(r2.content); files.append({"file": name, "bytes": len(r2.content), "sha256": hashlib.sha256(r2.content).hexdigest(), "via": "pmc_bin"})
                    have.add(name); break
            except requests.RequestException: pass
            time.sleep(0.5)
    if err and files: err = None
    M = {"doc": doc, "v": 2, "source": URL.format(doc), "error": err, "files": files, "jats": J}
    json.dump(M, open(man, "w"), indent=1)
    store.append("raw_bundle", {"doc": doc, "error": err, "files": [{"file": f["file"], "sha256": f["sha256"]} for f in files]})
    time.sleep(0.5)
    return M

def match(M):
    """Map every JATS-declared object to a retrieved file. Returns gaps: objects with no file."""
    have = {f["file"].rsplit(".", 1)[0]: f["file"] for f in M["files"]} | {f["file"]: f["file"] for f in M["files"]}
    def find(h): return have.get(h) or have.get(h.rsplit(".", 1)[0])
    out = {"image_tables": [], "figures": [], "supplements": [], "missing": []}
    for t in M["jats"]["tables"]:
        if not t["has_table"]:
            fs = [find(g) for g in t["graphics"]]
            out["image_tables"].append({"id": t["id"], "files": [f for f in fs if f]})
            if not any(fs): out["missing"].append(("image_table", t["id"]))
    for f in M["jats"]["figures"]:
        fs = [find(g) for g in f["graphics"]]
        out["figures"].append({"id": f["id"], "files": [x for x in fs if x]})
        if not any(fs): out["missing"].append(("figure", f["id"]))
    for s in M["jats"]["supplements"]:
        fs = [find(g) for g in s["files"]]
        out["supplements"].append({"id": s["id"], "files": [x for x in fs if x]})
        if s["files"] and not any(fs): out["missing"].append(("supplement", s["id"]))
    return out

if __name__ == "__main__":
    docs = sorted(pathlib.Path(p).stem for p in glob.glob("raw/*.xml")) if sys.argv[1:] == ["--all"] else sys.argv[1:]
    for doc in docs:
        M = fetch(doc); g = match(M)
        print(json.dumps({"doc": doc, "err": M["error"], "files": len(M["files"]), "image_tables": len(g["image_tables"]),
                          "figures": len(g["figures"]), "supplements": len(g["supplements"]), "missing": g["missing"]}), flush=True)
