"""
test_experiments_scoring.py
===========================
experiments.score_field: deneylerde (sayfa, alan) hücresinin skoru ve etiketi.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from webrulebench.evaluation.experiments import score_field, MATCH_AT  # noqa: E402


def test_rouge_identical_is_match():
    assert score_field(["a b c"], ["a b c"], "rouge") == (1.0, "MATCH")


def test_rouge_partial():
    s, label = score_field(["a b"], ["a x"], "rouge")
    assert s == 0.5 and label == "PARTIAL" and s < MATCH_AT


def test_empty_ground_truth_is_not_scored():
    assert score_field([], ["a"], "rouge") == (None, "NO_GT")


def test_empty_prediction_is_miss():
    assert score_field(["a"], [], "rouge") == (0.0, "MISS")


def test_jaccard_ignores_order():
    assert score_field(["x", "y"], ["y", "x"], "jaccard")[0] == 1.0


def test_exact_match_normalizes_whitespace():
    assert score_field(["10 TL"], ["10  TL"], "exact_match")[0] == 1.0
    assert score_field(["10 TL"], ["11 TL"], "exact_match")[0] == 0.0
