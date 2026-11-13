"""
test_rule_utils.py
==================
Checks rule_utils.py (shared CSS/XPath/Regex runner) and the support of
metrics.score_selector for multiple rule types.
"""

import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from webrulebench.rules.rule_utils import css_to_xpath, run_css, run_xpath, run_regex, run_rule, split_selector_list
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
    """For every rule type, the score must be perfect when GT and LLM use the same rule."""
    soup = BeautifulSoup(HTML, "html.parser")
    score, label = score_selector(
        soup, rule, rule, field="title",
        rule_type=rule_type, gt_rule_type=rule_type, raw_html=HTML,
    )
    assert label != "WRONG"
    assert score > 0.9


def test_score_selector_mixed_rule_types_css_gt_xpath_llm():
    """GT uses CSS, LLM uses XPath — a high score is expected when they find the same element."""
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
    """rule_utils.run_xpath silently returns [] on an invalid XPath (it raises no exception),
    so score_selector sees it as MISS — unlike the select() exception in CSS, no distinction
    is made here between 'invalid syntax' and 'no match at all'."""
    soup = BeautifulSoup(HTML, "html.parser")
    score, label = score_selector(
        soup, "h1.title", "//h1[unbalanced(", field="title",
        rule_type="xpath", gt_rule_type="css", raw_html=HTML,
    )
    assert (score, label) == (0.0, "MISS")


def test_score_selector_defaults_to_css_backward_compat():
    """If rule_type is not given, the old behaviour (css/css) must be kept."""
    soup = BeautifulSoup(HTML, "html.parser")
    score, label = score_selector(soup, "h1.title", "h1.title", field="title")
    assert (score, label) == (1.0, "MATCH")          # exact match, same label as in experiments


def test_run_regex_stops_catastrophic_backtracking(monkeypatch):
    from webrulebench.rules import rule_utils
    monkeypatch.setattr(rule_utils, "REGEX_TIMEOUT_S", 1.0)
    rule_utils.regex_timeouts(reset=True)
    assert run_regex("a" * 40 + "b", r"(a+)+$") == []
    assert rule_utils.regex_timeouts(reset=True) == [r"(a+)+$"]
    # the next regex works normally with a new helper process
    assert run_regex("<h1>Başlık</h1>", r"<h1>(.*?)</h1>") == ["Başlık"]
    assert rule_utils.regex_timeouts() == []


def test_run_regex_flags_and_invalid_pattern_unchanged():
    assert run_regex("<H1>\nx</H1>", r"<h1>(.*?)</h1>") == ["\nx"]   # IGNORECASE | DOTALL
    assert run_regex("abc", "([") == []


# --- selector lists are split at top-level commas only (commas inside (), [] and quotes are kept) ---

NESTED = """
<html><body>
<article><h2 class="headline">Inside</h2><p title="a, b">Text</p></article>
<h2 class="headline">Outside</h2>
</body></html>
"""


@pytest.mark.parametrize("selector, parts", [
    ("h1, h2", ["h1", "h2"]),
    ("article :is(h1, h2).headline", ["article :is(h1, h2).headline"]),
    (":not(.a, .b) > p , div[title='a, b'] ,", [":not(.a, .b) > p", "div[title='a, b']"]),
    ('a[data-x="),("], b', ['a[data-x="),("]', "b"]),
    ("", []),
])
def test_split_selector_list(selector, parts):
    assert split_selector_list(selector) == parts


def test_nested_comma_selector_runs_as_one_selector():
    soup = BeautifulSoup(NESTED, "html.parser")
    assert [e.get_text() for e in run_css(soup, "article :is(h1, h2).headline")] == ["Inside"]
    assert [e.get_text() for e in run_css(soup, 'p[title="a, b"], h9')] == ["Text"]
    assert len(run_css(soup, "article :is(h1, h2).headline, body > h2")) == 2     # a real list still works


def test_nested_comma_selector_in_scoring():
    """The values an experiment scores (rule_values) and the regex generator's CSS values."""
    from webrulebench.evaluation.experiments import rule_values, score_field
    from webrulebench.rules.regex_generator import css_values
    soup = BeautifulSoup(NESTED, "html.parser")
    rule = "article :is(h1, h2).headline"
    assert rule_values(NESTED, soup, rule, "css", "text", False) == ["Inside"]
    assert css_values(soup, rule) == ["Inside"]
    assert score_field(["Inside"], rule_values(NESTED, soup, rule, "css", "text", False), "rouge") == (1.0, "MATCH")
    # without merging, the first alternative of the list that matches is used; the nested comma is not an alternative
    assert rule_values(NESTED, soup, "h9, article :is(h1, h2).headline", "css", "text", False) == ["Inside"]


def test_nested_comma_selector_as_reference_in_score_selector():
    soup = BeautifulSoup(NESTED, "html.parser")
    score, label = score_selector(soup, "article :is(h1, h2).headline", "article h2")
    assert label == "MATCH" and score == 1.0
