"""Re-parse finished JATS docs with the current parser. Value/qualifier-only changes keep candidate ids and number indices,
so the parse is installed (old kept in work/reparse/<doc>.<oldparser>.json) and the doc is listed for revalidation.
Structure changes (ids, kinds or number counts) are NOT installed; they are listed for scripts/patch_extract.py.
usage: reparse_jats.py [DOC ...]   (default: every doc with ext/<doc>.adj.json and a JATS parse)"""
import sys, os, json, glob, shutil
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from epistemic import parse, store
docs = sys.argv[1:] or sorted(os.path.basename(p)[:-9] for p in glob.glob("ext/*.adj.json"))
os.makedirs("work/reparse", exist_ok=True); vals, structs = [], []
for d in docs:
    if not os.path.exists(f"raw/{d}.xml") or not os.path.exists(f"parsed/{d}.json"): continue
    old = json.load(open(f"parsed/{d}.json"))
    if old.get("source_format") == "pdf": continue
    new = parse.parse(f"raw/{d}.xml")
    O = {c["id"]: c for c in old["candidates"]}; N = {c["id"]: c for c in new["candidates"]}
    shape = lambda c: (c["kind"], len(c["numbers"]))
    st = [i for i in set(O) | set(N) if i not in O or i not in N or shape(O[i]) != shape(N[i])]
    key = lambda c: [(x["value"], x.get("qualifier")) for x in c["numbers"]] + [c.get("prelabel"), c.get("malformed")]
    vc = [i for i in set(O) & set(N) if i not in st and key(O[i]) != key(N[i])]
    if st:
        structs.append(d); json.dump(new, open(f"work/reparse/{d}.{new['parser'].split()[-1]}.json", "w"), indent=1)
        print(d, "STRUCT", len(st), "value", len(vc)); continue
    if not vc and old.get("parser") == new["parser"]: continue
    shutil.copy(f"parsed/{d}.json", f"work/reparse/{d}.{old.get('parser', 'x').split()[-1]}.json")
    json.dump(new, open(f"parsed/{d}.json", "w"), indent=1)
    store.append("parse_event", {"doc": d, "parser": new["parser"], "raw_sha256": store.file_hash(f"raw/{d}.xml"), "parsed_sha256": store.file_hash(f"parsed/{d}.json"),
                                 "previous_parser": old.get("parser"), "value_changes": len(vc), "struct_changes": 0})
    if vc: vals.append(d); print(d, "value-only", len(vc))
json.dump({"value_only": vals, "struct": structs}, open("work/reparse/last.json", "w"))
print("value-only", len(vals), "struct", len(structs), structs)
