# Annotation study and LLM experiments (paper, Section 3)

Material behind the illustrative examples of the WebRuleBench paper: ten article layouts (ten news sites,
nine languages, 423 ground-truth pages), annotated independently by three annotators (A1–A3) and used for
LLM experiments with five local models.

| File | Content |
|---|---|
| `annotator_guide.md` | the guideline that defines the fields |
| `sample.json` | the ten layouts (top ten "Article 1" layouts by number of ground-truth pages) |
| `analyze.py` | inter-annotator agreement: Fleiss' κ on normalized rules, Krippendorff's α on extracted content (Table 3) |
| `make_figures.py` | the agreement figure and the LaTeX table |
| `analyze_rules.py` | analysis of the LLM rules (Section 3.2): lost points by label, XPath class tests, regex on skeleton vs. raw page, extraction time per page; writes the results table |
| `results/agreement.json`, `results/per_*.csv` | agreement results |
| `results/fig_agreement.*`, `results/table_agreement.tex` | figure and table |
| `results/experiments/*.json` | the eight LLM experiment records, one comparison group run with WebRuleBench 1.0.4: configuration, prompts, generated rules, per-page scores, tokens and model digest |
| `results/llm_experiments.csv` | one row per experiment: mean, sample-page and other-page scores, tokens, time, per-field means |
| `results/manifest_llm_experiments.json` | reproducibility manifest of the experiments, as exported by the reports section |
| `results/rule_analysis.json`, `results/table_llm.tex` | output of `analyze_rules.py` and the results table |

## Data

The rules of the three annotators, the approved ground truth and the page list are archived on Zenodo under
CC BY 4.0 (doi:[10.5281/zenodo.23143117](https://doi.org/10.5281/zenodo.23143117)); the archived HTML pages are
available on request for research use (doi:[10.5281/zenodo.23143325](https://doi.org/10.5281/zenodo.23143325)),
since their content is copyrighted by the publishers. Both use the WebRuleBench data-folder layout.

## Reproducing

```bash
pip install -e .                                   # from the repository root
export WRB_DATA_DIR=<folder with the open record and the extracted html.zip>
python paper/annotation_study/analyze.py --annotators A1 A2 A3   # agreement (Table 3)
python paper/annotation_study/make_figures.py                    # figure and LaTeX table (needs .[figures])
python paper/annotation_study/analyze_rules.py                   # rule analysis (Section 3.2)
```

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
