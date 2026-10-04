# Changelog

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
