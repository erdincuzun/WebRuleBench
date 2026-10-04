"""
prompt_builder.py
=================
Şablon bazlı otomatik prompt üretimi.

Bir şablonun (layout_templates.json) adı, açıklaması ve alanlarından —
ad, etiket, açıklama, zorunluluk — ve seçilen kural dilinden (css / xpath /
regex) LLM'e gönderilecek sistem + kullanıcı prompt'unu üretir.

Otomatik prompt bilerek sadedir: yalnızca görevi, bulunacak alanları ve
çıktı biçimini söyler. Seçici kuralları, anti-pattern'ler gibi ayrıntılar
kullanıcıların template_prompts.json'a eklediği deneme prompt'larında
denenir (webrulebench/webapp/routes/templates.py).

Kullanım:
    from webrulebench.pipeline.prompt_builder import build_prompt
    p = build_prompt(template, "css")   # -> {"system": ..., "user": ...}
"""

import json

from webrulebench.pipeline.llm_extractor import USER_PROMPT_TEMPLATES_BY_RULE_TYPE

RULE_TYPES = ("css", "xpath", "regex")

_TASK = {
    "css":   "write one CSS selector for each field below.",
    "xpath": "write one XPath expression for each field below.",
    "regex": "write one Python regular expression for each field below. The regex is matched against "
             "the page's raw HTML text (the skeleton is only structural context) and must contain "
             "exactly one capturing group — the extracted value.",
}

_EXAMPLE_VALUE = {"css": "<css selector>", "xpath": "<xpath expression>", "regex": "<regex>"}


def _page_phrase(template: dict) -> str:
    name = (template.get("name") or template.get("id") or "").strip()
    desc = (template.get("description") or "").strip()
    return f"a web page of type \"{name}\"" + (f" ({desc})" if desc else "")


def _field_line(fname: str, fdef: dict) -> str:
    desc = (fdef.get("description") or fdef.get("label") or "").strip()
    line = f"- {fname}"
    if desc and desc.lower() != fname.lower():
        line += f": {desc}"
    return line + (" (required)" if fdef.get("required") else "")


def build_system_prompt(template: dict, rule_type: str = "css") -> str:
    if rule_type not in RULE_TYPES:
        raise ValueError(f"rule_type must be one of {RULE_TYPES}")
    fields  = template.get("fields") or {}
    example = json.dumps({f: _EXAMPLE_VALUE[rule_type] for f in fields}, ensure_ascii=False)
    lines   = "\n".join(_field_line(f, d) for f, d in fields.items()) or "- (no fields defined)"

    return (
        f"You extract data from web pages. You are given an HTML skeleton of {_page_phrase(template)}: "
        f"tag names, classes and ids, with headings and short text snippets kept as content hints "
        f"(long texts are shortened; links, image sources and styles are removed); {_TASK[rule_type]}\n\n"
        f"Fields (use null if a field is not on the page):\n{lines}\n\n"
        f"Return ONLY a JSON object with exactly these keys, no other text:\n{example}"
    )


def build_user_prompt(rule_type: str = "css") -> str:
    return USER_PROMPT_TEMPLATES_BY_RULE_TYPE[rule_type]


def build_prompt(template: dict, rule_type: str = "css") -> dict:
    return {"system": build_system_prompt(template, rule_type),
            "user":   build_user_prompt(rule_type)}
