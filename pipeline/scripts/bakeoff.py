"""Model bake-off for number-role extraction against the gold data layer.
One prompt for every model; candidates are sent in chunks with their table/section context; output is compact JSON.
Usage:
  python scripts/bakeoff.py select                 # freeze the 20-paper slice -> work/bake/slice.json (ledgered)
  python scripts/bakeoff.py run <model> [smoke]    # run one model on the slice (or the smoke doc only)
  python scripts/bakeoff.py anthropic-batch [smoke] # all Claude models via Message Batches (50% off)
Spend is tracked per provider in work/bake/spend.json and capped by *_BUDGET_USD in .env."""
import os, sys, json, time, random, re, glob, threading, concurrent.futures as cf
import requests
sys.path.insert(0, os.path.expanduser("~/epistemic")); os.chdir(os.path.expanduser("~/epistemic"))
from epistemic.context import describe, table_index
from epistemic.typed import ROLE_HELP
from epistemic.typecheck import REASONS
from epistemic import store

B = "work/bake"; os.makedirs(B, exist_ok=True)
CHUNK = 200
MODELS = {  # name: (provider, model id, $/M in, $/M out)
  "opus": ("anthropic", "claude-opus-5-5", 4.0, 20.0),
  "sonnet": ("anthropic", "claude-sonnet-5-5", 2.0, 10.0),
  "haiku": ("anthropic", "claude-haiku-5-5", 0.10, 0.50),
  "kimi": ("openrouter", "moonshotai/kimi-k3.1-pro", 2.0, 10.0),
  "glm": ("openrouter", "z-ai/glm-5.3", 0.07, 1.4),
  "nemotron": ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b", 0.6, 2.4),
  "qwen27b": ("openrouter", "qwen/qwen3.8-27b", 0.2, 2.5),
  "minimax": ("openrouter", "minimax/minimax-m3.1-flash", 0.15, 0.6),
  "deepseek": ("deepseek", "deepseek-flash", 0.30, 1.20),  # peak price as the safe estimate
  "qwen_local": ("local", "nvidia/Qwen3.8-Flash-Next-FP4-Local", 0.0, 0.0),
}
LOCK = threading.Lock()

def spend_get():
    try: return json.load(open(f"{B}/spend.json"))
    except Exception: return {}
def spend_add(provider, usd):
    with LOCK:
        s = spend_get(); s[provider] = round(s.get(provider, 0) + usd, 6); json.dump(s, open(f"{B}/spend.json", "w"))
        return s[provider]
def budget(provider):
    return float(os.environ.get(provider.upper() + "_BUDGET_USD", "0") or 0) if provider != "local" else 1e9

ROLES_TXT = "\n".join(f"{k}: {v}" for k, v in ROLE_HELP.items())
SYSTEM = f"""You label every number found by a parser in a scientific paper (coffee and cardiovascular epidemiology).
For each item decide whether its numbers are data (a value reported, measured, defined or used by this study or a cited study: a statistic, sample size, category bound, dose, date, setting) or not data.
If data, give exactly one role per number, in the order of "n", using only these roles:
{ROLES_TXT}
If not data, give one reason from: {", ".join(sorted(REASONS))}.
Notes: the 95 of "95% CI" is not data (ci_level_label); citation numbers and table or figure numbers are not data; a number inside a name like "type 2 diabetes" is not data (prose_word).
Answer with JSON only, no prose: {{"items":[{{"id":"<id>","d":1,"r":["role",...]}} or {{"id":"<id>","d":0,"why":"<reason>"}}]}} with one entry for every input item."""

def gold_for(doc):
    g = {}; copies = set()
    for l in open(f"data/{doc}.jsonl"):
        r = json.loads(l)
        if r.get("span_copy") or r.get("nested_copy"): copies.add(r["candidate"]); continue
        g.setdefault(r["candidate"], {})[int(r["datum_id"].rsplit("#", 1)[1])] = r
    return g, copies

def items_for(doc):
    P = json.load(open(f"parsed/{doc}.json")); T = table_index(P); g, copies = gold_for(doc)
    caps, items = {}, []
    for c in P["candidates"]:
        if c["id"] in copies or not c["numbers"] or (c.get("prelabel") or {}).get("not_data"): continue
        x = describe(P, c, T); it = {"id": c["id"], "n": [n.get("raw") for n in c["numbers"]]}
        a = c["anchor"]
        if "row" in a:
            caps[a["table"]] = x.get("table_caption", "")[:250]
            it.update(t=a["table"], col=(x.get("column_header") or "")[:120], row=(x.get("row_label") or "")[:120], sec=(x.get("row_section") or "")[:80], cell=c["text"][:80])
        else:
            it.update(where=str(a.get("section") or a.get("table") or a.get("figure") or "")[:60], ctx=(c.get("local_context") or c["text"])[:400], hl=c["text"][:120])
        items.append(it)
    return P, caps, items

