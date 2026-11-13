"""
test_score_selector.py
=======================
Checks the score_selector() function on real sample pages and approved ground-truth
selectors (tests/fixtures/).
"""

import json
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from webrulebench.evaluation.metrics import score_selector

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_DOMAINS = ["harborherald.example", "pulsedaily.example", "noticiasdelnorte.example"]   # synthetic (demo/make_fixtures.py)


def _load_fixture(domain: str):
    gt = json.loads((FIXTURES_DIR / domain / "ground_truth.json").read_text(encoding="utf-8"))
    html = (FIXTURES_DIR / domain / gt["file"]).read_text(encoding="utf-8", errors="ignore")
    return gt, BeautifulSoup(html, "html.parser")


@pytest.mark.parametrize("domain", FIXTURE_DOMAINS)
def test_gt_selector_scores_well_against_itself(domain):
    """A GT selector compared with itself must never be WRONG.

    Note: a layout is assigned to several pages, so on a single sample page
    some optional fields (e.g. images) may find no element (MISS/NULL) —
    this is normal. The real guarantee is that a selector compared with itself
    is never WRONG (score 0, element found but content does not match).
    """
    gt, soup = _load_fixture(domain)
    for field, selector in gt["selectors"].items():
        score, label = score_selector(soup, selector, selector, field=field)
        assert label != "WRONG", f"{domain}/{field}: self-match should never be WRONG, got {label}"
        if label in ("PARTIAL", "MATCH", "CONTAINER"):
            assert score > 0.5, f"{domain}/{field}: expected reasonably high self-match, got {score} ({label})"


@pytest.mark.parametrize("domain", FIXTURE_DOMAINS)
def test_title_selector_finds_nonempty_text(domain):
    """The GT selector for the title field must actually find something on the page."""
    gt, soup = _load_fixture(domain)
    title_selector = gt["selectors"].get("title")
    if not title_selector:
        pytest.skip(f"{domain} has no title selector in this layout")
    elems = soup.select(title_selector)
    assert elems, f"{domain}: title selector '{title_selector}' matched no elements"
    assert elems[0].get_text(strip=True)


def test_missing_selector_scores_zero():
    soup = BeautifulSoup("<html><body><h1>Title</h1></body></html>", "html.parser")
    score, label = score_selector(soup, "h1", "div.does-not-exist", field="title")
    assert label == "MISS"
    assert score == 0.0


def test_empty_llm_selector_is_null():
    soup = BeautifulSoup("<html><body><h1>Title</h1></body></html>", "html.parser")
    score, label = score_selector(soup, "h1", None, field="title")
    assert (score, label) == (0.0, "NULL")
