"""
webrulebench/webapp/routes/auth.py — Login, logout, session info.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — shared helpers, paths, authentication

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        data     = request.get_json(silent=True) or {}
        username = (data.get("username") or "").strip().lower()
        token    = (data.get("token") or "").strip()
        if not username or not token:
            return jsonify({"success": False, "error": _t("Username and token are required")})
        info = users_store.verify(username, token)
        if not info:
            import time
            time.sleep(0.8)          # slow down brute-force attempts
            # do not reveal whether the username exists or is inactive
            return jsonify({"success": False, "error": _t("Wrong username or token (or the account is inactive)")})
        session["username"] = username
        session["tv"] = int(info.get("token_version", 0))
        users_store.touch_login(username)
        return jsonify({"success": True, "username": username, "role": info.get("role", "user")})
    return render_template("index.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@bp.route("/api/me")
def api_me():
    u = current_user()
    if not u:
        return jsonify({"logged_in": False})
    # only safe fields (the token hash is not given out)
    return jsonify({"logged_in": True, **users_store.public(u, load_users().get(u, {}))})


@bp.route("/api/users")
def api_users():
    _, err = require_login()
    if err: return err
    users = load_users()
    return jsonify({"users": [{"username": u, "role": v.get("role", "user"), "active": v.get("active", True)}
                              for u, v in users.items()]})
