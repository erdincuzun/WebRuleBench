"""
experiments.py
==============
LLM değerlendirme deneyleri (WebRuleBench 5. bölüm).

Bir deney = sabit bir yapılandırmanın (backend/model, kural dili, prompt,
temizleme stratejisi, kural kaynağı) seçilen layout'lara uygulanması:

  her layout için
    1. örnek sayfa seçilir (ilk GT sayfası ya da seed'li rastgele)
    2. sayfa temizlenir → yapısal iskelet → LLM bir kez çağrılır → kural seti
       (kural kaynağı "llm_css_regexn" ise LLM CSS üretir, regex_generator
        yalnızca örnek sayfayı kullanarak regex'e çevirir)
    3. kurallar layout'un TÜM GT sayfalarında LLM'siz çalıştırılır ve alan bazında
       GT içeriğiyle (GT'nin CSS kuralının çıkardığı değer) şablon metriğiyle skorlanır
    → örnek sayfa skoru ile diğer sayfaların skoru (genelleme) ayrı raporlanır.

Deney experiments/<id>.json dosyasına her layout'tan sonra yazılır: yapılandırma,
kullanılan prompt'ların tam metni, üretilen kurallar, sayfa × alan skorları,
token/süre. Yarıda kalan deney kaldığı yerden sürdürülebilir (tamamlanan
layout'lar atlanır).
"""

from __future__ import annotations

import json
import random
import re
import secrets
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from webrulebench.paths import DATA_DIR as ROOT   # veri klasörü (WRB_DATA_DIR ya da proje kökü)
EXP_DIR       = ROOT / "experiments"
RAW_DIR       = ROOT / "dataset" / "raw"
GT_DIR        = ROOT / "ground_truth" / "approved"
TEMPLATES     = ROOT / "layout_templates.json"
PROMPTS_FILE  = ROOT / "template_prompts.json"

RULE_TYPES    = ("css", "xpath", "regex")
RULE_SOURCES  = ("llm", "llm_css_regexn")
MATCH_AT      = 0.9

_lock    = threading.Lock()
_running = {}          # id → {"thread", "cancel": Event}
_queued  = set()       # grup kuyruğunda sırasını bekleyen deney id'leri
_groups  = {}          # grup id → cancel Event (çalışan grup)
_quick   = {}          # hızlı test belirteci → {user, at, payload} (kaydedilene kadar bellekte)
UI_STRATEGIES = ("whitelist", "raw_regex")     # arayüzde sunulan temizleme stratejileri


# ---------------------------------------------------------------------------
# yardımcılar
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return default


def _templates() -> dict:
    return _load_json(TEMPLATES, {}).get("templates", {})


def _rule_of(v, lang: str):
    if isinstance(v, dict):
        return v.get(lang) or ""
    if lang != "css":
        return ""
    if isinstance(v, list):
        return ", ".join(x for x in v if isinstance(x, str))
    return v or ""


def layout_template_id(layout: dict, templates: dict) -> str:
    """Layout'un şablonu. Eski layout'larda template_id yok, page_type var (article / listing):
    aynı adlı şablon varsa o kullanılır."""
    tid = layout.get("template_id") or ""
    if tid:
        return tid
    pt = layout.get("page_type") or ""
    return pt if pt in templates else ""

class ExperimentError(ValueError):
    """User-facing validation error: English message template + parameters ({name} placeholders).
    str(ex) is the formatted English text; the web app (webrulebench/webapp/core.py) translates it at the API boundary with
    _t(ex.i18n_msg, **ex.i18n_params) (see webrulebench/webapp/i18n/README.md). Subclass of ValueError,
    so existing `except ValueError` handlers keep working."""
    def __init__(self, msg: str, **params):
        self.i18n_msg, self.i18n_params = msg, params
        super().__init__(msg.format(**params) if params else msg)


def exp_path(exp_id: str) -> Path:
    if not re.fullmatch(r"[\w-]+", exp_id or ""):
        raise ExperimentError("Invalid experiment id")
    return EXP_DIR / f"{exp_id}.json"


