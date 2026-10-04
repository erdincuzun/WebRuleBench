"""
llm_models.py
=============
LLM backend kaydı — URL, API tipi, modeller, anahtar değişkeni, üretim parametreleri.

Kayıt veri klasöründeki llm_models.json dosyasında tutulur ve arayüzdeki
"⚙ LLM Modelleri" sayfasından düzenlenir. Dosya yoksa aşağıdaki varsayılanlar
kullanılır (ilk kayıtta dosyaya yazılır).

API tipleri (çağrının biçimi — llm_extractor bu tipe göre çağırır):
  ollama     yerel Ollama /api/chat
  anthropic  Anthropic Messages API
  gemini     Google Generative Language generateContent ({model} URL'de)
  openai     OpenAI uyumlu /chat/completions (Groq, NVIDIA NIM, OpenRouter, vLLM, LM Studio …)

API anahtarları burada DEĞİL: env_key yalnızca değişkenin adıdır; değer ortam
değişkeninden ya da proje kökündeki .env dosyasından okunur (llm_extractor._api_key).

Kullanım:
  from webrulebench.pipeline.llm_models import BACKENDS, default_model
  cfg = BACKENDS["nvidia"]
  cfg["api"], cfg["url"], cfg["default_model"], cfg["env_key"], cfg["params"]
"""

import copy
import json

from webrulebench.paths import DATA_DIR
MODELS_FILE = DATA_DIR / "llm_models.json"
# replay: kayıtlı yanıtları geri oynatan sahte backend (hakem demosu, testler); url = yanıt dosyası (veri klasörüne göre)
API_TYPES   = ("ollama", "anthropic", "gemini", "openai", "replay")

# Varsayılanlar: bu dosya json'a taşınmadan önceki davranışın aynısı (üretim parametreleri dahil),
# böylece eski deney sonuçlarıyla karşılaştırılabilirlik korunur.
_DEFAULTS: dict[str, dict] = {
    "ollama": {
        "api":           "ollama",
        "url":           "http://localhost:11434/api/chat",
        "default_model": "qwen2.5-coder:14b",
        "models":        [],
        "env_key":       None,  # lokal, key gerekmez
        "notes":         "Local Ollama server",
        "params":        {"temperature": 0.0, "max_tokens": 512, "seed": 42, "num_ctx": 16384},
    },
    "claude": {
        "api":           "anthropic",
        "url":           "https://api.anthropic.com/v1/messages",
        "default_model": "claude-sonnet-4-6",
        "models":        [],
        "env_key":       "ANTHROPIC_API_KEY",
        "notes":         "Anthropic Claude API",
        "params":        {"max_tokens": 512},
    },
    "gemini": {
        "api":           "gemini",
        "url":           "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "default_model": "gemini-2.5-flash-lite",
        "models":        [],
        "env_key":       "GEMINI_API_KEY",
        "notes":         "Google Gemini AI Studio",
        "params":        {"temperature": 0.1, "max_tokens": 512},
    },
    "groq": {
        "api":           "openai",
        "url":           "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "models":        [],
        "env_key":       "GROQ_API_KEY",
        "notes":         "Groq — OpenAI-compatible, fast inference",
        "params":        {"temperature": 0.0, "max_tokens": 512},
    },
    "nvidia": {
        "api":           "openai",
        "url":           "https://integrate.api.nvidia.com/v1",
        "default_model": "qwen/qwen3-coder-480b-a35b-instruct",
        "env_key":       "NVIDIA_API_KEY",
        "notes":         "NVIDIA NIM — OpenAI-compatible, 40 requests per minute limit",
        "models": [
            "qwen/qwen3-coder-480b-a35b-instruct",
            "nicoboss/DeepSeek-R1-Distill-Qwen-32B-Uncensored",
            "meta/llama-3.3-70b-instruct",
            "mistralai/mistral-7b-instruct-v0.3",
            "microsoft/phi-3-medium-128k-instruct",
        ],
        "params":        {"temperature": 0.7, "top_p": 0.8, "max_tokens": 4096},
    },
}


def _load() -> dict:
    try:
        data = json.loads(MODELS_FILE.read_text(encoding="utf-8")).get("backends")
        if isinstance(data, dict) and data:
            return data
    except (FileNotFoundError, ValueError):
        pass
    return copy.deepcopy(_DEFAULTS)


