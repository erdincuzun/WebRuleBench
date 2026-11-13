"""
test_html_cleaner.py
=====================
Checks that the HTMLCleaner strategies run on the sample pages (tests/fixtures/)
without crashing and show the expected basic behaviour (size reduction,
script/style removal).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from webrulebench.pipeline.html_cleaner import HTMLCleaner, CleanerConfig, STRATEGIES

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_DOMAINS = ["harborherald.example", "pulsedaily.example", "noticiasdelnorte.example"]   # synthetic (demo/make_fixtures.py)


def _load_html(domain: str) -> str:
    return (FIXTURES_DIR / domain / "article_001.html").read_text(encoding="utf-8", errors="ignore")


@pytest.mark.parametrize("domain", FIXTURE_DOMAINS)
@pytest.mark.parametrize("strategy", STRATEGIES)
def test_strategy_runs_without_error_and_shrinks_html(domain, strategy):
    html = _load_html(domain)
    cleaner = HTMLCleaner(CleanerConfig())
    result = cleaner.clean(html, strategy=strategy)

    assert result.cleaned_chars > 0
    # Every strategy removes noise, so the output must be smaller than or equal to the original
    assert result.cleaned_chars <= result.original_chars


@pytest.mark.parametrize("domain", FIXTURE_DOMAINS)
def test_whitelist_strategy_removes_script_and_style(domain):
    html = _load_html(domain)
    cleaner = HTMLCleaner(CleanerConfig())
    result = cleaner.clean(html, strategy="whitelist")

    assert "<script" not in result.cleaned_html
    assert "<style" not in result.cleaned_html


def test_unknown_strategy_raises():
    cleaner = HTMLCleaner(CleanerConfig())
    with pytest.raises(ValueError):
        cleaner.clean("<html></html>", strategy="not_a_real_strategy")


def test_none_strategy_returns_page_unchanged():
    html = _load_html(FIXTURE_DOMAINS[0])
    assert HTMLCleaner(CleanerConfig()).clean(html, strategy="none").cleaned_html == html
