"""Cumulative Jev spend from the ledger (verification events with backend jev). Exit 1 if at or above the stop line."""
import json, sys
tok = sum(json.loads(l)["body"].get("input_tokens", 0) for l in open("ledger.jsonl")
          if json.loads(l)["kind"] == "verification_event" and json.loads(l)["body"].get("backend") == "jev")
usd = tok * 0.042 / 1e6; stop = float(sys.argv[1]) if len(sys.argv) > 1 else 4.50
print(json.dumps({"jev_input_tokens": tok, "jev_usd": round(usd, 4), "stop_at": stop}))
sys.exit(1 if usd >= stop else 0)
