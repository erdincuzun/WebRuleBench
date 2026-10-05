"""
webrulebench/webapp/routes/reports.py — Rapor & Dışa Aktarma: raporlar, manifest, dataset card, denetim kaydı, JSONL/CSV/HF dışa aktarma.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("reports", __name__)


@bp.route("/api/reports/dataset")
def api_reports_dataset():
    _, err = require_login()
    if err: return err
    return jsonify(_dataset_report())


@bp.route("/api/reports/quality")
def api_reports_quality():
    """Annotation ilerlemesi (kullanıcı × site) ve layout × kural dili GT durumu / κ."""
    _, err = require_login()
    if err: return err
    meta = _site_meta_map()
    audit_times = _audit_compile_times()
    layouts = []
    for dom in meta:
        if not load_ground_truth(dom).get("layouts"):
            continue
        for l in _gt_layout_summaries(dom, audit_times):
            layouts.append({"domain": dom, "country": meta[dom]["country"], "language": meta[dom]["language"], **l})
    progress = []
    if ANNOTATIONS_DIR.exists():
        for f in sorted(ANNOTATIONS_DIR.glob("*/*.json")):
            try:
                ann = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue
            pa   = ann.get("page_assignments", {})
            lays = ann.get("layouts", {})
            ts   = [l.get("updated_at") for l in lays.values() if l.get("updated_at")]
            progress.append({
                "user": f.stem, "domain": f.parent.name, "country": (meta.get(f.parent.name) or {}).get("country", ""),
                "assigned": sum(1 for v in pa.values() if v.get("layout_id") and not v.get("skipped")),
                "skipped":  sum(1 for v in pa.values() if v.get("skipped")),
                "layouts":  len(lays),
                "rules":    {lang: sum(1 for l in lays.values() for v in (l.get("selectors") or {}).values()
                                       if _rule_of(v, lang)) for lang in RULE_LANGS},
                "last": max(ts) if ts else None,
            })
    users = load_users()
    pooled = _pooled_kappa(layouts)
    return jsonify({"layouts": _strip_ratings(layouts), "progress": progress, "kappa": pooled,
                    "users": [{"username": u, "role": i.get("role", "user"), "active": i.get("active", True)}
                              for u, i in sorted(users.items())]})


_agreement_cache: dict = {}   # kural dili → (dosya imzası, sonuç)


def _agreement_signature() -> tuple:
    """Annotation ve onaylı GT dosyalarının sayısı ve son değişiklik zamanı; değişince uyum yeniden hesaplanır."""
    files = list(ANNOTATIONS_DIR.glob("*/*.json")) + list(APPROVED_DIR.glob("*.json"))
    return len(files), max((f.stat().st_mtime for f in files), default=0)


@bp.route("/api/reports/agreement")
def api_reports_agreement():
    """Annotatör uyumu iki düzeyde: kural (Fleiss κ) ve içerik (Krippendorff α), ≥2 annotatörlü onaylı layout'lar,
    seçili kural dili. Kurallar bütün GT sayfalarında çalıştırıldığından hesap uzun sürebilir; sonuç annotation ya da
    GT dosyaları değişene kadar saklanır. ?cached=1 → yalnızca hazır sonucu döndür (yoksa {"pending": true})."""
    _, err = require_login()
    if err: return err
    lang = request.args.get("lang", "css")
    if lang not in RULE_LANGS:
        return jsonify({"error": _t("Unknown rule_type: {rule_type}", rule_type=lang)}), 400
    sig = _agreement_signature()
    hit = _agreement_cache.get(lang)
    if hit and hit[0] == sig and not request.args.get("refresh"):
        return jsonify(hit[1])
    if request.args.get("cached"):
        return jsonify({"pending": True})
    from webrulebench.evaluation import agreement as AG
    t0 = datetime.now()
    res = AG.agreement_study(lang=lang)
    for r in res["per_layout"]:
        r["name"] = ((load_ground_truth(r["domain"]).get("layouts") or {}).get(r["layout_id"]) or {}).get("name", r["layout_id"])
    res.update(computed_at=t0.isoformat(timespec="seconds"), seconds=round((datetime.now() - t0).total_seconds(), 1))
    _agreement_cache[lang] = (sig, res)
    return jsonify(res)


@bp.route("/api/reports/llm")
def api_reports_llm():
    _, err = require_login()
    if err: return err
    from webrulebench.evaluation import reports as R
    return jsonify({**R.llm_results(), "sites": _site_meta_map()})


@bp.route("/api/reports/manifest")
def api_reports_manifest():
    """Tekrarlanabilirlik manifesti (JSON indirme). ?ids=a,b → yalnızca bu deneyler; boşsa tamamlananlar."""
    _, err = require_login()
    if err: return err
    from webrulebench.evaluation import reports as R
    ids = [x for x in (request.args.get("ids") or "").split(",") if x]
    ds  = _dataset_report()
    dataset = {"sites": len(ds["sites"]), "sites_with_gt": sum(1 for s in ds["sites"] if s["layouts"]),
               "pages": sum(s["pages"] for s in ds["sites"]), "gt_pages": sum(s["gt_pages"] for s in ds["sites"]),
               "layouts": sum(s["layouts"] for s in ds["sites"]),
               "templates": {t["id"]: t["layouts"] for t in ds["templates"]}}
    m = R.manifest(ids, _gt_compiled_map(), dataset)
    name = f"webrulebench_manifest_{datetime.now().strftime('%Y%m%d-%H%M')}.json"
    return Response(json.dumps(m, ensure_ascii=False, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.route("/api/export/dataset-card")
def api_export_dataset_card():
    """HuggingFace dataset card (README.md): istatistikler, alanlar, biçim, atıf."""
    _, err = require_login()
    if err: return err
    ds = _dataset_report()
    gs = [s for s in ds["sites"] if s["layouts"]]
    countries = sorted({s["country"] for s in gs if s["country"]})
    langs = sorted({x.strip() for s in gs for x in (s["language"] or "").split("/") if x.strip()})
    tmpl_rows = "\n".join(f"| `{t['id']}` | {t['name']} | {t['layouts']} | {t['sites']} | {t['gt_pages']} | "
                          f"{', '.join(f'`{f}`' for f in t['fields'])} |" for t in ds["templates"])
    by_country = {}
    for s in gs:
        c = by_country.setdefault(s["country"] or "?", {"sites": 0, "gt_pages": 0, "language": s["language"]})
        c["sites"] += 1
        c["gt_pages"] += s["gt_pages"]
    country_rows = "\n".join(f"| {c} | {v['language'] or '—'} | {v['sites']} | {v['gt_pages']} |"
                             for c, v in sorted(by_country.items(), key=lambda x: -x[1]["sites"]))
    lang_tags = "\n".join(f"- {l}" for l in langs) or "- multilingual"
    card = f"""---
