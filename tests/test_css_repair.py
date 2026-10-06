"""
test_css_repair.py
==================
LLM'in CSS kurallarına sezgisel onarım: varsayılan kapalı (kural modelin yazdığı gibi döner); açıkken iskelette
class olarak geçen adlar etikete çevrilmez ve tırnak içindeki metin bozulmaz. Deney yapılandırması seçimi kaydeder.
"""

import json

import pytest

from webrulebench.pipeline.llm_extractor import LLMExtractor

SKELETON = ('<html><body><article><h1 class="title">x</h1><div class="meta"><div class="tags"><a>t</a></div></div>'
            '<div class="c-detail__category"><a>c</a></div><main id="content"><p>b</p></main></article></body></html>')


def _rules(monkeypatch, rules, repair):
    ex = LLMExtractor(backend="ollama", model="m", rule_type="css", fields=list(rules), repair_css=repair)
    monkeypatch.setattr(ex, "_call_llm", lambda prompt: (json.dumps(rules), "", 1, 1))
    return ex.extract(SKELETON, domain="x.example").selectors


def test_rules_are_scored_as_written_by_default(monkeypatch):
    rules = {"title": "h1.title", "tags": "div.meta div.tags a", "body": "article p"}
    assert _rules(monkeypatch, rules, repair=False) == rules


@pytest.mark.parametrize("rule,expected", [
    ("h1.title", "h1.title"),                                            # class in the skeleton, not <title>
    ("article div.meta div.tags a", "article div.meta div.tags a"),
    ("div.c-detail__category.a", "div.c-detail__category a"),            # no class "a" → descendant <a>
    ("span:contains('27 Mart 2026')", "span:contains('27 Mart 2026')"),  # quoted text is left alone
    ('div[class="a b"] p', 'div[class="a b"] p'),
    ("header article-header h1", "header.article-header h1"),            # missing dot between classes
])
def test_repairs(monkeypatch, rule, expected):
    assert _rules(monkeypatch, {"title": rule}, repair=True)["title"] == expected


def test_weak_body_selector_is_replaced_only_with_repair(monkeypatch):
    assert _rules(monkeypatch, {"body": "article p"}, repair=True)["body"] == "main#content"
    assert _rules(monkeypatch, {"body": "article p"}, repair=False)["body"] == "article p"


def test_experiment_config_records_the_choice(monkeypatch):
    from webrulebench.evaluation.experiments import validate_config
    from webrulebench.pipeline import llm_models
    monkeypatch.setattr(llm_models, "model_catalog", lambda *a, **k: {"reachable": False, "models": []})
    base = {"backend": "ollama", "model": "m"}
    assert validate_config({**base, "rule_type": "css"})["css_repair"] is False
    assert validate_config({**base, "rule_type": "css", "css_repair": True})["css_repair"] is True
    assert validate_config({**base, "rule_type": "xpath", "css_repair": True})["css_repair"] is False
    assert validate_config({**base, "rule_type": "regex", "rule_source": "llm_css_regexn", "css_repair": True})["css_repair"] is True
