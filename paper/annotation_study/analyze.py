"""
analyze.py — annotatör uyumu çalışması (paper/annotation_study)
===============================================================
sample.json'daki layout'lar için annotatörlerin CSS kurallarını iki düzeyde karşılaştırır:

  1. Kural düzeyi  — normalize kurallar üzerinden Fleiss κ (layout'lar konu) ve P̄o
  2. İçerik düzeyi — kuralların layout'un BÜTÜN GT sayfalarında çıkardığı değerler üzerinden
                     Krippendorff α (uzaklık = 1 − alan metriği: ROUGE-1 F1 / Jaccard / tam eşleşme)
                     ve annotatör çiftleri arasındaki ortalama içerik benzerliği

Hesap webrulebench.evaluation.agreement'tadır; web arayüzü (Raporlar → Annotation & GT) aynı fonksiyonu kullanır.

Kullanım:  python paper/annotation_study/analyze.py [--annotators euzun user2 user3]
           Çıktılarda annotatörler verilen sırayla A1, A2, A3… olarak anonimleştirilir.
Çıktılar:  paper/annotation_study/results/agreement.json, per_field.csv, per_pair.csv, per_layout.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from webrulebench.evaluation.agreement import agreement_study  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotators", nargs="+", default=["euzun", "user2", "user3"])
    ap.add_argument("--max-pairs", type=int, default=20000, help="D_e kestirimi için rastgele çift sayısı")
    args = ap.parse_args()
    users = args.annotators
    label = {u: f"A{i}" for i, u in enumerate(users, 1)}   # çıktılarda anonim ad

    sample = json.loads((HERE / "sample.json").read_text(encoding="utf-8"))
    res = agreement_study([(s["domain"], s["layout_id"]) for s in sample["sites"]], users=users, lang="css",
                          max_pairs=args.max_pairs, seed=0, min_annotators=0)
    per_field, per_layout = res["per_field"], res["per_layout"]
    per_pair = [{"pair": f"{label[r['a']]}–{label[r['b']]}", "cells": r["cells"], "content_similarity": r["content_similarity"]}
                for r in res["per_pair"]]

    OUT.mkdir(exist_ok=True)
    result = {"annotators": [label[u] for u in users], "sample": sample, "per_field": per_field, "per_pair": per_pair,
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
