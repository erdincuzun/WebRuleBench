"""
webrulebench — komut satırı (pip install -e . ile kurulur; ya da python -m webrulebench)

    webrulebench serve [--port 5001] [--host 127.0.0.1] [--data DIR] [--no-debug]
    webrulebench demo  [--port 5002] [--rebuild]           # hakem demosu (LLM gerekmez)
    webrulebench users list | create-admin <ad> | create <ad> [--role] | reset-token <ad> | activate|deactivate <ad>
    webrulebench --version

Seçenekler ortam değişkenlerine çevrilir (WRB_DATA_DIR, WRB_PORT, WRB_HOST, WRB_DEBUG; bkz. paths.py).
Veri klasörü webrulebench.paths yüklenirken belirlendiğinden, ortam değişkenleri proje modülleri
import edilmeden önce ayarlanır.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from webrulebench import __version__

_PROJECT_DIR = Path(__file__).resolve().parents[2]   # src/webrulebench/cli.py → depo kökü


def _demo_dir() -> Path:
    """paths.default_demo_dir() ile aynı (paths'i erken yüklememek için burada)."""
    if (_PROJECT_DIR / "pyproject.toml").exists():
        return _PROJECT_DIR / "demo" / "data"
    return Path.cwd() / "webrulebench-demo"


def _serve():
    from webrulebench.webapp.app import main
    main()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="webrulebench", description="WebRuleBench — benchmark LLM-generated web extraction rules")
    ap.add_argument("--version", action="version", version=f"WebRuleBench {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="start the web application")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--host", default=None)
    s.add_argument("--data", default=None, help="data folder (default: data/)")
    s.add_argument("--no-debug", action="store_true")

    d = sub.add_parser("demo", help="reviewer demo: synthetic sites, no LLM needed")
    d.add_argument("--port", type=int, default=5002)
    d.add_argument("--rebuild", action="store_true", help="recreate the demo data folder")

    sub.add_parser("users", help="user management (see 'webrulebench users -h')", add_help=False)

    if argv[:1] == ["users"]:                       # ayrıştırmayı manage_users'a bırak
        from webrulebench.webapp.manage_users import main as users_main
        return users_main(argv[1:])
    a = ap.parse_args(argv)

    if a.cmd == "serve":
        if a.data:
            os.environ["WRB_DATA_DIR"] = str(Path(a.data).expanduser().resolve())
        if a.port:
            os.environ["WRB_PORT"] = str(a.port)
        if a.host:
            os.environ["WRB_HOST"] = a.host
        if a.no_debug:
            os.environ["WRB_DEBUG"] = "0"
        return _serve()

    if a.cmd == "demo":
        demo_dir = _demo_dir()
        os.environ["WRB_DATA_DIR"] = str(demo_dir)
        if a.rebuild or not demo_dir.exists():
            from webrulebench.demo.setup_demo import main as setup
            setup(["--dir", str(demo_dir)] + (["--force"] if demo_dir.exists() else []))
        else:
            print(f"Using existing {demo_dir} (login: {demo_dir / 'REVIEWER_LOGIN.txt'}); --rebuild to recreate.")
        os.environ["WRB_PORT"] = str(a.port)
        os.environ.setdefault("WRB_DEBUG", "0")
        return _serve()


if __name__ == "__main__":
    main()
