"""
test_excluded_fields.py
=======================
Ground-truth approval: a field that an annotator wrote a rule for but that is not written to the ground
truth must be an explicit decision of the administrator. Saving is refused until each such field is
confirmed; the decision (who, when, reason, annotators) is stored with the layout, survives a layout
edit and ends when the field gets a rule. Runs on the reviewer demo data in a separate process
(WRB_DATA_DIR), so the real data folder is not touched.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

SCRIPT = r"""
import json, sys
from webrulebench.webapp import core
from webrulebench.webapp.app import app

out = {}
# pure function: which fields have an annotator rule but no GT rule
users = {"a": {"title": "h1", "tags": "ul.tags a", "links": []},
         "b": {"title": "h1.t", "tags": {"css": None, "xpath": "//ul/li/a"}, "author": ""}}
out["unit"] = core.unapproved_fields(["title", "author", "tags", "links"], users, {"title": "h1"})
out["unit_gt_dict"] = core.unapproved_fields(["title", "tags"], users, {"title": "h1", "tags": {"css": "ul a", "xpath": None}})
out["unit_no_template"] = core.unapproved_fields([], users, {})

# annotation validation (the Test button): a selector with a comma inside parentheses is one selector
from bs4 import BeautifulSoup
page = '<article><h2 class="headline">Inside</h2></article><h2 class="headline">Outside</h2>'
out["validation"] = [core._run_selector(BeautifulSoup(page, "html.parser"), sel, merge, with_texts=True)["texts"]
                     for sel, merge in (("article :is(h1, h2).headline", False), ("article :is(h1, h2).headline", True),
                                        ("h9, article :is(h1, h2).headline", False))]

user, token = [l.split(":", 1)[1].strip() for l in open(sys.argv[1], encoding="utf-8").read().splitlines()[:2]]
c = app.test_client()
assert c.post("/login", json={"username": user, "token": token}).get_json()["success"]

dom = sorted(p.stem for p in core.APPROVED_DIR.glob("*.json"))[0]
lid = sorted(core.load_ground_truth(dom)["layouts"])[0]
url = f"/api/compile/{dom}/{lid}"
d = c.get(url).get_json()
sels, pages = d["gt_selectors"], d["gt_pages"]
field = next(f for f in sels if all(u["selectors"].get(f) for u in d["users"].values()))
annotators = sorted(d["users"])
rest = {f: v for f, v in sels.items() if f != field}
summary = lambda: next(l for l in c.get(f"/api/gt/layouts/{dom}").get_json()["layouts"] if l["layout_id"] == lid)
layout = lambda: core.load_ground_truth(dom)["layouts"][lid]

out["field"], out["annotators"] = field, annotators
out["before"] = summary()["unreviewed"]
r = c.post(url, json={"selectors": rest, "pages": pages})                      # left out without a decision
out["refused"] = [r.status_code, r.get_json().get("unconfirmed")]
out["unchanged"] = field in layout()["selectors"] and "excluded_fields" not in layout()
r = c.post(url, json={"selectors": rest, "pages": pages, "excluded": {field: "  not a real field here  "}})
out["saved"] = [r.status_code, r.get_json()]
out["decision"] = layout().get("excluded_fields")
out["after_decision"] = summary()["unreviewed"]
r = c.post(url, json={"selectors": rest, "pages": pages, "excluded": {field: "not a real field here"}})
out["same_decision_kept"] = layout()["excluded_fields"] == out["decision"]
# the layout editor sends a fresh layout object: the decision is kept
L = layout()
c.post("/api/layout/save", json={"domain": dom, "layout_id": lid,
       "layout": {"name": L["name"], "page_type": L.get("page_type", "article"), "template_id": L.get("template_id"),
                  "selectors": L["selectors"]}})
out["kept_on_edit"] = layout().get("excluded_fields") == out["decision"]
r = c.post(url, json={"selectors": sels, "pages": pages})                      # field approved again
out["restored"] = [r.status_code, "excluded_fields" in layout(), summary()["unreviewed"]]

# a note on an approved field is stored with the layout; a note on a field without a rule is not
other = next(f for f in sels if f != field)
c.post(url, json={"selectors": sels, "pages": pages, "notes": {other: " read as the byline ", "no_such_field": "x"}})
out["notes"] = [other, layout().get("field_notes")]
c.post(url, json={"selectors": sels, "pages": pages})
out["notes_cleared"] = "field_notes" not in layout()

