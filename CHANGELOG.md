# Changelog

## 1.0.4 — 2026-10

- LLM evaluation: the heuristic repairs of the CSS rules an LLM writes (a missing dot between class names, a class
  name written as a tag, a weak body selector replaced by the page's `main` or `article` element) are now an
  experiment option, **off by default**, so that rules are scored as the model wrote them. The choice is saved with
  the experiment and shown in its views; experiments created before 1.0.4 resume as they ran (with repairs).
- Two repair errors are fixed: a class named like an HTML tag (`h1.title`, `div.meta`) is no longer turned into a
  descendant tag when the class occurs in the skeleton, and text inside quotes, brackets or parentheses
  (`:contains('27 Mart 2026')`, `[class="a b"]`) is left unchanged.
- Ollama: optional per-model `think` setting (LLM Models → model parameters) for thinking models; `false` makes
  the model answer without thinking, so that the output limit is not spent on thinking. The setting is saved in the
  experiment's backend snapshot. An empty response whose output went to thinking now says so.
- A call error (e.g. a timeout) is no longer reported as "Empty response".
- `paper/annotation_study`: the LLM experiments of the paper were re-run with 1.0.4 as one comparison group of
  eight configurations (five local models with CSS rules; XPath, regex and CSS → REGEXN with qwen2.5-coder 14B);
  `analyze_rules.py` also measures the extraction time per page of each rule language, runs regexes with the
  flags of the experiments and writes the results table. The records of 1.0.3 remain in that release.

## 1.0.3 — 2026-10

- Ground-truth approval page: the per-field column shows rule agreement (share of annotator pairs that wrote the
  same normalized rule) and is now labeled so; Fleiss' κ and Krippendorff's α are in Reports → Annotation & GT.
- `metrics.score_selector` labels a score ≥ 0.9 as `MATCH`, as the experiments do (it returned `PARTIAL`).
- Experiment group, cross check: the per-field and per-layout cards no longer cut off the GT column.
- Interface and manifest use American spelling ("generalization"), as the documentation does.
- `paper/annotation_study`: records of the LLM experiments reported in the paper (configurations, prompts,
  generated rules, per-page scores), their manifest, and `analyze_rules.py`, which reproduces the rule analysis.
- README: the Python example scores rules with the functions the experiments use and runs on the demo data;
  the replay backend and the agreement module are documented.

## 1.0.2 — 2026-10

- Reports → Annotation & GT: content-level inter-annotator agreement on request — Krippendorff's α per field on the
  values each annotator's rule extracts from all ground-truth pages, next to rule-level Fleiss' κ and the share of
  identical rules; per annotator pair and per layout; per rule language; exportable as CSV / LaTeX / Markdown / PNG.
- The computation lives in `webrulebench.evaluation.agreement`; `paper/annotation_study/analyze.py` uses the same
  function (results unchanged).

## 1.0.1 — 2026-10

- Source code moved to `src/webrulebench/` (src layout); `pip install`, the `webrulebench` command and
  `./run.sh` / `./run_demo.sh` work as before.
- Fix: exporting a ground truth with a legacy list-valued rule no longer fails.
- Annotation study outputs label the annotators A1–A3; its data are archived on Zenodo
  (doi:10.5281/zenodo.23143117, HTML pages on request: doi:10.5281/zenodo.23143325).
- Documentation: Zenodo DOI, `demo/README.md`, corrected module paths.

## 1.0.0 — 2026-10

First public release (SoftwareX submission).

- Web application with six sections — data collection, templates & prompts, annotation, ground-truth
  approval, LLM evaluation, reports & export — and settings for LLM backends and users; English and
  Turkish interface.
- Multi-annotator rule collection in CSS, XPath (suggested from CSS) and regex (generated from CSS with an
  extended REGEXN); ground-truth approval with rule-level agreement (normalized rules, Fleiss' κ over
  layouts) and content-level scores (ROUGE / Jaccard / exact match; Krippendorff's α in the study script).
- Layout-based LLM experiments: one LLM call per layout, rules scored on every ground-truth page,
  sample-page vs. other-page scores, comparative experiments, cross-check, quick test, resume.
- LLM backend registry: Ollama, Anthropic, Gemini, OpenAI-compatible endpoints and a `replay` backend.
- Reports with CSV / LaTeX / Markdown tables and PNG charts; JSONL / CSV / HuggingFace export with a
  dataset card; reproducibility manifest.
- Token-based users with salted hashes, roles and an audit log.
- Reviewer demo (`webrulebench demo`, `./run_demo.sh`, Dockerfile) with synthetic sites and recorded LLM
  responses; code and data separated (`data/`, `webrulebench/defaults/`, `WRB_DATA_DIR`).
- Annotation study scripts (`paper/annotation_study/`).
