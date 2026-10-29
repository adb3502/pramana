"""Storage: four layers in one DuckDB file plus an append-only, hash-chained ledger.
raw_doc (content hashes) -> parsed (JSON on disk) -> datum (one row per number) -> claim.
Every extraction and validation event is a ledger entry; a silent edit breaks the chain."""
import json, glob, hashlib, pathlib, datetime, sys
import duckdb

LEDGER = pathlib.Path("ledger.jsonl")

def _last_hash():
    if not LEDGER.exists() or LEDGER.stat().st_size == 0: return "0" * 64
    return json.loads(LEDGER.read_text().strip().splitlines()[-1])["hash"]

def append(kind, body, rules_version="v2"):
    import fcntl
    with open(".ledger.lock", "w") as lk:  # parallel workers must not interleave seq/prev
        fcntl.flock(lk, fcntl.LOCK_EX)
        return _append(kind, body, rules_version)

def _append(kind, body, rules_version):
    seq = sum(1 for _ in open(LEDGER)) if LEDGER.exists() else 0
    rec = {"seq": seq, "kind": kind, "body": body, "prev": _last_hash(), "rules_version": rules_version,
           "time_utc": datetime.datetime.utcnow().isoformat(timespec="seconds")}
    rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
    with open(LEDGER, "a") as f: f.write(json.dumps(rec) + "\n")
    return rec["hash"]

def verify():
    prev = "0" * 64
    for line in open(LEDGER):
        rec = json.loads(line); h = rec.pop("hash")
        if rec["prev"] != prev or hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest() != h:
            return False, rec["seq"]
        prev = h
    return True, None

def file_hash(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()

def load(db="epistemic.duckdb"):
    con = duckdb.connect(db)
    if glob.glob("data/*.jsonl"):
        con.execute("CREATE OR REPLACE TABLE datum AS SELECT * FROM read_json_auto('data/*.jsonl', union_by_name=true)")
    rows = []
    for p in glob.glob("raw/*.xml"):
        rows.append({"doc": pathlib.Path(p).stem, "sha256": file_hash(p), "bytes": pathlib.Path(p).stat().st_size})
    if rows:
        con.execute("CREATE OR REPLACE TABLE raw_doc (doc VARCHAR, sha256 VARCHAR, bytes BIGINT)")
        con.executemany("INSERT INTO raw_doc VALUES (?, ?, ?)", [(r["doc"], r["sha256"], r["bytes"]) for r in rows])
    models, claims, flags = [], [], []
    for p in glob.glob("ext/*.json"):
        if pathlib.Path(p).stem.count(".") != 1: continue   # skip <doc>.<side>.patch / .prepatch (mission 2 targeted re-extraction)
        doc, side = pathlib.Path(p).stem.split(".")
        e = json.load(open(p))
        for m in e.get("models", []):
            models.append((doc, side, m.get("model_id"), m.get("label"), m.get("role"), json.dumps(m.get("adjusted_for"))))
        for c in e.get("claims", []):
            claims.append((doc, side, c.get("text_paraphrase"), c.get("relation"), c.get("hedging"), c.get("location"), json.dumps(c.get("supported_by"))))
        for b in e.get("bias_flags", []):
            flags.append((doc, side, b.get("stage"), b.get("severity"), b.get("kind"), b.get("observation")))
    con.execute("CREATE OR REPLACE TABLE model (doc VARCHAR, extractor VARCHAR, model_id VARCHAR, label VARCHAR, role VARCHAR, adjusted_for VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE claim (doc VARCHAR, extractor VARCHAR, text VARCHAR, relation VARCHAR, hedging VARCHAR, location VARCHAR, supported_by VARCHAR)")
    con.execute("CREATE OR REPLACE TABLE bias_flag (doc VARCHAR, extractor VARCHAR, stage VARCHAR, severity VARCHAR, kind VARCHAR, observation VARCHAR)")
    if models: con.executemany("INSERT INTO model VALUES (?,?,?,?,?,?)", models)
    if claims: con.executemany("INSERT INTO claim VALUES (?,?,?,?,?,?,?)", claims)
    if flags: con.executemany("INSERT INTO bias_flag VALUES (?,?,?,?,?,?)", flags)
    return con

if __name__ == "__main__":
    if sys.argv[1:] == ["verify"]: print(verify())
    else:
        con = load(); print(con.execute("SELECT count(*) FROM datum").fetchone() if glob.glob("data/*.jsonl") else "no data yet")
