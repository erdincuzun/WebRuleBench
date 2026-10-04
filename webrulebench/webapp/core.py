"""
webrulebench/webapp/core.py
==============
WebRuleBench web uygulamasının çekirdeği: Flask uygulama nesnesi, veri yolları, oturum ve
yetki kontrolleri (require_login / require_admin, /api/* giriş kapısı), arayüz dili, bölüm
tanımları ve route'ların paylaştığı yardımcılar (siteler, sayfalar, GT, annotation, kural
çalıştırma, GT özeti ve κ, dışa aktarma satırları, denetim kaydı).

Route'lar webrulebench/webapp/routes/ altındaki blueprint'lerdedir; uygulama webapp/app.py'de kurulur:
    webrulebench serve
"""

import json
import logging
import os
import re
import sys
import shutil
import secrets
import copy
import requests as _requests
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request, send_file, session, redirect, url_for, Response

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False
app.secret_key = secrets.token_hex(32)

# ---------------------------------------------------------------------------
# DELETION AUDIT LOG
# ---------------------------------------------------------------------------
from webrulebench.paths import DATA_DIR as _DATA_DIR
_audit_log_path = _DATA_DIR / "dataset" / "deletion_audit.log"
_audit_log_path.parent.mkdir(parents=True, exist_ok=True)

