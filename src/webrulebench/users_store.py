"""
users_store.py
==============
Kullanıcılar (<veri klasörü>/users.json): giriş token'ı, rol, durum.

- Token'lar düz metin değil, kullanıcı başına tuzlu SHA-256 özeti olarak saklanır
  ("sha256$<tuz>$<özet>"). Token yalnızca üretildiği anda bir kez gösterilir.
  Eski biçimdeki düz metin "token" alanları ilk okumada özete çevrilir; aynı token
  ile giriş çalışmaya devam eder.
- token_version: token yenilenince artar; oturum çerezinde tutulan sürüm eşleşmezse
  oturum geçersiz sayılır (başka cihazlardaki oturumlar kapanır).
- active: pasif kullanıcı giriş yapamaz; annotation'ları ve geçmişi korunur.
  Kullanıcı silinmez — annotation, derleme ve deney kayıtları kullanıcı adına bağlıdır.
- Son admin'in rolü düşürülemez, son admin pasifleştirilemez, admin kendini pasifleştiremez.

webapp (web), mcp_server.py (MCP) ve webrulebench/webapp/manage_users.py (komut satırı) kullanır.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone

from webrulebench.paths import DATA_DIR
USERS_FILE = DATA_DIR / "users.json"
ROLES      = ("admin", "user")
_NAME_RE   = re.compile(r"[a-z0-9][a-z0-9_.-]{1,31}")
_lock      = threading.Lock()


class UserError(ValueError):
    """English message template + parameters ({name} placeholders). str(ex) is the formatted
    English text; the web app (webrulebench/webapp/core.py) translates it at the API boundary with
    _t(ex.i18n_msg, **ex.i18n_params) (see webrulebench/webapp/i18n/README.md)."""
    def __init__(self, msg: str, **params):
        self.i18n_msg, self.i18n_params = msg, params
        super().__init__(msg.format(**params) if params else msg)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_token(token: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    return f"sha256${salt}${hashlib.sha256((salt + token).encode()).hexdigest()}"


def _matches(stored: str, token: str) -> bool:
    try:
        _, salt, _ = stored.split("$", 2)
    except ValueError:
        return False
    return hmac.compare_digest(stored, hash_token(token, salt))


def new_token() -> str:
    return secrets.token_urlsafe(24)          # ~32 karakter, 192 bit


def _save(users: dict):
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)   # yeni kurulum / ayrı veri klasörü
    tmp = USERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(USERS_FILE)


def load() -> dict:
    """Kullanıcıları oku; düz metin token kalmışsa özete çevirip kaydet."""
    with _lock:
        if not USERS_FILE.exists():
            return {}
        users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        changed = False
        for info in users.values():
            if "token" in info:                       # eski biçim → özet
                info["token_hash"] = hash_token(info.pop("token"))
                changed = True
        if changed:
            _save(users)
        return users


def save(users: dict):
    with _lock:
        _save(users)


def public(username: str, info: dict) -> dict:
    """Dışarı verilebilen alanlar (token özeti hariç)."""
    return {"username": username, "role": info.get("role", "user"), "active": info.get("active", True),
            "created_at": info.get("created_at"), "last_login": info.get("last_login"),
            "token_rotated_at": info.get("token_rotated_at")}


def verify(username: str, token: str) -> dict | None:
    """Kullanıcı adı + token doğruysa ve hesap etkinse kullanıcı kaydı, değilse None."""
    info = load().get((username or "").strip().lower())
    if not info or not token or not info.get("active", True):
        return None
    return info if _matches(info.get("token_hash", ""), token) else None


def verify_any(token: str) -> str | None:
    """Yalnızca token ile (MCP): eşleşen etkin kullanıcının adı."""
    if not token:
        return None
    for u, info in load().items():
        if info.get("active", True) and _matches(info.get("token_hash", ""), token):
            return u
    return None


def session_ok(username: str, token_version) -> bool:
    """Oturum hâlâ geçerli mi: kullanıcı var, etkin ve token sürümü değişmemiş."""
    info = load().get(username or "")
    return bool(info and info.get("active", True) and int(token_version or 0) == int(info.get("token_version", 0)))


def token_version(username: str) -> int:
    return int(load().get(username, {}).get("token_version", 0))


def touch_login(username: str):
    with _lock:
        users = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        if username in users:
            users[username]["last_login"] = _now()
            _save(users)


def _admins(users: dict) -> list:
    return [u for u, i in users.items() if i.get("role") == "admin" and i.get("active", True)]


def create(username: str, role: str = "user") -> str:
    """Yeni kullanıcı; üretilen token'ı döndürür (bir kez gösterilir)."""
    username = (username or "").strip().lower()
    if not _NAME_RE.fullmatch(username):
        raise UserError("Username must be 2–32 characters: lowercase letters, digits, . _ - (starting with a letter or digit)")
    if role not in ROLES:
        raise UserError("Invalid role")
    users = load()
    if username in users:
        raise UserError("'{name}' already exists", name=username)
    token = new_token()
    users[username] = {"role": role, "active": True, "token_hash": hash_token(token), "token_version": 0,
                       "created_at": _now(), "token_rotated_at": _now()}
    save(users)
    return token


def reset_token(username: str) -> str:
    """Yeni token üret; eski token ve onunla açılmış bütün oturumlar geçersiz olur."""
    users = load()
    if username not in users:
        raise UserError("User not found")
    token = new_token()
    users[username]["token_hash"] = hash_token(token)
    users[username]["token_version"] = int(users[username].get("token_version", 0)) + 1
    users[username]["token_rotated_at"] = _now()
    save(users)
    return token


def set_role(username: str, role: str):
    users = load()
    if username not in users:
        raise UserError("User not found")
    if role not in ROLES:
        raise UserError("Invalid role")
    if users[username].get("role") == "admin" and role != "admin" and _admins(users) == [username]:
        raise UserError("The last admin cannot be demoted — make another user admin first")
    users[username]["role"] = role
    save(users)


def set_active(username: str, active: bool, actor: str | None = None):
    users = load()
    if username not in users:
        raise UserError("User not found")
    if not active:
        if username == actor:
            raise UserError("You cannot deactivate your own account")
        if users[username].get("role") == "admin" and _admins(users) == [username]:
            raise UserError("The last admin cannot be deactivated")
    users[username]["active"] = bool(active)
    save(users)
