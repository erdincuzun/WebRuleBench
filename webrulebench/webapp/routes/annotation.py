"""
webrulebench/webapp/routes/annotation.py — Annotation: kural doğrulama, XPath/Regex önerisi, layout, annotation kaydı, sayfa atama, toplu test, Auto Detect.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("annotation", __name__)


@bp.route("/api/validate", methods=["POST"])
def api_validate():
    """Validate a CSS selector, XPath expression, or Regex pattern against an HTML file."""
    data      = request.json
    domain    = data.get("domain")
    filename  = data.get("filename")
    selector  = data.get("selector", "").strip()
    field     = data.get("field", "")
    merge     = data.get("merge", False)
    rule_type = data.get("rule_type", "css")

    if not selector:
        return jsonify({"valid": False, "message": _t("Selector cannot be empty")})
    if rule_type not in ("css", "xpath", "regex"):
        return jsonify({"valid": False, "message": _t("Unknown rule_type: {rule_type}", rule_type=rule_type)})

    path = DATASET_DIR / domain / filename
    if not path.exists():
        return jsonify({"valid": False, "message": _t("File not found")})

    # Auto-detect merge from template field definition if not passed explicitly
    if not merge and domain and filename:
        gt     = load_ground_truth(domain)
        pa     = gt.get("page_assignments", {}).get(filename, {})
        lid    = pa.get("layout_id")
        layout = gt.get("layouts", {}).get(lid, {}) if lid else {}
        tid    = layout.get("template_id")
        tmpl   = get_template(tid) if tid else None
        if tmpl and field:
            base_field = field.split("[")[0]  # images[0] → images
            merge = bool(tmpl.get("fields", {}).get(base_field, {}).get("merge", False))

    try:
        html = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        result = _run_selector(soup, selector, merge, rule_type=rule_type, raw_html=html)
        # compare_css: aynı alanın CSS selector'ı — XPath/Regex sonucu onunla aynı mı?
        compare_css = (data.get("compare_css") or "").strip()
        if compare_css and rule_type != "css" and not result.get("syntax_error"):
            kind = _field_kind(domain, filename, field)
            if rule_type == "regex" and kind in ("image", "url"):
                # regex src/href değerini yakalar → CSS tarafında da nitelik değerleri karşılaştırılır
                from webrulebench.rules.regex_generator import css_values, regex_values
                result["compare"] = _compare_texts(css_values(soup, compare_css, kind, merge),
                                                   regex_values(html, selector, kind))
            else:
                css_res = _run_selector(soup, compare_css, merge, with_texts=True)
                result["compare"] = _compare_texts(css_res["texts"], result["texts"])
            if "," in compare_css and not merge:
                result["compare"]["note"] = _t("With comma-separated CSS alternatives only the first matching one is used (merge off); "
                                               "XPath '|' and regex return all matches.")
        result.pop("texts", None)
        return jsonify(result)
    except Exception as e:
        return jsonify({"valid": False, "message": _t("Error: {error}", error=e)})


@bp.route("/api/suggest-xpath", methods=["POST"])
def api_suggest_xpath():
    """Given a CSS selector, suggest the equivalent XPath expression (best-effort).

    Convenience for annotators: pick a CSS selector as usual and get a pre-filled
    XPath starting point instead of writing it from scratch — still editable, and
    the annotator can also type a Regex pattern independently of both.
    """
    from webrulebench.rules.rule_utils import css_to_xpath, css_to_xpath_readable

    data     = request.json or {}
    selector = (data.get("selector") or "").strip()
    if not selector:
        return jsonify({"success": False, "error": _t("Selector cannot be empty")})

    # Aday sırası: okunaklı → okunaklı + tam class eşleşmesi → cssselect çevirisi.
    # Sayfa verilmişse, CSS ile aynı içeriği çıkaran ilk aday seçilir.
    candidates = [x for x in (css_to_xpath_readable(selector),
                              css_to_xpath_readable(selector, strict_classes=True),
                              css_to_xpath(selector)) if x]
    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return jsonify({"success": False, "error": _t("The CSS selector could not be converted to XPath")})

    path = DATASET_DIR / (data.get("domain") or "") / (data.get("filename") or "")
    if not (data.get("domain") and data.get("filename") and path.exists()):
        return jsonify({"success": True, "xpath": candidates[0], "verified": None})

    html    = path.read_text(encoding="utf-8")
    soup    = BeautifulSoup(html, "html.parser")
    merge   = bool(data.get("merge", False))
    css_txt = _run_selector(soup, selector, merge, with_texts=True)["texts"]
    for xp in candidates:
        if _same_texts(_run_selector(soup, xp, merge, rule_type="xpath", raw_html=html)["texts"], css_txt):
            return jsonify({"success": True, "xpath": xp, "verified": True})
    return jsonify({"success": True, "xpath": candidates[0], "verified": False})


@bp.route("/api/suggest-regex", methods=["POST"])
def api_suggest_regex():
    """CSS selector → regex (regex_generator: REGEXN'in genişletilmiş hali).

    Body: {selector, domain, filename?, layout_id?, field?}
    Aday regex'ler bu layout'un sayfalarında (en fazla 6; seçili sayfa önce) CSS ile
    karşılaştırılır; en çok sayfada aynı sonucu veren seçilir.
    """
    _, err = require_login()
    if err: return err
    from webrulebench.rules.regex_generator import generate, css_values, KIND_OF_TYPE

    data     = request.get_json(silent=True) or {}
    selector = (data.get("selector") or "").strip()
    domain   = (data.get("domain") or "").strip()
    if not selector or not domain or not (DATASET_DIR / domain).is_dir():
        return jsonify({"success": False, "error": _t("Selector and site are required")})

    # alan tipi (image/url → nitelik yakalanır) ve merge, layout'un şablonundan
    gt        = load_ground_truth(domain)
    layout_id = data.get("layout_id") or gt.get("page_assignments", {}).get(data.get("filename") or "", {}).get("layout_id")
    layout    = gt.get("layouts", {}).get(layout_id, {}) if layout_id else {}
    fdef      = ((get_template(layout.get("template_id", "")) or {}).get("fields") or {}).get(data.get("field") or "", {})
    kind      = KIND_OF_TYPE.get(fdef.get("type"), "text")
    merge     = bool(fdef.get("merge"))

    pages = [data.get("filename")] if data.get("filename") and data.get("filename") != "_" else []
    if layout_id:
        pages += [f for f, v in gt.get("page_assignments", {}).items()
                  if v.get("layout_id") == layout_id and not v.get("skipped")]
    pages = [p for p in dict.fromkeys(pages) if (DATASET_DIR / domain / p).is_file()][:6]
    if not pages:
        return jsonify({"success": False, "error": _t("No pages are assigned to the layout for validation")})

    htmls    = [(DATASET_DIR / domain / p).read_text(encoding="utf-8", errors="ignore") for p in pages]
    expected = [css_values(h, selector, kind, merge) for h in htmls]
    if not any(expected):
        return jsonify({"success": False, "error": _t("The CSS returns no results on these pages")})
    r = generate(selector, htmls, expected, kind)
    if not r:
        return jsonify({"success": False,
                        "error": _t("This selector is not supported (pseudo-classes :nth-child/:first-child/:not, + ~ combinators)")})
    return jsonify({"success": True, **r, "kind": kind, "pages": pages})


@bp.route("/api/layout/save", methods=["POST"])
def api_save_layout():
    """Save or update a layout definition (admin)."""
    _, err = require_admin()
    if err: return err
    data      = request.json
    domain    = data.get("domain")
    layout_id = data.get("layout_id")
    layout    = data.get("layout")  # {name, page_type, selectors, optional_fields, template_id, metric_overrides}

    gt = load_ground_truth(domain)
    if not gt.get("layouts"):
        gt["layouts"] = {}
    gt["layouts"][layout_id] = layout
    save_ground_truth(domain, gt)

    return jsonify({"success": True, "layout_id": layout_id})


@bp.route("/api/annotate/<domain>/<filename>", methods=["GET"])
def api_get_annotate(domain, filename):
    """Kullanıcının bu sayfa için annotation'ını döndür."""
    username, err = require_login()
    if err: return err

    ann = load_user_annotation(domain, username)
    gt  = load_ground_truth(domain)

    # layout_id doğrudan query param'dan gelebilir (layout bazlı çağrı)
    layout_id = request.args.get("layout_id")
    if not layout_id and filename != "_":
        pa        = gt.get("page_assignments", {}).get(filename, {})
        layout_id = pa.get("layout_id")

    layout   = gt.get("layouts", {}).get(layout_id, {}) if layout_id else {}
    template = get_template(layout.get("template_id", "")) or {}

    # Selector'lar layout bazlı
    ann_layout = ann.get("layouts", {}).get(layout_id, {}) if layout_id else {}
    selectors  = ann_layout.get("selectors", {})
    updated_at = ann_layout.get("updated_at")

    return jsonify({
        "domain":      domain,
        "filename":    filename,
        "annotator":   username,
        "selectors":   selectors,
        "updated_at":  updated_at,
        "layout_id":   layout_id,
        "layout":      layout,
        "template":    template,
    })


@bp.route("/api/annotate/<domain>/<filename>", methods=["POST"])
def api_save_annotate(domain, filename):
    """Kullanıcının CSS selector annotation'ını kaydet."""
    username, err = require_login()
    if err: return err

    body      = request.json or {}
    selectors = {k: v for k, v in body.get("selectors", {}).items() if v}

    ann = load_user_annotation(domain, username)

    # Layout bazlı kayıt: önce kullanıcı annotation'ına, sonra GT'ye bak
    gt        = load_ground_truth(domain)
    user_pa   = ann.get("page_assignments", {}).get(filename, {})
    gt_pa     = gt.get("page_assignments", {}).get(filename, {})
    # Düzenlenen layout istemciden gelir (layout listesinden açılan annotation sayfanın atamasından
    # farklı bir layout olabilir); gelmezse sayfanın atamasına bakılır (eski istemciler).
    layout_id = body.get("layout_id") or user_pa.get("layout_id") or gt_pa.get("layout_id")
    if layout_id and layout_id not in gt.get("layouts", {}) and layout_id not in ann.get("layouts", {}):
        return jsonify({"success": False, "error": _t("Layout not found")}), 404
    if not layout_id:
        return jsonify({"success": False, "error": _t("The page is not assigned to a layout")})

    layouts = ann.setdefault("layouts", {})
    now     = datetime.now(timezone.utc).isoformat()

    old_sels = layouts.get(layout_id, {}).get("selectors", {})
    history  = layouts.get(layout_id, {}).get("history", [])
    for field, new_val in selectors.items():
        old_val = old_sels.get(field)
        if old_val and str(old_val) != str(new_val):
            history.append({"field": field, "old": old_val, "new": new_val, "at": now})
            _audit(f"ANNOTATE  user={username}  domain={domain}  layout={layout_id}  field={field}")

    # Layout meta bilgisini GT'den kopyala
    gt_layout = gt.get("layouts", {}).get(layout_id, {})
    layouts[layout_id] = {
        "name":       gt_layout.get("name", layout_id),
        "page_type":  gt_layout.get("page_type", "article"),
        "template_id": gt_layout.get("template_id", ""),
        "selectors":  selectors,
        "updated_at": now,
        "history":    history,
    }
    save_user_annotation(domain, username, ann)
    return jsonify({"success": True})


@bp.route("/api/annotate/<domain>/<filename>/all")
def api_all_annotate(domain, filename):
    """Tüm kullanıcıların bu sayfa için selector'larını döndür (kıyas için)."""
    gt        = load_ground_truth(domain)
    pa        = gt.get("page_assignments", {}).get(filename, {})
    layout_id = pa.get("layout_id")

    ann_dir = ANNOTATIONS_DIR / domain
    result  = {}
    if ann_dir.exists():
        for f in ann_dir.glob("*.json"):
            ann        = json.loads(f.read_text(encoding="utf-8"))
            ann_layout = ann.get("layouts", {}).get(layout_id, {}) if layout_id else {}
            if ann_layout.get("selectors"):
                result[f.stem] = {
                    "selectors":  ann_layout["selectors"],
                    "updated_at": ann_layout.get("updated_at"),
                }
    return jsonify({"domain": domain, "filename": filename, "annotations": result})


@bp.route("/api/page/assign", methods=["POST"])
def api_assign_page():
    """Assign a page to a layout or mark as skipped — writes only to user's annotation file."""
    username, err = require_login()
    if err: return err

    data      = request.json
    domain    = data.get("domain")
    filename  = data.get("filename")
    layout_id = data.get("layout_id")  # None if skipped
    skipped   = data.get("skipped", False)

    ann = load_user_annotation(domain, username)
    ann.setdefault("page_assignments", {})[filename] = {
        "layout_id": layout_id,
        "skipped":   skipped,
    }
    save_user_annotation(domain, username, ann)

    return jsonify({"success": True})


@bp.route("/api/layout/delete", methods=["POST"])
def api_delete_layout():
    """Delete a layout and unassign its pages."""
    _, err = require_admin()
    if err: return err
    data      = request.json
    domain    = data.get("domain")
    layout_id = data.get("layout_id")

    gt = load_ground_truth(domain)
    if layout_id in gt["layouts"]:
        del gt["layouts"][layout_id]

    # Unassign pages using this layout
    for page, assignment in gt["page_assignments"].items():
        if assignment.get("layout_id") == layout_id:
            assignment["layout_id"] = None

    save_ground_truth(domain, gt)
    return jsonify({"success": True})


@bp.route("/api/auto_detect", methods=["POST"])
def api_auto_detect():
    """Run enriched pipeline to auto-detect CSS selectors for an article page."""


    data     = request.json
    domain   = data.get("domain")
    filename = data.get("filename")
    backend  = data.get("backend", "ollama")
    model    = data.get("model") or None
    path     = DATASET_DIR / domain / filename
    if not path.exists():
        return jsonify({"error": _t("File not found")}), 404
    try:
        from webrulebench.pipeline.html_cleaner import HTMLCleaner
        from webrulebench.pipeline.skeleton import Skeleton
        from webrulebench.pipeline.llm_extractor import LLMExtractor
        html          = path.read_text(encoding="utf-8", errors="ignore")
        cleaned       = HTMLCleaner().clean(html, strategy="whitelist")
        sk            = Skeleton(strategy="enriched")
        skel          = sk.extract(cleaned.cleaned_html)
        extractor     = LLMExtractor(
            backend       = backend,
            model         = model,
        )
        result        = extractor.extract(skel.skeleton_html, domain=domain)
        return jsonify({"success": True, "selectors": result.selectors})
    except Exception as e:
        import traceback
        return jsonify({"success": False, "error": str(e),
                        "detail": traceback.format_exc()}), 500


@bp.route("/api/bulk_test", methods=["POST"])
def api_bulk_test():
    """Test a layout's selectors against multiple pages at once."""
    data      = request.json
    domain    = data.get("domain", "")
    layout_id = data.get("layout_id", "")
    filenames = data.get("filenames", [])   # list of HTML filenames to test

    source    = data.get("source", "gt")    # "gt": onaylı GT kuralları · "mine": kullanıcının kendi kuralları

    gt      = load_ground_truth(domain)
    layouts = gt.get("layouts", {})
    layout  = layouts.get(layout_id)
    if not layout:
        return jsonify({"error": _t("Layout not found")}), 404

    selectors    = layout.get("selectors", {})
    if source == "mine":
        username = current_user()
        mine = (load_user_annotation(domain, username).get("layouts", {}).get(layout_id) or {}).get("selectors") or {}
        if not any(mine.values()):
            return jsonify({"error": _t("You have no rules for this layout yet — write and save them first")}), 400
        selectors = mine
    opt_fields   = set(layout.get("optional_fields", []))
    template_id  = layout.get("template_id")
    tmpl         = get_template(template_id) if template_id else None
    tmpl_fields  = tmpl.get("fields", {}) if tmpl else {}

    # Collect scalar field names (non-image, non-url or links)
    if tmpl_fields:
        scalar_keys = [f for f, fd in tmpl_fields.items()
                       if fd.get("type") not in ("image", "url") or f == "links"]
    else:
        scalar_keys = ["title", "body", "date", "author", "category", "summary"]

    # Build list of {key, selector, optional, merge} for scalar fields
    test_fields = []
    for k in scalar_keys:
        v = selectors.get(k)
        if isinstance(v, dict):          # {css, xpath, regex} → CSS kısmı
            v = v.get("css")
        if v and isinstance(v, str):
            merge = bool(tmpl_fields.get(k, {}).get("merge", False))
            test_fields.append({"key": k, "selector": v, "optional": k in opt_fields, "merge": merge})

    # images blocks
    img_merge = bool(tmpl_fields.get("images", {}).get("merge", False))
    img_val = selectors.get("images")
    if img_val:
        blocks = img_val if isinstance(img_val, list) else [img_val]
        for i, b in enumerate(blocks):
            s = (b.get("css") if "css" in b else b.get("image")) if isinstance(b, dict) else b
            if s:
                test_fields.append({"key": f"images[{i}]", "selector": s,
                                    "optional": "images" in opt_fields, "merge": img_merge})

    # related_links blocks
    rel_merge = bool(tmpl_fields.get("related_links", {}).get("merge", False))
    rel_val = selectors.get("related_links")
    if rel_val:
        blocks = rel_val if isinstance(rel_val, list) else [rel_val]
        for i, b in enumerate(blocks):
            s = (b.get("css") if "css" in b else b.get("link")) if isinstance(b, dict) else b
            if s:
                test_fields.append({"key": f"related_links[{i}]", "selector": s,
                                    "optional": "related_links" in opt_fields, "merge": rel_merge})

    # links
    links_merge = bool(tmpl_fields.get("links", {}).get("merge", False))
    links_val = selectors.get("links")
    if links_val:
        items = links_val if isinstance(links_val, list) else [links_val]
        for i, s in enumerate(items):
            if s and isinstance(s, str):
                test_fields.append({"key": f"links[{i}]", "selector": s,
                                    "optional": "links" in opt_fields, "merge": links_merge})

    results = []
    for filename in filenames:
        path = DATASET_DIR / domain / filename
        if not path.exists():
            results.append({"filename": filename, "fields": {}, "error": _t("File not found")})
            continue

        html = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")

        field_results = {}
        all_required_pass = True

        for tf in test_fields:
            key      = tf["key"]
            sel      = tf["selector"]
            optional = tf["optional"]
            merge    = tf.get("merge", False)

            r       = _run_selector(soup, sel, merge)
            valid   = r["valid"]
            preview = r["previews"][0] if r["previews"] else ""
            field_results[key] = {"valid": valid, "preview": preview, "optional": optional}

            if not valid and not optional:
                all_required_pass = False

        results.append({
            "filename":          filename,
            "fields":            field_results,
            "all_required_pass": all_required_pass,
        })

    # field column order for the table header
    field_keys = [tf["key"] for tf in test_fields]
    optional_keys = {tf["key"] for tf in test_fields if tf["optional"]}

    return jsonify({
        "field_keys":    field_keys,
        "optional_keys": list(optional_keys),
        "results":       results,
    })
