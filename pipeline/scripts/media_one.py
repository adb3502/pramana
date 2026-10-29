import sys, json, os
sys.argv = [sys.argv[0]] + sys.argv[1:]
sys.path.insert(0, "scripts"); sys.path.insert(0, ".")
import media as M
i = sys.argv[1]
t = M.jload(f"{M.W}/text/{i}.json"); print(M.claims_one(t))
c = M.jload(f"{M.W}/claims/{i}.json"); links = {l["i"]: l["href"] for l in t["links"]}
for cl in c.get("claims", []):
    for ct in cl.get("cites", []):
        hit = M.resolve_link(links[ct["link"]]) if isinstance(ct.get("link"), int) and ct["link"] in links else None
        if isinstance(ct.get("link"), int) and ct["link"] in links: ct["href"] = links[ct["link"]]
        ct["resolved"] = hit or M.resolve_desc(ct.get("description"))
c["resolved"] = True; M.jdump(c, f"{M.W}/claims/{i}.json")
K, P = M.graph_index(); rows = []
for cl in c.get("claims", []):
    hit = next((x["resolved"] for x in cl.get("cites", []) if x.get("resolved")), None)
    rows.append({"claim": cl["text"], "quote": cl.get("quote"), "language": cl.get("language"), "source": hit, "traceability": M.trace(cl),
                 "fidelity": M.fidelity(cl, hit), "strength": M.strength(K, P, cl), "spin": cl.get("spin") or []})
M.jdump(rows, f"{M.W}/scored_{i}.json"); print(json.dumps(rows, indent=1)[:6000])
