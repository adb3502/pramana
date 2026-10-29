"""Re-read units whose Laya B pass silently failed (missed > 5%), then re-validate, re-gate, re-judge and re-run closure. Markers are left in place so the live threads do not race us."""
import json, glob, os, sys, subprocess, concurrent.futures as cf
PY = ".venv/bin/python"
BAD = set()
def bad_units():
    out = []
    for p in glob.glob("ext/*.B.json"):
        d = json.load(open(p))
        if not str(d.get("extractor", "")).startswith("laya"): continue
        m = len(d["missed"]); n = m + len(d["data"]) + len(d["not_data"])
        if n and m > 0.05 * n: out.append(p[4:-7])
    return sorted(out)
def sh(cmd, log): return subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode == 0
def fix(u):
    os.makedirs("logs/repair", exist_ok=True)
    with open(f"logs/repair/{u}.log", "a") as log:
        if os.path.exists(f"ext/{u}.B.json.laya_fail") and u not in BAD: pass
        else:
          os.replace(f"ext/{u}.B.json", f"ext/{u}.B.json.laya_fail")
          if not sh([PY, "-m", "epistemic.passr", "B", "laya", u], log) or not os.path.exists(f"ext/{u}.B.json"):
              os.replace(f"ext/{u}.B.json.laya_fail", f"ext/{u}.B.json"); return u, "passr_fail"
        if not os.path.exists(f"ext/{u}.A.json"): return u, "reread_only"
        sh([PY, "-c", f"from epistemic import validate; validate.run(\"{u}\", \".\", None, write_data=True)"], log)
        ok = sh([PY, "-m", "epistemic.laya_gate", u], log) and sh([PY, "-m", "epistemic.judge", u], log)
        doc = u.split("_")[0]
        if ok and os.path.exists(f"validation/{doc}.closure.json"): sh([PY, "-m", "epistemic.closure", doc], log)
        if ok: open(f"logs/repair/{u}.ok", "w").close()
        return u, "ok" if ok else "judge_fail"
if __name__ == "__main__":
    BAD.update(bad_units())
    us = sorted(BAD | {p[12:-4] for p in glob.glob("logs/repair/*.log") if not os.path.exists(p[:-4] + ".ok")}); print(len(us), "units to repair", flush=True)
    with cf.ThreadPoolExecutor(int(sys.argv[1]) if len(sys.argv) > 1 else 3) as ex:
        for i, (u, st) in enumerate(ex.map(fix, us)): print(i + 1, u, st, flush=True)
