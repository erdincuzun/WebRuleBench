"""
webrulebench/webapp/routes/evaluation.py — LLM Değerlendirme: deneyler, hızlı test, karşılaştırmalı deney grupları, cross-check.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("evaluation", __name__)


@bp.route("/api/experiments/options")
def api_experiments_options():
    """Yeni deney formu: backend/model, kural dili, strateji, şablon prompt'ları, uygun layout'lar."""
    _, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    from webrulebench.pipeline import llm_models as LM
    from webrulebench.pipeline.llm_models import BACKENDS
    from webrulebench.pipeline.html_cleaner import STRATEGIES
    tmpls   = load_templates().get("templates", {})
    prompts = load_template_prompts().get("prompts", {})
    sites   = {s["domain"]: s for s in load_sites()}
    layouts = X.eligible_layouts()
    for l in layouts:
        l["site_name"] = sites.get(l["domain"], {}).get("name", l["domain"])
        l["country"]   = sites.get(l["domain"], {}).get("country", "")
    return Response(json.dumps({
        "backends": [{"name": n, "default_model": c.get("default_model"), "models": LM.available_models(n),
                      "info": {m["name"]: m["info"] for m in LM.model_catalog(n)["models"] if m.get("info")},
                      "has_key": _backend_has_key(c), "notes": c.get("notes", "")} for n, c in BACKENDS.items()],
        "rule_types": list(X.RULE_TYPES),
        "strategies": [st for st in X.UI_STRATEGIES if st in STRATEGIES],
        "templates":  {tid: {"name": t.get("name", tid), "icon": t.get("icon", ""),
                             "prompts": [{"id": p["id"], "name": p["name"], "rule_type": p["rule_type"], "owner": p.get("owner")}
                                         for p in prompts.values() if p.get("template_id") == tid]}
                       for tid, t in tmpls.items()},
        "layouts": layouts,
    }, ensure_ascii=False), mimetype="application/json")


@bp.route("/api/experiments")
def api_experiments_list():
    _, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    return Response(json.dumps({"experiments": X.list_all()}, ensure_ascii=False), mimetype="application/json")


@bp.route("/api/experiments", methods=["POST"])
def api_experiments_create():
    """Deney oluştur ve arka planda başlat (giriş yapan herkes; sahibi kaydedilir)."""
    username, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    body = request.get_json(silent=True) or {}
    known = {(l["domain"], l["layout_id"]) for l in X.eligible_layouts()}
    layouts = [l for l in (body.get("layouts") or []) if (l.get("domain"), l.get("layout_id")) in known]
    configs = body.get("configs") or ([body["config"]] if body.get("config") else [])
    try:
        if len(configs) > 1:              # birden çok model × kural dili → karşılaştırmalı deney (grup)
            gid, ids = X.create_group(body.get("name") or "", configs, layouts, username)
            X.start_group(gid)
            _audit(f"EXPERIMENT_GROUP_START  id={gid}  user={username}  configs={len(configs)}  layouts={len(layouts)}")
            return jsonify({"success": True, "group": gid, "ids": ids})
        e = X.create(body.get("name") or "", configs[0] if configs else {}, layouts, username)
    except (ValueError, IndexError) as ex:
        return jsonify({"success": False, "error": _ex_text(ex) if str(ex) else _t("Configuration missing")}), 400
    X.start(e["id"])
    _audit(f"EXPERIMENT_START  id={e['id']}  user={username}  layouts={len(layouts)}  "
           f"backend={e['config']['backend']}  model={e['config'].get('model')}  rule_type={e['config']['rule_type']}")
    return jsonify({"success": True, "id": e["id"]})


@bp.route("/api/quick-test", methods=["POST"])
def api_quick_test():
    """Hızlı test: tek layout, tek model, kaydedilmez (sonuç 1 saat bellekte; kaydet ile deneye dönüşür)."""
    username, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    body = request.get_json(silent=True) or {}
    try:
        r = X.quick_run(body.get("config") or {}, body.get("domain") or "", body.get("layout_id") or "", username)
    except ValueError as ex:
        return jsonify({"success": False, "error": _ex_text(ex)}), 400
    except Exception as ex:
        return jsonify({"success": False, "error": f"{type(ex).__name__}: {ex}"}), 500
    return Response(json.dumps({"success": True, **r}, ensure_ascii=False), mimetype="application/json")


@bp.route("/api/quick-test/<token>/save", methods=["POST"])
def api_quick_test_save(token):
    username, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    try:
        e = X.save_quick(token, (request.get_json(silent=True) or {}).get("name") or "", username)
    except ValueError as ex:
        return jsonify({"success": False, "error": _ex_text(ex)}), 400
    _audit(f"EXPERIMENT_QUICK_SAVE  id={e['id']}  user={username}")
    return jsonify({"success": True, "id": e["id"]})


@bp.route("/api/experiment-groups/<gid>")
def api_experiment_group(gid):
    """Grup: üyelerin özeti ve layout bazında özetleri (sayfa ayrıntısı hariç)."""
    _, err = require_login()
    if err: return err
    members = _group_or_404(gid)
    if not members:
        return jsonify({"error": _t("Group not found")}), 404
    slim = []
    for e in members:
        slim.append({k: e.get(k) for k in ("id", "name", "status", "progress", "config", "summary", "error",
                                            "created_at", "created_by", "finished_at", "prompts_used")}
                    | {"layouts": [{k: l.get(k) for k in ("domain", "layout_id", "name", "template_id", "sample_page",
                                                          "n_pages", "summary", "error", "llm")} for l in e.get("layouts", [])]})
    for m in slim:
        for l in m["layouts"]:
            if l.get("llm"):
                l["llm"] = {k: v for k, v in l["llm"].items() if k != "raw_response"}
    return Response(json.dumps({"id": gid, "name": members[0]["group"]["name"], "created_by": members[0]["created_by"],
                                "created_at": members[0]["created_at"], "scope": members[0]["scope"], "members": slim},
                               ensure_ascii=False), mimetype="application/json")


@bp.route("/api/experiment-groups/<gid>/cross-check")
def api_experiment_group_cross(gid):
    _, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    if not _group_or_404(gid):
        return jsonify({"error": _t("Group not found")}), 404
    return Response(json.dumps(X.cross_check(gid), ensure_ascii=False), mimetype="application/json")


@bp.route("/api/experiment-groups/<gid>/<action>", methods=["POST"])
def api_experiment_group_action(gid, action):
    username, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    members = _group_or_404(gid)
    if not members:
        return jsonify({"error": _t("Group not found")}), 404
    if not _exp_can_edit(members[0], username):
        return jsonify({"error": _t("Only the group's owner or an admin")}), 403
    if action == "cancel":
        return jsonify({"success": X.cancel_group(gid)})
    if action == "resume":
        if gid in X._groups:
            return jsonify({"success": False, "error": _t("The group is already running")})
        X.start_group(gid)
        return jsonify({"success": True})
    return jsonify({"error": _t("Unknown action")}), 400


@bp.route("/api/experiment-groups/<gid>", methods=["DELETE"])
def api_experiment_group_delete(gid):
    username, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    members = _group_or_404(gid)
    if not members:
        return jsonify({"error": _t("Group not found")}), 404
    if not _exp_can_edit(members[0], username):
        return jsonify({"error": _t("Only the group's owner or an admin")}), 403
    if gid in X._groups or any(m["status"] in ("running", "queued") for m in members):
        return jsonify({"success": False, "error": _t("A running group cannot be deleted — stop it first")})
    for m in members:
        X.exp_path(m["id"]).unlink(missing_ok=True)
    _audit(f"EXPERIMENT_GROUP_DELETE  id={gid}  user={username}  members={len(members)}")
    return jsonify({"success": True})


@bp.route("/api/experiments/<exp_id>")
def api_experiments_get(exp_id):
    _, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    try:
        e = X.load(exp_id)
    except ValueError:
        e = None
    if not e:
        return jsonify({"error": _t("Experiment not found")}), 404
    return Response(json.dumps(e, ensure_ascii=False), mimetype="application/json")


@bp.route("/api/experiments/<exp_id>/<action>", methods=["POST"])
def api_experiments_action(exp_id, action):
    """cancel (durdur) / resume (yarıda kalanı sürdür) — sahibi veya admin."""
    username, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    try:
        e = X.load(exp_id)
    except ValueError:
        e = None
    if not e:
        return jsonify({"error": _t("Experiment not found")}), 404
    if not _exp_can_edit(e, username):
        return jsonify({"error": _t("Only the experiment's owner or an admin")}), 403
    if action == "cancel":
        return jsonify({"success": X.cancel(exp_id)})
    if action == "resume":
        if e["status"] in ("running", "queued"):
            return jsonify({"success": False, "error": _t("The experiment is already running")})
        X.start(exp_id)
        return jsonify({"success": True})
    return jsonify({"error": _t("Unknown action")}), 400


@bp.route("/api/experiments/<exp_id>", methods=["DELETE"])
def api_experiments_delete(exp_id):
    username, err = require_login()
    if err: return err
    from webrulebench.evaluation import experiments as X
    try:
        e = X.load(exp_id)
    except ValueError:
        e = None
    if not e:
        return jsonify({"error": _t("Experiment not found")}), 404
    if not _exp_can_edit(e, username):
        return jsonify({"error": _t("Only the experiment's owner or an admin")}), 403
    if e["status"] in ("running", "queued"):
        return jsonify({"success": False, "error": _t("A running experiment cannot be deleted — stop it first")})
    X.exp_path(exp_id).unlink(missing_ok=True)
    _audit(f"EXPERIMENT_DELETE  id={exp_id}  user={username}")
    return jsonify({"success": True})
