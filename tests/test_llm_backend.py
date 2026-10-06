"""
test_llm_backend.py
===================
Ollama çağrısı: modele özel `think` ayarı isteğe yalnızca verildiğinde eklenir; düşünen model çıktı
token'larını düşünmeye harcayıp boş yanıt dönerse hata bunu söyler; çağrı hatası "Empty response" ile
örtülmez. (Sunucu gerekmez: _post taklit edilir.)
"""

import pytest

from webrulebench.pipeline import llm_models as LM
from webrulebench.pipeline.llm_extractor import LLMExtractor

CFG = {"api": "ollama", "url": "http://localhost:11434/api/chat"}


def _extractor(monkeypatch, reply):
    ex = LLMExtractor(backend="ollama", model="m", rule_type="css", fields=["title"])
    sent = []

    def fake_post(url, **kw):
        sent.append(kw["json"])
        return reply

    monkeypatch.setattr(ex, "_post", fake_post)
    return ex, sent


@pytest.mark.parametrize("value,expected", [("false", False), ("True", True), ("0", False), (True, True)])
def test_think_parameter_parses_booleans(value, expected):
    assert LM.PARAM_KEYS["think"](value) is expected


def test_think_parameter_rejects_other_values():
    with pytest.raises(ValueError):
        LM.PARAM_KEYS["think"]("maybe")


def test_think_is_sent_only_when_set(monkeypatch):
    ex, sent = _extractor(monkeypatch, {"message": {"content": "{}"}, "prompt_eval_count": 3, "eval_count": 1})
    ex._call_ollama("p", CFG, "", {"max_tokens": 512})
    ex._call_ollama("p", CFG, "", {"max_tokens": 512, "think": False})
    assert "think" not in sent[0]
    assert sent[1]["think"] is False and sent[1]["options"]["num_predict"] == 512


def test_output_spent_on_thinking_is_reported(monkeypatch):
    ex, _ = _extractor(monkeypatch, {"message": {"content": "", "thinking": "Let me see"}, "eval_count": 512})
    text, error, _, gtok = ex._call_ollama("p", CFG, "", {})
    assert text == "" and "think = false" in error and gtok == 512


def test_call_error_is_not_masked_by_empty_response(monkeypatch):
    ex = LLMExtractor(backend="ollama", model="m", rule_type="css", fields=["title"])
    monkeypatch.setattr(ex, "_call_llm", lambda prompt: ("", "Timeout (30 s)", 0, 0))
    res = ex.extract("<html><body><h1>t</h1></body></html>", domain="x.example")
    assert not res.success and res.error == "Timeout (30 s)"
