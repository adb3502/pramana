"""Closed-paper gate v1: a paper is CLOSED only when nothing about it still needs the original.
Checks (each recorded with its count, so an open paper says exactly what is left):
  files      every JATS-declared figure, image table and supplement retrieved, or recorded as unobtainable
  parsed     every retrieved file parsed (status parsed/read/image) or explicitly skipped with a reason
  labelled   every candidate number in <doc>, <doc>_S, <doc>_F labelled by both extractors (no missed items)
  disputes   no unresolved extractor disagreement (needs_adjudication and not adjudicated)
  reads      no figure/PDF number whose two independent reads disagree (needs_check) left unadjudicated
  structure  structure pass present; every typed number in it anchored
  closure    closure-test completeness >= CLOSURE_MIN
Silence (analyses promised but not reported, or reported without numbers) is recorded, not a failure: it is a fact about the paper.
Usage: python -m epistemic.gate [PMC... | --all]  -> work/gate.json, prints one line per paper"""
import os, sys, json, glob, pathlib
CLOSURE_MIN = float(os.environ.get("CLOSURE_MIN", "0.85"))   # single runs vary by about +-0.05, so hard verdicts decide, the score is a floor

def check(doc):
    R = {"doc": doc, "open": []}
    M = json.load(open(f"bundles/{doc}/MANIFEST.json")) if os.path.exists(f"bundles/{doc}/MANIFEST.json") else None
    if M is None: R["open"].append("files: bundle not fetched")
    else:
        from .bundle import match
        miss = match(M)["missing"]; R["unobtainable"] = miss
    for suf, key in (("_S", "sources"), ("_F", "sources")):
        p = f"parsed/{doc}{suf}.json"
        if os.path.exists(p):
            bad = [s for s in json.load(open(p))[key] if str(s.get("status", "")).startswith("failed")]
            if bad: R["open"].append(f"parsed{suf}: {len(bad)} failed")
    units = [u for u in (doc, doc + "_S", doc + "_F") if os.path.exists(f"parsed/{u}.json")]
    missed = disputes = checks = 0
    for u in units:
        for side in ("A", "B"):
            p = f"ext/{u}.{side}.json"
            if not os.path.exists(p):
                P = json.load(open(f"parsed/{u}.json"))
                if any(c["numbers"] and not (c.get("prelabel") or {}).get("not_data") and c["kind"] != "figure_point" for c in P["candidates"]):
                    R["open"].append(f"labelled: {u} has no extractor {side}")
                continue
            missed += len(json.load(open(p)).get("missed", []))
        if os.path.exists(f"data/{u}.jsonl"):
            for l in open(f"data/{u}.jsonl"):
                r = json.loads(l); disputes += bool(r.get("needs_adjudication") and not r.get("adjudicated"))
        P = json.load(open(f"parsed/{u}.json")); checks += sum(1 for c in P["candidates"] if c.get("needs_check") and not c.get("check_resolved"))
    if missed: R["open"].append(f"labelled: {missed} items missed by an extractor")
    if disputes: R["open"].append(f"disputes: {disputes} unresolved")
    if checks: R["open"].append(f"reads: {checks} needs_check")
    p4 = f"ext/{doc}.S4.json"
    if not os.path.exists(p4): R["open"].append("structure: missing")
    else:
        S = json.load(open(p4)); un = S.get("unanchored", [])
        R["unanchored"] = sum(1 for m in un if not m.get("derived")); R["derived"] = sum(1 for m in un if m.get("derived"))
        if R["unanchored"]: R["open"].append(f"structure: {R['unanchored']} unanchored numbers")
        an = S.get("analyses") or []
        R["silence"] = {"not_reported": sum(1 for a in an if a.get("status") == "not_reported"),
                        "reported_without_numbers": sum(1 for a in an if a.get("status") == "reported_without_numbers"), "analyses": len(an)}
    pc = f"validation/{doc}.closure.json"
    if not os.path.exists(pc): R["open"].append("closure: not tested")
    else:
        C = json.load(open(pc)); R["closure"] = C["completeness"]
        hard = {k: g.get("gap") for k, g in C["grades"].items() if g.get("verdict") in ("mismatch", "records_missing")}
        R["detail_gaps"] = {k: g.get("gap") for k, g in C["grades"].items() if g.get("verdict") == "partial"}
        if hard: R["open"].append(f"closure: {len(hard)} hard misses {list(hard)}")
        if R["closure"] < CLOSURE_MIN: R["open"].append(f"closure: {R['closure']} < {CLOSURE_MIN}")
    R["status"] = "closed" if not R["open"] else "open"
    return R

if __name__ == "__main__":
    docs = sorted({pathlib.Path(p).stem for p in glob.glob("raw/*.xml")} | {pathlib.Path(p).stem for p in glob.glob("parsed/W*.json") if "_" not in pathlib.Path(p).stem}) if sys.argv[1:] in ([], ["--all"]) else sys.argv[1:]
    out = [check(d) for d in docs]; json.dump(out, open("work/gate.json", "w"), indent=1)
    for r in out: print(r["doc"], r["status"], "; ".join(r["open"]), "| silence", r.get("silence"))
    print("closed", sum(r["status"] == "closed" for r in out), "of", len(out))
