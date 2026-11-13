"""
test_agreement_study.py
=======================
Annotator agreement at two levels (webrulebench.evaluation.agreement) on the reviewer demo data: three annotators
select the same content with different rules, so κ is low at the rule level and α is high at the content level; an
annotator who interprets a field differently (category) lowers content agreement. The Reports endpoint returns the
same result and stores it. The real data folder is not touched (separate process, WRB_DATA_DIR).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

SCRIPT = r"""
import json, sys
from webrulebench.evaluation.agreement import agreement_study
from webrulebench.webapp.app import app

out = {"css": agreement_study(lang="css"), "xpath": agreement_study(lang="xpath")}
user, token = [l.split(":", 1)[1].strip() for l in open(sys.argv[1], encoding="utf-8").read().splitlines()[:2]]
c = app.test_client()
out["anon"] = c.get("/api/reports/agreement?lang=css").status_code
assert c.post("/login", json={"username": user, "token": token}).get_json()["success"]
out["pending"] = c.get("/api/reports/agreement?lang=css&cached=1").get_json()
out["api"] = c.get("/api/reports/agreement?lang=css").get_json()
out["cached"] = c.get("/api/reports/agreement?lang=css&cached=1").get_json()
out["bad_lang"] = c.get("/api/reports/agreement?lang=sql").status_code
print(json.dumps(out))
"""


def test_agreement_on_demo_data(tmp_path):
    out = tmp_path / "demo"
    env = {**os.environ, "WRB_DATA_DIR": str(out)}
    subprocess.run([sys.executable, "-m", "webrulebench.demo.setup_demo", "--dir", str(out)], cwd=ROOT,
                   check=True, capture_output=True, text=True, env=env)
    res = json.loads(subprocess.run([sys.executable, "-c", SCRIPT, str(out / "REVIEWER_LOGIN.txt")], cwd=ROOT,
                                    check=True, capture_output=True, text=True, env=env).stdout)

    css = res["css"]
    assert css["annotators"] == ["demo-annotator-a", "demo-annotator-b", "demo-annotator-c"]
    assert len(css["per_pair"]) == 3 and all(p["cells"] > 0 for p in css["per_pair"])
    assert all(r["annotators"] >= 2 for r in css["per_layout"]) and len(css["per_layout"]) == 5
    f = {r["field"]: r for r in css["per_field"]}
    for name in ("title", "body", "date"):             # same content, rules written differently
        assert f[name]["rule_kappa"] < 0.5 and f[name]["content_alpha"] > 0.9
    assert f["category"]["content_alpha"] < 0.5         # annotator who interprets the field differently
    assert all(-1 <= r["content_alpha"] <= 1 for r in css["per_field"] if r["content_alpha"] is not None)

    assert res["xpath"]["per_field"] == [] and res["xpath"]["per_layout"] == []   # the demo has no XPath rules

    assert res["anon"] == 401
    assert res["pending"] == {"pending": True}
    assert res["api"]["per_field"] == css["per_field"] and res["api"]["per_pair"] == css["per_pair"]
    assert all(r["name"] for r in res["api"]["per_layout"])          # layout names are added
    assert res["cached"]["computed_at"] == res["api"]["computed_at"]   # the second request returns the stored result
    assert res["bad_lang"] == 400