def load(exp_id: str) -> dict | None:
    e = _load_json(exp_path(exp_id), None)
    if e and e.get("status") in ("queued", "running") and exp_id not in _running and exp_id not in _queued:
        e["status"] = "interrupted"          # sunucu yeniden başladı (ör. debug reloader)
    return e


def save(e: dict):
    EXP_DIR.mkdir(exist_ok=True)
    tmp = exp_path(e["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(exp_path(e["id"]))


def list_all() -> list:
    """Deney özetleri (layout ayrıntıları hariç), yeniden eskiye."""
    out = []
    for p in sorted(EXP_DIR.glob("*.json")):
        e = load(p.stem)
        if not e:
            continue
        out.append({k: e.get(k) for k in ("id", "name", "created_at", "created_by", "status", "progress",
                                          "config", "summary", "error", "finished_at", "group", "kind")})
    return sorted(out, key=lambda x: x.get("created_at") or "", reverse=True)


# ---------------------------------------------------------------------------
# kapsam: değerlendirilebilir layout'lar
# ---------------------------------------------------------------------------
def eligible_layouts(domains: list | None = None, templates: list | None = None) -> list:
    """GT'de CSS kuralı ve en az bir atanmış sayfası olan (şablonlu) layout'lar."""
    out, tmpls = [], _templates()
    for f in sorted(GT_DIR.glob("*.json")):
        gt  = _load_json(f, {})
        dom = f.stem                     # dosya adı esastır (içteki "domain" alanı yanlış kopyalanmış olabilir)
        if domains and dom not in domains:
            continue
        pa = gt.get("page_assignments", {})
        for lid, l in (gt.get("layouts") or {}).items():
            tid = layout_template_id(l, tmpls)
            if not tid or (templates and tid not in templates):
                continue
            if not any(_rule_of(v, "css") for v in (l.get("selectors") or {}).values()):
                continue
            pages = sorted(p for p, v in pa.items() if v.get("layout_id") == lid and not v.get("skipped")
                           and (RAW_DIR / dom / p).is_file())
            if pages:
                out.append({"domain": dom, "layout_id": lid, "name": l.get("name", lid),
                            "template_id": tid, "template_inferred": not l.get("template_id"), "pages": len(pages)})
    return out


# ---------------------------------------------------------------------------
# prompt çözümü
# ---------------------------------------------------------------------------
def resolve_prompt(template: dict, template_id: str, rule_type: str, prompt_id: str | None) -> dict:
    """{source, name, system, user}. prompt_id yoksa / 'auto' ise şablondan otomatik prompt."""
    from webrulebench.pipeline.prompt_builder import build_prompt
    if prompt_id and prompt_id != "auto":
        p = _load_json(PROMPTS_FILE, {}).get("prompts", {}).get(prompt_id)
        if not p or p.get("template_id") != template_id:
            raise ExperimentError("Prompt not found: {id}", id=prompt_id)
        if p.get("rule_type") != rule_type:
            raise ExperimentError("Prompt '{name}' is for {prompt_rule}; the experiment uses {rule}",
                                  name=p.get("name"), prompt_rule=p.get("rule_type"), rule=rule_type)
        return {"source": prompt_id, "name": p.get("name"), "system": p["system_prompt"], "user": p["user_prompt"]}
    b = build_prompt(template, rule_type)
    return {"source": "auto", "name": "Automatic prompt", "system": b["system"], "user": b["user"]}


# ---------------------------------------------------------------------------
# kural çalıştırma ve skorlama
# ---------------------------------------------------------------------------
def _kind(fdef: dict) -> str:
    from webrulebench.rules.regex_generator import KIND_OF_TYPE
    return KIND_OF_TYPE.get(fdef.get("type"), "text")


def rule_values(html: str, soup, rule: str, rule_type: str, kind: str, merge: bool) -> list:
    """Kuralın çıkardığı değerler: metin alanı → eleman metinleri, image/url → src/href listesi."""
    from webrulebench.rules.regex_generator import css_values, regex_values, html_to_text
    if not rule:
        return []
    if rule_type == "css":
        return css_values(soup, rule, kind, merge)
    if rule_type == "regex":
        return regex_values(html, rule, kind)
    # xpath
    from webrulebench.rules.rule_utils import run_xpath
    out = []
    for el in run_xpath(html, rule):
        if isinstance(el, str):
            v = el.strip()
        elif kind == "image":
            v = el.get("src") if el.tag == "img" else next((i.get("src") for i in el.iter("img") if i.get("src")), None)
        elif kind == "url":
            v = el.get("href") or next((a.get("href") for a in el.iter("a") if a.get("href")), None)
        else:
            from lxml import etree
            v = html_to_text(etree.tostring(el, encoding="unicode", method="html"))
        if v and v.strip():
            out.append(v.strip())
    return out


def score_field(gt_vals: list, pred_vals: list, metric: str) -> tuple:
    """(skor | None, etiket). GT boşsa (None, 'NO_GT')."""
    from webrulebench.evaluation.metrics import word_f1_similarity
    if not gt_vals:
        return None, "NO_GT"
    if not pred_vals:
        return 0.0, "MISS"
    if metric == "jaccard":
        a, b = {"".join(v.split()) for v in gt_vals}, {"".join(v.split()) for v in pred_vals}
        s = len(a & b) / len(a | b) if a | b else 0.0
    elif metric == "exact_match":
        s = 1.0 if " ".join(" ".join(gt_vals).split()) == " ".join(" ".join(pred_vals).split()) else 0.0
    else:
        s = word_f1_similarity(" ".join(gt_vals), " ".join(pred_vals))
    return round(s, 4), ("MATCH" if s >= MATCH_AT else "PARTIAL" if s > 0 else "WRONG")


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else None


# ---------------------------------------------------------------------------
# tek layout
# ---------------------------------------------------------------------------
def run_layout(cfg: dict, item: dict, prompts_used: dict) -> dict:
    from bs4 import BeautifulSoup
    from webrulebench.pipeline.html_cleaner import HTMLCleaner
    from webrulebench.pipeline.skeleton import Skeleton
    from webrulebench.pipeline.llm_extractor import LLMExtractor

    dom, lid = item["domain"], item["layout_id"]
    gt     = _load_json(GT_DIR / f"{dom}.json", {})
    layout = gt["layouts"][lid]
    tmpls  = _templates()
    tid    = layout_template_id(layout, tmpls)
    tmpl   = tmpls.get(tid, {})
    fields = tmpl.get("fields") or {}
    pages  = sorted(p for p, v in gt.get("page_assignments", {}).items()
                    if v.get("layout_id") == lid and not v.get("skipped") and (RAW_DIR / dom / p).is_file())
    if cfg.get("max_pages"):
        pages = pages[: int(cfg["max_pages"])]

    smp = cfg.get("sample") or {}
    if smp.get("mode") == "random":
        rnd    = random.Random(f"{smp.get('seed', 0)}|{dom}|{lid}")
        sample = rnd.choice(pages)
    else:
        sample = pages[0]

    rule_type = cfg["rule_type"]
    source    = cfg.get("rule_source", "llm")
    llm_rt    = "css" if source == "llm_css_regexn" else rule_type
    pkey      = f"{tid}|{llm_rt}"
    if pkey not in prompts_used:
        pid = (cfg.get("prompts") or {}).get(tid) if llm_rt == rule_type else None
        prompts_used[pkey] = resolve_prompt(tmpl, tid, llm_rt, pid)
    prompt = prompts_used[pkey]

    # 1-2. örnek sayfa → iskelet → LLM
    html_s  = (RAW_DIR / dom / sample).read_text(encoding="utf-8", errors="ignore")
    cleaned = HTMLCleaner().clean(html_s, strategy=cfg.get("strategy", "whitelist"))
    skel    = Skeleton(strategy="enriched").extract(cleaned.cleaned_html).skeleton_html
    ex = LLMExtractor(backend=cfg["backend"], model=cfg.get("model") or None, rule_type=llm_rt,
                      system_prompt=prompt["system"], user_prompt=prompt["user"], fields=list(fields))
    res   = ex.extract(skel, domain=dom)
    rules = {f: (v if isinstance(v, str) else "") for f, v in (res.selectors or {}).items()}

    generated = {}
    if source == "llm_css_regexn":
        from webrulebench.rules.regex_generator import generate, css_values
        css_rules, rules = rules, {}
        for f, css in css_rules.items():
            if not css:
                continue
            k, m = _kind(fields.get(f, {})), bool(fields.get(f, {}).get("merge"))
            r = generate(css, [html_s], [css_values(html_s, css, k, m)], k)   # yalnızca örnek sayfa
            rules[f] = r["regex"] if r else ""
            # verified: örnek sayfada CSS ile aynı sonucu veriyor mu (değilse en yakın aday seçildi)
            generated[f] = {"css": css, "strategy": r["strategy"] if r else None,
                            "verified": bool(r and r["passed"] == r["total"])}

    # 3. tüm GT sayfalarında skorla (GT içeriği: GT'nin CSS kuralı)
    gt_sels, page_scores = layout.get("selectors") or {}, {}
    for p in pages:
        html = html_s if p == sample else (RAW_DIR / dom / p).read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")
        row  = {}
        for f, fdef in fields.items():
            k, m = _kind(fdef), bool(fdef.get("merge"))
            gt_rule = _rule_of(gt_sels.get(f), "css")
            gt_vals = rule_values(html, soup, gt_rule, "css", k, m) if gt_rule else []
            try:
                pred = rule_values(html, soup, rules.get(f) or "", rule_type, k, m)
            except Exception:
                pred = []
            s, label = score_field(gt_vals, pred, fdef.get("metric", "rouge"))
            row[f] = {"score": s, "label": label}
        page_scores[p] = row

    per_field = {f: _mean(page_scores[p][f]["score"] for p in pages) for f in fields}
    others    = [p for p in pages if p != sample]
    return {
        **item, "template_id": tid, "sample_page": sample, "n_pages": len(pages),
        "prompt_key": pkey, "rules": rules, "regexn": generated or None,
        "llm": {"success": res.success, "error": res.error, "elapsed_ms": round(res.elapsed_ms, 1),
                "prompt_tokens": res.prompt_tokens, "gen_tokens": res.gen_tokens,
                "skeleton_chars": len(skel), "raw_response": (res.raw_response or "")[:4000]},
        "pages": page_scores,
        "summary": {
            "mean":        _mean(v["score"] for p in pages for v in page_scores[p].values()),
            "sample_mean": _mean(v["score"] for v in page_scores[sample].values()),
            "others_mean": _mean(v["score"] for p in others for v in page_scores[p].values()) if others else None,
            "per_field":   per_field,
        },
    }


# ---------------------------------------------------------------------------
# deney özeti
# ---------------------------------------------------------------------------
def summarize(e: dict) -> dict:
    ls = [l for l in e.get("layouts", []) if not l.get("error")]
    per_field, per_template, labels = {}, {}, {}
    for l in ls:
        for f, v in l["summary"]["per_field"].items():
            per_field.setdefault(f, []).append(v)
        per_template.setdefault(l["template_id"], []).append(l["summary"]["mean"])
        for row in l["pages"].values():
            for c in row.values():
                labels[c["label"]] = labels.get(c["label"], 0) + 1
    return {
        "layouts":      len(ls),
        "failed":       sum(1 for l in e.get("layouts", []) if l.get("error")),
        "mean":         _mean(l["summary"]["mean"] for l in ls),
        "sample_mean":  _mean(l["summary"]["sample_mean"] for l in ls),
        "others_mean":  _mean(l["summary"]["others_mean"] for l in ls),
        "per_field":    {f: _mean(v) for f, v in per_field.items()},
        "per_template": {t: _mean(v) for t, v in per_template.items()},
        "labels":       labels,
        "llm_calls":    len(e.get("layouts", [])),
        "prompt_tokens": sum((l.get("llm") or {}).get("prompt_tokens", 0) for l in e.get("layouts", [])),
        "gen_tokens":   sum((l.get("llm") or {}).get("gen_tokens", 0) for l in e.get("layouts", [])),
        "llm_ms":       round(sum((l.get("llm") or {}).get("elapsed_ms", 0) for l in e.get("layouts", [])), 1),
    }


# ---------------------------------------------------------------------------
# oluşturma / çalıştırma
# ---------------------------------------------------------------------------
def validate_config(cfg: dict) -> dict:
    from webrulebench.pipeline.llm_models import BACKENDS
    from webrulebench.pipeline.html_cleaner import STRATEGIES
    c = dict(cfg)
    if c.get("backend") not in BACKENDS:
        raise ExperimentError("Invalid backend")
    if c.get("rule_type") not in RULE_TYPES:
        raise ExperimentError("Invalid rule language")
    c.setdefault("rule_source", "llm")
    if c["rule_source"] not in RULE_SOURCES:
        raise ExperimentError("Invalid rule source")
    if c["rule_source"] == "llm_css_regexn" and c["rule_type"] != "regex":
        raise ExperimentError("LLM CSS → REGEXN is only available in regex experiments")
    c.setdefault("strategy", "whitelist")
    if c["strategy"] not in STRATEGIES:
        raise ExperimentError("Invalid cleaning strategy")
    smp = c.get("sample") or {"mode": "first"}
    if smp.get("mode") not in ("first", "random"):
        raise ExperimentError("Invalid sample page selection")
    if smp["mode"] == "random":
        smp["seed"] = int(smp.get("seed") or 0)
    c["sample"] = smp
    c["delay_s"] = max(0.0, float(c.get("delay_s") or 0))
    c["max_pages"] = int(c["max_pages"]) if c.get("max_pages") else None
    # tekrarlanabilirlik: backend'in o anki API tipi, URL'i ve üretim parametreleri deneye yazılır
    # (ayar sayfasında sonradan değişse de deneyin hangi ayarla çalıştığı bilinir)
    b = BACKENDS[c["backend"]]
    model = c.get("model") or b.get("default_model")
    from webrulebench.pipeline.llm_models import effective_params
    overrides = dict((b.get("model_params") or {}).get(model) or {})
    # params: bu çağrıda gerçekten kullanılan (birleşik) değerler; model_overrides: bunlardan modele özel olanlar
    c["backend_snapshot"] = {"api": b.get("api"), "url": b.get("url"), "params": effective_params(c["backend"], model),
                             "model_overrides": overrides, "model": model}
    if b.get("api") == "ollama":
        # model makinede yoksa deney başlamadan reddedilir; varsa digest ve bilgileri kaydedilir
        # (aynı etiket yeniden çekilirse model dosyası değişebilir — digest hangi dosyanın kullanıldığını sabitler)
        from webrulebench.pipeline.llm_models import model_catalog
        cat = model_catalog(c["backend"])
        if cat["reachable"]:
            m = next((x for x in cat["models"] if x["name"] == model), None)
            if not m or not m["installed"]:
                raise ExperimentError("'{model}' is not installed in this Ollama (ollama pull {model})", model=model)
            c["backend_snapshot"]["model_info"] = {k: m["info"].get(k) for k in
                ("digest", "parameter_size", "quantization", "family", "context_length", "size")}
    return c


def create(name: str, cfg: dict, layouts: list, user: str) -> dict:
    cfg = validate_config(cfg)
    if not layouts:
        raise ExperimentError("Select at least one layout")
    tmpls = _templates()
    llm_rt = "css" if cfg["rule_source"] == "llm_css_regexn" else cfg["rule_type"]
    for tid, pid in (cfg.get("prompts") or {}).items():       # prompt ↔ kural dili uyumu baştan kontrol
        if llm_rt == cfg["rule_type"]:
            resolve_prompt(tmpls.get(tid, {}), tid, llm_rt, pid)
    e = {
        "id":         datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2),
        "name":       name.strip() or f"{cfg['backend']} · {cfg.get('model') or 'default'} · {cfg['rule_type']}",
        "created_at": _now(), "created_by": user,
        "status":     "queued", "config": cfg,
        "scope":      [{"domain": l["domain"], "layout_id": l["layout_id"]} for l in layouts],
        "progress":   {"done": 0, "total": len(layouts)},
        "prompts_used": {}, "layouts": [], "summary": None, "error": None,
    }
    save(e)
    return e


def start(exp_id: str):
    """Arka planda çalıştır (ya da yarıda kalanı sürdür)."""
    with _lock:
        if exp_id in _running:
            return
        cancel = threading.Event()
        t = threading.Thread(target=_worker, args=(exp_id, cancel), daemon=True, name=f"exp-{exp_id}")
        _running[exp_id] = {"thread": t, "cancel": cancel}
    t.start()


def cancel(exp_id: str) -> bool:
    r = _running.get(exp_id)
    if r:
        r["cancel"].set()
    return bool(r)


def _worker(exp_id: str, cancel_ev: threading.Event):
    from bs4 import BeautifulSoup  # noqa: F401 — bağımlılığı erken doğrula
    e = _load_json(exp_path(exp_id), None)
    try:
        cfg  = e["config"]
        done = {(l["domain"], l["layout_id"]) for l in e["layouts"]}
        e["status"] = "running"
        e.setdefault("started_at", _now())
        save(e)
        known = {(x["domain"], x["layout_id"]): x for x in eligible_layouts()}
        for s in e["scope"]:
            key = (s["domain"], s["layout_id"])
            if key in done:
                continue
            if cancel_ev.is_set():
                e["status"] = "cancelled"
                break
            item = known.get(key) or {"domain": key[0], "layout_id": key[1]}
            try:
                res = run_layout(cfg, item, e["prompts_used"])
            except Exception as ex:
                res = {**item, "error": f"{type(ex).__name__}: {ex}", "trace": traceback.format_exc()[-2000:]}
            e["layouts"].append(res)
            e["progress"] = {"done": len(e["layouts"]), "total": len(e["scope"])}
            e["summary"]  = summarize(e)
            save(e)
            if cfg.get("delay_s"):
                cancel_ev.wait(cfg["delay_s"])
        else:
            e["status"] = "done"
        e["finished_at"] = _now()
        e["summary"] = summarize(e)
        save(e)
    except Exception as ex:
        e["status"], e["error"] = "error", f"{type(ex).__name__}: {ex}"
        save(e)
    finally:
        _running.pop(exp_id, None)


# ---------------------------------------------------------------------------
# hızlı test (kaydedilmez; istenirse save_quick ile deneye dönüşür)
# ---------------------------------------------------------------------------
QUICK_TTL_S = 3600


def quick_run(cfg: dict, domain: str, layout_id: str, user: str) -> dict:
    cfg = validate_config({**cfg, "max_pages": cfg.get("max_pages") or 5})
    item = next((x for x in eligible_layouts([domain]) if x["layout_id"] == layout_id), None)
    if not item:
        raise ExperimentError("This layout cannot be evaluated (no CSS rule or pages in the GT)")
    prompts_used = {}
    result = run_layout(cfg, item, prompts_used)
    token  = secrets.token_hex(8)
    now    = time.time()
    for k in [k for k, v in _quick.items() if now - v["at"] > QUICK_TTL_S]:
        _quick.pop(k, None)
    payload = {"config": cfg, "result": result, "prompts_used": prompts_used}
    _quick[token] = {"user": user, "at": now, "payload": payload}
    return {"token": token, **payload}


def save_quick(token: str, name: str, user: str) -> dict:
    q = _quick.get(token)
    if not q or q["user"] != user:
        raise ExperimentError("Quick test result not found (it may have expired) — run it again")
    p, r = q["payload"], q["payload"]["result"]
    e = {
        "id":         datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2),
        "name":       name.strip() or f"Quick test · {p['config']['backend']} · {p['config'].get('model') or 'default'} · {r['domain']}",
        "kind":       "quick", "created_at": _now(), "created_by": user, "finished_at": _now(),
        "status":     "done", "config": p["config"],
        "scope":      [{"domain": r["domain"], "layout_id": r["layout_id"]}],
        "progress":   {"done": 1, "total": 1}, "prompts_used": p["prompts_used"], "layouts": [r], "error": None,
    }
    e["summary"] = summarize(e)
    save(e)
    _quick.pop(token, None)
    return e


