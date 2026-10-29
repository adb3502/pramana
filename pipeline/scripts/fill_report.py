"""Fill REPORT_DRAFT.md placeholders from current artifacts -> REPORT.md. Usage: python scripts/fill_report.py "<end time>" """
import json, glob, subprocess, statistics, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import summarize

docs = sorted(pathlib.Path(p).stem for p in glob.glob("validation/*.json") if pathlib.Path(p).stem.count(".") == 0)
R = [summarize.row(d) for d in docs]
table = subprocess.run([sys.executable, "scripts/summarize.py", "--md"], capture_output=True, text=True).stdout.strip()
F = [json.loads(l) for l in open("logs/paper_findings.jsonl")]
outside = [f for f in F if f["finding"] == "estimate outside its CI"]
off = [f for f in F if f["finding"] != "estimate outside its CI"]
fmt = lambda f: (f'- {f["doc"]} {f["anchor"]["table"]} row {f["anchor"]["row"]} col {f["anchor"]["col"]}: `{f["text"].strip()}`' if "row" in f["anchor"]
                 else f'- {f["doc"]} text section {f["anchor"].get("section")} (estimate and CI in adjacent spans; estimate `{f["estimate"]}`, CI {f["ci"]})')
findings = (f"Estimate outside its own CI ({len(outside)}; near-certain errors in the published table):\n" + "\n".join(map(fmt, outside)) +
            f"\n\nRatio off the log-midpoint of its CI by more than rounding can explain ({len(off)}; weaker evidence, since a non-Wald interval can be asymmetric):\n" + "\n".join(map(fmt, off)) +
            "\n\nPMC12178019 (Ma 2025, coffee/tea and macrovascular complications in type 2 diabetes) accounts for 12 of these, including a reversed CI (1.987 (0.782-0.051)) and a malformed cell; its tables deserve low weight until checked against the source PDF.")
jev = json.loads(subprocess.run([sys.executable, "scripts/jev_spent.py"], capture_output=True, text=True).stdout)
ext = 0.0
for f in glob.glob("logs/PMC*.[AB].json"):
    try: ext += json.load(open(f)).get("total_cost_usd") or 0
    except Exception: pass
adj = sum(json.load(open(f)).get("cost_usd_equiv", 0) for f in glob.glob("ext/*.adj.json")) + \
      sum(json.load(open(f)).get("cost_usd_equiv", 0) for f in glob.glob("ext/superseded/*.adj*.json"))
dec = [x for f in glob.glob("ext/*.adj.json") for x in json.load(open(f))["decisions"] if x.get("jev") and x.get("role")]
jevadj = f'{sum(1 for x in dec if x["jev"] == x["role"])}/{len(dec)}'
nled = sum(1 for _ in open("ledger.jsonl"))
s = open("REPORT_DRAFT.md").read()
rep = {"__END__": sys.argv[1], "__NDOCS__": str(len(R)), "__NNUM__": f'{sum(r["numbers"] for r in R):,}', "__NDATA__": f'{sum(r["data"] for r in R):,}',
       "__NLEDGER__": str(nled), "__MEDROLE__": f'{statistics.median(r["role"] for r in R if r["role"] is not None):.3f}',
       "__MEDKAPPA__": f'{statistics.median(r["kappa"] for r in R):.3f}', "__NFIND__": str(len(F)),
       "__JEVTOK__": f'{jev["jev_input_tokens"]/1e6:.2f}M', "__JEVUSD__": f'${jev["jev_usd"]:.2f}', "__EXTUSD__": f"{ext:.0f}", "__ADJUSD__": f"{adj:.0f}",
       "__TABLE__": table, "__FINDINGS__": findings, "__JEVADJ__": jevadj}
for k, v in rep.items(): s = s.replace(k, v)
assert "__" not in s.replace("__init__", ""), [w for w in s.split() if "__" in w][:5]
open("REPORT.md", "w").write(s)
print(json.dumps({k: v for k, v in rep.items() if k not in ("__TABLE__", "__FINDINGS__")}))
