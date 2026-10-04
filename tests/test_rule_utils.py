"""
test_rule_utils.py
==================
rule_utils.py (CSS/XPath/Regex ortak çalıştırıcı) ve metrics.score_selector'ın
çoklu kural tipi desteğini doğrular.
"""

import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from webrulebench.rules.rule_utils import css_to_xpath, run_css, run_xpath, run_regex, run_rule
from webrulebench.evaluation.metrics import score_selector

HTML = """
<html><body>
<article>
  <h1 class="title">Hello World</h1>
  <div class="meta"><time>2024-01-01</time></div>
  <div class="body"><p>Some article text here.</p></div>
</article>
</body></html>
"""


def test_css_to_xpath_simple_class():
    xpath = css_to_xpath("h1.title")
    assert xpath is not None
    assert "h1" in xpath and "title" in xpath


def test_css_to_xpath_comma_selector_unions():
    xpath = css_to_xpath("div.a, div.b")
    assert xpath is not None
    assert " | " in xpath


def test_css_to_xpath_invalid_returns_none():
    assert css_to_xpath("") is None
    assert css_to_xpath(None) is None


def test_run_css_finds_element():
    soup  = BeautifulSoup(HTML, "html.parser")
    elems = run_css(soup, "h1.title")
    assert len(elems) == 1
    assert elems[0].get_text(strip=True) == "Hello World"


def test_run_xpath_finds_element():
    elems = run_xpath(HTML, "//h1[@class='title']")
    assert len(elems) == 1
    assert elems[0].text_content().strip() == "Hello World"


def test_run_regex_extracts_group():
    matches = run_regex(HTML, r'<h1 class="title">([^<]+)</h1>')
    assert matches == ["Hello World"]


def test_run_rule_dispatches_by_type():
    soup = BeautifulSoup(HTML, "html.parser")
    assert len(run_rule(soup, "h1.title", "css")) == 1
    assert len(run_rule(HTML, "//h1[@class='title']", "xpath")) == 1
    assert run_rule(HTML, r'<h1 class="title">([^<]+)</h1>', "regex") == ["Hello World"]


def test_run_rule_unknown_type_raises():
    with pytest.raises(ValueError):
        run_rule(HTML, "h1", "sparql")


@pytest.mark.parametrize("rule_type,rule", [
    ("css", "h1.title"),
    ("xpath", "//h1[@class='title']"),
    ("regex", r'<h1 class="title">([^<]+)</h1>'),
])
def test_score_selector_self_match_across_rule_types(rule_type, rule):
    """Her kural tipinde, GT ve LLM aynı kuralı kullanırsa skor mükemmel olmalı."""
    soup = BeautifulSoup(HTML, "html.parser")
    score, label = score_selector(
        soup, rule, rule, field="title",
        rule_type=rule_type, gt_rule_type=rule_type, raw_html=HTML,
    )
    assert label != "WRONG"
    assert score > 0.9


def test_score_selector_mixed_rule_types_css_gt_xpath_llm():
    """GT CSS, LLM XPath kullanıyor — aynı elementi bulduklarında yüksek skor beklenir."""
    soup = BeautifulSoup(HTML, "html.parser")
    score, label = score_selector(
        soup, "h1.title", "//h1[@class='title']", field="title",
        rule_type="xpath", gt_rule_type="css", raw_html=HTML,
    )
    assert label != "WRONG"
    assert score > 0.9


def test_score_selector_regex_no_match_is_miss():
    soup = BeautifulSoup(HTML, "html.parser")
    score, label = score_selector(
        soup, "h1.title", r"nonexistent-pattern-(\d+)", field="title",
        rule_type="regex", gt_rule_type="css", raw_html=HTML,
    )
    assert (score, label) == (0.0, "MISS")


def test_score_selector_malformed_xpath_is_miss_not_error():
    """rule_utils.run_xpath hatalı XPath'te sessizce [] döner (exception fırlatmaz),
    bu yüzden score_selector bunu MISS olarak görür — CSS'teki select() exception'ından
    farklı olarak burada 'geçersiz söz dizimi' ile 'hiç eşleşme yok' ayrımı yapılmaz."""
    soup = BeautifulSoup(HTML, "html.parser")
    score, label = score_selector(
        soup, "h1.title", "//h1[unbalanced(", field="title",
        rule_type="xpath", gt_rule_type="css", raw_html=HTML,
    )
    assert (score, label) == (0.0, "MISS")


def test_score_selector_defaults_to_css_backward_compat():
    """rule_type verilmezse eski davranış (css/css) korunmalı."""
    soup = BeautifulSoup(HTML, "html.parser")
    score, label = score_selector(soup, "h1.title", "h1.title", field="title")
    assert label != "WRONG"
    assert score > 0.9