def chunks(doc):
    P, caps, items = items_for(doc)
    head = f"Paper: {P['title'][:200]}\n"
    for i in range(0, len(items), CHUNK):
        part = items[i:i + CHUNK]
        tabs = {t: caps[t] for t in {it.get("t") for it in part if it.get("t")}}
        yield i // CHUNK, head + "Table captions: " + json.dumps(tabs, ensure_ascii=False) + "\nItems:\n" + "\n".join(json.dumps(it, ensure_ascii=False) for it in part), [it["id"] for it in part]

def parse_out(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.M).strip()
    m = t[t.find("{"): t.rfind("}") + 1]
    return json.loads(m)["items"]

def call_chat(provider, model, user, max_tokens):
    if provider == "openrouter":
        url, key = "https://openrouter.ai/api/v1/chat/completions", os.environ["OPENROUTER_API_KEY"]
        extra = {"reasoning": {"effort": "low", "exclude": True}, "usage": {"include": True}, "response_format": {"type": "json_object"}}
    elif provider == "deepseek":
        url, key = "https://api.deepseek.com/chat/completions", os.environ["DEEPSEEK_API_KEY"]
        extra = {"response_format": {"type": "json_object"}, "effort": "low"}
    elif provider == "anthropic":
        H = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": model, "max_tokens": max_tokens, "system": SYSTEM, "messages": [{"role": "user", "content": user}]}
        err = None
        for a in range(8):
            try:
                r = requests.post("https://api.anthropic.com/v1/messages", headers=H, json=body, timeout=900)
                if r.status_code in (429, 500, 502, 503, 529): time.sleep(15 * (a + 1)); continue
                r.raise_for_status(); d = r.json(); u = d["usage"]
                return "".join(b.get("text", "") for b in d["content"] if b["type"] == "text"), u["input_tokens"], u["output_tokens"], None
            except requests.RequestException as e:
                err = e; time.sleep(15 * (a + 1))
        raise RuntimeError(f"anthropic failed: {str(err)[:200]}")
    else:
        url, key = "http://127.0.0.1:8000/v1/chat/completions", "local"
        extra = {"response_format": {"type": "json_object"}, "chat_template_kwargs": {"enable_thinking": False}}
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], "temperature": 0, "max_tokens": max_tokens, **extra}
    for a in range(5):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=600)
            if r.status_code in (429, 500, 502, 503, 529): time.sleep(10 * (a + 1)); continue
            if r.status_code == 400 and "effort" in body: body.pop("effort"); continue
            r.raise_for_status(); d = r.json()
            u = d.get("usage") or {}
            return d["choices"][0]["message"]["content"] or "", u.get("prompt_tokens", 0), u.get("completion_tokens", 0), u.get("cost")
        except requests.RequestException as e:
            err = e; time.sleep(10 * (a + 1))
    raise RuntimeError(f"{provider} failed: {str(err)[:200]}")

def run_chat(name, docs):
    provider, model, pin, pout = MODELS[name]
    os.makedirs(f"{B}/{name}", exist_ok=True)
    docs = docs[:{"opus": 5, "sonnet": 10}.get(name, len(docs))]
    jobs = [(d, k, u, ids) for d in docs for k, u, ids in chunks(d) if not os.path.exists(f"{B}/{name}/{d}.{k}.json")]
    def one(job):
        d, k, u, ids = job
        if spend_get().get(provider, 0) >= budget(provider): return d, k, "budget"
        try: text, tin, tout, cost = call_chat(provider, model, u, 8000 if name == "kimi" else 16000)
        except Exception as e: return d, k, f"error {e}"
        usd = cost if cost is not None else (tin * pin + tout * pout) / 1e6
        spend_add(provider, usd)
        try: out = parse_out(text); ok = True
        except Exception: out, ok = text[:4000], False
        json.dump({"doc": d, "chunk": k, "ids": ids, "items": out, "parsed": ok, "in": tin, "out": tout, "usd": usd}, open(f"{B}/{name}/{d}.{k}.json", "w"))
        return d, k, "ok" if ok else "parse_fail"
    with cf.ThreadPoolExecutor(4 if provider != "local" else 8) as ex:
        res = list(ex.map(one, jobs))
    store.append("bakeoff_run", {"model": name, "model_id": model, "docs": docs, "results": [r[2][:40] for r in res], "spend": spend_get().get(provider)})
    return res

