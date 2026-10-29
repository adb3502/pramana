"""Resume an Anthropic message batch submitted by bakeoff.py: poll by id (retrying through network blips) and save results.
Usage: python scripts/bake_collect.py <batch_id>"""
import os, sys, json, time, requests
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
sys.argv_saved = sys.argv; sys.argv = [sys.argv[0], "x"]
import importlib.util
spec = importlib.util.spec_from_file_location("bk", "scripts/bakeoff.py"); bk = importlib.util.module_from_spec(spec); spec.loader.exec_module(bk)
from epistemic import store
bid = sys.argv_saved[1]; B = bk.B
meta = json.load(open(f"{B}/anthropic_batch_{bid}.json"))["meta"]
H = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}
def get(url, **kw):
    for a in range(60):
        try:
            r = requests.get(url, headers=H, timeout=120, **kw); r.raise_for_status(); return r
        except requests.RequestException as e:
            print("retry", a, str(e)[:120], flush=True); time.sleep(30)
    raise SystemExit("gave up")
while True:
    s = get(f"https://api.anthropic.com/v1/messages/batches/{bid}").json()
    print(time.strftime("%H:%M"), s.get("processing_status"), s.get("request_counts"), flush=True)
    if s.get("processing_status") == "ended": break
    time.sleep(120)
res = get(s["results_url"]); n_ok = 0
for line in res.text.splitlines():
    x = json.loads(line); name, d, k, ids = meta[x["custom_id"]]
    _, model, pin, pout = bk.MODELS[name]
    if x["result"]["type"] != "succeeded":
        json.dump({"doc": d, "chunk": k, "ids": ids, "error": x["result"]}, open(f"{B}/{name}/{d}.{k}.err.json", "w")); continue
    m = x["result"]["message"]; u = m["usage"]
    usd = (u["input_tokens"] * pin + u["output_tokens"] * pout) / 2e6; bk.spend_add("anthropic", usd)
    text = "".join(b.get("text", "") for b in m["content"] if b["type"] == "text")
    try: out = bk.parse_out(text); ok = True
    except Exception: out, ok = text, False
    json.dump({"doc": d, "chunk": k, "ids": ids, "items": out, "parsed": ok, "in": u["input_tokens"], "out": u["output_tokens"], "usd": usd, "stop": m.get("stop_reason")}, open(f"{B}/{name}/{d}.{k}.json", "w"))
    n_ok += ok
store.append("bakeoff_run", {"batch": bid, "ok": n_ok, "n": len(meta), "spend": bk.spend_get().get("anthropic")})
print(f"batch {bid}: {n_ok}/{len(meta)} parsed", bk.spend_get())
