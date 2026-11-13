"""
analyze_rules.py — analysis of rule errors in the LLM experiments (paper, Section 3.2)
================================================================================
Reproduces the following from the experiment records under results/experiments/ (RUNS):

  1. Distribution of lost points by label (MISS = the rule extracted nothing)      — records only
  2. XPath: rules that test the class attribute by exact equality (@class='…'); the score when
     only these tests are turned into a class-list membership test               — needs HTML pages
  3. Regexes written by the model: matches in the skeleton (what the model saw) and in the raw page — needs HTML pages
  4. Extraction time of the rule languages (ms/page, from raw HTML)               — needs HTML pages
  5. Results table of the paper (results/table_llm.tex)

For 2-4, WRB_DATA_DIR must point to the data folder that holds the approved GT and the raw pages
(the open record on Zenodo + html.zip, provided on request).

Usage:   python paper/annotation_study/analyze_rules.py
Output:  paper/annotation_study/results/rule_analysis.json, results/table_llm.tex
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
from webrulebench.rules.rule_utils import split_selector_list  # noqa: E402

HERE = Path(__file__).resolve().parent
EXPS = HERE / "results" / "experiments"
RX_FLAGS = re.I | re.S          # as in the experiments (rule_utils.run_regex)
# (model, rule language, rule source) — order of the table in the paper
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
    """Share of lost points (1 − score) by label."""
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
    """Score as in the experiment (mean of the layout means); rewrite is applied to the rules first."""
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
    # runs: {label: (experiment record, "css" | "xpath" | "regex")}
    """Time to extract all fields of the layout from one page (ms/page, starting from raw HTML):
    CSS → Beautiful Soup (html.parser) DOM + select; XPath → lxml tree + xpath; regex → re on the raw text.
    For each page the minimum of `repeats` measurements is taken; text normalisation is not included in the measurement."""
    import time
    import lxml.html
    from bs4 import BeautifulSoup as BS

    def css(html, rules):
        soup = BS(html, "html.parser")
        for r in rules:
            for part in split_selector_list(r):
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
    """Results table of the paper: model, rule language, scores (0–100), range of the sample-page difference over
    the layouts, LLM time and extraction time (median ms/page); below it the reference points (annotators' own
    rules, generic rules) and the runs with a random sample page.
    a: thinking disabled; b: one response cut off at the output limit; c: regex written from the skeleton."""
    lang = {"css": "CSS", "xpath": "XPath", "regex": "regex"}
    # settings shared by all experiments are read from the records
    common = {(json.dumps(e["config"]["sample"], sort_keys=True), e["config"]["strategy"],
               *(e["config"]["backend_snapshot"]["params"].get(k) for k in ("temperature", "seed", "max_tokens")),
               e["config"]["backend_snapshot"]["model_info"]["quantization"]) for e in runs}
    assert len(common) == 1, f"experiments differ in settings: {common}"
    sample, strategy, temp, seed, max_tokens, quant = next(iter(common))
    assert json.loads(sample)["mode"] == "first"
    res = HERE / "results"
    ref = json.loads((res / "ceiling_baseline.json").read_text(encoding="utf-8"))
    rnd = [e for e in (json.loads(p.read_text(encoding="utf-8")) for p in sorted((res / "experiments_sample_pages").glob("*.json")))
           if e["config"]["sample"]["mode"] == "random"]
    rng = lambda xs: f"{min(xs):.1f}--{max(xs):.1f}"
    lines = [r"\begin{table}[!htb]", r"  \centering", r"  \scriptsize", r"  \setlength{\tabcolsep}{3pt}", r"  \setlength{\abovetopsep}{3pt}",
             r"  \caption{LLM experiments on the ten layouts, scored against the reviewed reference. "
             + f"Ollama, 4-bit quantized models ({quant.replace('_', chr(92) + '_')}); temperature {temp:g}, seed {seed}, at most {max_tokens} output tokens; "
             + f"{strategy.replace('_', ' ')} cleaning; first ground-truth page of each layout as the sample. "
             + r"\textbf{Mean:} score (0--100) of the scored page--field pairs, averaged per layout, then over the ten layouts. \textbf{Sample:} score on the ten sample pages, one per layout. "
             r"\textbf{Gap:} smallest/largest difference between the sample page and the other pages of a layout. "
             r"\textbf{LLM:} seconds for the ten calls (Apple M1 Pro, 16 GB RAM). \textbf{ms/page:} median extraction time from "
             r"the raw HTML, including parsing.}",
             r"  \label{tab:llm}", r"  \begin{tabular}{@{}>{\raggedright\arraybackslash}p{2.75cm}rlrrrrr@{}}", r"    \toprule",
             r"    Model (Ollama) & Params & Rules & Mean & Sample & Gap & LLM (s) & ms/page \\", r"    \midrule"]
    used, digests = set(), {}
    for i, e in enumerate(runs):
        c, s = e["config"], e["summary"]
        snap = c.get("backend_snapshot") or {}
        info, params = snap.get("model_info") or {}, snap.get("params") or {}
        digests[c["model"]] = info.get("digest", "")[:12]
        rules = "CSS$\\rightarrow$REGEXN" if c.get("rule_source") == "llm_css_regexn" else lang[c["rule_type"]]
        marks = ""
        if (snap.get("model_overrides") or {}).get("think") is False:
            marks += "a"
        if any(not (lay.get("llm") or {}).get("success") and (lay.get("llm") or {}).get("gen_tokens") == params.get("max_tokens")
               for lay in e["layouts"]):
            marks += "b"
        used |= set(marks)
        rmark = ""
        if c["rule_type"] == "regex" and c.get("rule_source", "llm") == "llm":
            rmark, used = "$^{c}$", used | {"c"}
        gaps = [100 * (lay["summary"]["sample_mean"] - lay["summary"]["others_mean"]) for lay in e["layouts"] if not lay.get("error")]
        if i and c["rule_type"] != runs[i - 1]["config"]["rule_type"] and c["rule_type"] == "xpath":
            lines.append(r"    \midrule")
        lines.append(f"    \\texttt{{{c['model']}}}{'$^{' + ','.join(marks) + '}$' if marks else ''} & "
                     f"{info.get('parameter_size', '')} & {rules}{rmark} & {100 * s['mean']:.1f} & {100 * s['sample_mean']:.1f} & "
                     f"${min(gaps):+.1f}$/${max(gaps):+.1f}$ & {s['llm_ms'] / 1000:.0f} & {speed[label(e)]['median_ms']:.1f} \\\\")
    ann = [ref[a]["summary"] for a in ("A1", "A2", "A3")]
    base = ref["baseline"]["summary"]
    lines += [r"    \midrule",
              f"    Annotators' rules$^{{d}}$ & & CSS & {rng([a['mean'] for a in ann])} & {rng([a['sample_mean'] for a in ann])} & & & \\\\",
              f"    Generic rules$^{{e}}$ & & CSS & {base['mean']:.1f} & {base['sample_mean']:.1f} & & & \\\\",
              f"    \\texttt{{qwen2.5-coder:14b}}, random page$^{{f}}$ & 14.8B & CSS & {rng([100 * e['summary']['mean'] for e in rnd])} & "
              f"{rng([100 * e['summary']['sample_mean'] for e in rnd])} & & & \\\\",
              r"    \bottomrule"]
    notes = {"a": r"$^a$ thinking disabled", "b": r"$^b$ one response cut off at the output limit",
             "c": r"$^c$ written from the skeleton, which omits attributes"}
    note = lambda s: r"    \multicolumn{8}{@{}p{\linewidth}@{}}{\rule{0pt}{2.4ex}" + s + r"} \\"
    lines += [note("; ".join(notes[k] for k in sorted(used)) + r"; $^d$ the own rules of A1--A3, scored like an LLM configuration; an optimistic upper reference, because "
                   r"the reference was built from these rules; $^e$ the same for every site, e.g.\ \texttt{h1}, \texttt{article}, \texttt{time}, written without "
                   + f"looking at a page; $^f$ {len(rnd)} runs, each with a randomly chosen ground-truth page per layout."),
              note("Model digests: " + "; ".join(f"\\texttt{{{m}}} \\texttt{{{d}}}" for m, d in digests.items()) + ".")]
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
    # CSS → Beautiful Soup (html.parser), XPath → lxml, regex → re: the engines used by the experiments
    out["extraction_ms_per_page"] = extraction_speed({label(e): (e, e["config"]["rule_type"]) for e in runs})
    (HERE / "results" / "rule_analysis.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    write_table(runs, out["extraction_ms_per_page"], HERE / "results" / "table_llm.tex")
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
