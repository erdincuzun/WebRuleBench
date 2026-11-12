# Worked example: a custom template for shop product pages

WebRuleBench ships with three templates — `article`, `listing` and `product` — but the fields to extract are
not fixed in the code. A **template** defines the fields of a page type: their names, how a value is read
from the page and how it is scored. Every layout of a site uses one template, and the automatic prompt for the
LLM is generated from it. This example defines a template for shop product pages that also records the
discount and the shipping cost, and follows it through annotation, approval and an LLM experiment.

The steps work in the web application (no code) or through the JSON API; both are shown.

## 1. Plan the fields

For each field, decide three things:

| Setting | Values | What it does |
|---|---|---|
| **Type** | `text`, `date`, `price`, `list`, `url`, `image` | `url` reads the `href` of the selected element, `image` the `src`; every other type reads the element's text. |
| **Metric** | `rouge`, `exact_match`, `jaccard` | `rouge`: word overlap (ROUGE-1 F1), for running text. `exact_match`: the same text after whitespace normalization, for short values such as a price. `jaccard`: overlap of two sets of values, for lists such as images or tags. |
| **Merge** | on / off | Off: of the comma-separated alternatives of a CSS rule (`h1.title, h1`), the first that matches is used. On: all alternatives are applied and their values combined — useful when the values of a field are in several places, for example images. |

**Required** marks a field that every page of this type has; it is shown to the LLM as `(required)`.
The **description** of a field is the main input of the automatic prompt, so write it as an instruction:
what the value is and what it is not.

For a shop product page:

| Field | Type | Metric | Merge | Required | Description |
|---|---|---|---|---|---|
| `name` | text | rouge | off | yes | Product name as shown in the main heading |
| `price` | price | exact_match | off | yes | Current selling price including the currency, without the old price |
| `old_price` | price | exact_match | off | no | Price before the discount, if a discount is shown |
| `discount` | text | exact_match | off | no | Discount as shown on the page, e.g. "-20%" |
| `shipping` | text | rouge | off | no | Shipping cost or delivery note next to the price |
| `description` | text | rouge | off | no | Product description text, without reviews |
| `images` | image | jaccard | on | no | Product images in the gallery, not thumbnails of other products |

## 2. Create the template

**In the application** (administrator): *Templates & Prompts* → **+ New template** → enter the id `shop_product`,
then add the fields above on the editor page and save.

**Through the API**, with a logged-in administrator session (`POST /login` with username and token first):

```json
POST /api/templates
{
  "id": "shop_product",
  "name": "Shop Product Page",
  "description": "Product detail page of an online shop",
  "page_type": "article",
  "icon": "🛒",
  "fields": {
    "name":        {"label": "Name",        "type": "text",  "metric": "rouge",       "required": true,
                    "description": "Product name as shown in the main heading"},
    "price":       {"label": "Price",       "type": "price", "metric": "exact_match", "required": true,
                    "description": "Current selling price including the currency, without the old price"},
    "old_price":   {"label": "Old price",   "type": "price", "metric": "exact_match", "required": false,
                    "description": "Price before the discount, if a discount is shown"},
    "discount":    {"label": "Discount",    "type": "text",  "metric": "exact_match", "required": false,
                    "description": "Discount as shown on the page, e.g. \"-20%\""},
    "shipping":    {"label": "Shipping",    "type": "text",  "metric": "rouge",       "required": false,
                    "description": "Shipping cost or delivery note next to the price"},
    "description": {"label": "Description", "type": "text",  "metric": "rouge",       "required": false,
                    "description": "Product description text, without reviews"},
    "images":      {"label": "Images",      "type": "image", "metric": "jaccard",     "required": false, "merge": true,
                    "description": "Product images in the gallery, not thumbnails of other products"}
  }
}
```

Templates are stored in `layout_templates.json` of the data folder, so they can also be copied between
installations as a file.

## 3. Check the automatic prompt

*Templates & Prompts* → **💬 Prompt** on the new template (or `GET /api/templates/shop_product/prompts`) shows the
prompt generated for each rule language. For CSS it begins:

```
You extract data from web pages. You are given an HTML skeleton of a web page of type "Shop Product Page"
(Product detail page of an online shop): tag names, classes and ids, ... write one CSS selector for each field below.

Fields (use null if a field is not on the page):
- name: Product name as shown in the main heading (required)
- price: Current selling price including the currency, without the old price (required)
- old_price: Price before the discount, if a discount is shown
...
```

The automatic prompt cannot be edited; it is the fixed baseline of the template. To try another wording, add a
named prompt variant on the same page and select it in an experiment.

## 4. Collect pages and define a layout

1. *Data Collection* → **+ New site** with the shop's address. Download product pages one by one, or use
   **⚡ Bulk add** to extract product links from a category page with a CSS selector. The site's robots.txt is
   checked before each download.
2. In the annotation screen, create a **New layout** for the product pages of the site and choose the template
   `shop_product`. Mark the fields that some products do not have (`old_price`, `discount`) as optional for
   this layout.
3. Write a CSS rule for each field (click the element or type the rule) and check it with **Test**. Then use the
   bulk test to apply the rules to the other downloaded pages and assign the pages on which they work.

If several annotators take part, each writes rules independently in their own annotation file.

## 5. Approve the ground truth

*Ground Truth Approval* → the site → **⚙ Compile** on the layout. The page shows the annotators' rules side by
side, how many pages each rule returns a value on, and — with several annotators — the agreement on the rules
and on the extracted content. Select one rule per field (or write one) and save. A field that an annotator wrote
a rule for can only be left out with a recorded decision.

## 6. Run an experiment

*LLM Evaluation* → **⚡ Quick test** tries one model on one layout with the automatic prompt; a full experiment
or a comparison group runs several models and rule languages on all layouts of the template. The LLM sees the
skeleton of one sample page per layout; its rules are then applied to every ground-truth page and scored with the
metric of each field. The results can be compared by field, which shows, for example, whether models confuse
`price` with `old_price`.

## Scoring a rule from Python

The functions the experiments use can be called directly, for example to check a rule before annotating:

```python
from bs4 import BeautifulSoup
from webrulebench.evaluation.experiments import rule_values, score_field

html = """<div class="product"><h1>Trail Shoe</h1>
  <span class="price-old">€120.00</span><span class="price-now">€96.00</span>
  <span class="badge">-20%</span></div>"""
soup = BeautifulSoup(html, "html.parser")

reference = rule_values(html, soup, "span.price-now", "css", kind="text", merge=False)
generated = rule_values(html, soup, "//span[@class='price-now']", "xpath", kind="text", merge=False)
print(score_field(reference, generated, "exact_match"))      # (1.0, 'MATCH')

wrong = rule_values(html, soup, "div.product span", "css", kind="text", merge=False)
print(score_field(reference, wrong, "exact_match"))          # (0.0, 'WRONG') — also took the old price and the badge
```

`kind` is `"image"` or `"url"` for fields of those types and `"text"` otherwise; `merge` is the field's merge
setting. A field whose reference has no value on a page is not scored (`(None, 'NO_GT')`).

## Notes

- Changing or deleting a field of a template that layouts already use can invalidate their rules; add a new
  template instead when the field set changes substantially.
- Choose `exact_match` only for values that are written the same way on every page. For a price shown as
  "96,00 €" on one page and "€96.00" on another, the annotated rules decide what the reference is; the metric
  does not normalize currencies.
- The tests in `tests/test_custom_template.py` run this example: they create the template through the API,
  check its automatic prompt and run the scoring snippet.
