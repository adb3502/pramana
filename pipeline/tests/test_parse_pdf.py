"""Regression tests for PDF parser behaviors found in mission 2. Run: .venv/bin/python -m pytest -q tests  (or python tests/test_parse_pdf.py)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from epistemic.parse_pdf import undehyphen, dual_read, fix
from epistemic.parse import numbers_in

def test_dehyphen_join_restored():
    # docling joins '45–' + newline + '69' into '4569'; the raw text layer still has the line break
    assert undehyphen("aged 4569 years", "(aged 45–\n69 years)") == "aged 45–69 years"
    assert [x["value"] for x in numbers_in(undehyphen("1998 2009 cohort", "1998–\n2009 cohort"))] == [1998, 2009]

def test_dual_read_catches_join():
    nums = numbers_in("aged 4569 years")              # the unfixed docling read
    assert dual_read(nums, {"pymupdf": "aged 45– 69 years"}) is False
    assert nums[0]["read_agree"] is False

def test_middot_and_thousands():
    assert [x["value"] for x in numbers_in(fix("0·81 (0·72, 0·92)"))] == [0.81, 0.72, 0.92]
    nums = numbers_in("33568")
    assert dual_read(nums, {"pymupdf": "33 568"}) is True   # plain-space thousands in the independent read

if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"): f(); print("ok", k)
