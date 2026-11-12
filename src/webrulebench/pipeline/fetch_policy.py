"""
fetch_policy.py
===============
Politeness rules for downloading pages: robots.txt and a pause between requests to the same site.

The tool downloads a small number of pages per site for annotation, but it should still ask before it
fetches. Before a page is downloaded, the site's robots.txt is read (once per host, cached) and the URL
is checked for the user agents "WebRuleBench" and "*". A disallowed URL is not downloaded. Requests to
the same host are spaced by the site's Crawl-delay or the configured minimum, whichever is longer.

Both are settings the administrator can change (Data Collection → download settings); they are stored
in ``dataset/download_settings.json`` of the data folder:

    {"respect_robots": true, "min_delay_s": 1.0}

robots.txt that cannot be used is handled as in RFC 9309: a 4xx answer means there are no rules (allowed);
a 5xx answer or a network error means the site could not say (not allowed until it can be read).
"""
from __future__ import annotations

import json
import time
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlparse

DEFAULTS = {"respect_robots": True, "min_delay_s": 1.0}
USER_AGENT_TOKEN = "WebRuleBench"
MAX_CRAWL_DELAY_S = 30.0          # a longer Crawl-delay is capped, so that a bulk download still ends
CACHE_S = 3600


class FetchPolicy:
    def __init__(self, settings_file: Path | None, http_get, sleep=time.sleep, clock=time.monotonic):
        """http_get(url) -> (status_code, text); raises on a network error."""
        self.settings_file, self._get, self._sleep, self._clock = settings_file, http_get, sleep, clock
        self._robots: dict = {}       # host -> (read_at, parser | None, state)
        self._last: dict = {}         # host -> time of the last request

    # --- settings ---------------------------------------------------------------------------------
    def settings(self) -> dict:
        s = dict(DEFAULTS)
        try:
            if self.settings_file and self.settings_file.is_file():
                s.update({k: v for k, v in json.loads(self.settings_file.read_text(encoding="utf-8")).items() if k in DEFAULTS})
        except (ValueError, OSError):
            pass
        return s

    def save_settings(self, new: dict) -> dict:
        s = self.settings()
        if "respect_robots" in new:
            s["respect_robots"] = bool(new["respect_robots"])
        if "min_delay_s" in new:
            s["min_delay_s"] = max(0.0, min(60.0, float(new["min_delay_s"])))
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(json.dumps(s, indent=1), encoding="utf-8")
        return s

    # --- robots.txt -------------------------------------------------------------------------------
    def _rules(self, url: str):
        """(parser | None, state) for the host of url; state: rules | no-rules | unreachable."""
        u = urlparse(url)
        host = f"{u.scheme}://{u.netloc}"
        hit = self._robots.get(host)
        if hit and self._clock() - hit[0] < CACHE_S:
            return hit[1], hit[2]
        parser, state = None, "unreachable"
        try:
            status, text = self._get(host + "/robots.txt")
            if 200 <= status < 300:
                parser = urllib.robotparser.RobotFileParser()
                parser.parse((text or "").splitlines())
                state = "rules"
            elif 400 <= status < 500:
                state = "no-rules"
        except Exception:
            pass
        self._robots[host] = (self._clock(), parser, state)
        return parser, state

    def check(self, url: str) -> dict:
        """{"allowed": bool, "robots": checked-state, "crawl_delay": seconds | None}. With the check switched off the
        URL is allowed and robots.txt is not read."""
        if not self.settings()["respect_robots"]:
            return {"allowed": True, "robots": "not checked", "crawl_delay": None}
        parser, state = self._rules(url)
        if state == "no-rules":
            return {"allowed": True, "robots": "no robots.txt", "crawl_delay": None}
        if parser is None:
            return {"allowed": False, "robots": "robots.txt unreachable", "crawl_delay": None}
        allowed = parser.can_fetch(USER_AGENT_TOKEN, url)
        delay = parser.crawl_delay(USER_AGENT_TOKEN)
        return {"allowed": allowed, "robots": "allowed" if allowed else "disallowed",
                "crawl_delay": float(delay) if delay is not None else None}

    # --- pause between requests to one host -------------------------------------------------------
    def wait(self, url: str, crawl_delay: float | None = None) -> float:
        """Sleep so that requests to the host are spaced by max(min_delay_s, Crawl-delay); returns the pause."""
        host = urlparse(url).netloc
        gap = max(float(self.settings()["min_delay_s"]), min(float(crawl_delay or 0.0), MAX_CRAWL_DELAY_S))
        last, pause = self._last.get(host), 0.0
        if last is not None and gap > 0:
            pause = max(0.0, gap - (self._clock() - last))
            if pause:
                self._sleep(pause)
        self._last[host] = self._clock()
        return pause
