"""
test_llm_backend.py
===================
Ollama ve OpenAI uyumlu çağrı: modele özel `think` ayarı isteğe yalnızca verildiğinde eklenir; düşünen model çıktı
token'larını düşünmeye harcayıp boş yanıt dönerse hata bunu söyler; çağrı hatası "Empty response" ile
örtülmez; sağlayıcının durma nedeni (finish_reason) kaydedilir, çıktı sınırına takılan yanıt bunu söyler;
çağrı süresi yanıt başlıkları gelmeden takılsa da toplamdır; 429/503 beklenip sınırlı sayıda yeniden denenir,
bekleme süresi LLM süresine girmez.
(Dış sunucu gerekmez: _post taklit edilir ya da yerel bir test sunucusu kullanılır.)
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


@pytest.fixture
def stalled_headers_server():
    """Durum satırını yollayıp başlıkları ara ara bir bayt yazan, başlıkları hiç bitirmeyen sunucu."""
    import socket
    import threading
    import time

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen()
    stop = threading.Event()

    def serve():
        try:
            conn, _ = srv.accept()
            with conn:
                conn.sendall(b"HTTP/1.1 200 OK\r\nX-Wait: ")
                while not stop.wait(0.2):           # time.sleep değil: başka testler onu taklit eder
                    conn.sendall(b"a")
        except OSError:
            pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.getsockname()[1]}/v1"
    stop.set()
    srv.close()
    t.join(2)


def test_call_timeout_is_total_even_before_headers_arrive(monkeypatch, stalled_headers_server):
    import time
    monkeypatch.setitem(LM.BACKENDS, "stalled", {"api": "openai", "url": stalled_headers_server})
    ex = LLMExtractor(backend="stalled", model="m", rule_type="css", fields=["title"], timeout=1)
    t0 = time.monotonic()
    text, error, _, _ = ex._call_llm("p")
    assert text == "" and error == "Timeout (1 s)" and time.monotonic() - t0 < 3


def test_timeout_comes_from_backend_unless_given(monkeypatch):
    monkeypatch.setitem(LM.BACKENDS, "slow", {"api": "openai", "url": "http://localhost:1/v1", "timeout": 900})
    assert LLMExtractor(backend="slow").timeout == 900
    assert LLMExtractor(backend="slow", timeout=30).timeout == 30
    monkeypatch.setitem(LM.BACKENDS, "plain", {"api": "openai", "url": "http://localhost:1/v1"})
    assert LLMExtractor(backend="plain").timeout == LM.DEFAULT_TIMEOUT_S


def _status_server(replies):
    """Sırayla (durum, başlıklar, gövde) yanıtlarını veren sunucu; son yanıt tekrarlanır."""
    import http.server
    import threading

    calls = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            status, headers, body = replies[min(len(calls), len(replies) - 1)]
            calls.append(status)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, calls


OK_REPLY = (200, {}, b'{"choices": [{"message": {"content": "{\\"title\\": \\"h1\\"}"}, "finish_reason": "stop"}]}')


def test_busy_and_rate_limited_calls_are_retried_and_wait_is_not_timed(monkeypatch):
    from webrulebench.pipeline import llm_extractor as LE
    srv, calls = _status_server([(503, {}, b'{"error": {"code": "model_capacity_exhausted"}}'),
                                 (429, {"Retry-After": "7"}, b'{"error": {"code": "rate_limit_exceeded"}}'),
                                 OK_REPLY])
    waits, real_sleep = [], LE.time.sleep

    def fake_sleep(s):                          # istenen süreyi kaydeder, gerçekte 0,5 s bekler
        waits.append(s)
        real_sleep(0.5)

    monkeypatch.setattr(LE.time, "sleep", fake_sleep)
    monkeypatch.setitem(LM.BACKENDS, "busy", {"api": "openai", "url": f"http://127.0.0.1:{srv.server_port}/v1"})
    ex = LLMExtractor(backend="busy", model="m", rule_type="css", fields=["title"])
    res = ex.extract("<html><body><h1>t</h1></body></html>", domain="x.example")
    srv.shutdown()
    assert calls == [503, 429, 200] and waits == [10, 20]       # Retry-After 7 < katlanan 20
    assert res.success and res.retries == 2 and res.metrics()["retries"] == 2
    assert 0 <= res.elapsed_ms < 500            # beklemeler (2 × 0,5 s) süreye girmez


def test_retries_are_limited(monkeypatch):
    from webrulebench.pipeline import llm_extractor as LE
    srv, calls = _status_server([(503, {}, b'{"error": {"code": "model_capacity_exhausted"}}')])
    monkeypatch.setattr(LE.time, "sleep", lambda s: None)
    monkeypatch.setitem(LM.BACKENDS, "full", {"api": "openai", "url": f"http://127.0.0.1:{srv.server_port}/v1"})
    ex = LLMExtractor(backend="full", model="m", rule_type="css", fields=["title"])
    text, error, _, _ = ex._call_llm("p")
    srv.shutdown()
    assert len(calls) == LE.MAX_RETRIES + 1 and text == "" and error.startswith("HTTP 503")


def test_other_errors_are_not_retried(monkeypatch):
    srv, calls = _status_server([(400, {}, b'{"error": {"code": "bad_request"}}')])
    monkeypatch.setitem(LM.BACKENDS, "bad", {"api": "openai", "url": f"http://127.0.0.1:{srv.server_port}/v1"})
    _, error, _, _ = LLMExtractor(backend="bad", model="m", rule_type="css", fields=["title"])._call_llm("p")
    srv.shutdown()
    assert calls == [400] and error.startswith("HTTP 400")


@pytest.mark.parametrize("retry_after,body,attempt,expected", [
    (None, "", 0, 10),          # katlanan bekleme: 10, 20, 40, 60, 60
    (None, "", 1, 20),
    (None, "", 2, 40),
    (None, "", 4, 60),
    ("5", "", 0, 10),           # sağlayıcının kısa süresi alt sınırın altında kalır
    ("30", "", 0, 30),          # daha uzunsa o beklenir
    ("999", "", 0, 60),
    (None, "not json", 1, 20),
])
def test_retry_wait(retry_after, body, attempt, expected):
    from webrulebench.pipeline.llm_extractor import _retry_wait
    assert _retry_wait(retry_after, body, attempt) == expected


def test_retry_wait_uses_evren_resets_at():
    import json
    from datetime import datetime, timedelta, timezone
    from webrulebench.pipeline.llm_extractor import _retry_wait
    reset = (datetime.now(timezone.utc) + timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
    w = _retry_wait(None, json.dumps({"error": {"evren": {"resets_at": reset}}}), 0)
    assert 18 <= w <= 20


# --- an experiment calls the LLM with the settings stored when it was created ---

def _capture(monkeypatch, snapshot):
    monkeypatch.setitem(LM.BACKENDS, "ollama", {"api": "ollama", "url": "http://changed-later:1/api/chat",
                                                "params": {"temperature": 0.9, "seed": 7, "max_tokens": 64},
                                                "model_params": {"m": {"temperature": 0.5}}, "timeout": 30})
    ex = LLMExtractor(backend="ollama", model="m", rule_type="css", fields=["title"], snapshot=snapshot)
    sent = {}

    def fake_post(url, **kw):
        sent.update(url=url, body=kw["json"])
        return {"message": {"content": '{"title": "h1"}'}, "prompt_eval_count": 1, "eval_count": 1}

    monkeypatch.setattr(ex, "_post", fake_post)
    ex.extract("<h1>x</h1>")
    return ex, sent


def test_snapshot_settings_are_used_instead_of_current_ones(monkeypatch):
    snap = {"api": "ollama", "url": "http://as-created:11434/api/chat", "timeout": 240,
            "params": {"temperature": 0.0, "seed": 42, "max_tokens": 512, "num_ctx": 16384}}
    ex, sent = _capture(monkeypatch, snap)
    assert sent["url"] == "http://as-created:11434/api/chat"
    opts = sent["body"]["options"]
    assert opts["temperature"] == 0.0 and opts["seed"] == 42 and opts["num_ctx"] == 16384     # not 0.9 / 0.5 / 7
    assert ex.timeout == 240


def test_current_settings_are_used_without_a_snapshot(monkeypatch):
    ex, sent = _capture(monkeypatch, None)
    assert sent["url"] == "http://changed-later:1/api/chat"
    assert sent["body"]["options"]["temperature"] == 0.5 and sent["body"]["options"]["seed"] == 7
    assert ex.timeout == 30