# where each approved rule comes from: the annotators who wrote it, or nobody (the administrator)
out["unit_sources"] = core.rule_sources(
    {"title": "H1", "tags": {"css": "ul.x a", "xpath": "//ul/li/a"}, "body": "div.own"},
    {"a": {"title": "h1", "tags": "ul.tags a", "body": "div.b"}, "b": {"title": "h1 ", "tags": {"css": None, "xpath": "//ul/li/a"}}})
edited = {**sels, other: "div.written-by-the-admin"}
c.post(url, json={"selectors": edited, "pages": pages})
out["sources"] = [layout()["rule_sources"].get(other), layout()["rule_sources"].get(field), summary()["admin_rules"]]
c.post(url, json={"selectors": sels, "pages": pages})

# page coverage: on how many pages of the layout a rule returns a value
rule = sels[field] if isinstance(sels[field], str) else sels[field]["css"]
r = c.post(f"/api/compile-coverage/{dom}/{lid}", json={"rule_type": "css", "rules": {
    "gt": {"field": field, "rule": rule}, "none": {"field": field, "rule": "div.no-such-class-anywhere"},
    "bad": {"field": field, "rule": "div[[["}, "blank": {"field": field, "rule": "  "}}}).get_json()
out["coverage"] = [r["total"], len(pages), r["coverage"]["gt"]["n"], r["coverage"]["none"], r["coverage"]["bad"]["n"], sorted(r["coverage"])]
out["coverage_bad_lang"] = c.post(f"/api/compile-coverage/{dom}/{lid}", json={"rule_type": "sql"}).status_code
print(json.dumps(out))
"""


def test_left_out_fields_need_a_recorded_decision(tmp_path):
    out = tmp_path / "demo"
    env = {**os.environ, "WRB_DATA_DIR": str(out)}
    subprocess.run([sys.executable, "-m", "webrulebench.demo.setup_demo", "--dir", str(out)], cwd=ROOT,
                   check=True, capture_output=True, text=True, env=env)
    res = json.loads(subprocess.run([sys.executable, "-c", SCRIPT, str(out / "REVIEWER_LOGIN.txt")], cwd=ROOT,
                                    check=True, capture_output=True, text=True, env=env).stdout.splitlines()[-1])

    assert res["validation"] == [["Inside"], ["Inside"], ["Inside"]]

    # rules count in any rule language; empty values and empty lists are not rules
    assert res["unit"] == {"tags": ["a", "b"]}
    assert res["unit_gt_dict"] == {}
    assert res["unit_no_template"] == {"tags": ["a", "b"], "title": ["a", "b"]}

    field, annotators = res["field"], res["annotators"]
    assert res["before"] == []
    assert res["refused"] == [409, {field: annotators}] and res["unchanged"]       # nothing is written
    assert res["saved"][0] == 200 and res["saved"][1]["success"] and res["saved"][1]["excluded"] == 1
    d = res["decision"][field]
    assert d["reason"] == "not a real field here" and d["annotators"] == annotators and d["by"] and d["at"]
    assert res["after_decision"] == []                    # a recorded decision is not reported as open
    assert res["same_decision_kept"]                      # who decided and when is not overwritten
    assert res["kept_on_edit"]
    assert res["restored"] == [200, False, []]

    other, notes = res["notes"]
    assert notes == {other: "read as the byline"} and res["notes_cleared"]

    # same rule after normalization counts; a rule nobody wrote has no annotators
    assert res["unit_sources"] == {"title": {"css": ["a", "b"]}, "tags": {"css": [], "xpath": ["b"]}, "body": {"css": []}}
    src_other, src_field, admin_rules = res["sources"]
    assert src_other == {"css": []} and other in admin_rules
    assert src_field["css"] and set(src_field["css"]) <= set(annotators)

    total, n_pages, n_gt, none, n_bad, keys = res["coverage"]
    assert total == n_pages and 0 < n_gt <= total
    assert none["n"] == 0 and len(none["empty"]) == total          # every page is listed as empty
    assert n_bad == 0 and keys == ["bad", "gt", "none"]            # invalid rule: no value; blank rule: skipped
    assert res["coverage_bad_lang"] == 400
