"""Second repair pass: units whose Laya gate silently errored (ext/<u>.laya.json errors > 0). Re-gate, re-judge, re-run closure."""
import json, glob, os, subprocess, concurrent.futures as cf
PY = ".venv/bin/python"
def sh(cmd, log): return subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode == 0
us = sorted(p[4:-10] for p in glob.glob("ext/*.laya.json") if json.load(open(p)).get("errors", 0) > 0)
print(len(us), "units", flush=True)
def fix(u):
    with open(f"logs/repair/{u}.gate.log", "a") as log:
        ok = sh([PY, "-m", "epistemic.laya_gate", u], log) and sh([PY, "-m", "epistemic.judge", u], log)
        doc = u.split("_")[0]
        if ok and os.path.exists(f"validation/{doc}.closure.json"): sh([PY, "-m", "epistemic.closure", doc], log)
        return u, ok
with cf.ThreadPoolExecutor(3) as ex:
    for i, (u, ok) in enumerate(ex.map(fix, us)): print(i + 1, u, ok, flush=True)
