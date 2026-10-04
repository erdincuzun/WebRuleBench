# Interface languages (i18n)

The interface is in **English by default** and can be switched to **Turkish** with the
EN / TR switch in the header (cookie `lang`, remembered for a year).

## How it works

- **Source strings are English.** Every user-visible string in templates, JavaScript
  and server messages is written in English in the code.
- **Translations** live in `src/webrulebench/webapp/i18n/<lang>/*.json` as `{"English text": "translation"}`.
  Files are split by page group and merged when loaded (`i18n.py`); a missing entry
  simply shows the English text.
- **Placeholders** use `{name}` on both sides: `T("{n} pages", {n: 3})` ↔ `"{n} sayfa"`.

| Where | Use |
|---|---|
| Jinja templates | `{{ T("Save") }}`, `{{ T("{n} sites", n=count) }}`, attributes: `title="{{ T('Close') }}"` |
| JavaScript (any page) | `T('Save')`, `T('{n} sites', {n: count})` — `static/i18n.js`, dictionary from `/i18n/<lang>.js` |
| Python (src/webrulebench/webapp/core.py, webrulebench/webapp/routes/) | `_t("Site not found")`, `_t("{name} already exists", name=n)` |
| Dates / numbers in JS | `toLocaleString(LOCALE)` (`en-GB` or `tr-TR`) instead of a fixed `'tr-TR'` |
| Long help texts (`{% block help %}`) | two blocks: `{% if lang == 'tr' %} …Turkish… {% else %} …English… {% endif %}` |

## Rules

1. Write the English text as natural, concise UI English (sentence case for buttons and
   headings, e.g. "Add site", "Save GT"). Keep emojis/icons outside or at the start of the string
   consistently in both languages.
2. One string per meaningful unit. Do not split sentences into fragments that are translated
   separately; use placeholders instead. Do not put HTML inside translated strings unless the
   markup is unavoidable (then keep identical markup in the translation).
3. Do not translate user data (site names, notes, layout names, rules, prompt texts),
   technical identifiers (CSS, XPath, Regex, JSON keys, file paths, field names such as `title`)
   or the LLM prompts.
4. Inside JavaScript template literals call `T()` at render time (not at file load), so the
   dictionary is available.
5. In JavaScript, never name a variable `T` (it would shadow the translation function).
6. Server-side messages that modules raise (`users_store.UserError`, `ValueError` in
   `experiments.py`, …) are written in English and translated at the API boundary with
   `_t(str(ex))`; add the English message to `i18n/tr/server.json`.

## Adding a language

Create `src/webrulebench/webapp/i18n/<code>/` with the same JSON files, add the code to `LANGS` and
`LOCALES` in `src/webrulebench/webapp/i18n.py` and to `LOCALE` in `static/i18n.js`.