language:
{lang_tags}
license: other
task_categories:
- other
tags:
- web-extraction
- css-selector
- xpath
- regex
- llm-benchmark
pretty_name: WebRuleBench
---

# WebRuleBench

Ground-truth extraction rules for news web pages, used to benchmark LLM-generated
extraction rules (CSS selectors, XPath, regular expressions) against human-curated ones.

*Generated by WebRuleBench on {datetime.now().strftime('%Y-%m-%d')}. Only approved ground truth is included.*

## Statistics

| | |
|---|---|
| Sites with ground truth | {len(gs)} |
| Countries | {len(countries)} |
| Languages | {len(langs)} |
| Layouts | {sum(s['layouts'] for s in gs)} |
| Pages with ground truth | {sum(s['gt_pages'] for s in gs)} |

### Templates

| Template | Name | Layouts | Sites | GT pages | Fields |
|---|---|---|---|---|---|
{tmpl_rows}

### Sites per country

| Country | Language | Sites | GT pages |
|---|---|---|---|
{country_rows}

## Data format

`webrulebench_hf.jsonl` has one row per (domain, page, field): the ground-truth rule and the value it
extracts from the stored HTML page. `webrulebench_layouts.jsonl` has one row per layout with all rules.

A **layout** is a group of pages from one site that share the same HTML structure; one rule set is written
per layout and applied to all of its pages. Rules were written by several annotators and compiled by an
administrator; inter-annotator agreement is reported as Fleiss' κ per field.

## Evaluation protocol

For each layout an LLM sees a cleaned structural skeleton of one sample page and returns one rule per field.
The rules are applied to every ground-truth page of the layout and scored against the values extracted by the
ground-truth CSS rule, with the field's metric (ROUGE / Jaccard / exact match). Scores are macro-averaged over
layouts; the score on pages other than the sample page measures generalization.

## Citation

