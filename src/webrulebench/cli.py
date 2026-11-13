"""
webrulebench — command line (installed with pip install -e .; or python -m webrulebench)

    webrulebench serve [--port 5001] [--host 127.0.0.1] [--data DIR] [--no-debug]
    webrulebench demo  [--port 5002] [--rebuild]           # reviewer demo (no LLM needed)
    webrulebench users list | create-admin <name> | create <name> [--role] | reset-token <name> | activate|deactivate <name>
    webrulebench --version

Options are turned into environment variables (WRB_DATA_DIR, WRB_PORT, WRB_HOST, WRB_DEBUG; see paths.py).
Because the data folder is determined when webrulebench.paths is loaded, the environment variables are set
before the project modules are imported.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from webrulebench import __version__

_PROJECT_DIR = Path(__file__).resolve().parents[2]   # src/webrulebench/cli.py → repository root


def _demo_dir() -> Path:
    """Same as paths.default_demo_dir() (here so that paths is not loaded early)."""
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

    d = sub.add_parser("demo", help="self-contained demo: synthetic sites, no LLM needed")
    d.add_argument("--port", type=int, default=5002)
    d.add_argument("--rebuild", action="store_true", help="recreate the demo data folder")

    sub.add_parser("users", help="user management (see 'webrulebench users -h')", add_help=False)

    if argv[:1] == ["users"]:                       # leave argument parsing to manage_users
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