_audit_logger = logging.getLogger("deletion_audit")
_audit_logger.setLevel(logging.INFO)
if not _audit_logger.handlers:
    _fh = logging.FileHandler(_audit_log_path, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _audit_logger.addHandler(_fh)

def _audit(msg: str):
    """Write a deletion event to the audit log (and stdout)."""
    _audit_logger.info(msg)
    print(f"[AUDIT] {msg}")


def _fetch_html(url: str) -> tuple[str | None, str, str | None]:
    """
    Fetch a URL: requests first, Playwright fallback.
    Returns (html, method, error_message)
    """
    # 1. requests
    try:
        resp = _requests.get(url, headers=FETCH_HEADERS, timeout=20, allow_redirects=True)
        if resp.status_code == 200 and len(resp.text) >= 1000:
            return resp.text, "requests", None
        # 403 ama içerik varsa kabul et
        if resp.status_code == 403 and len(resp.text) >= 3000:
            from bs4 import BeautifulSoup as _BS
            _soup = _BS(resp.text, "html.parser")
            if _soup.find_all("a", href=True):
                return resp.text, "requests", None
    except Exception:
        pass

    # 2. Playwright fallback
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx     = browser.new_context(user_agent=FETCH_HEADERS["User-Agent"])
            page    = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            html = page.content()
            browser.close()
            if html and len(html) >= 1000:
                return html, "playwright", None
    except Exception as e:
        return None, "failed", str(e)

    return None, "failed", "Could not download the page"

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
from webrulebench.paths import CODE_DIR             # paket klasörü
BASE_DIR        = _DATA_DIR                          # veri: proje kökü ya da WRB_DATA_DIR (paths.py)
DATASET_DIR     = BASE_DIR / "dataset" / "raw"
GROUND_TRUTH    = BASE_DIR / "ground_truth"
ANNOTATIONS_DIR = BASE_DIR / "annotations"
USERS_FILE      = BASE_DIR / "users.json"
EXCLUDED_FILE   = BASE_DIR / "dataset" / "excluded_domains.json"
SITES_FILE      = BASE_DIR / "sites.json"
INDEX_FILE      = BASE_DIR / "dataset" / "index.json"
DL_LOG_FILE     = BASE_DIR / "dataset" / "download_log.json"

TEMPLATES_FILE  = BASE_DIR / "layout_templates.json"
TEMPLATE_PROMPTS_FILE = BASE_DIR / "template_prompts.json"

FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

GROUND_TRUTH.mkdir(exist_ok=True)
ANNOTATIONS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# TEMPLATES
# ---------------------------------------------------------------------------
def load_templates() -> dict:
    if TEMPLATES_FILE.exists():
        return json.loads(TEMPLATES_FILE.read_text(encoding="utf-8"))
    return {"templates": {}, "metrics": {}, "field_types": {}}

def save_templates(data: dict):
    TEMPLATES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def get_template(template_id: str) -> dict | None:
    return load_templates()["templates"].get(template_id)

# Şablona eklenen deneme prompt'ları: {"prompts": {pid: {...}}}.
# Herkes görür; yalnızca sahibi veya admin düzenler/siler. Sürüm tutulmaz.
def load_template_prompts() -> dict:
    if TEMPLATE_PROMPTS_FILE.exists():
        return json.loads(TEMPLATE_PROMPTS_FILE.read_text(encoding="utf-8"))
    return {"prompts": {}}

def save_template_prompts(data: dict):
    TEMPLATE_PROMPTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def page_type_for_layout(layout: dict) -> str:
    """template_id varsa oradan, yoksa layout.page_type, yoksa 'article'."""
    tid = layout.get("template_id", "")
    if tid:
        t = get_template(tid)
        if t and t.get("page_type"):
            return t["page_type"]
    return layout.get("page_type", "article")

# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------
# Kullanıcı kayıtları users_store.py'de (token özetleri, token sürümü, etkin/pasif).
from webrulebench import users_store
from webrulebench.rules import rule_agreement as RA
from webrulebench.webapp import i18n as I18N


def get_lang() -> str:
    """İstek dili: 'lang' çerezi (en | tr); yoksa İngilizce."""
    try:
        return I18N.norm(request.cookies.get("lang"))
    except RuntimeError:                       # istek bağlamı dışında
        return I18N.DEFAULT


def _t(text: str, **params) -> str:
    """Arayüz metni: İngilizce kaynak → istek dilindeki çeviri (bkz. i18n.py)."""
    return I18N.translate(text, get_lang(), **params)


def _ex_text(ex: Exception) -> str:
    """Bir modülün fırlattığı hata mesajı → istek dili. users_store.UserError ve
    experiments.ExperimentError İngilizce şablonu ve parametreleri ayrı taşır
    (i18n_msg / i18n_params) — böylece değişken içeren mesajlar da sözlükte bulunur.
    Diğer istisnalar (ör. float() ValueError) str(ex) ile aranır; yoksa İngilizce kalır."""
    msg = getattr(ex, "i18n_msg", None)
    if isinstance(msg, str):
        return _t(msg, **(getattr(ex, "i18n_params", None) or {}))
    return _t(str(ex))


def load_users() -> dict:
    return users_store.load()

def save_users(users: dict):
    users_store.save(users)

def current_user() -> str | None:
    """Oturumdaki kullanıcı — hesap etkin ve token sürümü değişmemişse (token yenilenince
    ya da hesap pasifleştirilince diğer cihazlardaki oturumlar burada kapanır)."""
    u = session.get("username")
    if not u:
        return None
    if not users_store.session_ok(u, session.get("tv", 0)):
        session.clear()
        return None
    return u

def require_login():
    """Returns (username, error_response). error_response is None if logged in."""
    u = current_user()
    if not u:
        return None, (jsonify({"error": _t("Login required")}), 401)
    return u, None

# /api/* uçlarının hepsi giriş ister (yalnızca oturum durumu sorgusu açık). Uç bazında
# require_login/require_admin kontrolleri bunun üstüne yetkiyi ayrıca daraltır.
_PUBLIC_API = {"/api/me"}


@app.before_request
def _api_login_gate():
    if request.path.startswith("/api/") and request.path not in _PUBLIC_API and not current_user():
        return jsonify({"error": _t("Login required")}), 401


def require_admin():
    """Returns (username, error_response). error_response is None if admin."""
    u = current_user()
    if not u:
        return None, (jsonify({"error": _t("Login required")}), 401)
    users = load_users()
    if users.get(u, {}).get("role") != "admin":
        return None, (jsonify({"error": _t("Admin rights are required for this action")}), 403)
    return u, None

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def load_sites() -> list[dict]:
    # sites.json'dan bilgi al (varsa)
    meta = {}
    if SITES_FILE.exists():
        data = json.loads(SITES_FILE.read_text(encoding="utf-8"))
        for country in data["countries"]:
            for site in country["sites"]:
                domain = urlparse(site["url"]).netloc.replace("www.", "")
                meta[domain] = {
                    "name":     site["name"],
                    "url":      site["url"],
                    "country":  country["country"],
                    "code":     country.get("code", ""),
                    "continent": country.get("continent", ""),
                    # sitenin yayın dili ülkenin birincil dilinden farklıysa (ör. İngilizce baskı) site kaydında tutulur
                    "language": site.get("language") or country.get("language", ""),
                    "notes":    site.get("notes", ""),
                    "has_meta": True,
                }

    # dataset/raw/ altındaki tüm klasörler = siteler
    sites = []
    if DATASET_DIR.exists():
        for site_dir in sorted(DATASET_DIR.iterdir()):
            if not site_dir.is_dir():
                continue
            domain = site_dir.name
            if domain in meta:
                sites.append({"domain": domain, **meta[domain]})
            else:
                sites.append({
                    "domain":   domain,
                    "name":     domain,
                    "url":      f"https://{domain}",
                    "country":  "",
                    "code":     "",
                    "continent": "",
                    "language": "",
                    "notes":    "",
                    "has_meta": False,
                })
    return sites


# sites.json ülkelere göre gruplu: {"countries": [{country, code, continent, language, sites: [...]}]}
def _load_sites_file() -> dict:
    if SITES_FILE.exists():
        return json.loads(SITES_FILE.read_text(encoding="utf-8"))
    return {"countries": []}


def _save_sites_file(data: dict):
    if "meta" in data:
        data["meta"]["total_sites"]     = sum(len(c.get("sites", [])) for c in data["countries"])
        data["meta"]["total_countries"] = sum(1 for c in data["countries"] if c.get("country") != "Other")
    SITES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _upsert_site_meta(domain: str, name: str, country: str, notes: str = "",
                      url: str | None = None, new_country: dict | None = None) -> str | None:
    """Sitenin sites.json kaydını oluştur/güncelle; ülke değiştiyse doğru gruba taşı.
    Kayıttaki diğer anahtarlar (playwright, listing_urls, ...) korunur.
    new_country: listede olmayan bir ülke için {code, continent, language}.
    Hata varsa mesaj, yoksa None döner."""
    country = (country or "").strip() or "Other"
    data    = _load_sites_file()
    groups  = data["countries"]

    entry = None
    for g in groups:
        for i, st in enumerate(g.get("sites", [])):
            if urlparse(st.get("url", "")).netloc.replace("www.", "") == domain:
                entry = g["sites"].pop(i)
                break
        if entry:
            break
    if entry is None:
        entry = {"url": url or f"https://{domain}"}
    elif url:
        entry["url"] = url
    entry["name"]  = name
    entry["notes"] = notes

    target = next((g for g in groups if g.get("country") == country), None)
    if target is None:
        if country != "Other":
            nc = new_country or {}
            code = (nc.get("code") or "").strip().upper()
            if not code:
                return _t("An ISO code is required for a new country")
            if any((g.get("code") or "").upper() == code for g in groups):
                return _t("Code '{code}' is already used by another country", code=code)
            target = {"country": country, "code": code,
                      "continent": (nc.get("continent") or "").strip(),
                      "language":  (nc.get("language") or "").strip().lower(), "sites": []}
        else:
            target = {"country": "Other", "sites": []}
        groups.append(target)
    target.setdefault("sites", []).append(entry)
    # boşalan grup kalmasın
    data["countries"] = [g for g in groups if g.get("sites")]
    _save_sites_file(data)
    return None


def load_ground_truth(domain: str) -> dict:
    """Ground truth verisi ground_truth/approved/<domain>.json içinde."""
    approved = load_approved_gt(domain)
    if approved:
        return approved
    return {"domain": domain, "layouts": {}, "page_assignments": {}}


def save_ground_truth(domain: str, data: dict):
    save_approved_gt(domain, data)


def get_site_pages(domain: str) -> dict:
    site_dir = DATASET_DIR / domain
    if not site_dir.exists():
        return {"homepage": [], "listing": [], "article": []}
    files = sorted(site_dir.glob("*.html"))
    return {
        "homepage": [f.name for f in files if f.name == "homepage.html"],
        "listing":  [f.name for f in files if f.name.startswith("listing_")],
        "article":  [f.name for f in files if f.name.startswith("article_")],
    }


# ---------------------------------------------------------------------------
# LAYOUT-BASED HELPERS
# ---------------------------------------------------------------------------
def user_annotation_path(domain: str, username: str) -> Path:
    d = ANNOTATIONS_DIR / domain
    d.mkdir(exist_ok=True)
    return d / f"{username}.json"

def load_user_annotation(domain: str, username: str) -> dict:
    p = user_annotation_path(domain, username)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"domain": domain, "annotator": username, "layouts": {}, "page_assignments": {}}

