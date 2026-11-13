"""
test_demo.py
============
Reviewer demo end to end: webrulebench.demo.setup_demo sets up a temporary data folder; experiments
run with the replay backend complete and the strong model scores higher than the weak model.
The real data folder is not touched (separate process, WRB_DATA_DIR).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_demo_setup_end_to_end(tmp_path):
    out = tmp_path / "demo"
    env = {**os.environ, "WRB_DATA_DIR": str(out)}
    subprocess.run([sys.executable, "-m", "webrulebench.demo.setup_demo", "--dir", str(out)], cwd=ROOT,
                   check=True, capture_output=True, text=True, env=env)
    exps = [json.loads(p.read_text(encoding="utf-8")) for p in (out / "experiments").glob("*.json")]
    assert len(exps) == 4 and all(e["status"] == "done" for e in exps)
    mean = {(e["config"]["model"], e["config"]["rule_type"]): e["summary"]["mean"] for e in exps}
    assert mean[("demo-strong", "css")] > 0.9 > mean[("demo-weak", "css")]
    assert (out / "REVIEWER_LOGIN.txt").exists()
    assert json.loads((out / "users.json").read_text())["reviewer"]["role"] == "admin"
    assert len(list((out / "ground_truth" / "approved").glob("*.json"))) == 3
