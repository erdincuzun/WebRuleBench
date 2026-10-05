# Changelog

## Unreleased

- Ground-truth approval page: the per-field column shows rule agreement (share of annotator pairs that wrote the
  same normalized rule) and is now labeled so; Fleiss' κ and Krippendorff's α are in Reports → Annotation & GT.
- `metrics.score_selector` labels a score ≥ 0.9 as `MATCH`, as the experiments do (it returned `PARTIAL`).
- Experiment group, cross check: the per-field and per-layout cards no longer cut off the GT column.
- Interface and manifest use American spelling ("generalization"), as the documentation does.
- `paper/annotation_study`: records of the LLM experiments reported in the paper (configurations, prompts,
  generated rules, per-page scores), their manifest, and `analyze_rules.py`, which reproduces the rule analysis.

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
