"""Score the typed judge (Jev) on adjudicated hard rows vs the gold role. Runs verify for docs lacking a jev file.
Usage: python scripts/judge_hard.py N   (first N slice docs)"""
import os, sys, json
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic import verify
A = sys.argv[1:] or ["5"]
docs = json.load(open("work/bake/slice.json"))["docs"][:int(A[0])] if A[0].isdigit() else A
tot = ok = pick_ab = usd = 0; per = {}
for d in docs:
    f = f"verification/{d}.jev.json"
    if not os.path.exists(f): verify.run(d, "jev", only_disputed=True)
    V = json.load(open(f)); usd += V["report"].get("cost_usd", 0)
    J = V["judged"]; n = k = 0
    for l in open(f"data/{d}.jsonl"):
        r = json.loads(l)
        if not r.get("needs_adjudication"): continue
        i = int(r["datum_id"].rsplit("#", 1)[1])
        ans = (J.get(r["candidate"], {}).get(f"role_{i}") or {}).get("answer")
        gold = None if r.get("adj_not_data") else r.get("role")
        n += 1; k += (ans == gold) or (gold is None and ans in (None, "not_data", "none"))
        pick_ab += ans in (r.get("role_A"), r.get("role_B"))
    per[d] = f"{k}/{n}"; tot += n; ok += k
print(json.dumps({"docs": per, "hard_rows": tot, "jev_exact": round(ok / max(tot, 1), 3), "jev_picked_A_or_B": round(pick_ab / max(tot, 1), 3), "jev_usd_total": round(usd, 4)}))
