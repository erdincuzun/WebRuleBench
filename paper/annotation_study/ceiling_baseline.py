"""
ceiling_baseline.py
===================
Two reference points for the LLM scores, scored exactly like an LLM configuration (mean of the layout means over
the scored page–field pairs, against the reviewed reference):
- the CSS rules each annotator wrote for the layout (an upper reference; optimistic, because the reference was
  built from these rules);
- one generic rule set used for every site, written without looking at any page (a lower reference).
Writes results/ceiling_baseline.json.

    python paper/annotation_study/ceiling_baseline.py
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT / "src")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from webrulebench.evaluation import experiments as X
import rescore as R
BASELINE = {"title": "h1", "body": "article", "author": "[rel=author]", "date": "time", "category": "[class*=breadcrumb] a",
            "images": "article img", "images_caption": "figcaption", "related_links": "", "summary": "", "tags": "[rel=tag]"}
tm = X._templates(); e0 = json.load(open(sorted((R.HERE / "results" / "experiments").glob("*.json"))[0]))
def run(rules_of):
    e = {"config": {"rule_type": "css"}, "layouts": []}; out = []
    for lay in e0["layouts"]:
        fake = {**lay, "rules": rules_of(lay["domain"], lay["layout_id"])}
        _, s, *_ = R.rescore_layout(e, fake, tm); out.append(s)
    return {k: round(100 * X._mean(s[k] for s in out), 1) for k in ("mean", "sample_mean", "others_mean")}, \
           {f: (None if (v := X._mean(s["per_field"][f] for s in out)) is None else round(100 * v, 1)) for f in out[0]["per_field"]}
res = {}
for a in ("A1", "A2", "A3"):
    res[a] = run(lambda d, l, a=a: R.annotator_rules(d, l).get(a, {}))
res["baseline"] = run(lambda d, l: BASELINE)
for k, (s, pf) in res.items(): print(k.ljust(9), s, pf)
json.dump({k: {"summary": s, "per_field": pf} for k, (s, pf) in res.items()} | {"baseline_rules": BASELINE}, open(R.HERE / "results" / "ceiling_baseline.json", "w"), indent=1)