If you use the regex generation component, please cite:
Uzun, E. (2020). A regular expression generator based on CSS selectors for efficient extraction from HTML pages.
*Turkish Journal of Electrical Engineering & Computer Sciences*, 28(6), 3389–3401. doi:10.3906/elk-2004-67
"""
    return Response(card, mimetype="text/markdown",
                    headers={"Content-Disposition": "attachment; filename=README.md"})


@bp.route("/api/reports/audit")
def api_reports_audit():
    _, err = require_admin()
    if err: return err
    from webrulebench.evaluation import reports as R
    return jsonify({"entries": R.audit_entries()})


@bp.route("/api/export/jsonl")
def api_export_jsonl():
    """
    Her onaylı domain için layout bazında JSONL export.
    Satır formatı: {domain, layout_id, layout_name, page_type, template_id,
                    selectors: {field: selector}, metrics: {field: metric}, pages: [...]}
    """
    # layout başına bir satır üret
    by_layout: dict[str, dict] = {}
    for row in _build_export_rows():
        key = f"{row['domain']}|{row['layout_id']}"
        if key not in by_layout:
            by_layout[key] = {
                "domain":      row["domain"],
                "layout_id":   row["layout_id"],
                "layout_name": row["layout_name"],
                "page_type":   row["page_type"],
                "template_id": row["template_id"],
                "selectors":   {},
                "metrics":     {},
                "pages":       row["pages"],
            }
        by_layout[key]["selectors"][row["field"]] = row["selector"]
        by_layout[key]["metrics"][row["field"]]   = row["metric"]

    lines = [json.dumps(v, ensure_ascii=False) for v in by_layout.values()]
    from flask import Response
    return Response("\n".join(lines), mimetype="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=webrulebench_layouts.jsonl"})


@bp.route("/api/export/csv")
def api_export_csv():
    """Field-level CSV: domain, layout_id, page_type, template_id, field, selector, metric, page_count"""
    import csv, io
    rows = _build_export_rows()
    buf  = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "domain","layout_id","layout_name","page_type","template_id",
        "field","selector","metric","page_count"
    ])
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row[k] for k in writer.fieldnames})
    from flask import Response
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=webrulebench_selectors.csv"})


@bp.route("/api/export/hf")
def api_export_hf():
    """
    HuggingFace datasets uyumlu JSONL:
    Her satır bir (domain, page, field) üçlüsü — GT değeriyle birlikte.
    HTML üzerinden extract ederek gerçek metin değerlerini döndürür.
    """
    from flask import Response
    lines = []
    for domain_file in sorted(APPROVED_DIR.glob("*.json")):
        approved = json.loads(domain_file.read_text(encoding="utf-8"))
        domain   = domain_file.stem      # dosya adı esastır
        layouts  = approved.get("layouts", {})
        pa       = approved.get("page_assignments", {})  # {filename: {layout_id, skipped}}

        # Build reverse map: layout_id → [filenames]
        lid_pages_hf: dict = {}
        for fname, info in pa.items():
            if info.get("skipped") or not info.get("layout_id"):
                continue
            lid_pages_hf.setdefault(info["layout_id"], []).append(fname)

        for lid, layout in layouts.items():
            pages     = lid_pages_hf.get(lid, [])
            selectors = layout.get("selectors", {})
            tid       = layout.get("template_id", "")
            tmpl      = get_template(tid) or {}
            t_fields  = tmpl.get("fields", {})
            overrides = layout.get("metric_overrides", {})

            for fname in pages:
                html_path = DATASET_DIR / domain / fname
                if not html_path.exists():
                    continue
                html = html_path.read_text(encoding="utf-8", errors="ignore")
                soup = BeautifulSoup(html, "lxml")

                gt_values = {}
                for field, sel in selectors.items():
                    merge = bool(t_fields.get(field.split("[")[0], {}).get("merge", False))
                    gt_values[field] = _extract_with_selector(soup, sel, field, merge)

                metrics = {}
                for field in selectors:
                    metrics[field] = (
                        overrides.get(field)
                        or t_fields.get(field, {}).get("metric")
                        or ("jaccard" if field == "images" else "rouge")
                    )

                lines.append(json.dumps({
                    "domain":      domain,
                    "filename":    fname,
                    "layout_id":   lid,
                    "layout_name": layout.get("name", lid),
                    "page_type":   page_type_for_layout(layout),
                    "template_id": tid,
                    "selectors":   selectors,
                    "metrics":     metrics,
                    "ground_truth": gt_values,
                }, ensure_ascii=False))

    return Response("\n".join(lines), mimetype="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=webrulebench_hf.jsonl"})