def save_user_annotation(domain: str, username: str, data: dict):
    p = user_annotation_path(domain, username)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def user_assigned_count(domain: str, username: str) -> int:
    """Kullanıcının annotation dosyasındaki toplam atanmış sayfa sayısı."""
    ann = load_user_annotation(domain, username)
    pa  = ann.get("page_assignments", {})
    return sum(1 for v in pa.values() if isinstance(v, dict) and not v.get("skipped"))

def get_progress(username: str | None = None) -> dict:
    sites    = load_sites()
    total    = len(sites)
    complete = 0
    for site in sites:
        pages     = get_site_pages(site["domain"])
        all_pages = pages["article"] + pages["listing"]
        if username:
            assigned = user_assigned_count(site["domain"], username)
        else:
            gt       = load_ground_truth(site["domain"])
            pa       = gt.get("page_assignments", {})
            assigned = sum(1 for v in pa.values() if not v.get("skipped") and v.get("layout_id"))
        if all_pages and assigned >= min(5, len(all_pages)):
            complete += 1
    return {"total": total, "complete": complete}


def _validate_template_prompt(body: dict):
    """(clean_dict, error_str) — kullanıcı prompt'u .format(domain, skeleton) ile çalışabilmeli."""
    from webrulebench.pipeline.prompt_builder import RULE_TYPES
    name      = (body.get("name") or "").strip()
    rule_type = body.get("rule_type", "css")
    system    = (body.get("system_prompt") or "").strip()
    user      = (body.get("user_prompt") or "").strip()
    if not name:
        return None, _t("Prompt name is required")
    if rule_type not in RULE_TYPES:
        return None, _t("Invalid rule language")
    if not system:
        return None, _t("System prompt cannot be empty")
    if "{skeleton}" not in user:
        return None, _t("User prompt must contain the {skeleton} placeholder")
    try:
        user.format(domain="x", skeleton="x")
    except (KeyError, IndexError, ValueError) as e:
        return None, _t("Only {{domain}} and {{skeleton}} may be used in the user prompt; "
                        "write {{{{ }}}} for a literal brace ({error})", error=e)
    return {"name": name, "rule_type": rule_type, "system_prompt": system,
            "user_prompt": user, "notes": (body.get("notes") or "").strip()}, None


