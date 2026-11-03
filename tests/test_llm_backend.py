"""
test_llm_backend.py
===================
Ollama ve OpenAI uyumlu çağrı: modele özel `think` ayarı isteğe yalnızca verildiğinde eklenir; düşünen model çıktı
token'larını düşünmeye harcayıp boş yanıt dönerse hata bunu söyler; çağrı hatası "Empty response" ile
örtülmez; sağlayıcının durma nedeni (finish_reason) kaydedilir, çıktı sınırına takılan yanıt bunu söyler.
(Sunucu gerekmez: _post taklit edilir.)
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


OA_CFG = {"api": "openai", "url": "http://localhost:1/v1"}


def test_openai_thinking_is_sent_only_when_set(monkeypatch):
    ex, sent = _extractor(monkeypatch, {"choices": [{"message": {"content": "{}"}}]})
    ex._call_openai("p", OA_CFG, "", {"max_tokens": 512})
    ex._call_openai("p", OA_CFG, "", {"max_tokens": 512, "think": False})
    assert "thinking" not in sent[0] and "think" not in sent[0]
    assert sent[1]["thinking"] is False


def test_openai_output_spent_on_reasoning_is_reported(monkeypatch):
    ex, _ = _extractor(monkeypatch, {"choices": [{"message": {"content": None, "reasoning": "Let me see"},
                                                  "finish_reason": "length"}], "usage": {"completion_tokens": 512}})
    text, error, _, gtok = ex._call_openai("p", OA_CFG, "", {})
    assert text == "" and "think = false" in error and gtok == 512


def test_call_error_is_not_masked_by_empty_response(monkeypatch):
    ex = LLMExtractor(backend="ollama", model="m", rule_type="css", fields=["title"])
    monkeypatch.setattr(ex, "_call_llm", lambda prompt: ("", "Timeout (30 s)", 0, 0))
    res = ex.extract("<html><body><h1>t</h1></body></html>", domain="x.example")
    assert not res.success and res.error == "Timeout (30 s)"


def _openai_extract(monkeypatch, reply):
    monkeypatch.setitem(LM.BACKENDS, "oa", {"api": "openai", "url": "http://localhost:1/v1"})
    ex = LLMExtractor(backend="oa", model="m", rule_type="css", fields=["title"])
    monkeypatch.setattr(ex, "_post", lambda url, **kw: reply)
    return ex.extract("<html><body><h1>t</h1></body></html>", domain="x.example")


def test_finish_reason_is_recorded(monkeypatch):
    res = _openai_extract(monkeypatch, {"choices": [{"message": {"content": '{"title": "h1"}'}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    assert res.success and res.finish_reason == "stop" and res.metrics()["finish_reason"] == "stop"


def test_output_limit_is_reported_on_unparsed_response(monkeypatch):
    res = _openai_extract(monkeypatch, {"choices": [{"message": {"content": '{"title": "h1'}, "finish_reason": "length"}],
                                        "usage": {"prompt_tokens": 10, "completion_tokens": 512}})
    assert not res.success and res.finish_reason == "length"
    assert "output limit reached (512 tokens" in res.error


def test_ollama_done_reason_is_the_finish_reason(monkeypatch):
    ex, _ = _extractor(monkeypatch, {"message": {"content": "{}"}, "done_reason": "length", "eval_count": 512})
    ex._call_ollama("p", CFG, "", {})
    assert ex._finish == "length"


@pytest.fixture
def trickle_server():
    """Başlığı hemen yollayıp gövdeye ara ara bir boşluk yazan, yanıtı hiç bitirmeyen sunucu."""
    import http.server
    import threading
    import time

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                for _ in range(100):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(0.2)
            except OSError:
                pass

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_call_timeout_is_total_even_if_server_keeps_connection_alive(monkeypatch, trickle_server):
    import time
    monkeypatch.setitem(LM.BACKENDS, "trickle", {"api": "openai", "url": trickle_server})
    ex = LLMExtractor(backend="trickle", model="m", rule_type="css", fields=["title"], timeout=1)
    t0 = time.monotonic()
    text, error, _, _ = ex._call_llm("p")
    assert text == "" and error == "Timeout (1 s)" and time.monotonic() - t0 < 3


def test_timeout_comes_from_backend_unless_given(monkeypatch):
    monkeypatch.setitem(LM.BACKENDS, "slow", {"api": "openai", "url": "http://localhost:1/v1", "timeout": 900})
    assert LLMExtractor(backend="slow").timeout == 900
    assert LLMExtractor(backend="slow", timeout=30).timeout == 30
    monkeypatch.setitem(LM.BACKENDS, "plain", {"api": "openai", "url": "http://localhost:1/v1"})
    assert LLMExtractor(backend="plain").timeout == LM.DEFAULT_TIMEOUT_S
