"""
test_page_preview_security.py
=============================
Downloaded pages are untrusted content that the application shows in previews. They are served with a
Content-Security-Policy that blocks their scripts; the "JS enabled" mode runs scripts only in an opaque
origin; the preview frames are sandboxed. Runs on the reviewer demo data in a separate process
(WRB_DATA_DIR), so the real data folder is not touched.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
WEBAPP = ROOT / "src" / "webrulebench" / "webapp"

SCRIPT = r"""
import json, sys
from webrulebench.webapp import core
from webrulebench.webapp.app import app

user, token = [l.split(":", 1)[1].strip() for l in open(sys.argv[1], encoding="utf-8").read().splitlines()[:2]]
c = app.test_client()
site = sorted(p for p in core.DATASET_DIR.iterdir() if p.is_dir())[0]
(site / "evil.html").write_text("<html><body onload=\"x()\"><h1>t</h1><script>fetch('/api/users')</script></body></html>", encoding="utf-8")
url = f"/api/page/{site.name}/evil.html"
out = {"anon": c.get(url).status_code}
assert c.post("/login", json={"username": user, "token": token}).get_json()["success"]
r = c.get(url)
out["default"] = [r.status_code, r.headers.get("Content-Security-Policy"), r.headers.get("X-Content-Type-Options"),
                  r.mimetype, "<script>" in r.get_data(as_text=True)]
out["active"] = c.get(url + "?js=1").headers.get("Content-Security-Policy")
out["missing"] = c.get(f"/api/page/{site.name}/nope.html").status_code
out["outside"] = [c.get("/api/page/../sites.json").status_code, c.get("/api/page/%2e%2e/sites.json").status_code,
                  c.get(f"/api/page/{site.name}/..%2f..%2fsites.json").status_code]
print(json.dumps(out))
"""


def test_downloaded_pages_are_served_with_a_script_blocking_policy(tmp_path):
    out = tmp_path / "demo"
    env = {**os.environ, "WRB_DATA_DIR": str(out)}
    subprocess.run([sys.executable, "-m", "webrulebench.demo.setup_demo", "--dir", str(out)], cwd=ROOT,
                   check=True, capture_output=True, text=True, env=env)
    res = json.loads(subprocess.run([sys.executable, "-c", SCRIPT, str(out / "REVIEWER_LOGIN.txt")], cwd=ROOT,
                                    check=True, capture_output=True, text=True, env=env).stdout.splitlines()[-1])
    assert res["anon"] == 401
    status, csp, nosniff, mimetype, has_script = res["default"]
    assert status == 200 and mimetype == "text/html" and nosniff == "nosniff"
    assert has_script                                   # the page is served as downloaded …
    assert "script-src 'none'" in csp                   # … but the browser does not run its scripts
    assert "object-src 'none'" in csp and "base-uri 'none'" in csp and "form-action 'none'" in csp
    # opt-in mode: scripts run, in an opaque origin (a sandbox without allow-same-origin)
    assert res["active"].startswith("sandbox") and "allow-scripts" in res["active"] and "allow-same-origin" not in res["active"]
    assert res["missing"] == 404 and all(s in (404, 308, 401) for s in res["outside"]) and 200 not in res["outside"]


def test_every_preview_frame_is_sandboxed():
    """No iframe in the templates loads a downloaded page without a sandbox attribute."""
    frames = []
    for f in list((WEBAPP / "templates").rglob("*.html")):
        frames += [(f.name, m.group(0)) for m in re.finditer(r"<iframe\b[^>]*>", f.read_text(encoding="utf-8"))]
    assert {n for n, _ in frames} >= {"index.html", "gt_compile.html"}
    assert all("sandbox=" in tag for _, tag in frames), [x for x in frames if "sandbox=" not in x[1]]
    # the "JS enabled" mode of the viewer never combines scripts of the page with the application's origin
    js = (WEBAPP / "templates" / "index.html").read_text(encoding="utf-8")
    assert "_jsOn() ? 'allow-scripts' : 'allow-same-origin allow-scripts'" in js and "?js=1" in js
