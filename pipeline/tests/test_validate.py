"""Regression tests for validate (mission 2). Run: .venv/bin/python tests/test_validate.py"""
import sys, os, json, tempfile, shutil
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
from epistemic import validate

def _run(doc, ref=None):
    tmp = tempfile.mkdtemp()
    try:
        for sub in ("parsed", "ext"): os.makedirs(os.path.join(tmp, sub))
        shutil.copy(f"{ROOT}/parsed/{doc}.json", f"{tmp}/parsed/")
        for s in ("A", "B", "adj"):
            if os.path.exists(f"{ROOT}/ext/{doc}.{s}.json"): shutil.copy(f"{ROOT}/ext/{doc}.{s}.json", f"{tmp}/ext/")
        return validate.run(doc, tmp, ref)
    finally: shutil.rmtree(tmp)

def test_kappa_in_range_and_comma_ci_triplets():
    # v2.5d bug: the text-triplet loop overwrote the kappa variable (kappa 282)
    r = _run("PMC1756940", json.load(open(f"{ROOT}/reference/PMC1756940.json")))
    assert -1 <= r["data_vs_not_kappa"] <= 1
    assert r["external"]["found"] == 6 and r["ratio_triplets"] >= 6   # Woodward Discussion "0.68 (0.42, 1.10)" comma CIs

if __name__ == "__main__":
    test_kappa_in_range_and_comma_ci_triplets(); print("ok")