def _prompt_for_edit(pid):
    """(data, prompt, error_response) — sahibi veya admin değilse 403."""
    username, err = require_login()
    if err: return None, None, err
    data = load_template_prompts()
    p = data["prompts"].get(pid)
    if not p:
        return None, None, (jsonify({"error": _t("Prompt not found")}), 404)
    if p.get("owner") != username and load_users().get(username, {}).get("role") != "admin":
        return None, None, (jsonify({"error": _t("Only the owner or an admin can change this")}), 403)
    return data, p, None


def _user_activity() -> dict:
    """Kullanıcı başına: annotation'ı olan site sayısı, son annotation, başlatılan deney sayısı."""
    out = {}
    if ANNOTATIONS_DIR.exists():
        for f in ANNOTATIONS_DIR.glob("*/*.json"):
            a = out.setdefault(f.stem, {"sites": 0, "last_annotation": None, "experiments": 0})
            a["sites"] += 1
            try:
                ts = [l.get("updated_at") for l in json.loads(f.read_text(encoding="utf-8")).get("layouts", {}).values()]
            except ValueError:
                ts = []
            last = max((t for t in ts if t), default=None)
            if last and (not a["last_annotation"] or last > a["last_annotation"]):
                a["last_annotation"] = last
    exp_dir = BASE_DIR / "experiments"
    if exp_dir.exists():
        for f in exp_dir.glob("*.json"):
            try:
                who = json.loads(f.read_text(encoding="utf-8")).get("created_by")
            except ValueError:
                continue
            if who:
                out.setdefault(who, {"sites": 0, "last_annotation": None, "experiments": 0})["experiments"] += 1
    return out


APPROVED_DIR = BASE_DIR / "ground_truth" / "approved"

def load_approved_gt(domain: str) -> dict | None:
    """Load approved GT from ground_truth/approved/<domain>.json or None."""
    path = APPROVED_DIR / f"{domain}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None

def save_approved_gt(domain: str, data: dict):
    APPROVED_DIR.mkdir(parents=True, exist_ok=True)
    path = APPROVED_DIR / f"{domain}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# GT ONAYI — ÖZET (site listesi, layout listesi)
# ---------------------------------------------------------------------------
RULE_LANGS = ("css", "xpath", "regex")


def _rule_of(val, lang: str) -> str:
    """Alan değerinden bir kural dilinin metni: düz string = CSS, dict = {css, xpath, regex}, list = CSS listesi."""
    if isinstance(val, dict):
        return val.get(lang) or ""
    if lang != "css":
        return ""
    if isinstance(val, list):
        return ", ".join(v for v in val if isinstance(v, str))
    return val or ""


def _rule_langs(selectors: dict) -> list:
    return [lang for lang in RULE_LANGS if any(_rule_of(v, lang) for v in (selectors or {}).values())]


def _rule_ratings(users: dict, field: str, lang: str) -> list:
    """Annotatörlerin bir alan için normalize edilmiş kuralları (boşlar None)."""
    return [RA.normalize_rule(_rule_of(d["selectors"].get(field), lang), lang) for d in users.values()]


def _audit_compile_times() -> dict:
    """Eski derlemelerin zamanı: layout'ta 'compiled' bilgisi yoksa denetim kaydındaki son COMPILE satırı.
    {(domain, layout_id): datetime(UTC)}"""
    out = {}
    if not _audit_log_path.exists():
        return out
    for line in _audit_log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "  COMPILE  " not in line:
            continue
        try:
            ts  = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").astimezone(timezone.utc)
            dom = line.split("domain=", 1)[1].split()[0]
            lid = line.split("layout=", 1)[1].split()[0]
        except (ValueError, IndexError):
            continue
        out[(dom, lid)] = ts
    return out