# ---------------------------------------------------------------------------
# karşılaştırmalı deney (grup): model × kural dili başına bir deney, sırayla
# ---------------------------------------------------------------------------
def create_group(name: str, cfgs: list, layouts: list, user: str) -> tuple:
    if len(cfgs) < 2:
        raise ExperimentError("A comparison needs at least two configurations (model × rule language)")
    gid = "g-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    gname = name.strip() or f"Comparison · {len(cfgs)} configurations"
    ids = []
    for c in cfgs:
        rule = "CSS→REGEXN" if c.get("rule_source") == "llm_css_regexn" else c.get("rule_type")
        e = create(f"{c.get('backend')} · {c.get('model') or 'default'} · {rule}", c, layouts, user)
        e["group"] = {"id": gid, "name": gname}
        save(e)
        ids.append(e["id"])
    return gid, ids


def group_members(gid: str) -> list:
    out = []
    for p in sorted(EXP_DIR.glob("*.json")):
        e = load(p.stem)
        if e and (e.get("group") or {}).get("id") == gid:
            out.append(e)
    return sorted(out, key=lambda e: e["created_at"])


def start_group(gid: str):
    """Grubun bitmemiş deneylerini sırayla çalıştır (yerel modelleri aynı anda yüklememek için)."""
    with _lock:
        if gid in _groups:
            return
        cancel_ev = threading.Event()
        _groups[gid] = cancel_ev
        ids = [e["id"] for e in group_members(gid) if e["status"] not in ("done",)]
        _queued.update(ids)

    def run():
        try:
            for i in ids:
                with _lock:
                    _queued.discard(i)
                    if i in _running:
                        continue
                    if cancel_ev.is_set():
                        e = _load_json(exp_path(i), None)
                        if e and e["status"] in ("queued", "running", "interrupted"):
                            e["status"] = "cancelled"
                            save(e)
                        continue
                    _running[i] = {"thread": threading.current_thread(), "cancel": cancel_ev}
                _worker(i, cancel_ev)
        finally:
            with _lock:
                _queued.difference_update(ids)
                _groups.pop(gid, None)

    threading.Thread(target=run, daemon=True, name=f"grp-{gid}").start()


