"""
rescore.py
==========
Rescores the saved LLM rules of the eight experiments against the reviewed reference. No LLM is called:
the rules each model generated are in the experiment records and only the comparison is repeated.

Why: the reference used for the submitted results had been approved from one annotator's rules. The
three-annotator study and a page-by-page comparison of the rules' output showed fields missing from it and
rules that selected the wrong element or more than the field; the administrator reviewed them (see
paper/softwarex/gt_review.md). The records as submitted are kept in results/experiments_submitted/.

Reads   results/experiments_submitted/*.json   and the data folder (WRB_DATA_DIR): reference, annotator rules, pages
Writes  results/experiments/*.json             the records with the new per-page scores and summaries
        results/llm_experiments.csv            one row per experiment (same columns as before)
        results/coverage.csv                   scored page–field pairs by layout and field, and why the others are not scored
        results/sample_gap.csv                 sample page vs. other pages, per experiment and layout
        results/rescore.json                   summary: submitted vs. rescored, coverage, distribution of the gaps

    python paper/annotation_study/rescore.py
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup  # noqa: E402

from webrulebench.evaluation import experiments as X  # noqa: E402
from webrulebench.rules import rule_agreement as RA  # noqa: E402

HERE = Path(__file__).resolve().parent
SRC, OUT = HERE / "results" / "experiments_submitted", HERE / "results" / "experiments"
ANNOTATORS = {"A1": "euzun", "A2": "user2", "A3": "user3"}        # file names in the working data folder
_docs: dict = {}


def doc(dom: str, page: str):
    if (dom, page) not in _docs:
        html = (X.RAW_DIR / dom / page).read_text(encoding="utf-8", errors="ignore")
        _docs[(dom, page)] = (html, BeautifulSoup(html, "html.parser"))
    return _docs[(dom, page)]


def annotator_rules(dom: str, lid: str) -> dict:
    """{annotator: {field: css rule}}; the open data record names the files A1–A3."""
    out = {}
    for label, user in ANNOTATORS.items():
        for name in (user, label):
            p = X.ROOT / "annotations" / dom / f"{name}.json"
            if p.is_file():
                sels = (json.loads(p.read_text(encoding="utf-8")).get("layouts", {}).get(lid) or {}).get("selectors") or {}
                out[label] = {f: X._rule_of(v, "css") for f, v in sels.items()}
                break
    return out


def source(layout: dict, ann: dict, f: str, fd: dict, rule: str) -> list:
    """Annotators who wrote the approved rule (stored at approval; computed here for layouts approved before
    the source was stored). Empty: written or edited by the administrator."""
    stored = ((layout.get("rule_sources") or {}).get(f) or {}).get("css")
    if stored is not None:
        return sorted({u: a for a, u in ANNOTATORS.items()}.get(u, u) for u in stored)
    merge = bool(fd.get("merge"))
    return sorted(a for a, r in ann.items() if RA.normalize_rule(r.get(f), "css", merge) == RA.normalize_rule(rule, "css", merge))


def rescore_layout(e: dict, lay: dict, tmpls: dict) -> tuple:
    """New page scores and summary of one layout of one experiment; also the reference values per page."""
    dom, lid, rt = lay["domain"], lay["layout_id"], e["config"]["rule_type"]
    layout = X._load_json(X.GT_DIR / f"{dom}.json", {})["layouts"][lid]
    fields = tmpls[X.layout_template_id(layout, tmpls)]["fields"]
    pages, scores, has_ref = sorted(lay["pages"]), {}, {}
    for p in pages:
        html, soup = doc(dom, p)
        row = {}
        for f, fd in fields.items():
            k, m = X._kind(fd), bool(fd.get("merge"))
            g = X._rule_of((layout.get("selectors") or {}).get(f), "css")
            gt_vals = X.rule_values(html, soup, g, "css", k, m) if g else []
            try:
                pred = X.rule_values(html, soup, lay["rules"].get(f) or "", rt, k, m)
            except Exception:
                pred = []
            s, label = X.score_field(gt_vals, pred, fd.get("metric", "rouge"))
            row[f] = {"score": s, "label": label}
            has_ref[(p, f)] = bool(gt_vals)
        scores[p] = row
    sm = lay["sample_page"]
    summary = {"mean": X._mean(v["score"] for p in pages for v in scores[p].values()),
               "sample_mean": X._mean(v["score"] for v in scores[sm].values()),
               "others_mean": X._mean(v["score"] for p in pages if p != sm for v in scores[p].values()),
               "per_field": {f: X._mean(scores[p][f]["score"] for p in pages) for f in fields}}
    return scores, summary, layout, fields, has_ref


def coverage_rows(e: dict, tmpls: dict) -> list:
    """Per layout and field: scored pairs, and for the pairs without a reference value the reason."""
    rows = []
    for lay in e["layouts"]:
        dom, lid = lay["domain"], lay["layout_id"]
        _, _, layout, fields, has_ref = rescore_layout(e, lay, tmpls)
        ann, pages = annotator_rules(dom, lid), sorted(lay["pages"])
        for f, fd in fields.items():
            rule = X._rule_of((layout.get("selectors") or {}).get(f), "css")
            scored = sum(has_ref[(p, f)] for p in pages)
            who = sorted(a for a, r in ann.items() if r.get(f))
            if rule:
                status = "reference rule"
            elif f in (layout.get("excluded_fields") or {}):
                status = "left out by the administrator"
            elif who:
                status = "annotator rule without a decision"
            else:
                status = "no rule by any annotator"
            rows.append({"domain": dom, "layout_id": lid, "field": f, "pages": len(pages), "scored": scored,
                         "not_scored": len(pages) - scored, "status": status, "annotators_with_rule": " ".join(who),
                         "source": ("" if not rule else " ".join(source(layout, ann, f, fd, rule)) or "administrator")})
    return rows


def main():
    tmpls, now = X._templates(), datetime.now(timezone.utc).isoformat(timespec="seconds")
    OUT.mkdir(exist_ok=True)
    recs, gaps, summary = [], [], {"rescored_at": now, "experiments": []}
    for path in sorted(SRC.glob("*.json")):
        e = json.loads(path.read_text(encoding="utf-8"))
        before = {k: e["summary"][k] for k in ("mean", "sample_mean", "others_mean", "per_field", "labels")}
        for lay in e["layouts"]:
            if lay.get("error"):
                continue
            scores, lsum, *_ = rescore_layout(e, lay, tmpls)
            lay["pages"] = scores
            lay["summary"] = {**lay["summary"], **lsum}
            gaps.append({"experiment": e["name"], "domain": lay["domain"], "layout_id": lay["layout_id"],
                         "sample": lsum["sample_mean"], "others": lsum["others_mean"],
                         "difference_points": round(100 * (lsum["sample_mean"] - lsum["others_mean"]), 2)})
        e["summary"] = X.summarize(e)
        e["rescored"] = {"at": now, "reference": "reviewed reference (paper/softwarex/gt_review.md)",
                         "note": "Rules, prompts, tokens and times are those of the original run; only the scores were recomputed.",
                         "submitted_summary": before}
        (OUT / path.name).write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
        recs.append(e)
        summary["experiments"].append({"id": e["id"], "name": e["name"],
                                       "submitted": {k: before[k] for k in ("mean", "sample_mean", "others_mean")},
                                       "rescored": {k: e["summary"][k] for k in ("mean", "sample_mean", "others_mean")},
                                       "labels": e["summary"]["labels"]})

    # one row per experiment (the columns of the reports export)
    fields = list(recs[0]["summary"]["per_field"])
    with (HERE / "results" / "llm_experiments.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "model", "rule_language", "css_repair", "model_overrides", "layouts", "mean", "sample_page", "other_pages",
                    "llm_calls", "prompt_tokens", "gen_tokens", "llm_seconds"] + [f"field_{f}" for f in fields])
        for e in sorted(recs, key=lambda x: -x["summary"]["mean"]):
            c, s = e["config"], e["summary"]
            lang = "css→regexn" if c.get("rule_source") == "llm_css_regexn" else c["rule_type"]
            w.writerow([e["id"], c["model"], lang, c.get("css_repair", False),
                        json.dumps((c.get("backend_snapshot") or {}).get("model_overrides") or {}), s["layouts"], s["mean"],
                        s["sample_mean"], s["others_mean"], s["llm_calls"], s["prompt_tokens"], s["gen_tokens"],
                        round(s["llm_ms"] / 1000, 1)] + [("" if s["per_field"][f] is None else s["per_field"][f]) for f in fields])

    cov = coverage_rows(recs[0], tmpls)                      # the reference is the same for all experiments
    for name, rows in (("coverage", cov), ("sample_gap", gaps)):
        with (HERE / "results" / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    tot, scored = sum(r["pages"] for r in cov), sum(r["scored"] for r in cov)
    not_scored = Counter()
    for r in cov:
        not_scored["reference rule returns no value on the page" if r["status"] == "reference rule" else r["status"]] += r["not_scored"]
    by_field = {f: {"scored": sum(r["scored"] for r in cov if r["field"] == f),
                    "layouts_with_rule": sum(1 for r in cov if r["field"] == f and r["status"] == "reference rule")} for f in fields}
    d = [g["difference_points"] for g in gaps]
    q = statistics.quantiles(d, n=4)
    per_exp = {}
    for g in gaps:
        per_exp.setdefault(g["experiment"], []).append(g["difference_points"])
    summary["coverage"] = {"pairs": tot, "scored": scored, "not_scored": tot - scored, "not_scored_by_reason": dict(not_scored),
                           "by_field": by_field,
                           "rules": {"approved": sum(1 for r in cov if r["status"] == "reference rule"),
                                     "written_or_edited_by_administrator": sum(1 for r in cov if r["source"] == "administrator")}}
    summary["sample_vs_others"] = {
        "unit": "points (0–100), sample page minus the other pages of the layout",
        "pairs": len(d), "min": min(d), "q1": round(q[0], 2), "median": round(q[1], 2), "q3": round(q[2], 2), "max": max(d),
        "mean_absolute": round(sum(abs(x) for x in d) / len(d), 2),
        "largest_aggregate_difference": max(round(100 * abs(x["rescored"]["sample_mean"] - x["rescored"]["others_mean"]), 2)
                                            for x in summary["experiments"]),
        "per_experiment": {k: {"min": min(v), "median": round(statistics.median(v), 2), "max": max(v)} for k, v in per_exp.items()}}
    (HERE / "results" / "rescore.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("coverage", "sample_vs_others")}, ensure_ascii=False, indent=1))
    for x in sorted(summary["experiments"], key=lambda x: -x["rescored"]["mean"]):
        print(f'{x["name"]:44s} {100 * x["submitted"]["mean"]:5.1f} -> {100 * x["rescored"]["mean"]:5.1f}')


if __name__ == "__main__":
    main()
