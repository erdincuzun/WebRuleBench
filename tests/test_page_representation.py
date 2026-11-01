"""
test_page_representation.py
===========================
Deney ayarı skeleton = none: LLM iskelet yerine temizlenmiş sayfanın HTML'ini görür. Otomatik prompt
bunu söyler, iskeletli prompt değişmez (eski deneylerle karşılaştırılabilirlik), eski kayıtlar iskeletle
sürer ve HTML'deki yıldızlı metin *annotation* sanılıp silinmez. Sunucunun sessizce kestiği girdi
(bağlam penceresini aşan HTML) fark edilir.
"""

import pytest

from webrulebench.evaluation import experiments as X
from webrulebench.pipeline.llm_extractor import LLMExtractor, input_truncation
from webrulebench.pipeline.prompt_builder import build_prompt

TEMPLATE = {"name": "News Article", "fields": {"title": {"description": "headline", "required": True}}}


@pytest.mark.parametrize("rule_type", ["css", "xpath", "regex"])
def test_html_prompt_does_not_mention_skeleton(rule_type):
    p = build_prompt(TEMPLATE, rule_type, skeleton=False)
    assert "{skeleton}" in p["user"]          # yer tutucu adı aynı kalır (extract onu doldurur)
    assert "skeleton" not in (p["system"] + p["user"].replace("{skeleton}", "")).lower()


@pytest.mark.parametrize("rule_type", ["css", "xpath", "regex"])
def test_skeleton_prompt_is_the_default(rule_type):
    assert build_prompt(TEMPLATE, rule_type) == build_prompt(TEMPLATE, rule_type, skeleton=True)
    assert "HTML skeleton" in build_prompt(TEMPLATE, rule_type)["system"]


def test_config_defaults_to_skeleton_and_rejects_unknown():
    assert X.validate_config({"backend": "ollama", "rule_type": "css"})["skeleton"] == "enriched"
    assert X.validate_config({"backend": "ollama", "rule_type": "css", "skeleton": "none"})["skeleton"] == "none"
    with pytest.raises(X.ExperimentError):
        X.validate_config({"backend": "ollama", "rule_type": "css", "skeleton": "full"})


@pytest.mark.parametrize("annotated,expected", [(True, "<p>a c</p>"), (False, "<p>a *b* c</p>")])
def test_annotation_stripping_only_for_skeletons(monkeypatch, annotated, expected):
    ex = LLMExtractor(backend="ollama", model="m", rule_type="css", fields=["title"], user_prompt="{domain}|{skeleton}")
    sent = []
    monkeypatch.setattr(ex, "_call_llm", lambda prompt: (sent.append(prompt), ('{"title": "h1"}', "", 1, 1))[1])
    ex.extract("<p>a *b* c</p>", domain="d", annotated=annotated)
    assert sent[0] == "d|" + expected


@pytest.mark.parametrize("chars, tokens", [(66575, 16386), (200000, 8194), (900000, 65538), (344000, 65539)])
def test_ollama_half_window_is_truncation(chars, tokens):
    assert "half of a" in input_truncation(chars, tokens)


def test_high_chars_per_token_is_truncation():
    assert "characters/token" in input_truncation(70000, 10000)


@pytest.mark.parametrize("chars, tokens", [(53000, 20896), (12700, 2655), (60000, 16385), (100, 0), (40, 10)])
def test_untruncated_input_is_not_flagged(chars, tokens):
    assert input_truncation(chars, tokens) == ""
