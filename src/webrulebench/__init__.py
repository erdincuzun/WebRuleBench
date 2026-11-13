"""
WebRuleBench — benchmarking LLM-generated web extraction rules (CSS, XPath, regex)
against human-annotated ground truth (one or more annotators).

  pipeline/     page → cleaning → skeleton → LLM; backend registry; prompts
  rules/        rule execution, CSS → regex (REGEXN), rule agreement statistics
  evaluation/   metrics, layout-based experiments, reports
  webapp/       Flask web application (core, routes, templates, static, i18n)
  demo/         self-contained demo (synthetic pages, demo data folder)
  cli.py        `webrulebench serve | demo | users`
"""

__version__ = "1.1.2"   # single source of the version: pyproject.toml, --version and the manifest read it
