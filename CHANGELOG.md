# Changelog

## Unreleased

- Documentation: `docs/custom_template.md`, a worked example of a template for another page type (shop product
  pages with discount and shipping): planning the fields, creating the template in the interface or through the
  API, the automatic prompt, annotation, approval, an experiment and scoring a rule from Python. A test runs the
  example.
- Data collection: before a page is downloaded, the site's robots.txt is checked (user agents `WebRuleBench`
  and `*`; read once per site and cached) and a page that is not allowed is not downloaded; requests to one
  site are spaced by its `Crawl-delay` or a minimum pause (1 s by default). An administrator can switch the
  check off or change the pause on the Data Collection page (`dataset/download_settings.json`); the change is
  written to the audit log. Before, pages were requested without looking at robots.txt and without a pause.
- CSS selector lists are split only at top-level commas. A selector with a comma inside parentheses, square
  brackets or quotes — `article :is(h1, h2).headline`, `:not(.a, .b)`, `[title="a, b"]` — was split there and
  matched nothing; it now runs as one selector in annotation validation, scoring, the regex generator, the
  XPath translation and the MCP server, which all use one function (`rule_utils.split_selector_list`).
- Rule agreement: the order of the comma-separated alternatives of a CSS rule is kept when rules are
  normalized, except for merged fields. Without merging the first alternative that matches is used, so
  `h1, h2` and `h2, h1` can extract different text and are no longer counted as the same rule; for merged
  fields all alternatives are combined and the order is still ignored. The browser copy does the same.
- Experiments run and resume with the backend settings stored when they were created (API type, URL,
  generation parameters, timeout — `backend_snapshot`). Before, the call read the current settings, so editing
  a backend after creating an experiment changed the request while the record kept the old values. API keys
  are not stored and are still read from the environment.
- Security: downloaded pages are served with a `Content-Security-Policy` that blocks their scripts, inline
  event handlers and `javascript:` links, and every preview frame (page viewer, bulk-import link picker,
  ground-truth approval) is sandboxed; highlighting and picking still work. The viewer's **JS enabled** switch
  now runs a page's scripts in an opaque origin of its own (`sandbox allow-scripts`, no `allow-same-origin`)
  instead of the application's origin; picking is not available in that mode. The page route also refuses
  paths outside the dataset folder. The README documents the deployment assumptions.
- Ground-truth approval: a field that an annotator wrote a rule for but that is not written to the ground truth
  is marked on the approval page (⚠), and saving asks the administrator to confirm that it is left out. The
  decision is stored with the layout (`excluded_fields`: who, when, an optional reason and the annotators who
  wrote a rule) and the server refuses a save that leaves such a field out without one, so a field can no longer
  be missing from the reference by oversight. The layout list shows the number of fields without a decision.
- Ground-truth approval: each rule shows on how many pages of the layout it returns a value (e.g. `10/45`), for
  the annotators' rules, the current ground truth and the rule to be saved. A rule is written on one page and
  approved for all of them; one that depends on something only some pages have now shows it instead of silently
  returning nothing elsewhere. Values are extracted as in the scoring of experiments.
- Ground-truth approval: clicking a field opens a panel under the table where the rule to save is edited at full
  width, the pages without a value are listed (click to preview) and a note on the decision can be written (✎);
  notes are stored with the layout (`field_notes`). The panel replaces the "To save" column of the table.
- Ground-truth approval: more room for the table — the page union opens from a link in the footer ("n of m pages
  selected") instead of taking a fixed part of the page, rule cells are narrower, and the bar between the table
  and the page preview can be dragged to resize them (remembered in the browser; double-click resets).
- Ground-truth approval: in an approved layout, a page that an annotator assigned but that is not in the ground
  truth is marked "new" in the page list and is no longer selected by default, so that saving does not add it
  unnoticed; the footer link says how many new pages there are. Pages of the ground truth that no annotator
  assigned are now listed too (they were dropped on save before).
- Ground-truth approval: the source of each approved rule is stored with the layout (`rule_sources`: the
  annotators who wrote the same rule, or none when the administrator wrote or edited it on the approval page);
  the layout list shows the number of such rules (✎ n).
- LLM evaluation: new experiment option **Given to the LLM** — the skeleton (default, as before) or the HTML of
  the cleaned page itself (`skeleton = none`), with an automatic prompt that says so; the new cleaning strategy
  `none` leaves the page unchanged, so that the full page can be given to models with a large context window. The
  option is saved with the experiment and shown in its views; experiments without it run with the skeleton, and
  the skeleton prompts are unchanged.
- LLM evaluation: an input the server silently shortened because it did not fit the model's context window
  (Ollama keeps half of the window) is detected from the reported input tokens; the layout is marked as an error
  with the reason and left out of the means, as a failed call is. Its scores remain in the record.
- Regex rules run with a time limit (5 s per page): a pattern that backtracks catastrophically no longer stalls
  an experiment. It runs with Python's `re` as before, in a helper process that is restarted when the limit is
  exceeded; the page then counts as no match and the pattern is listed in the layout record (`regex_timeouts`).
- LLM evaluation: the provider's stop reason is saved with each layout's call (`finish_reason`: stop, length,
  max_tokens …); a response that could not be read and stopped at the output limit says so in its error, with
  the number of output tokens.
- LLM Models: per-backend call timeout (seconds; 180 if empty), for long inputs and thinking models. It is not
  sent to the model and is saved in the experiment's backend snapshot. It limits the whole call: a server that
  keeps the connection open without answering, or a request whose response never starts (e.g. after the computer
  slept), no longer holds an experiment indefinitely.
- LLM Models: the `think` setting also applies to OpenAI-compatible backends, sent as `thinking` only when set
  (e.g. EVREN LLM API, whose models think by default and share `max_tokens` between thinking and the answer). A
  response whose output tokens all went to reasoning says so in its error, as with Ollama.
- LLM calls: HTTP 429 (rate or quota limit) and 503 (server or model busy) are retried up to 5 times. The wait
  doubles each time (10, 20, 40, 60, 60 s); a longer wait given by the provider (`Retry-After`, or EVREN's
  `resets_at`) is used instead. The wait is not counted in the LLM time, and the number of retries is saved with
  each layout's call (`retries`).
- Title and descriptions (CITATION.cff, package metadata, README): "human-annotated ground truth"; a single
  annotator is enough, and with several the tool measures rule- and content-level agreement.
- The demo is called simply "demo" (it is meant for anyone trying the tool, not only reviewers); README test count
  updated.

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
