# Review of the reference after the annotation study (revision R1)

The reference used in the submitted paper was approved in May 2026 from the rules of annotator A1, before
annotators A2 and A3 wrote their rules (October 2026). The study showed fields for which A2 or A3 wrote a
rule while the reference had none, and pages on which the reference rule returned nothing while their rules
returned a value. The administrator reviewed each case on the approval page. This file records every
decision and its reason. The reference as submitted is kept in `data/ground_truth/approved_R0/`.

Source of the approved rules after the review (stored in each layout as `rule_sources`): of the 76 approved rules
of the ten layouts, 69 are the rule of at least one annotator and 7 were written or edited by the administrator
(abante.com.ph: related_links; abante.com.ph: tags; akipress.com: date; akipress.com: title; aljazeera.com: date; 24chasa.bg: images_caption; adevarul.ro: author). No field with an annotator rule is left without a decision.

Effect on the experiments (saved LLM rules rescored, no LLM call): scored page–field pairs 2,689 → 2,991 of 4,230;
the mean of each configuration changes by −2.8 to +2.2 points and the order of the eight configurations is unchanged.

Status: `changed` (rule added or replaced) · `left out` (recorded in the layout as `excluded_fields`) ·
`unchanged` · `open` (not reviewed yet)

## Fields with an annotator rule but no reference rule

| Site | Field | Annotators | Decision | Reason |
|---|---|---|---|---|
| abante.com.ph | author | A3 | left out (2026-11-11) | The page shows no byline. "Abante News" (the rule of A3) is a sidebar heading that is the same on every page, next to "Una sa Balita" and "Popular sa ABANTE"; the author name is only in the meta tag of the page (`meta[name=author]`: three values on the 45 pages) and is not visible. A3's rule was first added and then removed on review. |
| abante.com.ph | category | A3 | changed — A3's rule added (2026-11-11) | The section shown above the article (NEWS, METRO, ENTERTAINMENT, VISMIN, SPORTS, LIFESTYLE); value on 45 of 45 pages. Missing from the first reference by oversight. |
| abante.com.ph | tags | none | changed — rule added by the administrator (2026-11-11) | Tags are listed next to the date ("Abante News Tags: …") on 30 of 45 pages; rule `span.elementor-post-info__terms-list a`. No annotator had marked this field; it was found during the review. |
| abante.com.ph | images | A1, A2, A3 | changed — the rule of A2/A3 selected instead of A1's (2026-11-11) | Same content: `div.elementor-widget-container > img` (A2, A3) and `.elementor-widget-theme-post-featured-image img` (A1) return the same image on all 45 pages. The reference values do not change. |
| alayam.com | author | A2 | left out (2026-11-12) | The page shows no author. The rule of A2 (XPath only) selects the label of the short-link box ("رابط مختصر"). |
| 20minutos.es | tags | A2, A3 | changed — A2's rule added (2026-11-12) | The tag list of the article, on all 41 pages (`ul.c-detail__tags__list > li > a`). Missing from the first reference by oversight. The category rule of the first reference is kept: it returns the section link (e.g. "Internacional"); A2 had selected the tag list and A3 the label of the article type ("Noticia") for category. |
| abendzeitung.de | tags | A3 | changed — A3's rule added (2026-11-12) | The topic list under the article ("Themen: …"), on 34 of 41 pages (`ul.start > li > a.btn`). In the first reference this list had been selected by the category rule. |
| abendzeitung.de | category | A1, A2, A3 | changed — the rule of A2/A3 replaces A1's (2026-11-12) | **The first rule was wrong.** `div.schlagwortliste a.btn` selected the topic list ("Themen"), i.e. the tags, on 34 pages and the login buttons ("Zum Login", "Hinzufügen") on the 7 pages without that list. The rule of A2 and A3, `ul.breadcrumb > li > a`, returns the section from the breadcrumb (e.g. "Startseite > Panorama"). The reference values of this field change on all 41 pages. |
| abendzeitung.de | images_caption | A1, A2, A3 | changed — the rule of A2/A3 replaces A1's (2026-11-12) | `span.bildtitel` returns the caption without the photo credit; the first rule (`figure > figcaption`) included the credit ("© …"). Mean similarity of the two outputs 0.88. |
| abendzeitung.de | author, date | A1, A2, A3 | changed — the rule of A2/A3 selected instead of A1's (2026-11-12) | Same content: `span.author` / `time` and A1's `section.artdetail_time span.author` / `section.artdetail_time time` return the same values on all 41 pages. The author value is the byline next to the date (a name, or an agency code such as "dpa", "AZ"); 5 pages show no byline. |
| adevarul.ro | tags | A2, A3 | changed — A2's rule added (2026-11-11) | Tags are listed under the article on 37 of 40 pages (`div.tags-list > a`). The field was missing from the first reference by oversight. A3's rule (`span.label`) selects other labels of the page and was not used. |
| agenciabrasil.ebc.com.br | tags | A2, A3 | changed — A2's rule added (2026-11-12) | The tag list under the article, on all 40 pages (`div.row-tags > a`). In the first reference this list had been selected by the category rule. |
| agenciabrasil.ebc.com.br | category | A1, A2, A3 | changed — A2's rule replaces A1's (2026-11-12) | **The first rule was wrong.** `div.rowflex a.tag` selected the tag list of the article. The rule of A2, `div.header-noticia > a.editoria`, returns the section shown above the headline (e.g. "Economia", "Geral"). The reference values of this field change on all 40 pages. |
| 24chasa.bg | images_caption | A3 | changed — rule edited by the administrator (2026-11-12) | The caption of the main image, on 33 of 40 pages: `figure.featured-image > figcaption`, the first alternative of A3's rule. The other alternatives of that rule returned the caption a second time. Missing from the first reference by oversight. |