def _parse_iso(v):
    try:
        d = datetime.fromisoformat(v)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _gt_layout_summaries(domain: str, audit_times: dict) -> list:
    """Bir sitenin layout'ları için GT Onayı özeti (CSS; XPath/Regex durumu da ayrıca)."""
    gt       = load_ground_truth(domain)
    layouts  = gt.get("layouts", {})
    gt_pa    = gt.get("page_assignments", {})
    ann_dir  = ANNOTATIONS_DIR / domain
    anns     = {}
    if ann_dir.exists():
        for f in ann_dir.glob("*.json"):
            try:
                anns[f.stem] = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                continue

    result = []
    for lid, layout in layouts.items():
        tmpl   = get_template(layout.get("template_id", "")) or {}
        fields = list((tmpl.get("fields") or {}).keys()) or list((layout.get("selectors") or {}).keys())

        # derleme ekranıyla aynı kullanıcı kümesi: bu layout'a sayfa atamış ya da kural girmiş olanlar
        users, union_pages = {}, set()
        for uname, ann in anns.items():
            al    = ann.get("layouts", {}).get(lid, {})
            pages = [fn for fn, v in ann.get("page_assignments", {}).items()
                     if v.get("layout_id") == lid and not v.get("skipped")]
            sels  = al.get("selectors", {})
            if not pages and not sels:
                continue
            union_pages.update(pages)
            users[uname] = {"selectors": sels, "updated_at": al.get("updated_at"), "pages": len(pages)}

        gt_sels  = layout.get("selectors") or {}
        compiled = layout.get("compiled") or {}
        langs = {}
        for lang in RULE_LANGS:
            annotators = [u for u, d in users.items() if any(_rule_of(v, lang) for v in d["selectors"].values())]
            has_gt     = any(_rule_of(v, lang) for v in gt_sels.values())
            at = _parse_iso((compiled.get(lang) or {}).get("at"))
            if at is None and lang == "css" and has_gt:
                at = audit_times.get((domain, lid))        # eski derleme: zamanı denetim kaydından
            last = max((_parse_iso(users[u]["updated_at"]) for u in annotators
                        if _parse_iso(users[u]["updated_at"])), default=None)
            if not has_gt:
                status = "none"
            elif at and last and last > at:
                status = "stale"
            else:
                status = "approved"
            # layout × alan: gözlenen ikili kural uyumu (normalize); Fleiss κ raporda, layout'lar konu sayılarak
            ratings = {f: _rule_ratings(users, f, lang) for f in fields}
            kfields = {f: RA.observed_agreement(r) for f, r in ratings.items()}
            kappas = [k for k in kfields.values() if k is not None]
            langs[lang] = {
                "status":     status,
                "annotators": len(annotators),
                "kappa":      round(sum(kappas) / len(kappas), 3) if kappas else None,
                "kappa_fields": {f: round(k, 3) for f, k in kfields.items() if k is not None},
                "_ratings":   ratings,
                "compiled_at": at.isoformat() if at else None,
                "compiled_by": (compiled.get(lang) or {}).get("by"),
            }
        result.append({
            "layout_id":   lid,
            "name":        layout.get("name", lid),
            "template_id": layout.get("template_id", ""),
            "annotators":  sorted(users),
            "gt_pages":    sum(1 for v in gt_pa.values() if v.get("layout_id") == lid and not v.get("skipped")),
            "union_pages": len(union_pages),
            "langs":       langs,
        })
    return result


def _strip_ratings(lsums: list) -> list:
    """Ham kurallar (annotatör bağımsızlığı için) API yanıtına konmaz."""
    for l in lsums:
        for d in l.get("langs", {}).values():
            d.pop("_ratings", None)
    return lsums


def _pooled_kappa(lsums: list) -> dict:
    """{dil: {alan: {kappa, po, pe, n_subjects}}} — layout'lar konu, annotatörler puanlayıcı (Fleiss)."""
    out = {}
    for lang in RULE_LANGS:
        by_field = {}
        for l in lsums:
            for f, r in ((l.get("langs", {}).get(lang) or {}).get("_ratings") or {}).items():
                by_field.setdefault(f, []).append(r)
        res = {f: RA.fleiss_kappa(subs) for f, subs in by_field.items()}
        out[lang] = {f: {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}
                     for f, r in res.items() if r}
    return out


def _is_pending(lsum: dict) -> bool:
    """Derleme bekleyen: annotatörü olan ama GT'si olmayan ya da derlemeden sonra değişmiş bir kural dili."""
    return any(l["annotators"] and l["status"] in ("none", "stale") for l in lsum["langs"].values())


def _site_meta_map() -> dict:
    return {s["domain"]: {k: s.get(k, "") for k in ("name", "country", "code", "continent", "language")}
            for s in load_sites()}


