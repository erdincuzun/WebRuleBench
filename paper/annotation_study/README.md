# Annotation study and LLM experiments (paper, Section 3)

Material behind the illustrative examples of the WebRuleBench paper: ten article layouts (ten news sites,
nine languages, 423 ground-truth pages), annotated independently by three annotators (A1–A3) and used for
LLM experiments with five local models.

| File | Content |
|---|---|
| `annotator_guide_en.md` | the guideline that defines the fields (English translation) |
| `annotator_guide.md` | the same guideline in Turkish, as given to the annotators |
| `sample.json` | the ten layouts (top ten "Article 1" layouts by number of ground-truth pages) |
| `analyze.py` | inter-annotator agreement: Fleiss' κ on normalized rules, Krippendorff's α on extracted content (Table 3) |
| `make_figures.py` | the agreement figure and the LaTeX table |
| `analyze_rules.py` | analysis of the LLM rules (Section 3.2): lost points by label, XPath class tests, regex on skeleton vs. raw page, extraction time per page; writes the results table |
| `results/agreement.json`, `results/per_*.csv` | agreement results |
| `results/fig_agreement.*`, `results/table_agreement.tex` | figure and table |
| `results/experiments_submitted/*.json` | the eight LLM experiment records as run with WebRuleBench 1.0.4 (one comparison group): configuration, prompts, generated rules, tokens, model digest, and the per-page scores against the first reference |
| `rescore.py` | rescores the saved rules of these records against the reviewed reference (no LLM call) |
| `reference_check.py` | agreement of the reviewed reference with the annotators, and over-extraction on fields absent from a site (Section 3) |
| `results/experiments/*.json` | the same records with the rescored per-page scores and summaries; `rescored.submitted_summary` keeps the first summary |
| `results/llm_experiments.csv` | one row per experiment: mean, sample-page and other-page scores, tokens, time, per-field means (rescored) |
| `results/coverage.csv` | scored page–field pairs by layout and field; for the others the reason (no rule by any annotator, left out by the administrator, rule returns no value on the page) and the source of each approved rule |
| `results/sample_gap.csv` | sample page vs. the other pages, per experiment and layout |
| `results/rescore.json` | summary of the rescoring: first vs. rescored means, coverage, distribution of the sample-page differences |
| `results/manifest_llm_experiments.json` | reproducibility manifest of the original run, as exported by the reports section |
| `results/rule_analysis.json`, `results/table_llm.tex` | output of `analyze_rules.py` and the results table |

## Data

The rules of the three annotators, the approved ground truth and the page list are archived on Zenodo under
CC BY 4.0: version 1.1 with the reviewed reference and the experiment records (doi:[10.5281/zenodo.24175285](https://doi.org/10.5281/zenodo.24175285)), version 1.0 with the reference as first approved (doi:[10.5281/zenodo.23143117](https://doi.org/10.5281/zenodo.23143117)); the archived HTML pages are
available on request for research use (doi:[10.5281/zenodo.23143325](https://doi.org/10.5281/zenodo.23143325)),
since their content is copyrighted by the publishers. Both use the WebRuleBench data-folder layout.

## Reproducing

There are three levels:

1. **Demo, no data and no LLM.** `webrulebench demo` builds a synthetic study (three sites, three annotators,
   recorded LLM responses) in which every step of the workflow can be run; see the main README.
2. **The published numbers, without the HTML pages.** The records and results in `results/` (and in the open data
   record) contain every number of Tables 3 and 4 and of Section 3: per-page scores and summaries of each experiment,
   `coverage.csv`, `sample_gap.csv`, `rescore.json`, `ceiling_baseline.json`, `agreement.json`. They can be read and
   aggregated without the pages; the experiment records can also be opened in the web application.
3. **Recomputing them, with the HTML pages** (available on request): the scripts below run the rules on the pages
   again and rewrite `results/` with identical values.

```bash
pip install -e .                                   # from the repository root
export WRB_DATA_DIR=<folder with the open record and the extracted html.zip>
python paper/annotation_study/analyze.py --annotators A1 A2 A3   # agreement (Table 3)
python paper/annotation_study/make_figures.py                    # figure and LaTeX table (needs .[figures])
python paper/annotation_study/rescore.py                         # rescore the saved LLM rules (Table 4 scores, coverage)
python paper/annotation_study/reference_check.py                 # reference vs. annotators, over-extraction (Section 3)
python paper/annotation_study/analyze_rules.py                   # rule analysis (Section 3.2), writes the results table
```

Re-running an LLM experiment itself needs a local Ollama server with the model of the record (digests in the records).

## Reference used for the scores

The first reference had been approved from the rules of one annotator before the other two annotated. The study
and a page-by-page comparison of the output of the three annotators' rules showed fields that were missing from
it, two category rules that selected the tag list, and rules that returned more than the field. The administrator
reviewed these cases; every change and its reason is listed in `paper/annotation_study/reference_review.md`. The saved LLM rules
were then rescored. The order of the eight configurations did not change; the means changed by −2.8 to +2.2 points.

The experiment records can also be copied into `$WRB_DATA_DIR/experiments/` and opened in the web application
(LLM Evaluation and Reports); re-running an experiment needs a local Ollama server with the model of the record.

## Settings of the LLM experiments

- Ollama with temperature 0, seed 42, at most 512 output tokens and a 16,384-token context; one call per layout on
  the skeleton of the layout's first ground-truth page (whitelist cleaning); the models are qwen2.5-coder 14B and
  7B, ministral-3 8B, gemma4 and phi4 14B (digests in the records).
- gemma4 is a thinking model: it was run with thinking disabled (`think = false` in its model parameters, recorded
  in the experiment); with thinking on, it spends the 512 output tokens on thinking and returns no rules.
- CSS rules are scored as the model wrote them (CSS repair off, the default since 1.0.4).
- The records of WebRuleBench 1.0.3 (five configurations, CSS rules repaired) remain in that release.
