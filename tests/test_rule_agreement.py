"""
test_rule_agreement.py
======================
rule_agreement.py: kural normalizasyonu, gözlenen uyum, Fleiss κ ve Krippendorff α.
Tarayıcıdaki kopyanın (static/compile.js) aynı normalizasyonu yaptığı da denetlenir.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from webrulebench.rules.rule_agreement import normalize_rule, observed_agreement, fleiss_kappa, krippendorff_alpha  # noqa: E402

CASES = {
    "div.full-post-image  >img": "div.full-post-image > img",
    "DIV.b.a#x > IMG": "div#x.a.b > img",
    "a[href='x']": 'a[href="x"]',
    "a[ href = x ]": 'a[href="x"]',
    "h2 a, h1 a": "h1 a, h2 a",
    "*.x": ".x",
    'a[href~="x y"]': 'a[href~="x y"]',
    "li:nth-child(2) a": "li:nth-child(2) a",
    "span:not(.a > .b)": "span:not(.a > .b)",
}


@pytest.mark.parametrize("raw,expected", CASES.items())
def test_normalize_writing_differences(raw, expected):
    assert normalize_rule(raw) == expected


def test_normalize_keeps_meaning_differences():
    assert normalize_rule("div.x > img") != normalize_rule("div.x img")
    assert normalize_rule("h1") != normalize_rule("h1.title")


def test_normalize_empty_and_other_languages():
    assert normalize_rule("") is None and normalize_rule(None) is None
    assert normalize_rule("  //h1  ", "xpath") == "//h1"


def test_observed_agreement():
    assert observed_agreement(["a", "a", None]) == 1.0
    assert observed_agreement(["a", None, None]) is None          # tek dolu yanıt: tanımsız
    assert observed_agreement(["a", "b", "c"]) == 0.0
    assert observed_agreement(["a", "a", "b"]) == pytest.approx(1 / 3)


def test_fleiss_kappa_hand_computed():
    # P_i = 1/3, 1, 0 → P̄ = 4/9; kategoriler a2 b1 c3 d1 e1 (N=8) → P_e = 16/64
    r = fleiss_kappa([["a", "a", "b"], ["c", "c", "c"], ["d", "e"]])
    assert r["po"] == pytest.approx(4 / 9)
    assert r["pe"] == pytest.approx(0.25)
    assert r["kappa"] == pytest.approx((4 / 9 - 0.25) / 0.75)
    assert r["n_subjects"] == 3


def test_fleiss_kappa_ignores_single_rating_subjects():
    assert fleiss_kappa([["a", None], [None, None]]) is None


def test_krippendorff_alpha_nominal():
    # Krippendorff (nominal) elle: D_o = 2/6, D_e = 18/30 → α = 1 − (1/3)/(3/5) = 4/9
    nominal = lambda a, b: 0.0 if a == b else 1.0
    r = krippendorff_alpha([["a", "a"], ["b", "b"], ["a", "b"]], nominal)
    assert r["alpha"] == pytest.approx(4 / 9)
    assert krippendorff_alpha([["x", "x", "x"], ["y", "y", "y"]], nominal)["alpha"] == 1.0


@pytest.mark.skipif(not shutil.which("node"), reason="node yok")
def test_browser_copy_normalizes_identically():
    src = (ROOT / "webrulebench" / "webapp" / "static" / "compile.js").read_text(encoding="utf-8")
    code = src[src.index("function _splitTop"):src.index("function _observedAgreement")]
    js = code + f"\nconsole.log(JSON.stringify({json.dumps(list(CASES))}.map(c => _normalizeRule(c))));"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [normalize_rule(c) for c in CASES]


def test_fleiss_kappa_undefined_for_single_subject():
    r = fleiss_kappa([["a", "b"]])
    assert r["kappa"] is None and r["po"] == 0.0
