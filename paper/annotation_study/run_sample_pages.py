"""
run_sample_pages.py
===================
Robustness check for the choice of the sample page (revision R1). The submitted experiments gave the model the
first ground-truth page of each layout. Here the strongest configuration (qwen2.5-coder:14b, CSS rules, same
settings) is run again (a) with the first page, to check that the run is repeatable, and (b) three times with a
randomly chosen ground-truth page per layout (sample seeds 1, 2, 3). Needs a local Ollama server with the model
of the record. The records are saved in the data folder (LLM Evaluation) and copied to
results/experiments_sample_pages/.

    python paper/annotation_study/run_sample_pages.py
"""
import json
import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from webrulebench.evaluation import experiments as X  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results" / "experiments_sample_pages"
BASE = next(json.loads(p.read_text(encoding="utf-8")) for p in sorted((HERE / "results" / "experiments_submitted").glob("*.json"))
            if (c := json.loads(p.read_text(encoding="utf-8"))["config"])["model"] == "qwen2.5-coder:14b"
            and c["rule_type"] == "css" and c.get("rule_source", "llm") == "llm")


def main():
    known = {(l["domain"], l["layout_id"]): l for l in X.eligible_layouts()}
    layouts = [known[(s["domain"], s["layout_id"])] for s in BASE["scope"]]
    base = {k: BASE["config"][k] for k in ("backend", "model", "rule_type", "rule_source", "strategy", "css_repair", "delay_s", "max_pages")}
    cfgs = [{**base, "sample": {"mode": "first"}}] + [{**base, "sample": {"mode": "random", "seed": s}} for s in (1, 2, 3)]
    snap = X.validate_config(dict(cfgs[0]))["backend_snapshot"]
    old = BASE["config"]["backend_snapshot"]
    assert snap["params"] == old["params"] and snap["model_info"]["digest"] == old["model_info"]["digest"], "settings or model differ from the record"
    gid, ids = X.create_group("Sample page robustness (R1) · qwen2.5-coder:14b · CSS", cfgs, layouts, BASE["created_by"])
    OUT.mkdir(exist_ok=True)
    for i, (eid, cfg) in enumerate(zip(ids, cfgs)):
        e = X._load_json(X.exp_path(eid), None)
        e["name"] = f"qwen2.5-coder:14b · css · sample: {'first page' if cfg['sample']['mode'] == 'first' else 'random page, seed ' + str(cfg['sample']['seed'])}"
        X.save(e)
        X._worker(eid, threading.Event())
        e = X._load_json(X.exp_path(eid), None)
        shutil.copy(X.exp_path(eid), OUT / f"{eid}.json")
        s = e["summary"]
        same = sum(l["rules"] == b["rules"] for l, b in zip(e["layouts"], BASE["layouts"])) if i == 0 else None
        print(e["name"], "| status", e["status"], "| mean", s["mean"], "sample", s["sample_mean"], "others", s["others_mean"],
              "| failed", s["failed"], ("| layouts with the same rules as the submitted run: %d/10" % same) if same is not None else "",
              "| sample pages:", [l.get("sample_page") for l in e["layouts"]], flush=True)


if __name__ == "__main__":
    main()
