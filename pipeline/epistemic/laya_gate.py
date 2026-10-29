"""Laya gate v1: a second look at numbers the two extractors AGREED on (where shared errors hide).
Laya ckpt4 (local, free) answers the role of every agreed number; where it disagrees with the agreed role at p >= LAYA_GATE_P,
the row is flagged. judge.py then sends flags up the ladder: Jev; if Jev sides with Laya, Sonnet decides; otherwise the agreed role stands.
Writes ext/<unit>.laya.json. Usage: python -m epistemic.laya_gate UNIT...   env LAYA_URL (default http://127.0.0.1:8768), LAYA_MODEL epi4"""
import os, sys, json, concurrent.futures as cf
from .context import describe, table_index
from .laya_judge import Laya
from . import typed, store
P_MIN = float(os.environ.get("LAYA_GATE_P", "0.9"))

def run(unit):
    if not os.path.exists(f"data/{unit}.jsonl"): return {"unit": unit, "skipped": "no data"}
    P = json.load(open(f"parsed/{unit}.json")); T = table_index(P); cand = {c["id"]: c for c in P["candidates"]}
    rows = [json.loads(l) for l in open(f"data/{unit}.jsonl")]
    agreed = {}
    for r in rows:
        if r.get("agreed") and r.get("role") and not r.get("adjudicated"): agreed.setdefault(r["candidate"], {})[int(r["datum_id"].rsplit("#", 1)[1])] = r["role"]
    back = Laya(host=os.environ.get("LAYA_URL", "http://127.0.0.1:8768"), model=os.environ.get("LAYA_MODEL", "epi4"), head_max_len=576, max_len=1024)
    def one(cid):
        c = cand.get(cid)
        if c is None: return cid, None
        st = describe(P, c, T); st["numbers_in_order"] = [n.get("raw") for n in c["numbers"]]
        qs = typed.questions_for(c); Q = {f"role_{i}": qs[f"role_{i}"] for i in agreed[cid] if f"role_{i}" in qs}
        import fcntl, time as _t, random as _r
        os.makedirs("work/locks", exist_ok=True)
        for attempt in range(6):
            fh = None
            try:
                while fh is None:
                    for i in range(int(open("work/laya_slots").read()) if os.path.exists("work/laya_slots") else int(os.environ.get("LAYA_SLOTS", "16"))):
                        f = open(f"work/locks/laya_{i}", "w")
                        try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); fh = f; break
                        except OSError: f.close()
                    if fh is None: _t.sleep(0.2 + _r.random() * 0.3)
                return cid, back.ask(st, Q)
            except Exception:
                _t.sleep(2 * (attempt + 1))
            finally:
                if fh: fcntl.flock(fh, fcntl.LOCK_UN); fh.close()
        return cid, None
    flags, asked, err = [], 0, 0
    with cf.ThreadPoolExecutor(4) as ex:
        for cid, a in ex.map(one, list(agreed)):
            if a is None: err += 1; continue
            for i, role in agreed[cid].items():
                x = a.get(f"role_{i}"); asked += 1
                if x and x["answer"] != role and (x["p"] or 0) >= P_MIN:
                    flags.append({"datum_id": f"{cid}#{i}", "candidate": cid, "agreed": role, "laya": x["answer"], "p": round(x["p"], 4)})
    out = {"unit": unit, "model": back.model, "p_min": P_MIN, "asked": asked, "errors": err, "flags": flags}
    json.dump(out, open(f"ext/{unit}.laya.json", "w"), indent=1)
    rep = {"unit": unit, "asked": asked, "flags": len(flags), "errors": err}
    store.append("laya_gate", rep); return rep

if __name__ == "__main__":
    for u in sys.argv[1:]: print(json.dumps(run(u)), flush=True)
