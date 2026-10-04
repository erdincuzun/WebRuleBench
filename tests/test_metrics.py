"""
test_metrics.py
================
metrics.py içindeki temel benzerlik/skorlama fonksiyonları için birim testler.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from webrulebench.evaluation.metrics import word_f1_similarity, jaccard, dates_match, score_text, score_images


def test_word_f1_identical_strings():
    assert word_f1_similarity("hello world", "hello world") == 1.0


def test_word_f1_disjoint_strings():
    assert word_f1_similarity("hello world", "foo bar") == 0.0


def test_word_f1_partial_overlap():
    score = word_f1_similarity("the cat sat on the mat", "the cat sat")
    # precision = 3/3 = 1.0, recall = 3/6 = 0.5 -> F1 = 2*1*0.5/1.5 = 0.667
    assert 0.66 < score < 0.67


def test_word_f1_empty_input_is_zero():
    assert word_f1_similarity("", "hello") == 0.0
    assert word_f1_similarity("hello", "") == 0.0


def test_jaccard_identical_sets():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0


def test_jaccard_disjoint_sets():
    assert jaccard({"a"}, {"b"}) == 0.0


def test_jaccard_partial_overlap():
    # intersection={b,c} (2), union={a,b,c,d} (4) -> 0.5
    assert jaccard({"a", "b", "c"}, {"b", "c", "d"}) == 0.5


def test_jaccard_both_empty_is_one():
    assert jaccard(set(), set()) == 1.0


def test_dates_match_same_day_different_format():
    assert dates_match("2026-03-01", "March 1, 2026") is True


def test_dates_match_different_day():
    assert dates_match("2026-03-01", "2026-03-02") is False


def test_score_text_null_when_extracted_empty():
    score, label = score_text("", "some ground truth")
    assert (score, label) == (0.0, "NULL")


def test_score_text_no_gt():
    score, label = score_text("some text", "")
    assert (score, label) == (-1.0, "NO_GT")


def test_score_text_date_exact_match():
    score, label = score_text("2026-03-01", "March 1, 2026", field="date")
    assert (score, label) == (1.0, "MATCH")


def test_score_images_jaccard_based():
    score, label = score_images({"a.jpg", "b.jpg"}, {"a.jpg", "b.jpg"})
    assert (score, label) == (1.0, "PARTIAL")


def test_score_images_null_when_empty():
    score, label = score_images(set(), {"a.jpg"})
    assert (score, label) == (0.0, "NULL")
