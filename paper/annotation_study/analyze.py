"""
analyze.py — annotatör uyumu çalışması (paper/annotation_study)
===============================================================
sample.json'daki layout'lar için annotatörlerin CSS kurallarını iki düzeyde karşılaştırır:

  1. Kural düzeyi  — normalize kurallar üzerinden Fleiss κ (layout'lar konu) ve P̄o
  2. İçerik düzeyi — kuralların layout'un BÜTÜN GT sayfalarında çıkardığı değerler üzerinden
                     Krippendorff α (uzaklık = 1 − alan metriği: ROUGE-1 F1 / Jaccard / tam eşleşme)
                     ve annotatör çiftleri arasındaki ortalama içerik benzerliği

Kullanım:  python paper/annotation_study/analyze.py [--annotators euzun user2 user3]
Çıktılar:  paper/annotation_study/results/agreement.json, per_field.csv, per_pair.csv, per_layout.csv
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from webrulebench.evaluation import experiments as X  # noqa: E402
from webrulebench.paths import DATA_DIR  # noqa: E402
from webrulebench.rules import rule_agreement as RA  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"


def load_rules(domain: str, layout_id: str, users: list, fields: dict) -> dict:
    out = {}
    for u in users:
        p = DATA_DIR / "annotations" / domain / f"{u}.json"
        if not p.exists():
            continue
        sel = (json.loads(p.read_text(encoding="utf-8")).get("layouts", {}).get(layout_id) or {}).get("selectors") or {}
        if any(sel.values()):
            out[u] = {f: X._rule_of(sel.get(f), "css") or None for f in fields}
    return out


def similarity(a: list, b: list, metric: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    s, _ = X.score_field(a, b, metric)
    return s or 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotators", nargs="+", default=["euzun", "user2", "user3"])
    ap.add_argument("--max-pairs", type=int, default=20000, help="D_e kestirimi için rastgele çift sayısı")
    args = ap.parse_args()
    users = args.annotators

    sample = json.loads((HERE / "sample.json").read_text(encoding="utf-8"))
    tmpls = X._templates()
    rule_subjects, content_units, metric_of = {}, {}, {}
    pair_sims = {}                 # (a, b, field) -> [benzerlik]
    exact = {}                     # field -> [normalize kurallar aynı mı]
    per_layout = []

    for s in sample["sites"]:
        dom, lid = s["domain"], s["layout_id"]
        gt = json.loads((DATA_DIR / "ground_truth" / "approved" / f"{dom}.json").read_text(encoding="utf-8"))
        layout = gt["layouts"][lid]
        fields = tmpls[X.layout_template_id(layout, tmpls)]["fields"]
        rules = load_rules(dom, lid, users, fields)
        pages = sorted(p for p, v in gt["page_assignments"].items()
                       if v.get("layout_id") == lid and not v.get("skipped") and (X.RAW_DIR / dom / p).is_file())
        lay_sims, lay_rule = [], []
        for f, fd in fields.items():
            metric_of[f] = fd.get("metric", "rouge")
            norm = [RA.normalize_rule(rules[u][f]) for u in rules]
            rule_subjects.setdefault(f, []).append(norm)
            nn = [x for x in norm if x]
            for i, j in itertools.combinations(range(len(nn)), 2):
                exact.setdefault(f, []).append(nn[i] == nn[j])
            po = RA.observed_agreement(norm)
            if po is not None:
                lay_rule.append(po)
        for p in pages:
            html = (X.RAW_DIR / dom / p).read_text(encoding="utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            for f, fd in fields.items():
                vals = {}
                for u in rules:
                    r = rules[u][f]
                    if r:                      # kuralı yazılmamış annotatör = eksik değer
                        vals[u] = X.rule_values(html, soup, r, "css", X._kind(fd), bool(fd.get("merge")))
                if len(vals) >= 2:
                    content_units.setdefault(f, []).append(list(vals.values()))
                for a, b in itertools.combinations(sorted(vals), 2):
                    sim = similarity(vals[a], vals[b], metric_of[f])
                    pair_sims.setdefault((a, b, f), []).append(sim)
                    lay_sims.append(sim)
        per_layout.append({"domain": dom, "layout_id": lid, "pages": len(pages), "annotators": len(rules),
                           "rule_agreement": round(sum(lay_rule) / len(lay_rule), 3) if lay_rule else None,
                           "content_agreement": round(sum(lay_sims) / len(lay_sims), 3) if lay_sims else None})

    per_field = []
    for f in rule_subjects:
        k = RA.fleiss_kappa(rule_subjects[f])
        m = metric_of[f]
        a = RA.krippendorff_alpha(content_units.get(f, []), lambda x, y, m=m: 1 - similarity(x, y, m),
                                  max_pairs=args.max_pairs, seed=0)
        sims = [v for (p, q, ff), xs in pair_sims.items() if ff == f for v in xs]
        ex = exact.get(f, [])
        per_field.append({
            "field": f, "metric": m,
            "layouts": k["n_subjects"] if k else 0,
            "rule_kappa": round(k["kappa"], 3) if k and k["kappa"] is not None else None, "rule_po": round(k["po"], 3) if k else None,
            "rule_exact_share": round(sum(ex) / len(ex), 3) if ex else None,
            "content_alpha": round(a["alpha"], 3) if a else None, "content_units": a["units"] if a else 0,
            "content_similarity": round(sum(sims) / len(sims), 3) if sims else None,
        })
    per_pair = []
    for a, b in itertools.combinations(users, 2):
        xs = [v for (p, q, f), vs in pair_sims.items() if (p, q) == (a, b) for v in vs]
        per_pair.append({"pair": f"{a}–{b}", "cells": len(xs),
                         "content_similarity": round(sum(xs) / len(xs), 3) if xs else None})

    OUT.mkdir(exist_ok=True)
    result = {"annotators": users, "sample": sample, "per_field": per_field, "per_pair": per_pair,
              "per_layout": per_layout,
              "method": {"rule": "Fleiss kappa over layouts (subjects) x annotators; categories = normalized CSS rules (rule_agreement.normalize_rule)",
                         "content": "Krippendorff alpha over (layout, page, field) units; distance = 1 - field metric "
                                    "(ROUGE-1 F1 / Jaccard / exact match) on values extracted by each annotator's rule; "
                                    f"D_e estimated from {args.max_pairs} random value pairs (seed 0)"}}
    (OUT / "agreement.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for name, rows in (("per_field", per_field), ("per_pair", per_pair), ("per_layout", per_layout)):
        with (OUT / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    print(f"{'field':15} {'metric':11} {'lay':>3} {'κ_rule':>7} {'P̄o':>6} {'exact':>6} {'α_content':>9} {'sim':>6}")
    for r in sorted(per_field, key=lambda r: -(r["content_alpha"] or -9)):
        print(f"{r['field']:15} {r['metric']:11} {r['layouts']:>3} {str(r['rule_kappa']):>7} {str(r['rule_po']):>6} "
              f"{str(r['rule_exact_share']):>6} {str(r['content_alpha']):>9} {str(r['content_similarity']):>6}")
    print()
    for r in per_pair:
        print(f"{r['pair']:20} {r['content_similarity']}  ({r['cells']} cells)")
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()
