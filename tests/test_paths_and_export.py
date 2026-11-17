"""
test_paths_and_export.py
========================
- Values from a request that become path components (domain, page file) cannot leave the data folder: a delete
  request with "../" or an absolute path is refused and deletes nothing.
- The ground-truth export (HuggingFace-style JSONL) contains exactly the values the experiments score against.
- `webrulebench serve` starts with Flask debug mode off unless asked for.
Runs on the reviewer demo data in a separate process (WRB_DATA_DIR), so the real data folder is not touched.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from webrulebench.paths import inside, safe_name  # noqa: E402

SCRIPT = r"""
import json, sys
from pathlib import Path
from bs4 import BeautifulSoup
from webrulebench.webapp import core
from webrulebench.webapp.app import app
from webrulebench.evaluation import experiments as X

user, token = [l.split(":", 1)[1].strip() for l in open(sys.argv[1], encoding="utf-8").read().splitlines()[:2]]
victim = Path(sys.argv[2]); victim.mkdir(); (victim / "keep.txt").write_text("x")
c = app.test_client()
assert c.post("/login", json={"username": user, "token": token}).get_json()["success"]
site = sorted(p for p in core.DATASET_DIR.iterdir() if p.is_dir())[0]
rel = Path("..") / ".." / ".." / victim.relative_to(victim.anchor)
out = {"site_delete": [c.post("/api/site/delete", json={"domain": d}).status_code
                       for d in ("../" * 6 + str(victim).lstrip("/"), str(victim), "..", ".")],
       "page_delete": [c.post("/api/page/delete", json={"domain": site.name, "filename": f}).status_code
                       for f in ("../../keep.txt", str(victim / "keep.txt"))],
       "page_get": c.get("/api/page/%2e%2e/sites.json").status_code,
       "victim_kept": (victim / "keep.txt").exists(), "site_kept": site.is_dir()}

# export: the values of every (page, field) equal the values the experiments score against
rows = [json.loads(l) for l in c.get("/api/export/hf").get_data(as_text=True).splitlines() if l.strip()]
tmpls, mismatches, cells = X._templates(), [], 0
for r in rows:
    gt = X._load_json(X.GT_DIR / f"{r['domain']}.json", {})["layouts"][r["layout_id"]]
    fields = tmpls[X.layout_template_id(gt, tmpls)]["fields"]
    html = (core.DATASET_DIR / r["domain"] / r["filename"]).read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    for f, v in r["ground_truth"].items():
        fd = fields.get(f, {})
        ref = X.rule_values(html, soup, X._rule_of(r["selectors"][f], "css"), "css", X._kind(fd), bool(fd.get("merge")))
        cells += 1
        if v != ref or r["metrics"][f] != fd.get("metric", "rouge"):
            mismatches.append([r["domain"], r["filename"], f])
out["export"] = {"rows": len(rows), "cells": cells, "mismatches": mismatches[:5]}
print(json.dumps(out))
"""


@pytest.mark.parametrize("name,ok", [("example.com", True), ("article_001.html", True), ("layout-1", True),
                                     ("", False), (".", False), ("..", False), ("../x", False), ("a/b", False),
                                     ("a\\b", False), ("/etc", False), ("C:x", False), ("a\0b", False), (None, False)])
def test_safe_name(name, ok):
    assert safe_name(name) is ok


def test_inside(tmp_path):
    assert inside(tmp_path / "a" / "b.html", tmp_path)
    assert not inside(tmp_path / ".." / "x", tmp_path)


def _demo(tmp_path):
    out = tmp_path / "demo"
    env = {**os.environ, "WRB_DATA_DIR": str(out)}
    subprocess.run([sys.executable, "-m", "webrulebench.demo.setup_demo", "--dir", str(out)], cwd=ROOT,
                   check=True, capture_output=True, text=True, env=env)
    return out, env


def test_requests_cannot_leave_the_data_folder_and_export_matches_scoring(tmp_path):
    out, env = _demo(tmp_path)
    res = json.loads(subprocess.run([sys.executable, "-c", SCRIPT, str(out / "REVIEWER_LOGIN.txt"), str(tmp_path / "victim")],
                                    cwd=ROOT, check=True, capture_output=True, text=True, env=env).stdout.splitlines()[-1])
    assert res["site_delete"] == [400, 400, 400, 400]
    assert res["page_delete"] == [400, 400] and res["page_get"] == 400
    assert res["victim_kept"] and res["site_kept"]
    assert res["export"]["rows"] > 0 and res["export"]["cells"] > 0
    assert res["export"]["mismatches"] == []


def test_serve_starts_without_debug_mode(tmp_path):
    out, env = _demo(tmp_path)
    env = {k: v for k, v in env.items() if k not in ("WRB_DEBUG", "LLMWB_DEBUG")}
    code = "import json; from webrulebench.webapp import app as A; A.app.run = lambda **k: print(json.dumps(k)); A.main()"
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, text=True, env=env)
    assert json.loads(run.stdout.splitlines()[-1])["debug"] is False
    run = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True, text=True,
                         env={**env, "WRB_DEBUG": "1"})
    assert json.loads(run.stdout.splitlines()[-1])["debug"] is True
