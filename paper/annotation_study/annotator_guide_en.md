# Inter-annotator agreement study — Annotator guide

*English translation of the guide given to the annotators. The Turkish original, which the annotators used, is
[annotator_guide.md](annotator_guide.md); where the two differ, the original is what the annotators read.*

In this study, the extraction rules that several annotators write **independently of each other** for the same page
layouts are compared. Agreement is measured with Fleiss' κ (rule level) and content similarity (ROUGE / Jaccard)
and reported in the SoftwareX paper. For the results to be meaningful, **independence** is the most important rule.

## 1. Scope: 10 sites, the "Article 1" layout of each

The layouts are defined and the pages are assigned to them; you do not need to create layouts or assign pages. For
each layout you will write and save **your own rules**.

Selection criterion: among the 70 "Article 1" layouts that have an approved GT and an existing annotator's rules,
the **10 layouts with the most GT pages** (ties in alphabetical order; the selection is in `sample.json`). This way
the rules of each layout are tested on many pages.

| # | Site | Layout | Country | Language | GT pages |
|---|---|---|---|---|---|
| 1 | 525.az | layout-1 · Article 1 | Azerbaijan | az | 49 |
| 2 | abante.com.ph | layout-1 · Article 1 | Philippines | tl | 45 |
| 3 | akipress.com | layout-1 · Article 1 | Kyrgyzstan | en | 44 |
| 4 | alayam.com | layout-1 · Article 1 | Bahrain | ar | 42 |
| 5 | 20minutos.es | layout-2 · Article 1 | Spain | es | 41 |
| 6 | abendzeitung.de | layout-1 · Article 1 | Germany | de | 41 |
| 7 | aljazeera.com | layout-2 · Article 1 | Qatar | en | 41 |
| 8 | 24chasa.bg | layout-1 · Article 1 | Bulgaria | bg | 40 |
| 9 | adevarul.ro | layout-1 · Article 1 | Romania | ro | 40 |
| 10 | agenciabrasil.ebc.com.br | layout-2 · Article 1 | Brazil | pt | 40 |

Estimated time: 10–15 minutes per layout, 2–2.5 hours in total. You can work in any order and over several sessions.
Work only on these layouts; you do not need to write rules for the other layouts of a site (listing etc.).

## 2. Independence rules (important)

- Do not use the **"👤 Copy from another user"** button (it copies another annotator's rules).
- Until the study is finished, do not open the **Ground Truth Approval** section or the **Reports → Annotation & GT**
  tab (they show the other annotators' rules and the agreement).
- Do not discuss your rules with anyone; where you are unsure, decide yourself according to this guide and take a note.

## 3. How to do it

1. Log in (the user name and token are sent to you separately). You can switch the language to **TR** at the top right.
2. Open the site in the **Annotation** section; select a page assigned to the layout at the top (the layout panel
   shows the page counts).
3. Open the layout and, in the **My annotation** tab, write the rule for each field:
   - **CSS** is required. You can type it or select it by clicking on the page.
   - **XPath** and **Regex** are optional; you can leave them empty in this study (the comparison uses CSS).
4. Try each rule with **Test**. Before saving, check that the rules give the correct content on **at least 3
   different pages** of the layout: by selecting another page at the top, or in the **⚡ Bulk page assignment** window
   with **Rules: My rules** selected and **Test** (save your rules first). Do not use the **Ground truth** option in this
   window — it shows the results of the existing GT rules and breaks independence. As the pages are already
   assigned, you do not need to assign them; if you like, you can confirm the pages you checked with your own rules
   at once with **✓ Assign selected** (the assignment is written only to your annotation file).
5. **💾 Save**.

## 4. Fields and decision rules

**General**
- A rule must work on **all pages** of the layout: avoid article-specific ids/classes (`#post-12345`,
  `.article-98765`), position-based selectors (`:nth-child(7)`) and classes that look like random hashes
  (`.sc-f98b1ad2-0`, `.css-1x2y3z`).
- Prefer short, readable selectors: first a meaningful **id**, then a meaningful **class**, then a `data-*`
  attribute, and the tag structure last.
- If the field is not on the page, **leave it empty** (do not force a selector).
- If several elements are possible, choose the one that belongs to the **main content** of the article (not the
  sidebar, a "related news" box or an advertisement).

**Article (news page)**

| Field | What to select | Note |
|---|---|---|
| `title` * | The main headline of the article | Usually `h1`; not the general name of the site |
| `body` * | The container with the whole article text | The smallest element that contains the paragraphs; try to leave out share/comment/ad blocks |
| `author` | Name(s) of the author(s) | The name only; a label such as "By:" may be included |
| `date` | Publication date | The publication date, not the update date (the `time` element if there is one) |
| `category` | Category / section name | Usually the breadcrumb or the label above the headline |
| `images` | The main image(s) of the article | `img` elements; not logos, ads or the author's photo. There can be several images |
| `images_caption` | Image caption | `figcaption` etc. |
| `related_links` | "Related news" links in the article | `a` elements |
| `summary` | Lead / summary paragraph | The highlighted introductory text below the headline |
| `tags` | Tags / keywords | Usually the tag list at the end of the page |

(* required field)

You can write comma-separated alternative selectors (`h1.title, h1.headline`); for single-valued fields the **first**
alternative that matches on the page is used.

## 5. Taking notes

Take a short note for each layout (e.g. "the date appears in two places, I chose the publication date", "no
summary"). The notes will be used to interpret the causes of disagreements (an ambiguity of the guide or a real
difference of interpretation). You can send your notes in a `notes_<user>.md` file in this folder or by e-mail;
please also write down the total time you spent.

## 6. To be aware of (for the researcher)

- The other rules being compared (A1) were written **before** this guide; this should be stated as a limitation in
  the paper.
- Agreement is monitored in the Reports → Annotation & GT tab (κ by field, fields with low agreement) and on the GT
  Approval page of each layout (K1/K2).
