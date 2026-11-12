"""
test_experiment_snapshot.py
===========================
An experiment is executed (and resumed) with the backend settings stored when it was created, not with the
settings of the moment: changing a backend's URL or parameters afterwards changes neither the request nor
what the record says. Runs on the reviewer demo data with the replay backend, in a separate process
(WRB_DATA_DIR), so the real data folder is not touched.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

SCRIPT = r"""
import json
from webrulebench.pipeline import llm_models as LM
from webrulebench.evaluation import experiments as E

b = next(k for k, v in LM.BACKENDS.items() if v.get("api") == "replay")
item = E.eligible_layouts()[0]
cfg = E.validate_config({"backend": b, "model": LM.BACKENDS[b].get("default_model"), "rule_type": "css"})
out = {"snapshot_url": cfg["backend_snapshot"]["url"]}
first = E.run_layout(cfg, item, {})
out["first"] = [first["llm"]["success"], first["summary"]["mean"]]

# the settings are changed after the experiment was created (here: another file of recorded responses)
LM.BACKENDS[b]["url"] = "changed_after_creation.json"
LM.BACKENDS[b]["params"] = {"temperature": 1.0}
again = E.run_layout(cfg, item, {})
out["with_snapshot"] = [again["llm"]["success"], again["rules"] == first["rules"], again["summary"]["mean"]]
out["record_unchanged"] = cfg["backend_snapshot"]["url"] == out["snapshot_url"]

legacy = {k: v for k, v in cfg.items() if k != "backend_snapshot"}        # a record made before snapshots existed
old = E.run_layout(legacy, item, {})
out["without_snapshot"] = old["llm"]["success"]
print(json.dumps(out))
"""


def test_experiment_runs_with_the_settings_stored_at_creation(tmp_path):
    out = tmp_path / "demo"
    env = {**os.environ, "WRB_DATA_DIR": str(out)}
    subprocess.run([sys.executable, "-m", "webrulebench.demo.setup_demo", "--dir", str(out)], cwd=ROOT,
                   check=True, capture_output=True, text=True, env=env)
    res = json.loads(subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, check=True, capture_output=True,
                                    text=True, env=env).stdout.splitlines()[-1])
    assert res["first"][0] is True
    assert res["with_snapshot"] == [True, True, res["first"][1]]     # same request, same rules, same score
    assert res["record_unchanged"]
    assert res["without_snapshot"] is False                          # the current (changed) settings were used
