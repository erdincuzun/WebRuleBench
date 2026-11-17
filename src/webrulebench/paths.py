"""
paths.py
========
Separates code from data.

  webrulebench/defaults/   defaults shipped with the package (templates, prompt variants, LLM registry, ...)
  data/                    the user's data (pages, annotations, GT, experiments, users, .env);
                           not tracked by git. Missing settings files are copied from defaults/ on first use.

When running from a repository clone, the data folder is <repo>/data and the reviewer demo is <repo>/demo/data;
if the package is installed outside the repository, webrulebench-data/ and webrulebench-demo/ in the working
folder are used.
Another data folder can be given with WRB_DATA_DIR:

    WRB_DATA_DIR=~/my-study webrulebench serve

Environment variables (the old LLMWB_* names are also accepted):
    WRB_DATA_DIR   data folder                (default: <repo>/data)
    WRB_PORT       server port                (5001)
    WRB_HOST       address to listen on       (127.0.0.1; 0.0.0.0 in Docker)
    WRB_DEBUG      1 → Flask debug on         (0; never on a reachable server)
"""

import os
import shutil
from pathlib import Path


def env(name: str, default: str | None = None) -> str | None:
    """WRB_<name>; otherwise the old name LLMWB_<name>; otherwise default."""
    return os.environ.get(f"WRB_{name}") or os.environ.get(f"LLMWB_{name}") or default


CODE_DIR     = Path(__file__).resolve().parent              # the webrulebench/ package
PROJECT_DIR  = CODE_DIR.parents[1]                          # repository root (when running from a clone: src/webrulebench → root)
IN_CHECKOUT  = (PROJECT_DIR / "pyproject.toml").exists()
DEFAULTS_DIR = CODE_DIR / "defaults"


def default_data_dir() -> Path:
    return PROJECT_DIR / "data" if IN_CHECKOUT else Path.cwd() / "webrulebench-data"


def default_demo_dir() -> Path:
    return PROJECT_DIR / "demo" / "data" if IN_CHECKOUT else Path.cwd() / "webrulebench-demo"


DATA_DIR = Path(env("DATA_DIR") or default_data_dir()).expanduser().resolve()

# files in defaults/ are copied if missing from the data folder (existing ones are not touched)
DEFAULT_FILES = ("layout_templates.json", "template_prompts.json", "llm_models.json", "mcp_config.json", "sites.json")


def ensure_data_dir(data_dir: Path = DATA_DIR) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in DEFAULT_FILES:
        src, dst = DEFAULTS_DIR / name, data_dir / name
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)
    return data_dir


ensure_data_dir()


def safe_name(name) -> bool:
    """True for a single path component that cannot leave its folder: a domain, a page file name or a layout id.
    Rejects empty values, '.', '..', path separators, NUL and drive prefixes; used for every value from a request."""
    return (isinstance(name, str) and name not in ("", ".", "..") and not any(c in name for c in "/\\\0:")
            and len(name) <= 255)


def inside(path, folder) -> bool:
    """True if path, resolved, lies inside folder (resolved)."""
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except ValueError:
        return False
