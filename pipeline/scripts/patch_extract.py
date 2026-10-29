"""Targeted re-extraction after a parser fix changes a few candidates (mission 2).
  prep DOC OLD_PARSED   -> work/patch/DOC.json: the changed candidates (new parse) with their table row / paragraph context
  run DOC               -> headless A (sonnet) and B (sonnet + order seed) write ext/DOC.<S>.patch.json for exactly those ids
  merge DOC             -> replace those ids' records in ext/DOC.A.json and ext/DOC.B.json (old files kept as .prepatch), ledger
Disputes on patched ids are then adjudicated by scripts/adjudicate.py as usual (finish step re-run)."""
import sys, os, json, subprocess, pathlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
cmd, d = sys.argv[1], sys.argv[2]
P = pathlib.Path("work/patch"); P.mkdir(parents=True, exist_ok=True)
if cmd == "prep":
    old = {c["id"]: c for c in json.load(open(sys.argv[3]))["candidates"]}; new = json.load(open(f"parsed/{d}.json"))
    key = lambda c: (c["kind"], [(x["value"], x.get("qualifier")) for x in c["numbers"]], bool(c.get("needs_check")))
    ch = [c for c in new["candidates"] if c["id"] not in old or key(old[c["id"]]) != key(c)]
    rows = {}
    for T in new["tables"]:
        for ri, r in enumerate(T["rows"]): rows[(T["id"], ri)] = r["cells"]
    for c in ch:
        a = c["anchor"]
        if "table" in a and "row" in a:
            T = next(t for t in new["tables"] if t["id"] == a["table"])
            c["table_context"] = {"caption": T["caption"][:300], "header_rows": [r["cells"] for r in T["rows"][:3]], "this_row": rows.get((a["table"], a["row"]))}
    json.dump({"doc": d, "parser": new["parser"], "changed": ch}, open(P / f"{d}.json", "w"), indent=1)
    print(d, "changed candidates", len(ch))
elif cmd == "run":
    procs = []
    for side in ("A", "B"):
        seed = " Work through the candidates from last to first." if side == "B" else ""
        prompt = (f"Read briefs/EXTRACT_BRIEF.md (v3) and follow its rules and vocabulary. A parser fix changed a few candidates of {d}. "
                  f"Input: work/patch/{d}.json (the changed candidates, with table context) and your earlier full output ext/{d}.{side}.json "
                  f"(reuse its variable_id, group_id, model_id values; add new ones only if needed, in the same style). The full paper parse is parsed/{d}.json if you need more context. "
                  f"Output: ext/{d}.{side}.patch.json = {{\"doc\", \"data\": [...], \"not_data\": [...], \"new_variables\": [], \"new_groups\": [], \"new_models\": []}} "
                  f"with exactly one record for every candidate id in work/patch/{d}.json and no others; roles has one entry per number in the NEW numbers list. "
                  f"Never type a number. Write and run a Python script under work/patch/{d}.{side}/ with plain python3 that builds the output and asserts coverage and roles length.{seed}")
        out = open(f"logs/{d}.{side}.patch.json", "w")
        procs.append(subprocess.Popen([os.path.expanduser("~/.local/bin/claude"), "-p", prompt, "--model", "sonnet", "--allowedTools", "Read", "Write", "Edit",
                                       "Bash(python3:*)", "Bash(mkdir:*)", "Bash(ls:*)", "--output-format", "json"], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT))
    for p in procs: p.wait()
    print(d, [os.path.exists(f"ext/{d}.{s}.patch.json") for s in "AB"])
elif cmd == "merge":
    from epistemic import store
    ids = {c["id"] for c in json.load(open(P / f"{d}.json"))["changed"]}
    for side in ("A", "B"):
        e = json.load(open(f"ext/{d}.{side}.json")); pt = json.load(open(f"ext/{d}.{side}.patch.json"))
        got = {r["id"] for r in pt.get("data", [])} | {r["id"] for r in pt.get("not_data", [])}
        assert got == ids, (side, sorted(ids - got)[:5], sorted(got - ids)[:5])
        pathlib.Path(f"ext/{d}.{side}.prepatch.json").write_text(json.dumps(e))
        e["data"] = [r for r in e.get("data", []) if r["id"] not in ids] + pt.get("data", [])
        e["not_data"] = [r for r in e.get("not_data", []) if r["id"] not in ids] + pt.get("not_data", [])
        for k, kk in (("variables", "new_variables"), ("groups", "new_groups"), ("models", "new_models")): e.setdefault(k, []).extend(pt.get(kk, []))
        json.dump(e, open(f"ext/{d}.{side}.json", "w"), indent=1)
        store.append("extraction_event", {"doc": d, "extractor": "sonnet", "side": side, "brief": "EXTRACT_BRIEF v3", "kind": "patch",
                                          "patched_ids": len(ids), "patch_sha256": store.file_hash(f"ext/{d}.{side}.patch.json"), "output_sha256": store.file_hash(f"ext/{d}.{side}.json")})
    # adjudications for patched ids are stale
    ap = pathlib.Path(f"ext/{d}.adj.json")
    if ap.exists():
        a = json.load(open(ap)); a["decisions"] = [x for x in a["decisions"] if x["datum_id"].split("#")[0] not in ids]; json.dump(a, open(ap, "w"), indent=1)
    print(d, "merged", len(ids))
