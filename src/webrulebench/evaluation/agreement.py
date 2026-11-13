"""
webrulebench/evaluation/agreement.py — annotator agreement at two levels
===================================================================
  1. Rule level    — Fleiss κ over normalized rules (layouts as subjects) and P̄o
  2. Content level — over the values the rules extract on ALL GT pages of the layout:
                     Krippendorff α (distance = 1 − field metric: ROUGE-1 F1 / Jaccard / exact match)
                     and the mean content similarity between annotator pairs

The web interface (Reports → Annotation & GT) and paper/annotation_study/analyze.py use the same function.
"""
from __future__ import annotations

import itertools
import json

from bs4 import BeautifulSoup

from webrulebench.evaluation import experiments as X
from webrulebench.rules import rule_agreement as RA

ANNOTATIONS_DIR = X.ROOT / "annotations"


def similarity(a: list, b: list, metric: str) -> float:
    """Similarity of the values two annotators extracted on a page; 1 if both are empty, 0 if one is empty."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    s, _ = X.score_field(a, b, metric)
    return s or 0.0


def annotator_rules(domain: str, layout_id: str, fields: dict, lang: str = "css", users: list | None = None) -> dict:
    """{user: {field: rule | None}} — annotators who wrote at least one rule in this language for the layout.
    If users is given, only those, in the given order; otherwise all annotation files of the site (sorted by name)."""
    d = ANNOTATIONS_DIR / domain
    files = [d / f"{u}.json" for u in users] if users else sorted(d.glob("*.json"))
    out = {}
    for p in files:
        if not p.exists():
            continue
        try:
            sel = (json.loads(p.read_text(encoding="utf-8")).get("layouts", {}).get(layout_id) or {}).get("selectors") or {}
        except ValueError:
            continue
        if any(X._rule_of(v, lang) for v in sel.values()):
            out[p.stem] = {f: X._rule_of(sel.get(f), lang) or None for f in fields}
    return out


def approved_layouts() -> list:
    """[(domain name, layout_id)] — all layouts in the approved GT (sorted by domain name)."""
    out = []
    for f in sorted(X.GT_DIR.glob("*.json")):
        out += [(f.stem, lid) for lid in (X._load_json(f, {}).get("layouts") or {})]
    return out


def agreement_study(layouts: list | None = None, users: list | None = None, lang: str = "css",
                    max_pairs: int = 20000, seed: int = 0, min_annotators: int = 2) -> dict:
    """Field-level rule and content agreement, annotator pairs and a per-layout summary for the selected layouts
    (default: all layouts in the approved GT with at least min_annotators annotators)."""
    tmpls = X._templates()
    rule_subjects, content_units, metric_of = {}, {}, {}
    pair_sims = {}                 # (a, b, field) -> [similarity]; a < b
    exact = {}                     # field -> [are the normalized rules identical]
    per_layout, seen = [], []

    for dom, lid in (layouts if layouts is not None else approved_layouts()):
        gt = X._load_json(X.GT_DIR / f"{dom}.json", {})
        layout = (gt.get("layouts") or {}).get(lid)
        if not layout:
            continue
        fields = (tmpls.get(X.layout_template_id(layout, tmpls)) or {}).get("fields") or {}
        rules = annotator_rules(dom, lid, fields, lang, users)
        if len(rules) < min_annotators:
            continue
        seen += [u for u in rules if u not in seen]
        pages = sorted(p for p, v in (gt.get("page_assignments") or {}).items()
                       if v.get("layout_id") == lid and not v.get("skipped") and (X.RAW_DIR / dom / p).is_file())
        lay_sims, lay_rule = [], []
        for f, fd in fields.items():
            metric_of[f] = fd.get("metric", "rouge")
            norm = [RA.normalize_rule(rules[u][f], lang, bool(fd.get("merge"))) for u in rules]
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
                    if r:                      # annotator who did not write the rule = missing value
                        vals[u] = X.rule_values(html, soup, r, lang, X._kind(fd), bool(fd.get("merge")))
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
                                  max_pairs=max_pairs, seed=seed)
        sims = [v for (p, q, ff), xs in pair_sims.items() if ff == f for v in xs]
        ex = exact.get(f, [])
        per_field.append({
            "field": f, "metric": m,
            "layouts": k["n_subjects"] if k else 0,
            "rule_kappa": round(k["kappa"], 3) if k and k["kappa"] is not None else None,
            "rule_po": round(k["po"], 3) if k else None,
            "rule_exact_share": round(sum(ex) / len(ex), 3) if ex else None,
            "content_alpha": round(a["alpha"], 3) if a else None, "content_units": a["units"] if a else 0,
            "content_similarity": round(sum(sims) / len(sims), 3) if sims else None,
        })

    names = list(users) if users else sorted(seen)
    per_pair = []
    for a, b in itertools.combinations(names, 2):
        key = tuple(sorted((a, b)))
        xs = [v for (p, q, f), vs in pair_sims.items() if (p, q) == key for v in vs]
        per_pair.append({"a": a, "b": b, "cells": len(xs),
                         "content_similarity": round(sum(xs) / len(xs), 3) if xs else None})

    return {"lang": lang, "annotators": names, "per_field": per_field, "per_pair": per_pair, "per_layout": per_layout,
            "max_pairs": max_pairs, "seed": seed}
