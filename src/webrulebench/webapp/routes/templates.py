"""
webrulebench/webapp/routes/templates.py — Şablon & Prompt: şablonlar ve prompt varyantları.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("templates", __name__)


@bp.route("/api/templates")
def api_get_templates():
    data = load_templates()
    payload = {
        "templates":   data.get("templates", {}),
        "metrics":     data.get("metrics", {}),
        "field_types": data.get("field_types", {}),
    }
    return Response(
        json.dumps(payload, ensure_ascii=False),
        mimetype="application/json"
    )


@bp.route("/api/templates/<tid>")
def api_get_template(tid):
    t = get_template(tid)
    if not t:
        return jsonify({"error": _t("Template not found")}), 404
    # jsonify anahtarları sıralar; alan sırası korunmalı
    return Response(json.dumps(t, ensure_ascii=False), mimetype="application/json")


@bp.route("/api/templates", methods=["POST"])
def api_create_template():
    username, err = require_login()
    if err: return err
    users = load_users()
    if users.get(username, {}).get("role") != "admin":
        return jsonify({"error": _t("Permission denied")}), 403

    body = request.json or {}
    tid  = body.get("id", "").strip().lower().replace(" ", "_")
    if not tid:
        return jsonify({"error": _t("id is required")}), 400

    data = load_templates()
    if tid in data["templates"]:
        return jsonify({"error": _t("This id already exists")}), 409

    data["templates"][tid] = {
        "id":          tid,
        "name":        body.get("name", tid),
        "description": body.get("description", ""),
        "page_type":   body.get("page_type", "article"),
        "icon":        body.get("icon", "📄"),
        "fields":      body.get("fields", {}),
    }
    save_templates(data)
    return jsonify({"success": True, "id": tid})


@bp.route("/api/templates/<tid>", methods=["PUT"])
def api_update_template(tid):
    username, err = require_login()
    if err: return err
    users = load_users()
    if users.get(username, {}).get("role") != "admin":
        return jsonify({"error": _t("Permission denied")}), 403

    data = load_templates()
    if tid not in data["templates"]:
        return jsonify({"error": _t("Template not found")}), 404

    body     = request.json or {}
    template = data["templates"][tid]

    # Temel alanları güncelle
    for key in ("name", "description", "page_type", "icon", "fields"):
        if key in body:
            template[key] = body[key]

    save_templates(data)
    return jsonify({"success": True})


@bp.route("/api/templates/<tid>", methods=["DELETE"])
def api_delete_template(tid):
    username, err = require_login()
    if err: return err
    users = load_users()
    if users.get(username, {}).get("role") != "admin":
        return jsonify({"error": _t("Permission denied")}), 403

    data = load_templates()
    if tid not in data["templates"]:
        return jsonify({"error": _t("Template not found")}), 404
    del data["templates"][tid]
    save_templates(data)
    return jsonify({"success": True})


@bp.route("/api/templates/<tid>/prompts")
def api_template_prompts(tid):
    """Şablonun otomatik prompt'u (her kural dili için) + eklenmiş prompt'lar."""
    from webrulebench.pipeline.prompt_builder import build_prompt, RULE_TYPES
    t = get_template(tid)
    if not t:
        return jsonify({"error": _t("Template not found")}), 404
    prompts = [p for p in load_template_prompts()["prompts"].values() if p.get("template_id") == tid]
    prompts.sort(key=lambda p: p.get("created_at", ""))
    return Response(json.dumps({
        "auto":    {rt: build_prompt(t, rt) for rt in RULE_TYPES},
        "prompts": prompts,
    }, ensure_ascii=False), mimetype="application/json")


@bp.route("/api/templates/<tid>/prompts", methods=["POST"])
def api_create_template_prompt(tid):
    username, err = require_login()
    if err: return err
    if not get_template(tid):
        return jsonify({"error": _t("Template not found")}), 404
    clean, verr = _validate_template_prompt(request.get_json(silent=True) or {})
    if verr:
        return jsonify({"error": verr}), 400
    now  = datetime.now(timezone.utc).isoformat()
    data = load_template_prompts()
    pid  = f"{tid}-{secrets.token_hex(4)}"
    data["prompts"][pid] = {"id": pid, "template_id": tid, **clean,
                            "owner": username, "created_at": now, "updated_at": now}
    save_template_prompts(data)
    return jsonify({"success": True, "prompt": data["prompts"][pid]})


@bp.route("/api/template-prompts/<pid>", methods=["PUT"])
def api_update_template_prompt(pid):
    data, p, err = _prompt_for_edit(pid)
    if err: return err
    clean, verr = _validate_template_prompt(request.get_json(silent=True) or {})
    if verr:
        return jsonify({"error": verr}), 400
    p.update(clean, updated_at=datetime.now(timezone.utc).isoformat())
    save_template_prompts(data)
    return jsonify({"success": True, "prompt": p})


@bp.route("/api/template-prompts/<pid>", methods=["DELETE"])
def api_delete_template_prompt(pid):
    data, p, err = _prompt_for_edit(pid)
    if err: return err
    del data["prompts"][pid]
    save_template_prompts(data)
    return jsonify({"success": True})
