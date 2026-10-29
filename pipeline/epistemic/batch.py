"""Anthropic Message Batches for the whole pipeline (50% off). Requests queued by llm.chat in LLM_BATCH=collect mode are
submitted here; finished results fill the shared response cache, so rerunning any step picks its answers from the cache.
  python -m epistemic.batch submit      send everything queued (deduplicated against the cache), record batch ids
  python -m epistemic.batch collect     poll submitted batches; write finished results into the cache; ledger spend at batch price
  python -m epistemic.batch wait        collect every 60 s until no batch is in progress"""
import os, sys, json, time, requests
from . import llm, store
B = "work/batchq"; IDS = f"{B}/batches.json"
H = lambda: {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"}

def submit():
    if not os.path.exists(llm.QUEUE): return {"submitted": 0}
    os.replace(llm.QUEUE, f"{B}/queue.{int(time.time())}.jsonl.sent")
    sent = sorted(p for p in os.listdir(B) if p.endswith(".jsonl.sent"))[-1]
    reqs, seen = [], set()
    for l in open(f"{B}/{sent}"):
        r = json.loads(l)
        if r["custom_id"] in seen or llm.cache_get(r["custom_id"]) is not None: continue
        seen.add(r["custom_id"]); reqs.append(r)
    ids = json.load(open(IDS)) if os.path.exists(IDS) else {}
    n = 0
    for i in range(0, len(reqs), 5000):
        part = reqs[i:i + 5000]
        r = requests.post("https://api.anthropic.com/v1/messages/batches", headers=H(), json={"requests": [{"custom_id": x["custom_id"], "params": x["params"]} for x in part]}, timeout=600)
        r.raise_for_status(); bid = r.json()["id"]
        ids[bid] = {"status": "in_progress", "n": len(part), "price": {x["custom_id"]: x["price"] for x in part}, "submitted": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        n += len(part)
    json.dump(ids, open(IDS, "w"))
    store.append("batch_submit", {"requests": n, "batches": len(ids)})
    return {"submitted": n}

def collect():
    ids = json.load(open(IDS)) if os.path.exists(IDS) else {}; done = usd = errs = 0
    for bid, m in ids.items():
        if m["status"] != "in_progress": continue
        try: s = requests.get(f"https://api.anthropic.com/v1/messages/batches/{bid}", headers=H(), timeout=60).json()
        except requests.RequestException: continue
        if s.get("processing_status") != "ended": continue
        res = requests.get(s["results_url"], headers=H(), timeout=600)
        for line in res.text.splitlines():
            x = json.loads(line)
            if x["result"]["type"] != "succeeded":      # errored / expired / canceled: record it so a stuck paper is never silent
                errs += 1
                with open("work/batchq/errors.jsonl", "a") as ef:
                    ef.write(json.dumps({"batch": bid, "custom_id": x["custom_id"], "type": x["result"]["type"],
                                         "error": (x["result"].get("error") or {}), "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
                continue
            msg = x["result"]["message"]; u = msg["usage"]; pin, pout = m["price"].get(x["custom_id"], [0, 0])
            c = (u["input_tokens"] * pin + u["output_tokens"] * pout) / 2e6; usd += c
            llm.cache_put(x["custom_id"], "".join(b.get("text", "") for b in msg["content"] if b["type"] == "text"), {"model": msg.get("model"), "usd": c, "mode": "batch", "batch": bid})
            done += 1
        m["status"] = "ended"
    json.dump(ids, open(IDS, "w"))
    if usd: llm._spend("anthropic", usd)
    if done or errs: store.append("batch_collect", {"results": done, "errors": errs, "usd": round(usd, 4)})
    return {"collected": done, "errors": errs, "usd": round(usd, 4), "in_progress": sum(1 for m in ids.values() if m["status"] == "in_progress")}

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "submit": print(json.dumps(submit()))
    elif cmd == "collect": print(json.dumps(collect()))
    elif cmd == "wait":
        while True:
            r = collect(); print(json.dumps(r), flush=True)
            if r["in_progress"] == 0: break
            time.sleep(60)
