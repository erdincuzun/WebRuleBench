"""
reference_check.py
==================
Two checks of the reviewed reference reported in Section 3 of the paper. No LLM is called.

1. Agreement of the reference with the annotators: for every scored page–field pair, how many annotators' rules
   extract a value with similarity >= 0.8 (field metric) to the reference value. Pairs that agree with no annotator
   are listed by layout and field together with the source of the approved rule.
2. Over-extraction: on fields for which no annotator wrote a rule (the field is not on the site), the share of
   pairs on which the saved rules of each LLM configuration still return a value. The score does not count these.

Reads   the data folder (WRB_DATA_DIR): reference, annotator rules, pages
        results/coverage.csv, results/experiments/*.json   (written by rescore.py)
Writes  results/reference_check.json

    python paper/annotation_study/reference_check.py
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rescore import ANNOTATORS, annotator_rules, doc  # noqa: E402

from webrulebench.evaluation import experiments as X  # noqa: E402

HERE = Path(__file__).resolve().parent
THRESHOLD = 0.8


def values(dom: str, page: str, rule: str, lang: str, fd: dict) -> list:
    html, soup = doc(dom, page)
    try:
        return X.rule_values(html, soup, rule or "", lang, X._kind(fd), bool(fd.get("merge")))
    except Exception:
        return []


def layouts(tmpls: dict):
    for x in json.loads((HERE / "results" / "agreement.json").read_text(encoding="utf-8"))["sample"]["sites"]:
        dom, lid = x["domain"], x["layout_id"]
        gt = X._load_json(X.GT_DIR / f"{dom}.json", {})
        layout = gt["layouts"][lid]
        pages = sorted(p for p, v in gt["page_assignments"].items() if v.get("layout_id") == lid and not v.get("skipped"))
        yield dom, lid, layout, tmpls[X.layout_template_id(layout, tmpls)]["fields"], pages


def agreement_with_annotators(tmpls: dict) -> dict:
    totals, disagree = Counter(), defaultdict(Counter)
    for dom, lid, layout, fields, pages in layouts(tmpls):
        ann = annotator_rules(dom, lid)
        for f, fd in fields.items():
            ref_rule = X._rule_of((layout.get("selectors") or {}).get(f), "css")
            if not ref_rule:
                continue
            for p in pages:
                ref = values(dom, p, ref_rule, "css", fd)
                if not ref:
                    continue
                n = 0
                for rules in ann.values():
                    rule = rules.get(f)
                    got = values(dom, p, rule, "css", fd) if rule else []
                    if got and X.score_field(ref, got, fd.get("metric", "rouge"))[0] >= THRESHOLD:
                        n += 1
                key = "at_least_two" if n >= 2 else ("one" if n == 1 else "none")
                totals[key] += 1
                totals["scored_pairs"] += 1
                if not n:
                    src = ((layout.get("rule_sources") or {}).get(f) or {}).get("css")
                    disagree[(dom, f)]["pairs"] += 1
                    disagree[(dom, f)]["source"] = "administrator" if src == [] else " ".join(src or ["unknown"])
    s = totals["scored_pairs"]
    return {"threshold": THRESHOLD, **dict(totals),
            "share_at_least_one": round((totals["one"] + totals["at_least_two"]) / s, 4),
            "share_at_least_two": round(totals["at_least_two"] / s, 4),
            "agreeing_with_no_annotator": [{"domain": d, "field": f, **c} for (d, f), c in sorted(disagree.items())]}


def over_extraction(tmpls: dict) -> dict:
    absent = {(r["domain"], r["layout_id"], r["field"])
              for r in csv.DictReader((HERE / "results" / "coverage.csv").open(encoding="utf-8"))
              if r["status"] == "no rule by any annotator"}
    out = {}
    for path in sorted((HERE / "results" / "experiments").glob("*.json")):
        e = json.loads(path.read_text(encoding="utf-8"))
        n = hit = 0
        for lay in e["layouts"]:
            if lay.get("error"):
                continue
            dom, lid = lay["domain"], lay["layout_id"]
            layout = X._load_json(X.GT_DIR / f"{dom}.json", {})["layouts"][lid]
            for f, fd in tmpls[X.layout_template_id(layout, tmpls)]["fields"].items():
                if (dom, lid, f) not in absent:
                    continue
                for p in lay["pages"]:
                    n += 1
                    hit += bool(values(dom, p, lay["rules"].get(f), e["config"]["rule_type"], fd))
        out[e["name"]] = {"pairs": n, "with_value": hit, "share": round(hit / n, 4) if n else None}
    return out


def main():
    tmpls = X._templates()
    res = {"annotators": sorted(ANNOTATORS), "reference_vs_annotators": agreement_with_annotators(tmpls),
           "over_extraction_on_absent_fields": over_extraction(tmpls)}
    (HERE / "results" / "reference_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n",
                                                          encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