def _dataset_report() -> dict:
    """Site başına sayfa / GT sayfası / layout sayısı ve şablon × alan kapsamı (GT kuralı olan layout)."""
    from webrulebench.evaluation import experiments as X
    tmpls = X._templates()
    sites, templates, layout_pages = [], {}, []
    for s in load_sites():
        dom   = s["domain"]
        pages = get_site_pages(dom)
        gt    = load_ground_truth(dom)
        pa    = gt.get("page_assignments", {})
        lays  = gt.get("layouts", {})
        lay_tids = {}
        for lid, l in lays.items():
            tid = X.layout_template_id(l, tmpls) or "—"
            lay_tids[lid] = tid
            t = templates.setdefault(tid, {"id": tid, "name": (tmpls.get(tid) or {}).get("name", tid),
                                           "fields": list(((tmpls.get(tid) or {}).get("fields") or {}).keys()),
                                           "layouts": 0, "sites": set(), "gt_pages": 0, "coverage": {}})
            t["layouts"] += 1
            t["sites"].add(dom)
            sels = l.get("selectors") or {}
            for f in t["fields"]:
                if X._rule_of(sels.get(f), "css"):
                    t["coverage"][f] = t["coverage"].get(f, 0) + 1
        gt_pages, per_layout = 0, {lid: 0 for lid in lay_tids}
        for v in pa.values():
            if v.get("layout_id") in lay_tids and not v.get("skipped"):
                gt_pages += 1
                per_layout[v["layout_id"]] += 1
                templates[lay_tids[v["layout_id"]]]["gt_pages"] += 1
        layout_pages += [{"domain": dom, "layout_id": lid, "template_id": lay_tids[lid], "pages": n}
                         for lid, n in per_layout.items()]
        sites.append({"domain": dom, **{k: s.get(k, "") for k in ("name", "country", "code", "continent", "language")},
                      "has_meta": s.get("has_meta", False),
                      "article": len(pages["article"]), "listing": len(pages["listing"]),
                      "homepage": len(pages["homepage"]),
                      "pages": len(pages["article"]) + len(pages["listing"]) + len(pages["homepage"]),
                      "gt_pages": gt_pages, "skipped": sum(1 for v in pa.values() if v.get("skipped")),
                      "layouts": len(lays)})
    for t in templates.values():
        t["sites"] = len(t["sites"])
    return {"sites": sites, "templates": sorted(templates.values(), key=lambda t: -t["layouts"]),
            "layout_pages": layout_pages}


def _gt_compiled_map() -> dict:
    audit = _audit_compile_times()
    out = {}
    for f in sorted(APPROVED_DIR.glob("*.json")):
        gt = json.loads(f.read_text(encoding="utf-8"))
        dom = f.stem                     # dosya adı esastır
        for lid, l in (gt.get("layouts") or {}).items():
            c = dict(l.get("compiled") or {})
            if "css" not in c and audit.get((dom, lid)):
                c["css"] = {"at": audit[(dom, lid)].isoformat(), "by": None, "source": "audit_log"}
            if c:
                out.setdefault(dom, {})[lid] = c
    return out


# Yönlendirme sayfaları: ana sayfa (hub) + iş akışının her bölümü için ayrı
# sayfa. Bölüm sayfaları şimdilik mevcut annotation ekranındaki modalları
# /annotate?open=... derin linkleriyle açar; her bölüm zamanla kendi sayfasına
# taşınabilir. Sıra = makaledeki iş akışı sırası.
SECTIONS = [
    {"key": "data",         "path": "/data",         "icon": "🌐", "title": "Data Collection",
     "desc": "Add sites, download pages and bulk-add pages from a listing page."},
    {"key": "schema",       "path": "/schema",       "icon": "🗂", "title": "Templates & Prompts",
     "desc": "Extraction templates (fields, types, metrics), the prompt generated from each template, and prompt variants."},
    {"key": "annotation",   "path": "/annotation",   "icon": "✏️", "title": "Annotation",
     "desc": "Writing CSS / XPath / Regex rules and assigning pages to layouts in bulk."},
    {"key": "groundtruth",  "path": "/ground-truth", "icon": "✅", "title": "Ground Truth Approval",
     "desc": "Compiling annotators' rules: layer 1 Fleiss κ, layer 2 ROUGE."},
    {"key": "evaluation",   "path": "/evaluation",   "icon": "🤖", "title": "LLM Evaluation",
     "desc": "Experiments that compare LLM-generated rules with the ground truth; saved and comparable."},
    {"key": "reports",      "path": "/reports",      "icon": "📊", "title": "Reports & Export",
     "desc": "Dataset, annotation & GT quality and LLM result reports; tables and charts for papers, dataset export."},
]
_SECTIONS_BY_KEY = {s["key"]: s for s in SECTIONS}


@app.context_processor
def _inject_sections():
    lang = get_lang()
    return {"sections": SECTIONS, "T": _t, "lang": lang, "langs": I18N.LANGS,
            "i18n_version": I18N.version(lang)}


