"""
analyze_rules.py — LLM deneylerindeki kural hatalarının analizi (makale, Bölüm 3.2)
================================================================================
results/experiments/ altındaki deney kayıtlarından (RUNS) şunları yeniden üretir:

  1. Kayıp puanların etikete göre dağılımı (MISS = kural hiçbir şey çıkarmadı)  — yalnızca kayıtlar
  2. XPath: kuralların sınıf özniteliğini tam eşitlikle sınaması (@class='…'); yalnızca bu testler
     sınıf listesinde geçme testine çevrildiğinde skor                          — HTML sayfaları gerekir
  3. Modelin yazdığı regex'ler: iskelette (modelin gördüğü) ve ham sayfada eşleşme  — HTML sayfaları gerekir
  4. Kural dillerinin çıkarım süresi (ms/sayfa, ham HTML'den)                    — HTML sayfaları gerekir
  5. Makaledeki sonuç tablosu (results/table_llm.tex)

2-4 için WRB_DATA_DIR, onaylı GT'yi ve ham sayfaları içeren veri klasörünü göstermelidir
(Zenodo'daki açık kayıt + istek üzerine verilen html.zip).

Kullanım:  python paper/annotation_study/analyze_rules.py
Çıktı:     paper/annotation_study/results/rule_analysis.json, results/table_llm.tex
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
RX_FLAGS = re.I | re.S          # deneylerdeki gibi (rule_utils.run_regex)
# (model, kural dili, kural kaynağı) — makaledeki tablonun sırası
RUNS = [("qwen2.5-coder:14b", "css", "llm"), ("qwen2.5-coder:7b", "css", "llm"), ("ministral-3:8b", "css", "llm"),
        ("gemma4:latest", "css", "llm"), ("phi4:14b", "css", "llm"),
        ("qwen2.5-coder:14b", "xpath", "llm"), ("qwen2.5-coder:14b", "regex", "llm"),
        ("qwen2.5-coder:14b", "regex", "llm_css_regexn")]


def load(rule_type: str, source: str = "llm", model: str = "qwen2.5-coder:14b") -> dict:
    for p in sorted(EXPS.glob("*.json")):
        e = json.loads(p.read_text(encoding="utf-8"))
        c = e["config"]
        if c["model"] == model and c["rule_type"] == rule_type and c.get("rule_source", "llm") == source:
            return e
    raise SystemExit(f"no experiment for {model} / {rule_type} / {source}")


def label(e: dict) -> str:
    c = e["config"]
    return f"{c['model']} {'css→regexn' if c.get('rule_source') == 'llm_css_regexn' else c['rule_type']}"


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
                rx = re.compile(r, RX_FLAGS)
            except re.error:
                c["invalid"] += 1
                continue
            c[("raw" if rx.search(html) else "-") + " / " + ("skeleton" if rx.search(skel) else "-")] += 1
    return dict(c)


def extraction_speed(runs: dict, repeats: int = 3) -> dict:
    # runs: {etiket: (deney kaydı, "css" | "xpath" | "regex")}
    """Bir sayfadan layout'un bütün alanlarını çıkarma süresi (ms/sayfa, ham HTML'den başlayarak):
    CSS → Beautiful Soup (html.parser) DOM'u + select; XPath → lxml ağacı + xpath; regex → ham metinde re.
    Her sayfa için `repeats` ölçümün en küçüğü alınır; metin normalleştirmesi ölçüme dahil değildir."""
    import time
    import lxml.html
    from bs4 import BeautifulSoup as BS

    def css(html, rules):
        soup = BS(html, "html.parser")
        for r in rules:
            for part in (p.strip() for p in r.split(",") if p.strip()):
                try:
                    if soup.select(part):
                        break
                except Exception:
                    pass

    def xpath(html, rules):
        tree = lxml.html.fromstring(html)
        for r in rules:
            try:
                tree.xpath(r)
            except Exception:
                pass

    def regex(html, rules):
        for rx in rules:
            rx.findall(html)

    runner = {"css": css, "xpath": xpath, "regex": regex}
    out = {}
    for name, (e, lang) in runs.items():
        run = runner[lang]
        times = []
        for lay in e["layouts"]:
            rules = [r for r in lay["rules"].values() if r]
            if run is regex:
                comp = []
                for r in rules:
                    try:
                        comp.append(re.compile(r, RX_FLAGS))
                    except re.error:
                        pass
                rules = comp
            for page in sorted(lay["pages"]):
                html = (X.RAW_DIR / lay["domain"] / page).read_text(encoding="utf-8", errors="ignore")
                best = float("inf")
                for _ in range(repeats):
                    t0 = time.perf_counter()
                    run(html, rules)
                    best = min(best, time.perf_counter() - t0)
                times.append((best * 1000, lay["domain"]))
        ms = sorted(t for t, _ in times)
        slow = max(times)
        out[name] = {"pages": len(ms), "mean_ms": round(sum(ms) / len(ms), 2), "median_ms": round(ms[len(ms) // 2], 2),
                     "max_ms": round(slow[0], 1), "slowest_layout": slow[1]}
    return out


def write_table(runs: list, speed: dict, path: Path):
    """Makaledeki sonuç tablosu: model, kural dili, skorlar (0–100), LLM süresi, çıkarım süresi (medyan ms/sayfa).
    a: düşünme kapalı (think = false); b: bir layout'un yanıtı çıktı sınırında kesildi (kural yok)."""
    lang = {"css": "CSS", "xpath": "XPath", "regex": "regex"}
    # ortak ayarlar kayıtlardan okunur (bütün deneylerde aynı olmalı)
    common = {(json.dumps(e["config"]["sample"], sort_keys=True), e["config"]["strategy"],
               *(e["config"]["backend_snapshot"]["params"].get(k) for k in ("temperature", "seed", "max_tokens")))
              for e in runs}
    assert len(common) == 1, f"experiments differ in settings: {common}"
    sample, strategy, temp, seed, max_tokens = next(iter(common))
    sample = json.loads(sample)
    sample = ("each layout's first ground-truth page as sample" if sample["mode"] == "first"
              else f"a random ground-truth page of each layout as sample (seed {sample.get('seed')})")
    lines = [r"\begin{table}[!htb]", r"  \centering", r"  \footnotesize", r"  \setlength{\tabcolsep}{2.5pt}", r"  \setlength{\abovetopsep}{3pt}",
             r"  \caption{LLM experiments on the ten layouts of the annotation study (Ollama; temperature "
             f"{temp:g}, seed {seed}, at most {max_tokens} output tokens; {strategy.replace('_', ' ')} cleaning; {sample}). "
             r"Mean scores (0--100) on all ground-truth pages, the sample page and the other pages; LLM: time of the "
             r"ten calls on a laptop (Apple M1 Pro, 16 GB RAM); ms/page: median over pages of the best of three runs "
             r"from the raw HTML, parsing included.}",
             r"  \label{tab:llm}", r"  \begin{tabular}{@{}lrlrrrrr@{}}", r"    \toprule",
             r"    Model (Ollama) & Params & Rules & Mean & Sample & Others & LLM (s) & ms/page \\", r"    \midrule"]
    used = set()
    for i, e in enumerate(runs):
        c, s = e["config"], e["summary"]
        snap = c.get("backend_snapshot") or {}
        info, params = snap.get("model_info") or {}, snap.get("params") or {}
        rules = "CSS$\\rightarrow$REGEXN" if c.get("rule_source") == "llm_css_regexn" else lang[c["rule_type"]]
        marks = ""
        if (snap.get("model_overrides") or {}).get("think") is False:
            marks += "a"
        if any(not (lay.get("llm") or {}).get("success") and (lay.get("llm") or {}).get("gen_tokens") == params.get("max_tokens")
               for lay in e["layouts"]):
            marks += "b"
        used |= set(marks)
        if i and c["rule_type"] != runs[i - 1]["config"]["rule_type"] and c["rule_type"] == "xpath":
            lines.append(r"    \midrule")
        lines.append(f"    \\texttt{{{c['model']}}}{'$^{' + ','.join(marks) + '}$' if marks else ''} & "
                     f"{info.get('parameter_size', '')} & {rules} & {100 * s['mean']:.1f} & {100 * s['sample_mean']:.1f} & "
                     f"{100 * s['others_mean']:.1f} & {s['llm_ms'] / 1000:.0f} & {speed[label(e)]['median_ms']:.1f} \\\\")
    notes = {"a": r"$^a$ thinking disabled", "b": r"$^b$ one response cut off at the output limit"}
    lines += [r"    \bottomrule"]
    if used:      # dipnot tablonun sol kenarında, tablonun bir satırı olarak
        lines += [r"    \multicolumn{8}{@{}l}{\rule{0pt}{2.4ex}" + "; ".join(notes[k] for k in sorted(used)) + r".} \\"]
    lines += [r"  \end{tabular}", r"\end{table}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    runs = [load(rt, source=src, model=m) for m, rt, src in RUNS]
    xp, rx = load("xpath"), load("regex")
    out = {"lost_points_by_label": {label(e): lost_points(e) for e in runs if e["config"]["rule_type"] == "css"}}
    rules = [r for lay in xp["layouts"] for r in lay["rules"].values() if r]
    out["xpath"] = {"rules": len(rules),
                    "whole_class_attribute_tests": sum(1 for r in rules if re.search(r"@class\s*=\s*['\"]", r)),
                    "score": rescore_xpath(xp, lambda r: r),
                    "score_with_class_token_tests": rescore_xpath(
                        xp, lambda r: re.sub(r"@class\s*=\s*(['\"])(.*?)\1", class_token_test, r))}
    out["regex_matches_on_sample_page"] = regex_on_skeleton_vs_raw(rx)
    # CSS → Beautiful Soup (html.parser), XPath → lxml, regex → re: deneylerin kullandığı yürütücüler
    out["extraction_ms_per_page"] = extraction_speed({label(e): (e, e["config"]["rule_type"]) for e in runs})
    (HERE / "results" / "rule_analysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    write_table(runs, out["extraction_ms_per_page"], HERE / "results" / "table_llm.tex")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
