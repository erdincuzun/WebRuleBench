"""
test_score_selector.py
=======================
score_selector() fonksiyonunu gerçek örnek sayfalar ve onaylı ground-truth
selector'ları (tests/fixtures/) üzerinde doğrular.
"""

import json
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent))

from webrulebench.evaluation.metrics import score_selector

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_DOMAINS = ["harborherald.example", "pulsedaily.example", "noticiasdelnorte.example"]   # sentetik (demo/make_fixtures.py)


def _load_fixture(domain: str):
    gt = json.loads((FIXTURES_DIR / domain / "ground_truth.json").read_text(encoding="utf-8"))
    html = (FIXTURES_DIR / domain / gt["file"]).read_text(encoding="utf-8", errors="ignore")
    return gt, BeautifulSoup(html, "html.parser")


@pytest.mark.parametrize("domain", FIXTURE_DOMAINS)
def test_gt_selector_scores_well_against_itself(domain):
    """GT selector'ı kendisiyle karşılaştırıldığında hiçbir zaman WRONG olmamalı.

    Not: Bir layout birden çok sayfaya atanır; bu yüzden tekil örnek sayfada
    bazı opsiyonel alanlar (örn. images) hiç eleman bulamayabilir (MISS/NULL) —
    bu normaldir. Asıl garanti, selector kendisiyle karşılaştırıldığında asla
    WRONG (skor 0, eleman bulundu ama içerik uyuşmuyor) çıkmamasıdır.
    """
    gt, soup = _load_fixture(domain)
    for field, selector in gt["selectors"].items():
        score, label = score_selector(soup, selector, selector, field=field)
        assert label != "WRONG", f"{domain}/{field}: self-match should never be WRONG, got {label}"
        if label in ("PARTIAL", "MATCH", "CONTAINER"):
            assert score > 0.5, f"{domain}/{field}: expected reasonably high self-match, got {score} ({label})"


@pytest.mark.parametrize("domain", FIXTURE_DOMAINS)
def test_title_selector_finds_nonempty_text(domain):
    """title alanı için GT selector sayfada gerçekten bir şey bulmalı."""
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