def cancel_group(gid: str) -> bool:
    ev = _groups.get(gid)
    if ev:
        ev.set()
    return bool(ev)


# ---------------------------------------------------------------------------
# cross check: modeller arası uyum (GT'den bağımsız)
# ---------------------------------------------------------------------------
def _agree(a: list, b: list, metric: str):
    """İki modelin aynı alan için çıkardığı değerlerin uyumu (simetrik). İkisi de boşsa None."""
    if not a and not b:
        return None
    s, _ = score_field(a, b, metric) if a else score_field(b, a, metric)
    return s


def cross_check(gid: str) -> dict:
    """Ortak layout'larda her (sayfa, alan) için modellerin çıkardığı içeriklerin ikili uyumu.
    Kurallar yeniden çalıştırılır (LLM çağrısı yok). Yüksek uyum + düşük GT skoru = GT ya da
    ortak model hatası şüphesi; düşük uyum = zor alan."""
    from bs4 import BeautifulSoup
    members = [e for e in group_members(gid) if e.get("layouts")]
    if len(members) < 2:
        return {"members": len(members), "fields": {}, "layouts": [], "suspicious": [], "hard": []}
    by_key = [{(l["domain"], l["layout_id"]): l for l in e["layouts"] if not l.get("error")} for e in members]
    common = sorted(set.intersection(*[set(k) for k in by_key]))
    tmpls  = _templates()
    fields_acc, layouts_out, cells = {}, [], []
    for dom, lid in common:
        gt     = _load_json(GT_DIR / f"{dom}.json", {})
        layout = gt.get("layouts", {}).get(lid, {})
        fields = (tmpls.get(layout_template_id(layout, tmpls), {}) or {}).get("fields") or {}
        pages  = sorted(set.intersection(*[set(m[(dom, lid)]["pages"]) for m in by_key]))
        lay_ag, lay_gt = [], []
        for p in pages:
            html = (RAW_DIR / dom / p).read_text(encoding="utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")
            for f, fdef in fields.items():
                k, mg, metric = _kind(fdef), bool(fdef.get("merge")), fdef.get("metric", "rouge")
                vals = []
                for e, m in zip(members, by_key):
                    rt = e["config"]["rule_type"]
                    try:
                        vals.append(rule_values(html, soup, m[(dom, lid)]["rules"].get(f) or "", rt, k, mg))
                    except Exception:
                        vals.append([])
                pairs = [_agree(vals[i], vals[j], metric) for i in range(len(vals)) for j in range(i + 1, len(vals))]
                pairs = [x for x in pairs if x is not None]
                if not pairs:
                    continue
                ag = sum(pairs) / len(pairs)
                gts = [m[(dom, lid)]["pages"].get(p, {}).get(f, {}).get("score") for m in by_key]
                gts = [x for x in gts if x is not None]
                gt_mean = sum(gts) / len(gts) if gts else None
                fields_acc.setdefault(f, {"ag": [], "gt": []})
                fields_acc[f]["ag"].append(ag)
                if gt_mean is not None:
                    fields_acc[f]["gt"].append(gt_mean)
                lay_ag.append(ag)
                if gt_mean is not None:
                    lay_gt.append(gt_mean)
                cells.append({"domain": dom, "layout_id": lid, "page": p, "field": f, "agreement": ag, "gt": gt_mean})
        layouts_out.append({"domain": dom, "layout_id": lid, "name": layout.get("name", lid),
                            "agreement": _mean(lay_ag), "gt": _mean(lay_gt), "pages": len(pages)})

    def group_cells(pred):
        agg = {}
        for c in cells:
            if pred(c):
                a = agg.setdefault((c["domain"], c["layout_id"], c["field"]), {"n": 0, "ag": [], "gt": []})
                a["n"] += 1
                a["ag"].append(c["agreement"])
                a["gt"].append(c["gt"])
        return sorted([{"domain": d, "layout_id": l, "field": f, "pages": v["n"],
                        "agreement": _mean(v["ag"]), "gt": _mean(v["gt"])} for (d, l, f), v in agg.items()],
                      key=lambda x: -x["pages"])[:30]

    return {
        "members":    len(members),
        "models":     [{"id": e["id"], "name": e["name"]} for e in members],
        "common_layouts": len(common),
        "fields":     {f: {"agreement": _mean(v["ag"]), "gt": _mean(v["gt"])} for f, v in fields_acc.items()},
        "layouts":    sorted(layouts_out, key=lambda x: (x["agreement"] is None, x["agreement"] or 0)),
        # modeller uyuşuyor ama GT'ye uymuyor → GT'yi ya da ortak hatayı kontrol et
        "suspicious": group_cells(lambda c: c["agreement"] >= 0.9 and c["gt"] is not None and c["gt"] < 0.3),
        # modeller birbirinden ayrışıyor → zor alan
        "hard":       group_cells(lambda c: c["agreement"] < 0.3),
    }
