"""
test_custom_template.py
=======================
The worked example in docs/custom_template.md: the shop_product template is created through the API, its
automatic prompt lists the fields with their descriptions, and the scoring snippet of the document gives the
results it states. Runs on the reviewer demo data in a separate process (WRB_DATA_DIR).
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOC = (ROOT / "docs" / "custom_template.md").read_text(encoding="utf-8")


def _block(lang: str, start: str) -> str:
    """The first fenced code block of a language in the document that begins with `start`."""
    for m in re.finditer(r"^```(\w*)\n(.*?)^```", DOC, re.S | re.M):     # opening and closing fences in pairs
        if m.group(1) == lang and m.group(2).lstrip().startswith(start):
            return m.group(2)
    raise AssertionError(f"no {lang} block starting with {start!r}")


SCRIPT = r"""
import json, sys
from webrulebench.webapp.app import app
body = json.loads(sys.argv[2])
user, token = [l.split(":", 1)[1].strip() for l in open(sys.argv[1], encoding="utf-8").read().splitlines()[:2]]
c = app.test_client()
assert c.post("/login", json={"username": user, "token": token}).get_json()["success"]
post = lambda: c.post("/api/templates", data=sys.argv[2], content_type="application/json")   # field order as sent
out = {"create": post().get_json(),
       "again": post().status_code,
       "template": c.get("/api/templates/shop_product").get_json(),
       "prompt": c.get("/api/templates/shop_product/prompts").get_json()["auto"]["css"]["system"]}
print(json.dumps(out))
"""


def test_template_from_the_document_can_be_created_and_prompts_its_fields(tmp_path):
    body = json.loads(_block("json", "POST /api/templates").split("\n", 1)[1])
    out = tmp_path / "demo"
    env = {**os.environ, "WRB_DATA_DIR": str(out)}
    subprocess.run([sys.executable, "-m", "webrulebench.demo.setup_demo", "--dir", str(out)], cwd=ROOT,
                   check=True, capture_output=True, text=True, env=env)
    res = json.loads(subprocess.run([sys.executable, "-c", SCRIPT, str(out / "REVIEWER_LOGIN.txt"), json.dumps(body)],
                                    cwd=ROOT, check=True, capture_output=True, text=True, env=env).stdout.splitlines()[-1])
    assert res["create"] == {"success": True, "id": "shop_product"} and res["again"] == 409
    assert list(res["template"]["fields"]) == ["name", "price", "old_price", "discount", "shipping", "description", "images"]
    assert res["template"]["fields"]["images"]["merge"] is True
    prompt = res["prompt"]
    assert 'a web page of type "Shop Product Page" (Product detail page of an online shop)' in prompt
    assert "- name: Product name as shown in the main heading (required)" in prompt
    assert "- old_price: Price before the discount, if a discount is shown\n" in prompt
    # the excerpt in the document is what the tool generates
    for line in _block("", "You extract data").splitlines():
        line = line.strip()
        if line and not line.startswith("...") and "..." not in line:
            assert line in prompt.replace("\n(", " ("), line


def test_scoring_snippet_of_the_document():
    code = _block("python", "from bs4")
    expected = re.findall(r"#\s*(\(.*?\))", code)
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, text=True)
    assert r.stdout.split("\n")[:2] == expected == ["(1.0, 'MATCH')", "(0.0, 'WRONG')"]