def run_anthropic_batch(names, docs):
    key = os.environ["ANTHROPIC_API_KEY"]; H = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    reqs, meta = [], {}
    for name in names:
        _, model, pin, pout = MODELS[name]; os.makedirs(f"{B}/{name}", exist_ok=True)
        for d in (docs[:10] if name == "opus" else docs):
            for k, u, ids in chunks(d):
                if os.path.exists(f"{B}/{name}/{d}.{k}.json"): continue
                if os.path.exists(f"{B}/{name}/{d}.{k}.err.json"): os.remove(f"{B}/{name}/{d}.{k}.err.json")
                cid = f"{name}__{d}__{k}"; meta[cid] = (name, d, k, ids, pin, pout)
                reqs.append({"custom_id": cid, "params": {"model": model, "max_tokens": 16000,
                             "system": SYSTEM, "messages": [{"role": "user", "content": u}]}})
    if not reqs: return "nothing to do"
    # rough pre-check of input cost at batch price
    est = sum(len(r["params"]["messages"][0]["content"]) / 3.5 * MODELS[meta[r["custom_id"]][0]][2] / 2e6 for r in reqs)
    if spend_get().get("anthropic", 0) + est * 1.6 > budget("anthropic"): return f"refused: projected ${est*1.6:.2f} exceeds Anthropic budget"
    r = requests.post("https://api.anthropic.com/v1/messages/batches", headers=H, json={"requests": reqs}, timeout=120); r.raise_for_status()
    bid = r.json()["id"]; json.dump({"id": bid, "meta": {k: list(v[:4]) for k, v in meta.items()}}, open(f"{B}/anthropic_batch_{bid}.json", "w"))
    print("batch", bid, len(reqs), "requests", flush=True)
    while True:
        s = requests.get(f"https://api.anthropic.com/v1/messages/batches/{bid}", headers=H, timeout=60).json()
        if s.get("processing_status") == "ended": break
        time.sleep(60)
    res = requests.get(s["results_url"], headers=H, timeout=300)
    n_ok = 0
    for line in res.text.splitlines():
        x = json.loads(line); name, d, k, ids, pin, pout = meta[x["custom_id"]]
        if x["result"]["type"] != "succeeded":
            json.dump({"doc": d, "chunk": k, "ids": ids, "error": x["result"]}, open(f"{B}/{name}/{d}.{k}.err.json", "w")); continue
        m = x["result"]["message"]; u = m["usage"]
        usd = (u["input_tokens"] * pin + u["output_tokens"] * pout) / 2e6
        spend_add("anthropic", usd)
        text = "".join(b.get("text", "") for b in m["content"] if b["type"] == "text")
        try: out = parse_out(text); ok = True
        except Exception: out, ok = text[:4000], False
        json.dump({"doc": d, "chunk": k, "ids": ids, "items": out, "parsed": ok, "in": u["input_tokens"], "out": u["output_tokens"], "usd": usd}, open(f"{B}/{name}/{d}.{k}.json", "w"))
        n_ok += ok
    store.append("bakeoff_run", {"models": names, "batch": bid, "docs": docs, "ok": n_ok, "n": len(meta), "spend": spend_get().get("anthropic")})
    return f"batch {bid}: {n_ok}/{len(meta)} parsed"

def select():
    ding = sorted({os.path.basename(f).split(".")[0] for f in glob.glob("reference/PMC*.json")})
    EX = {"PMC2737446", "PMC1025516", "PMC3071630", "PMC7821939"}
    pool = []
    for f in sorted(glob.glob("data/*.jsonl")):
        d = os.path.basename(f)[:-6]
        if d in EX or d in ding or not os.path.exists(f"parsed/{d}.json"): continue
        n = len(items_for(d)[2])
        if 120 <= n <= 1200: pool.append(d)
    random.seed(11); rest = random.sample(pool, 20 - len(ding))
    sl = {"date": time.strftime("%Y-%m-%d"), "ding_docs": ding, "docs": ding + rest, "chunk": CHUNK}
    json.dump(sl, open(f"{B}/slice.json", "w"), indent=1)
    store.append("bakeoff_slice", {"docs": sl["docs"], "ding_docs": ding})
    print(json.dumps(sl)); print({d: len(items_for(d)[2]) for d in sl["docs"]})

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "select": select(); sys.exit()
    sl = json.load(open(f"{B}/slice.json")); docs = sl["docs"]
    smoke = "smoke" in sys.argv
    if smoke: docs = [min(docs, key=lambda d: len(items_for(d)[2]))]
    if cmd == "run": print(run_chat(sys.argv[2], docs))
    elif cmd == "anthropic-batch": print(run_anthropic_batch(["haiku", "sonnet", "opus"], docs))
    print("spend", spend_get())