## Pages on which the reference rule returns nothing but another annotator's rule returns a value

| Site | Field | Pages | Finding | Decision | Reason |
|---|---|---|---|---|---|
| abante.com.ph | related_links | 35 of 45 | The reference rule contained `article.category-metro` and matched only pages of the Metro section (10 of 45). The rules of A2 and A3 return 15–21 links per page, including a site-wide sidebar list. | changed — rule generalised (2026-11-11) | Each page has two lists of posts: a sidebar list under the heading "Una sa Balita" (9 posts, identical on all pages) and a list under the heading "Related News" (6 posts of the article's own section; 3 on News pages). The administrator defines related links as the links under "Related News"; A2 and A3 selected both lists. This is a difference in how the field is read, not an error, and the administrator's reading is kept. The first rule named the section class of the Metro pages and returned a value on those 10 pages only, although all 45 pages have the list. It was replaced by `div.elementor-widget-posts.elementor-posts--thumbnail-top article a[href]`, which selects the same list on all 45 pages and returns the same links as before on the 10 Metro pages. |
| adevarul.ro | author | 3 of 40 | The author is outside `header` on these pages; `div.authors > a` (A2, A3) returns the authors. | changed — rule written by the administrator (2026-11-11) | The author is shown twice on most pages: in the header and in a second byline. The first rule (`header div.authors a`) covered the header only and missed the 3 pages that have only the second byline. The rule of A2 and A3 (`div.authors > a`) finds the author on all 40 pages but returns the name twice on 37 of them, which would lower the score of a rule that extracts it once. The approved rule `div.authors:not(.metaFont) > a` selects the second byline: one author on each of the 40 pages, and the same value as the first rule on the 37 pages it covered. |
| abendzeitung.de | images | 4 of 41 | The article image is in another container on these pages; the rules of A2 and A3 return it (A3's rule also returns an author portrait on one page). | changed — A2's rule replaces A1's (2026-11-12) | `figure > div > picture > img` returns all images of the article: the main image and the images inside the text. The first rule (`div#fancyExtBild figure img`) covered the main image container only and returned nothing on 4 pages. Same output on 24 pages; on 17 pages the new rule returns more images. A3's rule was not used because it also returns author portraits. |
| 20minutos.es | related_links | 1 of 41 | A2's rule returns a shopping link in the subtitle list; the reference rule does not. | unchanged | The link is not a related article. |

## Rules that returned more than the field (found by comparing the output of the reference with the output of A2 and A3 on every page)

| Site | Field | First rule and its output | Decision | Approved rule |
|---|---|---|---|---|
| adevarul.ro | body | `main` matched two elements: the main element of the whole page, including the menu (about 14,700 characters on the page checked), and the article text inside it (about 3,400). | changed — A3's rule (2026-11-12) | `article > main`: the article text only. |
| akipress.com | body | `div.maintxt` also contained the region, section, date and headline above the text. | changed — A3's rule (2026-11-12) | `div.maintxt > div.txt` |
| akipress.com | date | `div.addinfo span` returned "Kyrgyzstan", "life", "March 26, 2026 / 04:45 PM": the region and section before the date. All three annotators had written this rule. | changed — edited by the administrator (2026-11-12) | `div.addinfo span:last-child`: the date only, on 44 of 44 pages. |
| akipress.com | title | `div.title` also returned the heading "Related content" on 23 of 44 pages. | changed — edited by the administrator (2026-11-12) | `div.maintxt > div.title` |
| aljazeera.com | date | `div.date-simple span` returned the date twice: the screen-reader copy "Published On 23 Feb 2026" and the visible "23 Feb 2026". | changed — edited by the administrator (2026-11-12) | `div.date-simple span[aria-hidden]` |
| 24chasa.bg | author | `div.author div.content` also returned the e-mail address under the name. | changed — A2's rule (2026-11-12) | `div.author > div > h2`: the name only; the author box is empty on 31 of 40 pages. |

Checked and kept: aljazeera.com author ("By …"; A3's rule without "By" misses 7 pages with agency bylines); akipress.com
category ("Kyrgyzstan | politics": region and section); alayam.com related_links (the box is empty on 36 pages and filled
on 2); aljazeera.com related_links (13 of 41 pages, same pages for all annotators); 24chasa.bg author (9 of 40 pages).
No field of 525.az was flagged.

## Pages

| Site | Finding | Decision |
|---|---|---|
| abendzeitung.de | `listing_006.html`, a listing page that A2 had assigned to the article layout, was added to the layout by the save of 2026-11-12 10:42 (all pages of the annotators' union were selected by default). | Removed again the same day; the layout has its 41 pages. The approval page now marks such pages as "new" and does not select them by default. |
