"""
paths.py
========
Kod ile veriyi ayırır.

  webrulebench/defaults/   pakette gelen varsayılanlar (şablonlar, prompt varyantları, LLM kayıt defteri, ...)
  data/                    kullanıcının verisi (sayfalar, annotation'lar, GT, deneyler, kullanıcılar, .env);
                           git'e girmez. Eksik ayar dosyaları ilk kullanımda defaults/'tan kopyalanır.

Depo klonundan çalışırken veri klasörü <depo>/data, hakem demosu <depo>/demo/data'dır; paket depo
dışında kuruluysa çalışma klasöründeki webrulebench-data/ ve webrulebench-demo/ kullanılır.
WRB_DATA_DIR ile başka bir veri klasörü verilebilir:

    WRB_DATA_DIR=~/my-study webrulebench serve

Ortam değişkenleri (eski LLMWB_* adları da geçerlidir):
    WRB_DATA_DIR   veri klasörü               (varsayılan: <depo>/data)
    WRB_PORT       sunucu portu               (5001)
    WRB_HOST       dinlenecek adres           (127.0.0.1; Docker'da 0.0.0.0)
    WRB_DEBUG      0 → Flask debug kapalı     (1)
"""

import os
import shutil
from pathlib import Path


def env(name: str, default: str | None = None) -> str | None:
    """WRB_<name>; yoksa eski ad LLMWB_<name>; yoksa default."""
    return os.environ.get(f"WRB_{name}") or os.environ.get(f"LLMWB_{name}") or default


CODE_DIR     = Path(__file__).resolve().parent              # webrulebench/ paketi
PROJECT_DIR  = CODE_DIR.parents[1]                          # depo kökü (klondan çalışırken: src/webrulebench → kök)
IN_CHECKOUT  = (PROJECT_DIR / "pyproject.toml").exists()
DEFAULTS_DIR = CODE_DIR / "defaults"


def default_data_dir() -> Path:
    return PROJECT_DIR / "data" if IN_CHECKOUT else Path.cwd() / "webrulebench-data"


def default_demo_dir() -> Path:
    return PROJECT_DIR / "demo" / "data" if IN_CHECKOUT else Path.cwd() / "webrulebench-demo"


DATA_DIR = Path(env("DATA_DIR") or default_data_dir()).expanduser().resolve()

# defaults/'taki dosyalar veri klasöründe yoksa kopyalanır (var olanlara dokunulmaz)
DEFAULT_FILES = ("layout_templates.json", "template_prompts.json", "llm_models.json", "mcp_config.json", "sites.json")


def ensure_data_dir(data_dir: Path = DATA_DIR) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in DEFAULT_FILES:
        src, dst = DEFAULTS_DIR / name, data_dir / name
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)
    return data_dir


ensure_data_dir()
