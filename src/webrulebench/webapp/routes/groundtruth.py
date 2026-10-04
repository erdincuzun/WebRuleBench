"""
webrulebench/webapp/routes/groundtruth.py — Ground Truth Onayı: özetler ve derleme (K1/K2, kaydetme).
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("groundtruth", __name__)


@bp.route("/api/gt/overview")
def api_gt_overview():
    """GT Onayı site listesi: layout'u olan her site için özet."""
    _, err = require_login()
    if err: return err
    audit_times = _audit_compile_times()
    result = []
    for site in load_sites():
        domain = site["domain"]
        if not load_ground_truth(domain).get("layouts"):
            continue
        lsums = _gt_layout_summaries(domain, audit_times)
        css   = [l["langs"]["css"] for l in lsums]
        dates = [c["compiled_at"] for l in lsums for c in l["langs"].values() if c["compiled_at"]]
        result.append({
            "domain":     domain,
            "name":       site.get("name", domain),
            "country":    site.get("country", ""),
            "layouts":    len(lsums),
            "annotators": len({u for l in lsums for u in l["annotators"]}),
            "approved":   sum(1 for c in css if c["status"] == "approved"),
            "stale":      sum(1 for c in css if c["status"] == "stale"),
            "none":       sum(1 for c in css if c["status"] == "none"),
            "pending":    sum(1 for l in lsums if _is_pending(l)),
            "last_compiled": max(dates) if dates else None,
        })
    return jsonify({"sites": result})


@bp.route("/api/gt/layouts/<domain>")
def api_gt_layouts(domain):
    """GT Onayı layout listesi: bir sitenin layout'ları, dil bazında durum ve κ."""
    _, err = require_login()
    if err: return err
    if not (DATASET_DIR / domain).is_dir():
        return jsonify({"error": _t("Site not found")}), 404
    lsums = _gt_layout_summaries(domain, _audit_compile_times())
    for l in lsums:
        l["pending"] = _is_pending(l)
    return jsonify({"domain": domain, "layouts": _strip_ratings(lsums)})


@bp.route("/api/gt/pending")
def api_gt_pending():
    """Site bazlı: layout ataması olan domain'lerin GT onay durumunu döndür."""
    sites  = load_sites()
    result = []
    for site in sites:
        domain   = site["domain"]
        gt       = load_ground_truth(domain)
        pa       = gt.get("page_assignments", {})
        assigned = [f for f, v in pa.items() if not v.get("skipped") and v.get("layout_id")]
        if not assigned:
            continue

        pages     = get_site_pages(domain)
        all_p     = pages["article"] + pages["listing"]
        result.append({
            "domain":         domain,
            "assigned_pages": len(assigned),
            "total_pages":    len(all_p),
            "layouts":        len(gt.get("layouts", {})),
        })
    return jsonify({"sites": result})


@bp.route("/api/gt/site/<domain>")
def api_gt_site(domain):
    """Site için ground_truth layout verileri ve approved GT'yi döndür."""
    gt = load_ground_truth(domain)
    pa = gt.get("page_assignments", {})

    # Her layout için atanmış sayfalar
    layout_pages: dict[str, list] = {}
    for fname, info in pa.items():
        if info.get("skipped") or not info.get("layout_id"):
            continue
        lid = info["layout_id"]
        layout_pages.setdefault(lid, []).append(fname)

    return jsonify({
        "domain":         domain,
        "layouts":        gt.get("layouts", {}),
        "layout_pages":   layout_pages,
        "total_assigned": sum(len(v) for v in layout_pages.values()),
    })


