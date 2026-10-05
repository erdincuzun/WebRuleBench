"""
test_agreement_study.py
=======================
İki düzeyde annotatör uyumu (webrulebench.evaluation.agreement) hakem demosunun verisinde: üç annotatör
aynı içeriği farklı kurallarla seçtiği için kural düzeyinde κ düşük, içerik düzeyinde α yüksek çıkar; bir alanı
farklı yorumlayan annotatör (category) içerik uyumunu düşürür. Raporlar uç noktası aynı sonucu verir ve saklar.
Gerçek veri klasörüne dokunulmaz (ayrı süreç, WRB_DATA_DIR).
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
    for name in ("title", "body", "date"):             # aynı içerik, farklı yazılmış kurallar
        assert f[name]["rule_kappa"] < 0.5 and f[name]["content_alpha"] > 0.9
    assert f["category"]["content_alpha"] < 0.5         # alanı farklı yorumlayan annotatör
    assert all(-1 <= r["content_alpha"] <= 1 for r in css["per_field"] if r["content_alpha"] is not None)

    assert res["xpath"]["per_field"] == [] and res["xpath"]["per_layout"] == []   # demoda XPath kuralı yok

    assert res["anon"] == 401
    assert res["pending"] == {"pending": True}
    assert res["api"]["per_field"] == css["per_field"] and res["api"]["per_pair"] == css["per_pair"]
    assert all(r["name"] for r in res["api"]["per_layout"])          # layout adları eklenir
    assert res["cached"]["computed_at"] == res["api"]["computed_at"]   # ikinci istek saklanan sonucu döndürür
    assert res["bad_lang"] == 400
