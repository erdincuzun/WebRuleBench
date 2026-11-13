# WebRuleBench — Web Application User Guide

Flask web application for collecting and approving ground truth and for evaluating LLMs. The **?** help of each section explains its formulas and rules.

---

## Installation and running

Requirements: Python 3.10+.

```bash
# in the project root
pip install -r requirements.txt

# first admin account (the token is printed only once)
webrulebench users create-admin <user>

# run
./run.sh                      # or: webrulebench serve
```

Open in the browser: **http://127.0.0.1:5001** — log in with a user name and token; the login is remembered in the browser.
The interface is in English by default; the **EN / TR** button in the top menu switches to Turkish (the choice is remembered).

Other users are added on the **👥 Users** page of the application (admin) or from the command line:

```bash
webrulebench users create <user> [--role user|admin]
webrulebench users reset-token <user>     # if the token is forgotten
webrulebench users list
```

---

## Workflow — six sections

The home page shows a card for each section; the top menu is shared by every page. The **?** in the header of each page opens the help of that section. Actions marked 🔒 are for admins only.

### 1. Data Collection
- Site list; filter by country ("⚠ Missing info" shows the sites without country information).
- 🔒 Add / edit a site: name, URL, country (from the list or a new country — ISO code, continent, language), note.
- 🔒 Add, re-download and delete pages; **⚡ Bulk add pages**: extracts the links of a listing page with a CSS selector and downloads the selected ones.
- Page types are given by the file name: `homepage.html`, `listing_NNN.html`, `article_NNN.html`.

### 2. Templates & Prompts
- Templates (`article`, `listing`, `product`): fields, type (`text`, `date`, `image`, `url`, `list`, `price`), metric (`rouge`, `jaccard`, `exact_match`), required flag, merging (`merge`). 🔒 Editing.
- **Prompts**: for each template and rule language (CSS / XPath / Regex), an automatic prompt (cannot be changed) and the variants added by users. Anyone can add a variant; only its owner or an admin can edit it. A user prompt must contain `{skeleton}`.

### 3. Annotation
Select a site → the work screen opens (go back with **← Site list**).

1. Select a page at the top (the page opens in the preview).
2. Assign the page to a **layout**. A layout is a group of pages with the same HTML structure (e.g. standard news, column, gallery); one rule set is applied to all of its pages. If no suitable layout exists, 🔒 an admin creates a new layout from a template. Use **Skip this page** for broken / empty pages.
3. Write the rule for each field of the layout — three tabs:
   - **CSS**: type it or select it by clicking on the page. See the result with **Test**.
   - **XPath**: generated automatically from the CSS (a candidate that gives the same text as the CSS on the page is suggested); can be edited by hand.
   - **Regex**: expert input; can be generated from the CSS on request (REGEXN — checked on several pages of the layout).
4. **💾 Save** — the rules are written only to your own annotation file (`annotations/<site>/<user>.json`).
5. **⚡ Bulk page assignment**: test the rules of the layout on all pages that can be assigned and assign the suitable ones at once with **✓ Assign selected**.

CSS examples:

```css
h1.article-title           → by class
h1#main-title              → by id
div.content p              → nested element
div[data-type="article"]   → attribute value
div[class*="content"]      → class contains "content"
h2 a, h3 a                 → alternatives (comma-separated)
```

Tips: assign pages with a similar structure to the same layout; use a separate layout for listing pages; avoid ids/classes that contain an article-specific number (they do not hold on other pages).

### 4. Ground Truth Approval
Site → layout → compile page. The rules of all annotators side by side; rule languages in separate tabs.
- **Layer 1 (rule agreement)**: per field, the share of annotator pairs that wrote the same (normalized) rule, and the most frequently written rule as the suggestion (✓ ≥ 0.6, ~ 0.4–0.6, ! < 0.4). Fleiss κ and Krippendorff α: **Reports → Annotation & GT**.
- **Layer 2 (K2)**: EM / Jaccard / ROUGE scores of the text extracted by each rule on the sample page; the highest ROUGE-L is suggested.
- 🔒 The admin selects which rule languages are included in the GT, applies the suggestions or changes them by hand, and writes them to `ground_truth/approved/<site>.json` with **💾 Save GT**. Other users see the page read-only.
- Status on the list pages: **approved**, **has updates** (annotations changed after approval), **no GT**.

### 5. LLM Evaluation
- **⚡ Quick test**: a single layout, not saved — for trying out prompts.
- **New experiment / ⚖ Comparative experiment**: model(s), rule language(s) (CSS, XPath, Regex, LLM CSS → REGEXN), cleaning strategy, prompt per template, sample page selection and layout scope. One LLM call is made per layout; the rules are scored on all GT pages of the layout (sample page and other pages separately).
- Experiment details, group page (ranking, heat map, per layout, **cross-check**) and pairwise comparison. An experiment can be cancelled and resumed where it stopped.
- **⚙ LLM Models**: backends, models installed in Ollama, model parameters, connection test. 🔒 Editing; the API key is written to `data/.env`.

### 6. Reports & Export
Tabs: 📦 Dataset · ✍ Annotation & GT · 🤖 LLM results · ⬇ Export · 🧾 Audit log (🔒).
- **Annotation & GT**: user progress, GT status, per-field Fleiss κ, and content-level agreement with **▶ Compute**: each annotator's rule is run on all GT pages of the layouts with ≥2 annotators; per-field Krippendorff α, annotator pairs and per-layout agreement (the result is kept until the files change).
- Every table can be exported as **CSV / LaTeX / MD**, every chart as **PNG / CSV**.
- Approved GT: JSONL, CSV, HuggingFace JSONL and a dataset card; a reproducibility manifest for experiments.

---

## Troubleshooting

- **Port in use**: start on another port: `WRB_PORT=5003 ./run.sh`.
- **Page looks empty in the preview**: some pages do not load in an iframe; open the file directly: `data/dataset/raw/<site>/article_001.html`.
- **Page cannot be downloaded**: for pages built with JavaScript, `playwright install chromium`.
- **LLM connection error**: **⚡ Test** in ⚙ LLM Models; for Ollama, is `ollama serve` running and is the model installed (`ollama list`)?
- **Admin token forgotten**: `webrulebench users reset-token <user>`.