# Modül düzeyinde tek sözlük; reload()/save() onu YERİNDE günceller, böylece
# `from llm_models import BACKENDS` yapan modüller değişikliği hemen görür.
BACKENDS: dict[str, dict] = _load()


def reload() -> dict:
    fresh = _load()
    BACKENDS.clear()
    BACKENDS.update(fresh)
    return BACKENDS


def save(backends: dict):
    MODELS_FILE.write_text(json.dumps({"backends": backends}, ensure_ascii=False, indent=2), encoding="utf-8")
    reload()


PARAM_KEYS = {"temperature": float, "top_p": float, "max_tokens": int, "seed": int, "num_ctx": int}


def effective_params(backend: str, model: str | None = None) -> dict:
    """Backend varsayılanları + o modele özel üzerine yazılanlar (model_params)."""
    cfg = BACKENDS.get(backend) or {}
    model = model or cfg.get("default_model")
    return {**(cfg.get("params") or {}), **((cfg.get("model_params") or {}).get(model) or {})}


def default_model(backend: str) -> str:
    """Backend adına göre varsayılan modeli döndür."""
    return BACKENDS.get(backend, {}).get("default_model", "")


def backend_url(backend: str, model: str = None) -> str:
    """Backend URL'ini döndür (Gemini için model adını yerleştirir)."""
    url = BACKENDS.get(backend, {}).get("url", "")
    if "{model}" in url:
        url = url.format(model=model or default_model(backend))
    return url


def list_backends() -> list[str]:
    return list(BACKENDS.keys())


# ---------------------------------------------------------------------------
# Ollama: model listesinin kaynağı makinenin kendisi (/api/tags).
# Kayıtta yalnızca seçimler tutulur: default_model, hidden (formlarda gizlenen),
# models (kayıtlı modeller — makinede yoksa "yüklü değil" uyarısı için).
# ---------------------------------------------------------------------------
def _ollama_base(cfg: dict) -> str:
    from urllib.parse import urlparse
    u = urlparse(cfg.get("url", ""))
    return f"{u.scheme}://{u.netloc}"


def ollama_installed(cfg: dict, timeout: float = 2.0) -> list | None:
    """Makinede yüklü modeller ve bilgileri; Ollama'ya ulaşılamazsa None."""
    import requests
    try:
        r = requests.get(_ollama_base(cfg) + "/api/tags", timeout=timeout)
        r.raise_for_status()
    except Exception:
        return None
    out = []
    for m in r.json().get("models", []):
        d = m.get("details") or {}
        out.append({
            "name":          m.get("name"),
            "digest":        m.get("digest"),
            "size":          m.get("size"),
            "modified_at":   m.get("modified_at"),
            "family":        d.get("family"),
            "parameter_size": d.get("parameter_size"),
            "quantization":  d.get("quantization_level"),
            "context_length": d.get("context_length"),
            "capabilities":  m.get("capabilities") or [],
        })
    return sorted(out, key=lambda x: x["name"] or "")


def model_catalog(name: str, timeout: float = 2.0) -> dict:
    """Bir backend'in model kataloğu.
    {models: [{name, installed, hidden, default, info}], reachable: bool|None}
    Ollama: yüklü ∪ kayıtlı; diğerleri: kayıtlı liste (reachable=None)."""
    cfg = BACKENDS.get(name) or {}
    default, hidden = cfg.get("default_model"), set(cfg.get("hidden") or [])
    registered = [m for m in dict.fromkeys([default, *(cfg.get("models") or [])]) if m]
    if cfg.get("api") != "ollama":
        return {"reachable": None,
                "models": [{"name": m, "installed": None, "hidden": m in hidden, "default": m == default, "info": None}
                           for m in registered]}
    inst = ollama_installed(cfg, timeout)
    by_name = {m["name"]: m for m in (inst or [])}
    names = list(dict.fromkeys([*by_name, *registered]))
    return {"reachable": inst is not None,
            "models": [{"name": m, "installed": (m in by_name) if inst is not None else None,
                        "hidden": m in hidden, "default": m == default, "info": by_name.get(m)} for m in names]}


def available_models(name: str, timeout: float = 2.0) -> list:
    """Formlarda sunulacak modeller: gizliler hariç; Ollama'da makinede olmayanlar hariç (ulaşılabiliyorsa)."""
    cat = model_catalog(name, timeout)
    return [m["name"] for m in cat["models"] if not m["hidden"] and m["installed"] is not False]
