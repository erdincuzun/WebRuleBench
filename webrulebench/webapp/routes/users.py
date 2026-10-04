"""
webrulebench/webapp/routes/users.py — Kullanıcı yönetimi (admin): liste, oluşturma, token/rol/durum.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("users", __name__)


@bp.route("/api/admin/users")
def api_admin_users():
    _, err = require_admin()
    if err: return err
    act = _user_activity()
    users = load_users()
    return jsonify({"users": [{**users_store.public(u, i), **act.get(u, {"sites": 0, "last_annotation": None, "experiments": 0})}
                              for u, i in sorted(users.items())]})


@bp.route("/api/admin/users", methods=["POST"])
def api_admin_users_create():
    actor, err = require_admin()
    if err: return err
    body = request.get_json(silent=True) or {}
    try:
        token = users_store.create(body.get("username") or "", body.get("role") or "user")
    except users_store.UserError as ex:
        return jsonify({"success": False, "error": _ex_text(ex)}), 400
    name = (body.get("username") or "").strip().lower()
    _audit(f"USER_CREATE  user={name}  role={body.get('role') or 'user'}  by={actor}")
    return jsonify({"success": True, "username": name, "token": token})


@bp.route("/api/admin/users/<username>/<action>", methods=["POST"])
def api_admin_users_action(username, action):
    """token (yenile, bir kez gösterilir) · role {role} · active {active}"""
    actor, err = require_admin()
    if err: return err
    body = request.get_json(silent=True) or {}
    try:
        if action == "token":
            token = users_store.reset_token(username)
            if username == actor:                    # kendi token'ı: bu oturum açık kalsın
                session["tv"] = users_store.token_version(username)
            _audit(f"USER_TOKEN_RESET  user={username}  by={actor}")
            return jsonify({"success": True, "token": token, "self": username == actor})
        if action == "role":
            users_store.set_role(username, body.get("role"))
            _audit(f"USER_ROLE  user={username}  role={body.get('role')}  by={actor}")
            return jsonify({"success": True})
        if action == "active":
            users_store.set_active(username, bool(body.get("active")), actor=actor)
            _audit(f"USER_{'ACTIVATE' if body.get('active') else 'DEACTIVATE'}  user={username}  by={actor}")
            return jsonify({"success": True})
    except users_store.UserError as ex:
        return jsonify({"success": False, "error": _ex_text(ex)}), 400
    return jsonify({"error": _t("Unknown action")}), 400