def _run_selector(soup, selector: str, merge: bool, rule_type: str = "css", raw_html: str = None,
                  with_texts: bool = False) -> dict:
    """Run a CSS selector, XPath expression, or Regex pattern against a page.

    merge=False → break-after-success: try each comma-part, return on first hit (CSS only).
    merge=True  → continue-after-success: run all parts, union results (CSS only).
    rule_type   : 'css' (default, against the BeautifulSoup tree) or 'xpath'/'regex'
                  (against raw_html via rule_utils.run_rule).
    """
    if rule_type != "css":
        from webrulebench.rules.rule_utils import run_rule
        # run_rule sözdizimi hatalarını yutup [] döner; "eşleşme yok" ile karışmasın diye önce derle
        try:
            if rule_type == "xpath":
                from lxml import etree
                etree.XPath(selector)
            else:
                import re as _re
                _re.compile(selector)
        except Exception as e:
            kind = "XPath" if rule_type == "xpath" else "regex"
            return {"valid": False, "message": _t("❌ Invalid {kind}: {error}", kind=kind, error=e), "count": 0, "previews": [], "texts": [],
                    "syntax_error": True}
        try:
            elems = run_rule(raw_html if raw_html is not None else str(soup), selector, rule_type)
        except Exception as e:
            return {"valid": False, "message": _t("Error: {error}", error=e), "count": 0, "previews": [], "texts": []}

        from webrulebench.rules.regex_generator import html_to_text
        texts = []
        for el in elems:
            if isinstance(el, str):
                texts.append(html_to_text(el))      # regex: iç HTML → düz metin
            elif hasattr(el, "text_content"):
                texts.append(el.text_content())
            else:
                texts.append(str(el))
        texts    = [" ".join(t.split()) for t in texts]
        previews = [t[:100] for t in texts if t][:3]

        if not elems:
            return {"valid": False, "message": _t("❌ No matches found"), "count": 0, "previews": [], "texts": []}
        return {"valid": True, "message": _t("✅ {n} matches found", n=len(elems)), "count": len(elems),
                "previews": previews, "texts": texts}

    parts = [p.strip() for p in selector.split(",") if p.strip()]

    if merge:
        seen  = set()
        elems = []
        for part in parts:
            try:
                for el in soup.select(part):
                    if id(el) not in seen:
                        seen.add(id(el))
                        elems.append(el)
            except Exception:
                continue
        matched_part = selector if elems else None
    else:
        matched_part  = None
        elems         = []
        for part in parts:
            try:
                found = soup.select(part)
            except Exception:
                continue
            if found:
                matched_part = part
                elems        = found
                break

    previews = []
    for el in elems[:3]:
        text = el.get_text(strip=True)[:100]
        if text:
            previews.append(text)
    # XPath/Regex sonucuyla karşılaştırma için (api_validate compare_css)
    texts = [" ".join(el.get_text(" ").split()) for el in elems] if with_texts else []

    if not elems:
        if len(parts) > 1:
            msg = (_t("❌ No elements found ({n} merged selectors tried)", n=len(parts)) if merge else
                   _t("❌ No elements found ({n} alternatives tried)", n=len(parts)))
        else:
            msg = _t("❌ No elements found")
        return {"valid": False, "message": msg, "count": 0, "previews": [], "texts": []}

    msg = _t("✅ {n} elements found", n=len(elems))
    if not merge and len(parts) > 1 and matched_part != selector:
        msg += f" [{matched_part}]"
    if merge and len(parts) > 1:
        msg += " " + _t("({n} selectors merged)", n=len(parts))

    return {"valid": True, "message": msg, "count": len(elems), "previews": previews, "texts": texts}


def _field_kind(domain: str, filename: str, field: str) -> str:
    """Alanın karşılaştırma biçimi: 'image' / 'url' (nitelik değeri) ya da 'text'."""
    from webrulebench.rules.regex_generator import KIND_OF_TYPE
    gt  = load_ground_truth(domain)
    lid = gt.get("page_assignments", {}).get(filename, {}).get("layout_id")
    tid = gt.get("layouts", {}).get(lid, {}).get("template_id", "") if lid else ""
    ftype = ((get_template(tid) or {}).get("fields") or {}).get((field or "").split("[")[0], {}).get("type")
    return KIND_OF_TYPE.get(ftype, "text")


def _same_texts(a: list, b: list) -> bool:
    # boşluklar yok sayılır: get_text(" ") etiketler arasına boşluk koyar, lxml text_content koymaz.
    # Sıra yok sayılır: CSS merge parça sırasıyla, XPath '|' belge sırasıyla döndürür.
    return sorted("".join(t.split()) for t in a) == sorted("".join(t.split()) for t in b)


def _compare_texts(css_texts: list, other_texts: list) -> dict:
    """CSS ile XPath/Regex çıktısını metin üzerinden karşılaştır (ayrıştırıcılar farklı
    olduğu için — CSS: html.parser, XPath: lxml — eleman kimliği karşılaştırılamaz)."""
    return {
        "css_count":   len(css_texts),
        "same":        _same_texts(css_texts, other_texts),
        "same_count":  len(css_texts) == len(other_texts),
    }


def _exp_can_edit(e: dict, username: str) -> bool:
    return e.get("created_by") == username or load_users().get(username, {}).get("role") == "admin"


def _backend_has_key(cfg: dict) -> bool:
    """API anahtarı ortamda ya da proje kökündeki .env'de tanımlı mı (değer okunmaz)."""
    key = cfg.get("env_key")
    if not key:
        return True
    if os.environ.get(key):
        return True
    env = BASE_DIR / ".env"
    return env.exists() and any(line.strip().startswith(key + "=") for line in env.read_text().splitlines())


