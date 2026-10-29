"""Breadth-first reference crawl via OpenAlex (better coverage than Europe PMC:
it includes references listed in supplements). Levels: 0 = seed.
Works at levels 0..MAXFETCH are fetched in full; the next level is only counted."""
import json, sys, time, pathlib, requests, concurrent.futures as cf
from collections import Counter
RAW = pathlib.Path("raw_oa"); RAW.mkdir(exist_ok=True)
S = requests.Session()
FIELDS = "id,doi,ids,title,publication_year,type,referenced_works,cited_by_count,open_access,primary_location,primary_topic"

def fetch1(wid):
    name = RAW / (wid + ".json")
    if name.exists(): return json.loads(name.read_text())
    for a in range(6):
        try:
            r = S.get(f"https://api.openalex.org/works/{wid}", params={"select": FIELDS}, timeout=60)
            if r.status_code == 200:
                d = r.json(); name.write_text(json.dumps(d)); return d
            if r.status_code == 404: return None
            time.sleep(min(30, 2 ** a))
        except Exception:
            time.sleep(min(30, 2 ** a))
    return None

def fetch(batch):
    return [w for w in map(fetch1, batch) if w]

def short(u): return u.rsplit("/", 1)[-1]

def main(seed, maxfetch):
    level = {seed: 0}; works = {}; frontier = [seed]; stats = []; failed = 0
    for L in range(0, maxfetch + 1):
        ids = [i for i in frontier if i not in works]
        batches = [ids[i:i + 5] for i in range(0, len(ids), 5)]
        with cf.ThreadPoolExecutor(8) as ex:
            for res in ex.map(fetch, batches):
                if res is None: failed += 1; continue
                for w in res: works[short(w["id"])] = w
        nxt = []; mentions = new = seen = noref = 0
        for i in frontier:
            w = works.get(i)
            refs = [short(r) for r in (w or {}).get("referenced_works", [])]
            if not refs: noref += 1
            for r in refs:
                mentions += 1
                if r in level: seen += 1; continue
                level[r] = L + 1; nxt.append(r); new += 1
        stats.append({"from_level": L, "papers": len(frontier), "fetched": sum(1 for i in frontier if i in works),
                      "no_reference_list": noref, "reference_mentions": mentions,
                      "new_unique_next_level": new, "already_seen": seen, "failed_batches": failed})
        print(json.dumps(stats[-1]), flush=True)
        frontier = nxt
    json.dump({"seed": seed, "level": level, "stats": stats}, open("oa_tree.json", "w"))
    with open("oa_works.jsonl", "w") as f:
        for k, w in works.items():
            w["level"] = level.get(k); f.write(json.dumps(w) + "\n")

if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
