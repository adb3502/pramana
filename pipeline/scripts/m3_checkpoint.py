"""Mission 3: rewrite the '## Mission 3 progress' block of STATUS.md with running totals (called after every batch)."""
import json, glob, os, datetime, subprocess, re
S = json.load(open("work/m3_screen.json")); keep = [r["pmcid"] for r in S["records"] if r["decision"] == "keep"]
done = [d for d in keep if os.path.exists(f"data/{d}.jsonl") and os.path.exists(f"ext/{d}.adj.json")]
fail = [d for d in keep if d not in done and os.path.exists(f"logs/{d}.A.json")]
tot = {"numbers": 0, "data": 0, "disputes": 0, "triplets": 0, "arith_fail": 0}
for d in done:
    v = json.load(open(f"validation/{d}.json"))
    tot["numbers"] += v["numbers"]; tot["disputes"] += v["needs_adjudication"] + v["data_disputes"]; tot["triplets"] += v["ratio_triplets"]; tot["arith_fail"] += len(v["arithmetic_failures"])
    tot["data"] += sum(1 for l in open(f"data/{d}.jsonl") if json.loads(l).get("role"))
jev = subprocess.run([".venv/bin/python", "scripts/jev_spent.py", "4.5"], capture_output=True, text=True).stdout.strip()
t = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime("%H:%M")
block = (f"## Mission 3 progress (auto, {t} IST)\n- kept {len(keep)}, done {len(done)}, started-not-finished {len(fail)}\n"
         f"- totals over done: numbers {tot['numbers']}, data {tot['data']}, disputes {tot['disputes']}, triplets {tot['triplets']}, arith_fail {tot['arith_fail']}\n- Jev {jev}\n")
s = open("STATUS.md").read()
s = re.sub(r"## Mission 3 progress.*?(?=\n## |\Z)", "", s, flags=re.S).rstrip() + "\n\n" + block
open("STATUS.md", "w").write(s); print(block)
