"""
test_fetch_policy.py
====================
Politeness rules of the downloader (pipeline/fetch_policy.py): the robots.txt of a site is read once and
checked before a page is downloaded; a disallowed page is refused; an absent robots.txt means no rules and
an unreachable one means "do not fetch"; requests to one host are spaced by the Crawl-delay or the
configured minimum; the administrator can switch the check off. No network: robots.txt is served by a stub.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from webrulebench.pipeline.fetch_policy import FetchPolicy, MAX_CRAWL_DELAY_S

ROBOTS = """
User-agent: *
Disallow: /private/
Crawl-delay: 4

User-agent: WebRuleBench
Disallow: /no-tools/
"""


def policy(tmp_path, answers, settings=None):
    """answers: {robots url: (status, text) | Exception}; returns (policy, list of fetched urls, list of sleeps)."""
    f = tmp_path / "download_settings.json"
    if settings is not None:
        f.write_text(json.dumps(settings), encoding="utf-8")
    fetched, sleeps, now = [], [], [0.0]

    def get(url):
        fetched.append(url)
        a = answers[url]
        if isinstance(a, Exception):
            raise a
        return a

    def sleep(s):
        sleeps.append(round(s, 3))
        now[0] += s

    p = FetchPolicy(f, get, sleep=sleep, clock=lambda: now[0])
    return p, fetched, sleeps, now


def test_robots_rules_are_checked_and_cached(tmp_path):
    p, fetched, *_ = policy(tmp_path, {"https://a.example/robots.txt": (200, ROBOTS)})
    assert p.check("https://a.example/news/1.html")["allowed"] is True
    # the more specific group applies to the tool; it has no Crawl-delay of its own
    assert p.check("https://a.example/no-tools/x.html") == {"allowed": False, "robots": "disallowed", "crawl_delay": None}
    assert fetched == ["https://a.example/robots.txt"]            # read once for the host


def test_general_rules_apply_when_the_tool_is_not_named(tmp_path):
    rules = "User-agent: *\nDisallow: /private/\nCrawl-delay: 4\n"
    p, *_ = policy(tmp_path, {"https://a.example/robots.txt": (200, rules)})
    assert p.check("https://a.example/private/x.html")["allowed"] is False
    assert p.check("https://a.example/news/1.html") == {"allowed": True, "robots": "allowed", "crawl_delay": 4.0}


@pytest.mark.parametrize("answer, allowed, state", [
    ((404, ""), True, "no robots.txt"),                 # no file: no rules
    ((403, "Forbidden"), True, "no robots.txt"),        # RFC 9309: a 4xx answer is "unavailable" -> no rules
    ((503, ""), False, "robots.txt unreachable"),       # server error: do not fetch
    (OSError("timeout"), False, "robots.txt unreachable"),
])
def test_robots_that_cannot_be_used(tmp_path, answer, allowed, state):
    p, *_ = policy(tmp_path, {"https://a.example/robots.txt": answer})
    r = p.check("https://a.example/news/1.html")
    assert r["allowed"] is allowed and r["robots"] == state


def test_check_can_be_switched_off(tmp_path):
    p, fetched, *_ = policy(tmp_path, {}, settings={"respect_robots": False})
    assert p.check("https://a.example/private/x.html") == {"allowed": True, "robots": "not checked", "crawl_delay": None}
    assert fetched == []                                # robots.txt is not even requested


def test_requests_to_one_host_are_spaced(tmp_path):
    p, _, sleeps, now = policy(tmp_path, {}, settings={"min_delay_s": 1.0})
    assert p.wait("https://a.example/1") == 0.0         # first request: no pause
    now[0] += 0.4
    assert p.wait("https://a.example/2") == pytest.approx(0.6)       # the rest of the minimum pause
    assert p.wait("https://b.example/1") == 0.0         # another host is not delayed
    assert p.wait("https://a.example/3", crawl_delay=4) == pytest.approx(4.0)      # Crawl-delay is longer
    assert p.wait("https://a.example/4", crawl_delay=600) == pytest.approx(MAX_CRAWL_DELAY_S)   # capped
    assert sleeps == [0.6, 4.0, MAX_CRAWL_DELAY_S]


def test_settings_defaults_and_saving(tmp_path):
    p, *_ = policy(tmp_path, {})
    assert p.settings() == {"respect_robots": True, "min_delay_s": 1.0}
    assert p.save_settings({"respect_robots": 0, "min_delay_s": "2.5", "other": 1}) == {"respect_robots": False, "min_delay_s": 2.5}
    assert p.settings() == {"respect_robots": False, "min_delay_s": 2.5}
    assert p.save_settings({"min_delay_s": -3})["min_delay_s"] == 0.0
    with pytest.raises(ValueError):
        p.save_settings({"min_delay_s": "soon"})


# --- in the application: the downloader asks the policy first; the settings are an admin action ---

APP_SCRIPT = r"""
import json, sys
from webrulebench.webapp import core
from webrulebench.webapp.app import app

calls = []
core.FETCH_POLICY._get = lambda url: (calls.append(url), (200, "User-agent: *\nDisallow: /private/\n"))[1]
core.FETCH_POLICY._sleep = lambda s: None
real_get = core._requests.get
core._requests.get = lambda url, **kw: (_ for _ in ()).throw(AssertionError("page requested: " + url))   # must not be reached
out = {"disallowed": core._fetch_html("https://site.example/private/a.html")}
core._requests.get = real_get

user, token = [l.split(":", 1)[1].strip() for l in open(sys.argv[1], encoding="utf-8").read().splitlines()[:2]]
c = app.test_client()
out["anon_post"] = c.post("/api/download-settings", json={"respect_robots": False}).status_code
assert c.post("/login", json={"username": user, "token": token}).get_json()["success"]
out["defaults"] = c.get("/api/download-settings").get_json()
out["saved"] = c.post("/api/download-settings", json={"respect_robots": False, "min_delay_s": 0}).get_json()
out["bad"] = c.post("/api/download-settings", json={"min_delay_s": "soon"}).status_code
out["off"] = core.FETCH_POLICY.check("https://site.example/private/a.html")["robots"]
out["audit"] = "DOWNLOAD_SETTINGS" in core._audit_log_path.read_text(encoding="utf-8")
print(json.dumps(out))
"""


def test_downloader_refuses_disallowed_pages_and_settings_need_admin(tmp_path):
    root = Path(__file__).parent.parent
    out = tmp_path / "demo"
    env = {**os.environ, "WRB_DATA_DIR": str(out)}
    subprocess.run([sys.executable, "-m", "webrulebench.demo.setup_demo", "--dir", str(out)], cwd=root,
                   check=True, capture_output=True, text=True, env=env)
    res = json.loads(subprocess.run([sys.executable, "-c", APP_SCRIPT, str(out / "REVIEWER_LOGIN.txt")], cwd=root,
                                    check=True, capture_output=True, text=True, env=env).stdout.splitlines()[-1])
    html, method, error = res["disallowed"]
    assert html is None and method == "robots" and "robots.txt" in error      # refused before any page request
    assert res["anon_post"] == 401
    assert res["defaults"] == {"respect_robots": True, "min_delay_s": 1.0}
    assert res["saved"] == {"success": True, "respect_robots": False, "min_delay_s": 0.0}
    assert res["bad"] == 400 and res["off"] == "not checked" and res["audit"]