@bp.route("/api/compile/<path:domain>/<layout_id>")
def api_compile_data(domain, layout_id):
    """Per-user selectors and page_assignments for a layout (compile view).
    Herkes görüntüleyebilir; kaydetme (POST) yalnızca admin."""
    _, err = require_login()
    if err: return err

    gt      = load_ground_truth(domain)
    layout  = gt.get("layouts", {}).get(layout_id)
    if not layout:
        return jsonify({"error": _t("Layout not found")}), 404

    users_data = load_users()
    result     = {}

    for uname in users_data:
        ann = load_user_annotation(domain, uname)
        ann_layout = ann.get("layouts", {}).get(layout_id, {})
        ann_pa     = ann.get("page_assignments", {})

        # Pages this user assigned to this layout (union contribution)
        pages = [f for f, v in ann_pa.items()
                 if v.get("layout_id") == layout_id and not v.get("skipped")]

        selectors = ann_layout.get("selectors", {})
        if not pages and not selectors:
            continue  # user hasn't touched this layout

        result[uname] = {
            "selectors": selectors,
            "pages":     pages,
        }

    # Union of all user page assignments
    union_pages = sorted(set(p for u in result.values() for p in u["pages"]))

    return Response(json.dumps({
        "layout_id":   layout_id,
        "layout":      layout,
        "users":       result,
        "union_pages": union_pages,
        "gt_selectors": layout.get("selectors", {}),
        "gt_pages":    [f for f, v in gt.get("page_assignments", {}).items()
                        if v.get("layout_id") == layout_id and not v.get("skipped")],
    }, ensure_ascii=False), mimetype="application/json")


@bp.route("/api/compile/texts", methods=["POST"])
def api_compile_texts():
    """Derleme K2/Test için: {key: kural} → çıkarılan metin ve eşleşme sayısı (regex/xpath ham HTML'de).
    Body: {domain, filename, rule_type, rules: {key: rule}}"""
    _, err = require_login()
    if err: return err
    data      = request.get_json(silent=True) or {}
    rule_type = data.get("rule_type", "regex")
    if rule_type not in ("css", "xpath", "regex"):
        return jsonify({"error": _t("Invalid rule_type")}), 400
    path = DATASET_DIR / (data.get("domain") or "") / (data.get("filename") or "")
    if not (data.get("domain") and data.get("filename") and path.is_file()):
        return jsonify({"error": _t("Page not found")}), 404
    html  = path.read_text(encoding="utf-8", errors="ignore")
    soup  = BeautifulSoup(html, "html.parser")
    texts, counts = {}, {}
    for key, rule in (data.get("rules") or {}).items():
        if not isinstance(rule, str) or not rule.strip():
            continue
        r = _run_selector(soup, rule, False, rule_type=rule_type, raw_html=html, with_texts=True)
        counts[key] = r.get("count", 0)
        texts[key]  = " ".join(t for t in r.get("texts", []) if t).strip() or None
    return jsonify({"texts": texts, "counts": counts})


@bp.route("/api/compile/<path:domain>/<layout_id>", methods=["POST"])
def api_compile_save(domain, layout_id):
    """Admin saves compiled selectors + union pages to GT for a layout."""
    _, err = require_admin()
    if err: return err

    data      = request.json
    selectors = data.get("selectors", {})   # {field: selector}
    pages     = data.get("pages", [])        # list of filenames (union)

    gt = load_ground_truth(domain)
    if layout_id not in gt.get("layouts", {}):
        return jsonify({"error": _t("Layout not found")}), 404

    # Update selectors
    gt["layouts"][layout_id]["selectors"] = selectors
    # Kim/ne zaman derledi — kural dili bazında (GT Onayı listelerindeki "güncelleme var" durumu için)
    username = current_user()
    now      = datetime.now(timezone.utc).isoformat()
    # yalnızca GT'de bulunan diller; GT'den çıkarılan dilin derleme bilgisi de silinir
    gt["layouts"][layout_id]["compiled"] = {lang: {"at": now, "by": username} for lang in _rule_langs(selectors)}

    # Update page_assignments: set these pages to this layout, keep others untouched
    pa = gt.setdefault("page_assignments", {})
    # Remove old assignments for this layout
    for fname, info in list(pa.items()):
        if info.get("layout_id") == layout_id:
            del pa[fname]
    # Add new
    for fname in pages:
        pa[fname] = {"layout_id": layout_id, "skipped": False}

    save_ground_truth(domain, gt)
    _audit(f"COMPILE  domain={domain}  layout={layout_id}  pages={len(pages)}  fields={list(selectors.keys())}")

    return jsonify({"success": True, "pages": len(pages), "fields": len(selectors)})
