"""
analyze_rules.py — LLM deneylerindeki kural hatalarının analizi (makale, Bölüm 3.2)
================================================================================
results/experiments/ altındaki deney kayıtlarından üç sonucu yeniden üretir:

  1. Kayıp puanların etikete göre dağılımı (MISS = kural hiçbir şey çıkarmadı)  — yalnızca kayıtlar
  2. XPath: kuralların sınıf özniteliğini tam eşitlikle sınaması (@class='…'); yalnızca bu testler
     sınıf listesinde geçme testine çevrildiğinde skor                          — HTML sayfaları gerekir
  3. Modelin yazdığı regex'ler: iskelette (modelin gördüğü) ve ham sayfada eşleşme  — HTML sayfaları gerekir

2 ve 3 için WRB_DATA_DIR, onaylı GT'yi ve ham sayfaları içeren veri klasörünü göstermelidir
(Zenodo'daki açık kayıt + istek üzerine verilen html.zip).

Kullanım:  python paper/annotation_study/analyze_rules.py
Çıktı:     paper/annotation_study/results/rule_analysis.json
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bs4 import BeautifulSoup  # noqa: E402

from webrulebench.evaluation import experiments as X  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPS = HERE / "results" / "experiments"


def load(rule_type: str, source: str = "llm", model: str = "qwen2.5-coder:14b") -> dict:
    for p in sorted(EXPS.glob("*.json")):
        e = json.loads(p.read_text(encoding="utf-8"))
        c = e["config"]
        if c["model"] == model and c["rule_type"] == rule_type and c.get("rule_source", "llm") == source:
            return e
    raise SystemExit(f"no experiment for {model} / {rule_type} / {source}")


def lost_points(e: dict) -> dict:
    """Etikete göre kaybedilen puan (1 − skor) payı."""
    loss = Counter()
    for lay in e["layouts"]:
        for cells in lay["pages"].values():
            for c in cells.values():
                if c.get("score") is not None:
                    loss[c["label"]] += 1 - c["score"]
    tot = sum(loss.values())
    return {k: round(v / tot, 3) for k, v in loss.most_common()}


def class_token_test(m) -> str:
    return " and ".join(f"contains(concat(' ', normalize-space(@class), ' '), ' {t} ')" for t in m.group(2).split())


def rescore_xpath(e: dict, rewrite) -> float:
    """Deneydeki gibi skorla (layout ortalamalarının ortalaması); kurallara önce rewrite uygulanır."""
    tmpls, means = X._templates(), []
    for lay in e["layouts"]:
        dom, lid = lay["domain"], lay["layout_id"]
        layout = X._load_json(X.GT_DIR / f"{dom}.json", {})["layouts"][lid]
        fields = tmpls[X.layout_template_id(layout, tmpls)]["fields"]
        gt_sels, scores = layout.get("selectors") or {}, []
        rules = {f: rewrite(r or "") for f, r in lay["rules"].items()}
        for page in sorted(lay["pages"]):
            html = (X.RAW_DIR / dom / page).read_text(encoding="utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            for f, fd in fields.items():
                k, m = X._kind(fd), bool(fd.get("merge"))
                g = X._rule_of(gt_sels.get(f), "css")
                gt_vals = X.rule_values(html, soup, g, "css", k, m) if g else []
                try:
                    pred = X.rule_values(html, soup, rules.get(f) or "", "xpath", k, m)
                except Exception:
                    pred = []
                s, _ = X.score_field(gt_vals, pred, fd.get("metric", "rouge"))
                if s is not None:
                    scores.append(s)
        means.append(sum(scores) / len(scores))
    return round(sum(means) / len(means), 4)


def regex_on_skeleton_vs_raw(e: dict) -> dict:
    from webrulebench.pipeline.html_cleaner import HTMLCleaner
    from webrulebench.pipeline.skeleton import Skeleton
    c = Counter()
    for lay in e["layouts"]:
        html = (X.RAW_DIR / lay["domain"] / lay["sample_page"]).read_text(encoding="utf-8", errors="ignore")
        skel = Skeleton(strategy="enriched").extract(
            HTMLCleaner().clean(html, strategy=e["config"]["strategy"]).cleaned_html).skeleton_html
        for r in lay["rules"].values():
            if not r:
                c["no rule"] += 1
                continue
            try:
                rx = re.compile(r, re.S)
            except re.error:
                c["invalid"] += 1
                continue
            c[("raw" if rx.search(html) else "-") + " / " + ("skeleton" if rx.search(skel) else "-")] += 1
    return dict(c)


def main():
    css14, css7 = load("css"), load("css", model="qwen2.5-coder:7b")
    xp, rx = load("xpath"), load("regex")
    out = {"lost_points_by_label": {"qwen2.5-coder:14b css": lost_points(css14), "qwen2.5-coder:7b css": lost_points(css7)}}
    rules = [r for lay in xp["layouts"] for r in lay["rules"].values() if r]
    out["xpath"] = {"rules": len(rules),
                    "whole_class_attribute_tests": sum(1 for r in rules if re.search(r"@class\s*=\s*['\"]", r)),
                    "score": rescore_xpath(xp, lambda r: r),
                    "score_with_class_token_tests": rescore_xpath(
                        xp, lambda r: re.sub(r"@class\s*=\s*(['\"])(.*?)\1", class_token_test, r))}
    out["regex_matches_on_sample_page"] = regex_on_skeleton_vs_raw(rx)
    (HERE / "results" / "rule_analysis.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
