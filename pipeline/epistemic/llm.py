"""One client for every backend the pipeline uses. chat(backend, system, user) -> (parsed JSON object, usd).
backends: haiku, sonnet, opus (Anthropic), qwen_local (vLLM on 127.0.0.1:8000), deepseek. Spend is ledgered by callers."""
import os, json, time, requests
B = {"haiku": ("anthropic", "claude-haiku-5-5", 0.10, 0.50), "sonnet": ("anthropic", "claude-sonnet-5-5", 2.0, 10.0),
     "opus": ("anthropic", "claude-opus-5-5", 4.0, 20.0), "qwen_local": ("local", "nvidia/Qwen3.8-Flash-Next-FP4-Local", 0, 0),
     "deepseek": ("deepseek", "deepseek-flash", 0.30, 1.20), "or_deepseek": ("openrouter", "deepseek/deepseek-v4.1-flash", 0.048, 0.191)}

SPEND = "work/llm_spend.json"
CACHE_DIR = "work/llm_cache"; QUEUE = os.environ.get("LLM_BATCH_QUEUE", "work/batchq/queue.jsonl")   # one queue per batch thread

class Deferred(BaseException):
    """Raised in batch-collect mode (LLM_BATCH=collect) after an Anthropic request is queued instead of sent.
    BaseException on purpose: the pipeline's own `except Exception` handlers must not swallow it, so a step that
    needs an answer stops without writing a partial output, and reruns once the batch has filled the cache."""

def _key(model, system, user, max_tokens, image):
    import hashlib
    return hashlib.sha256(json.dumps([model, system, user, max_tokens, hashlib.sha256((image or "").encode()).hexdigest()]).encode()).hexdigest()[:40]

def cache_get(k):
    p = f"{CACHE_DIR}/{k[:2]}/{k}.json"
    return json.load(open(p)) if os.path.exists(p) else None

def cache_put(k, text, meta):
    os.makedirs(f"{CACHE_DIR}/{k[:2]}", exist_ok=True)
    json.dump({"text": text, **meta}, open(f"{CACHE_DIR}/{k[:2]}/{k}.json", "w"))

def _parse(t):
    return json.loads(t[t.find("{"): t.rfind("}") + 1])

def _spend(prov, usd):
    import fcntl
    os.makedirs("work", exist_ok=True)
    with open(SPEND + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        s = json.load(open(SPEND)) if os.path.exists(SPEND) else {}
        s[prov] = round(s.get(prov, 0) + usd, 6); json.dump(s, open(SPEND, "w")); return s[prov]

def chat(backend, system, user, max_tokens=16000, image_png_b64=None):
    prov, model, pin, pout = B[backend]
    k = _key(model, system, user, max_tokens, image_png_b64)
    hit = cache_get(k)
    if hit is not None:
        try: return _parse(hit["text"]), 0.0
        except ValueError: pass
    if prov == "anthropic" and os.environ.get("LLM_BATCH") == "collect":
        import fcntl
        content = ([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_png_b64}}] if image_png_b64 else []) + [{"type": "text", "text": user}]
        params = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
        if system: params["system"] = system
        os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
        with open(QUEUE + ".lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            with open(QUEUE, "a") as f: f.write(json.dumps({"custom_id": k, "params": params, "price": [pin, pout]}) + "\n")
        raise Deferred(k)
    cap = float(os.environ.get(f"LLM_{prov.upper()}_CAP_USD", "1e9"))
    if prov != "local" and os.path.exists(SPEND) and json.load(open(SPEND)).get(prov, 0) >= cap:
        raise RuntimeError(f"budget: {prov} spend reached LLM_{prov.upper()}_CAP_USD={cap}")
    if prov == "anthropic":
        H = {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
        content = ([{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_png_b64}}] if image_png_b64 else []) + [{"type": "text", "text": user}]
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
        if system: body["system"] = system
        url = "https://api.anthropic.com/v1/messages"
    else:
        url, key = {"local": ("http://127.0.0.1:8000/v1/chat/completions", "local"), "deepseek": ("https://api.deepseek.com/chat/completions", os.environ.get("DEEPSEEK_API_KEY")),
                    "openrouter": ("https://openrouter.ai/api/v1/chat/completions", os.environ.get("OPENROUTER_API_KEY"))}[prov]
        H = {"Authorization": f"Bearer {key}"}
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "max_tokens": max_tokens,
                "response_format": {"type": "json_object"}}
        if prov == "local": body.update(chat_template_kwargs={"enable_thinking": False}, temperature=0)
        if prov == "openrouter": body.update(reasoning={"effort": "low", "exclude": True}, usage={"include": True})
    slot = _local_slot() if prov == "local" else None   # the local server degrades badly past a few concurrent requests
    try: return _send(prov, model, pin, pout, url, H, body, k)
    finally:
        if slot: slot.close()

def _local_slot():
    """Cross-process semaphore: at most LLM_LOCAL_SLOTS concurrent requests to the local model, whatever the number of workers."""
    import fcntl
    n = int(os.environ.get("LLM_LOCAL_SLOTS", "6")); os.makedirs("work/locks", exist_ok=True)
    while True:
        for i in range(n):
            f = open(f"work/locks/local_{i}", "w")
            try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); return f
            except BlockingIOError: f.close()
        time.sleep(0.5)

def _send(prov, model, pin, pout, url, H, body, k):
    err = None
    for a in range(6):
        try:
            r = requests.post(url, headers=H, json=body, timeout=900)
            if r.status_code in (429, 500, 502, 503, 529): time.sleep(15 * (a + 1)); continue
            r.raise_for_status(); d = r.json()
            if prov == "anthropic":
                t = "".join(b.get("text", "") for b in d["content"] if b["type"] == "text"); u = d["usage"]; tin, tout = u["input_tokens"], u["output_tokens"]
            else:
                t = d["choices"][0]["message"]["content"] or ""; u = d.get("usage") or {}; tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
            usd = (tin * pin + tout * pout) / 1e6
            if prov == "openrouter" and isinstance(u.get("cost"), (int, float)): usd = u["cost"]   # the provider's own charge (includes hidden reasoning)
            _spend(prov, usd)
            out = _parse(t); cache_put(k, t, {"model": model, "usd": usd, "mode": "sync"})
            return out, usd
        except (requests.RequestException, ValueError, KeyError) as e: err = e; time.sleep(10)
    raise RuntimeError(f"{prov}: {str(err)[:200]}")
