"""
prompt_builder.py
=================
Automatic template-based prompt generation.

Builds the system + user prompt sent to the LLM from a template's
(layout_templates.json) name, description and fields — name, label,
description, required flag — and the chosen rule language (css / xpath / regex).

The automatic prompt is deliberately plain: it states only the task, the fields
to find and the output format. Details such as selector rules and anti-patterns
are tried in the experimental prompts users add to template_prompts.json
(webrulebench/webapp/routes/templates.py).

Usage:
    from webrulebench.pipeline.prompt_builder import build_prompt
    p = build_prompt(template, "css")   # -> {"system": ..., "user": ...}
    p = build_prompt(template, "css", skeleton=False)   # the page's HTML is given instead of the skeleton
"""

import json

from webrulebench.pipeline.llm_extractor import (USER_PROMPT_TEMPLATES_BY_RULE_TYPE,
                                                   USER_PROMPT_TEMPLATES_HTML_BY_RULE_TYPE)

RULE_TYPES = ("css", "xpath", "regex")

_TASK = {
    "css":   "write one CSS selector for each field below.",
    "xpath": "write one XPath expression for each field below.",
    "regex": "write one Python regular expression for each field below. The regex is matched against "
             "the page's raw HTML text (the skeleton is only structural context) and must contain "
             "exactly one capturing group — the extracted value.",
}

# skeleton=False: the regex task refers to the HTML shown instead of the skeleton
_TASK_HTML = {**_TASK,
              "regex": "write one Python regular expression for each field below. The regex is matched against "
                       "the page's raw HTML text and must contain exactly one capturing group — the extracted value."}

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


def build_system_prompt(template: dict, rule_type: str = "css", skeleton: bool = True) -> str:
    if rule_type not in RULE_TYPES:
        raise ValueError(f"rule_type must be one of {RULE_TYPES}")
    fields  = template.get("fields") or {}
    example = json.dumps({f: _EXAMPLE_VALUE[rule_type] for f in fields}, ensure_ascii=False)
    lines   = "\n".join(_field_line(f, d) for f, d in fields.items()) or "- (no fields defined)"

    if skeleton:
        given = (f"You are given an HTML skeleton of {_page_phrase(template)}: tag names, classes and ids, "
                 f"with headings and short text snippets kept as content hints (long texts are shortened; "
                 f"links, image sources and styles are removed); {_TASK[rule_type]}")
    else:
        given = (f"You are given the HTML of {_page_phrase(template)} (non-content markup may have been "
                 f"removed); {_TASK_HTML[rule_type]}")
    return (
        f"You extract data from web pages. {given}\n\n"
        f"Fields (use null if a field is not on the page):\n{lines}\n\n"
        f"Return ONLY a JSON object with exactly these keys, no other text:\n{example}"
    )


def build_user_prompt(rule_type: str = "css", skeleton: bool = True) -> str:
    return (USER_PROMPT_TEMPLATES_BY_RULE_TYPE if skeleton else USER_PROMPT_TEMPLATES_HTML_BY_RULE_TYPE)[rule_type]


def build_prompt(template: dict, rule_type: str = "css", skeleton: bool = True) -> dict:
    return {"system": build_system_prompt(template, rule_type, skeleton),
            "user":   build_user_prompt(rule_type, skeleton)}