ENV_FILE = BASE_DIR / ".env"


def _env_value(key: str) -> str:
    """Anahtarın değeri (ortam değişkeni önce, sonra .env) — yalnızca sunucu içinde kullanılır."""
    from webrulebench.pipeline.llm_extractor import _api_key
    return _api_key(key) if key else ""


def _key_hint(key: str) -> str | None:
    v = _env_value(key)
    return f"…{v[-4:]}" if len(v) >= 8 else (_t("configured") if v else None)


def _set_env_key(key: str, value: str):
    """.env'de KEY=değer satırını ekle/değiştir; diğer satırlar korunur. Dosya yalnızca sahibine okunur (600)."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    out, done = [], False
    for line in lines:
        if line.strip().partition("=")[0].strip() == key and not line.strip().startswith("#"):
            if not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(line)
    if not done:
        out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def _public_backend(name: str, c: dict, catalog: bool = False) -> dict:
    from webrulebench.pipeline import llm_models as LM
    extra = {"catalog": LM.model_catalog(name)} if catalog else {}
    return {"name": name, "api": c.get("api"), "url": c.get("url"), "default_model": c.get("default_model"),
            "models": c.get("models") or [], "hidden": c.get("hidden") or [], "model_params": c.get("model_params") or {}, **extra,
            "env_key": c.get("env_key"), "notes": c.get("notes", ""),
            "params": c.get("params") or {}, "has_key": _backend_has_key(c),
            "key_hint": _key_hint(c.get("env_key")) if c.get("env_key") else None}


def _group_or_404(gid):
    from webrulebench.evaluation import experiments as X
    if not re.fullmatch(r"g-[\w-]+", gid or ""):
        return None
    return X.group_members(gid) or None


def _extract_with_selector(soup, selector: str, field: str, merge: bool = False) -> str | list:
    """Apply a CSS selector and return extracted text or image src list.

    merge=False → break-after-success (first matching part wins).
    merge=True  → continue-after-success (all parts run, results unioned).
    """
    # {css, xpath, regex} biçimindeki alanlar (GT ve kullanıcı annotation'ları) → CSS kısmı
    if isinstance(selector, dict):
        selector = selector.get("css") or ""
    if not selector:
        return "" if field != "images" else []

    parts = [p.strip() for p in selector.split(",") if p.strip()]

    if merge:
        seen = set()
        els  = []
        for part in parts:
            try:
                for el in soup.select(part):
                    if id(el) not in seen:
                        seen.add(id(el))
                        els.append(el)
            except Exception:
                continue
    else:
        els = []
        for part in parts:
            try:
                found = soup.select(part)
            except Exception:
                continue
            if found:
                els = found
                break

    if field == "images":
        srcs = []
        for el in els:
            for img in ([el] if el.name == "img" else []) + el.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if src:
                    srcs.append(src.strip())
        return srcs
    return " ".join(el.get_text(strip=True) for el in els).strip()


def _build_export_rows() -> list[dict]:
    """
    Her approved domain için layout başına (domain, layout_id, page_type,
    template_id, field, selector, metric) satırı döndür.
    """
    rows = []
    for domain_file in sorted(APPROVED_DIR.glob("*.json")):
        approved = json.loads(domain_file.read_text(encoding="utf-8"))
        domain   = domain_file.stem      # dosya adı esastır
        layouts  = approved.get("layouts", {})
        pa       = approved.get("page_assignments", {})  # {filename: {layout_id, skipped}}

        # Build reverse map: layout_id → [filenames]
        lid_pages: dict = {}
        for fname, info in pa.items():
            if info.get("skipped") or not info.get("layout_id"):
                continue
            lid_pages.setdefault(info["layout_id"], []).append(fname)

        for lid, layout in layouts.items():
            tid      = layout.get("template_id", "")
            tmpl     = get_template(tid) or {}
            t_fields = tmpl.get("fields", {})
            overrides = layout.get("metric_overrides", {})
            selectors = layout.get("selectors", {})
            pages     = lid_pages.get(lid, [])

            for field, sel in selectors.items():
                metric = overrides.get(field) or t_fields.get(field, {}).get("metric") or (
                    "jaccard" if field == "images" else "rouge"
                )
                rows.append({
                    "domain":      domain,
                    "layout_id":   lid,
                    "layout_name": layout.get("name", lid),
                    "page_type":   page_type_for_layout(layout),
                    "template_id": tid,
                    "field":       field,
                    "selector":    sel,
                    "metric":      metric,
                    "page_count":  len(pages),
                    "pages":       pages,
                })
    return rows


# ---------------------------------------------------------------------------
# BULK TEST
# ---------------------------------------------------------------------------


MCP_CONFIG_FILE = BASE_DIR / "mcp_config.json"


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

# Blueprint modülleri bu modülün bütün adlarını (alt çizgili yardımcılar dahil) kullanır
__all__ = [n for n in dir() if not n.startswith("__")]
