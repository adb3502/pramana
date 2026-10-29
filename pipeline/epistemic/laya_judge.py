"""Laya backend for typed.judge. Laya runs in its own venv (~/laya/.venv) as a local HTTP server
(scripts/laya_server.sh, 127.0.0.1:8765, Jev-compatible POST /v1systemone wire format). This adapter only needs requests."""
import os, requests

class Laya:
    name = "laya"
    def __init__(self, host=None, model="english", head_max_len=None, max_len=None):
        self.host = host or os.environ.get("LAYA_URL", "http://127.0.0.1:8765")
        self.model, self.head_max_len, self.max_len = model, head_max_len, max_len
        self.input_tokens = 0
    def ask(self, state, questions):
        q = {k: ({"type": "noul", "instructions": v["instructions"]} if v["type"] == "noul"
                 else {"type": "choice", "instructions": v["instructions"], "criteria": v["criteria"]})
             for k, v in questions.items()}
        body = {"model": self.model, "state": state, "questions": q}
        if self.head_max_len: body["head_max_len"] = self.head_max_len
        if self.max_len: body["max_len"] = self.max_len
        hs = [h.strip() for h in open("work/laya_hosts").read().split() if h.strip()] if os.path.exists("work/laya_hosts") else [self.host]; import random as _r; r = requests.post(f"{_r.choice(hs)}/v1/systemone", json=body, timeout=120)
        r.raise_for_status(); d = r.json()
        self.input_tokens += d.get("usage", {}).get("input_tokens", 0)
        out = {}
        for k, a in d["answers"].items():
            if a.get("type") == "noul" or "noul" in a: out[k] = {"answer": a["noul"] >= 0.5, "p": a["noul"]}
            else: out[k] = {"answer": a["choice"], "p": a.get("answer_confidence", a.get("confidence"))}
        return out
