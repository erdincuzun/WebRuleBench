"""
webrulebench/webapp/routes/llm.py — LLM Modelleri (backend kayıt defteri, .env anahtarları, bağlantı testi) ve MCP ayarı.
"""
from flask import Blueprint

from webrulebench.webapp.core import *  # noqa: F401,F403 — paylaşılan yardımcılar, yollar, kimlik doğrulama

bp = Blueprint("llm", __name__)


@bp.route("/api/llm-models")
def api_llm_models():
    _, err = require_login()
    if err: return err
    from webrulebench.pipeline import llm_models as LM
    LM.reload()
    return Response(json.dumps({"backends": [_public_backend(n, c, catalog=True) for n, c in LM.BACKENDS.items()],
                                "api_types": list(LM.API_TYPES), "file": LM.MODELS_FILE.name},
                               ensure_ascii=False), mimetype="application/json")


@bp.route("/api/llm-models/<name>", methods=["PUT"])
def api_llm_models_save(name):
    """Backend ekle/düzenle (admin). Body: {api, url, default_model, models, env_key, notes, params, api_key?, rename?}"""
    username, err = require_admin()
    if err: return err
    import re as _re
    from webrulebench.pipeline import llm_models as LM
    body = request.get_json(silent=True) or {}
    new_name = (body.get("rename") or name).strip().lower()
    if not _re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", new_name):
        return jsonify({"success": False, "error": _t("Name may only contain lowercase letters, digits, - and _ (max. 32 characters)")}), 400
    api = body.get("api")
    if api not in LM.API_TYPES:
        return jsonify({"success": False, "error": _t("Invalid API type")}), 400
    url = (body.get("url") or "").strip()
    if api == "replay":                      # kayıt dosyası (veri klasöründe), ağ adresi değil
        if not _re.fullmatch(r"[\w./-]+\.json", url) or ".." in url:
            return jsonify({"success": False, "error": _t("A replay backend needs a JSON file name in the data folder")}), 400
    elif not _re.match(r"https?://", url):
        return jsonify({"success": False, "error": _t("URL must start with http:// or https://")}), 400
    env_key = (body.get("env_key") or "").strip() or None
    if env_key and not _re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", env_key):
        return jsonify({"success": False, "error": _t("Key variable must consist of uppercase letters, digits and _ (e.g. OPENROUTER_API_KEY)")}), 400
    if api not in ("ollama", "replay") and not env_key and not _re.match(r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)[:/]", url):
        return jsonify({"success": False, "error": _t("A key variable is required for a remote API")}), 400
    params = {}
    for k, typ in (("temperature", float), ("top_p", float), ("max_tokens", int), ("seed", int), ("num_ctx", int)):
        v = (body.get("params") or {}).get(k)
        if v not in (None, ""):
            try:
                params[k] = typ(v)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": _t("{name} must be a number", name=k)}), 400
    models = [m.strip() for m in (body.get("models") or []) if isinstance(m, str) and m.strip()]
    default = (body.get("default_model") or "").strip() or (models[0] if models else "")
    if not default:
        return jsonify({"success": False, "error": _t("A default model is required")}), 400

    backends = copy.deepcopy(LM.BACKENDS)
    if new_name != name and new_name in backends:
        return jsonify({"success": False, "error": _t("'{name}' already exists", name=new_name)}), 409
    backends.pop(name, None)
    old = LM.BACKENDS.get(name) or {}
    hidden = body.get("hidden") if isinstance(body.get("hidden"), list) else old.get("hidden") or []
    model_params = old.get("model_params") or {}
    backends[new_name] = {"api": api, "url": url, "default_model": default, "models": list(dict.fromkeys(models)),
                          "hidden": [h for h in hidden if isinstance(h, str)], "model_params": model_params,
                          "env_key": env_key, "notes": (body.get("notes") or "").strip(), "params": params}
    LM.save(backends)
    api_key = (body.get("api_key") or "").strip()
    if api_key and env_key:
        _set_env_key(env_key, api_key)
    _audit(f"LLM_MODEL_SAVE  backend={new_name}  api={api}  user={username}" + ("  key=updated" if api_key else ""))
    return jsonify({"success": True, "backend": _public_backend(new_name, LM.BACKENDS[new_name])})


@bp.route("/api/llm-models/<name>", methods=["DELETE"])
def api_llm_models_delete(name):
    username, err = require_admin()
    if err: return err
    from webrulebench.pipeline import llm_models as LM
    backends = copy.deepcopy(LM.BACKENDS)
    if name not in backends:
        return jsonify({"success": False, "error": _t("Backend not found")}), 404
    if len(backends) == 1:
        return jsonify({"success": False, "error": _t("The last backend cannot be deleted")}), 400
    del backends[name]
    LM.save(backends)
    _audit(f"LLM_MODEL_DELETE  backend={name}  user={username}")   # .env'deki anahtar silinmez
    return jsonify({"success": True})


