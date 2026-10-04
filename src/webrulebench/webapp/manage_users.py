"""
manage_users.py
===============
Sunucu makinesinde kullanıcı yönetimi — özellikle tek admin token'ını unuttuğunda
kurtarma ve ilk kurulum için (web arayüzünde "şifremi unuttum" bilerek yok).

Kullanım:
  webrulebench users list
  webrulebench users create-admin <kullanıcı>      # ilk kurulum ya da yeni admin
  webrulebench users create <kullanıcı> [--role user|admin]
  webrulebench users reset-token <kullanıcı>       # yeni token; eski token ve oturumlar geçersiz
  webrulebench users activate|deactivate <kullanıcı>

Token yalnızca bir kez ekrana yazılır; <veri klasörü>/users.json'da özet olarak saklanır.
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # doğrudan çalıştırma: src/
from webrulebench import users_store as U  # noqa: E402

from webrulebench.paths import DATA_DIR  # noqa: E402
AUDIT_LOG = DATA_DIR / "dataset" / "deletion_audit.log"


def _audit(msg: str):
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}  by=cli\n")


def _show_token(user: str, token: str):
    print(f"\n  User : {user}\n  Token: {token}\n")
    print("  This token will not be shown again — pass it on to the person securely.\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="WebRuleBench user management (server side)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list users (without tokens)")
    for name in ("create-admin", "reset-token", "activate", "deactivate"):
        sub.add_parser(name).add_argument("username")
    c = sub.add_parser("create")
    c.add_argument("username")
    c.add_argument("--role", default="user", choices=U.ROLES)
    a = ap.parse_args(argv)

    try:
        if a.cmd == "list":
            users = U.load()
            if not users:
                print("No users — for the first admin: webrulebench users create-admin <name>")
            for u, i in sorted(users.items()):
                p = U.public(u, i)
                print(f"  {u:20} {p['role']:6} {'active' if p['active'] else 'INACTIVE':8} "
                      f"last login: {(p['last_login'] or '—')[:16]}")
        elif a.cmd in ("create-admin", "create"):
            role = "admin" if a.cmd == "create-admin" else a.role
            token = U.create(a.username, role)
            _audit(f"USER_CREATE  user={a.username.lower()}  role={role}")
            _show_token(a.username.lower(), token)
        elif a.cmd == "reset-token":
            token = U.reset_token(a.username)
            _audit(f"USER_TOKEN_RESET  user={a.username}")
            _show_token(a.username, token)
            print("  The old token and the sessions opened with it are no longer valid.")
        elif a.cmd in ("activate", "deactivate"):
            U.set_active(a.username, a.cmd == "activate")
            _audit(f"USER_{a.cmd.upper()}  user={a.username}")
            print(f"  {a.username}: {'active' if a.cmd == 'activate' else 'inactive'}")
    except U.UserError as e:
        sys.exit(f"Error: {e}")


if __name__ == "__main__":
    main()