@bp.route("/api/llm-models/<name>/test", methods=["POST"])
def api_llm_models_test(name):
    """Bağlantı testi: küçük bir istek (herkes). Body: {model?}"""
    _, err = require_login()
    if err: return err
    import time as _time
    from webrulebench.pipeline import llm_models as LM
    from webrulebench.pipeline.llm_extractor import LLMExtractor
    LM.reload()
    if name not in LM.BACKENDS:
        return jsonify({"success": False, "error": _t("Backend not found")}), 404
    model = ((request.get_json(silent=True) or {}).get("model") or "").strip() or None
    ex = LLMExtractor(backend=name, model=model, timeout=30,
                      system_prompt="You are a connectivity test. Reply with exactly: OK")
    t0 = _time.perf_counter()
    text, error, ptok, gtok = ex._call_llm("Reply with exactly: OK")
    ms = round((_time.perf_counter() - t0) * 1000)
    return jsonify({"success": not error and bool(text.strip()), "model": ex.model, "ms": ms,
                    "reply": (text or "").strip()[:200], "error": error or ("" if text.strip() else _t("Empty response")),
                    "prompt_tokens": ptok, "gen_tokens": gtok})


@bp.route("/api/llm-models/<name>/model", methods=["POST"])
def api_llm_models_model(name):
    """Tek model işlemi (admin): {model, action: default | hide | show | params, params?}.
    params: modele özel üretim parametreleri (boş değer = backend'inkini kullan; hepsi boş = sıfırla)."""
    username, err = require_admin()
    if err: return err
    from webrulebench.pipeline import llm_models as LM
    body   = request.get_json(silent=True) or {}
    model  = (body.get("model") or "").strip()
    action = body.get("action")
    backends = copy.deepcopy(LM.BACKENDS)
    c = backends.get(name)
    if not c or not model:
        return jsonify({"success": False, "error": _t("Backend or model not found")}), 404
    hidden = [h for h in (c.get("hidden") or []) if h != model]
    if action == "default":
        c["default_model"] = model
    elif action == "hide":
        if model == c.get("default_model"):
            return jsonify({"success": False, "error": _t("The default model cannot be hidden")}), 400
        hidden.append(model)
    elif action == "params":
        mp = {}
        for k, typ in LM.PARAM_KEYS.items():
            v = (body.get("params") or {}).get(k)
            if v in (None, ""):
                continue
            try:
                mp[k] = typ(v)
            except (TypeError, ValueError):
                err = _t("{name} must be true or false", name=k) if k == "think" else _t("{name} must be a number", name=k)
                return jsonify({"success": False, "error": err}), 400
        allp = dict(c.get("model_params") or {})
        if mp:
            allp[model] = mp
        else:
            allp.pop(model, None)
        c["model_params"] = allp
    elif action != "show":
        return jsonify({"success": False, "error": _t("Unknown action")}), 400
    c["hidden"] = hidden
    LM.save(backends)
    _audit(f"LLM_MODEL_{action.upper()}  backend={name}  model={model}  user={username}"
           + (f"  params={c.get('model_params', {}).get(model)}" if action == "params" else ""))
    return jsonify({"success": True})


@bp.route("/api/mcp_config", methods=["GET"])
def api_get_mcp_config():
    """MCP config'i döndür (backend, model, strategy)."""
    from webrulebench.pipeline.llm_models import BACKENDS
    if MCP_CONFIG_FILE.exists():
        cfg = json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8"))
    else:
        cfg = {"backend": "ollama", "model": None, "strategy": "whitelist"}
    return jsonify({**cfg, "backends": list(BACKENDS.keys())})


@bp.route("/api/mcp_config/save", methods=["POST"])
def api_save_mcp_config():
    """MCP config'i kaydet (admin only)."""
    _, err = require_admin()
    if err: return err
    from webrulebench.pipeline.llm_models import BACKENDS
    data     = request.json or {}
    backend  = data.get("backend", "ollama")
    if backend not in BACKENDS:
        return jsonify({"success": False, "error": _t("Invalid backend")}), 400
    cfg = {
        "backend":  backend,
        "model":    data.get("model") or None,
        "strategy": data.get("strategy", "whitelist"),
    }
    MCP_CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return jsonify({"success": True, "config": cfg})
