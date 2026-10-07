"""
webrulebench/demo/setup_demo.py — hakem demosu
=================================
Ayrı bir veri klasörü (varsayılan: demo/data/) kurar; gerçek veriye dokunmaz:

  · 3 sentetik haber sitesi, 5 layout, 29 sayfa (webrulebench/demo/generate_pages.py)
  · 3 annotatörün bağımsız kuralları — bilerek üç tür fark içerir:
      yalnızca yazımı farklı (normalize edilince aynı) · farklı seçici, aynı içerik ·
      gerçek yorum farkı (category = breadcrumb mı etiket mi; related_links'e "en çok okunanlar"
      dahil mi) → GT Onayı'nda kural uyumu ile içerik skoru arasındaki fark görülür
  · onaylı ground truth (annotatör A'nın kuralları, derleme bilgisiyle)
  · LLM gerektirmeyen "demo" backend'i (replay): demo-strong ve demo-weak modelleri;
    demo-weak tipik LLM hatalarını yapar (görsel yerine kapsayıcı, :nth-child, eksik alan)
  · hazır sonuçlar: karşılaştırmalı deney (strong CSS · weak CSS · strong XPath) + regex deneyi
  · "reviewer" admin hesabı — token ekrana bir kez yazılır

Kullanım:
    webrulebench demo [--rebuild]      (ya da: python -m webrulebench.demo.setup_demo [--dir DIR] [--force])
    webrulebench demo   (ya da ./run_demo.sh)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]              # webrulebench/ paketi (defaults/ burada)
PROJECT = CODE.parents[1]                               # depo kökü (src/webrulebench → kök)
DEFAULT_DIR = PROJECT / "demo" / "data" if (PROJECT / "pyproject.toml").exists() else Path.cwd() / "webrulebench-demo"

# ── annotatör kuralları (CSS) ───────────────────────────────────────
HARBOR_A = {"title": "h1.entry-title", "body": "div.entry-content", "author": "span.byline a.author",
            "date": "time.published", "category": "a.crumb-section", "images": "figure.wp-block-image img",
            "images_caption": "figure.wp-block-image figcaption", "related_links": "section.related-posts a",
            "summary": "p.entry-summary", "tags": "ul.post-tags a"}
HARBOR_B = {"title": "h1.entry-title", "body": "article .entry-content", "author": "a.author",
            "date": "time.published", "category": "nav.breadcrumbs a.crumb-section", "images": "figure.wp-block-image > img",
            "images_caption": "figcaption", "related_links": "section.related-posts ul li a",
            "summary": "p.entry-summary", "tags": "ul.post-tags  a"}
HARBOR_C = {"title": "h1", "body": "div.entry-content p", "author": "span.byline", "date": "time",
            "category": "ul.post-tags a", "images": "article img", "images_caption": "figure figcaption",
            "related_links": "section.related-posts a, ol.most-read a", "tags": "UL.post-tags A"}
HARBOR_LIST_A = {"links": "h2.story-title a", "titles": "h2.story-title", "dates": "div.story-card time", "images": "img.thumb"}
HARBOR_LIST_B = {"links": "h2.story-title a", "titles": "div.story-card h2", "dates": "div.story-card time", "images": "div.story-card img"}

PULSE_A = {"title": '[data-testid="headline"]', "body": '[data-testid="article-body"]', "author": '[data-testid="byline"] a',
           "date": '[data-testid="timestamp"] time', "category": '[data-testid="section-link"]',
           "images": '[data-testid="hero-image"] img', "images_caption": '[data-testid="hero-image"] figcaption',
           "related_links": '[data-testid="related"] a', "summary": '[data-testid="standfirst"]', "tags": '[data-testid="tag-list"] a'}
PULSE_B = {"title": "[data-testid='headline']", "body": "div.e1body0", "author": '[data-testid="byline"]  a', "date": '[data-testid="timestamp"] time',
           "category": "a.css-2b9x4c", "images": "figure.e1fig0 img", "images_caption": "figcaption",
           "related_links": "section[data-testid='related'] a", "summary": '[data-testid="standfirst"]', "tags": "div.css-7p2q9r a"}
PULSE_C = {"title": "h1", "body": '[data-testid="article-body"] p', "author": '[data-testid="byline"]',
           "date": '[data-testid="timestamp"]', "category": '[data-testid="tag-list"] a', "images": "figure img",
           "related_links": '[data-testid="related"] a', "tags": '[data-testid="tag-list"] a'}

NORTE_A = {"title": "h1.nota__titulo", "body": "div.nota__cuerpo", "author": "span.nota__autor", "date": "span.nota__fecha",
           "category": "div.migas a.seccion", "images": "div.nota__foto img", "images_caption": "div.nota__foto p.pie",
           "related_links": "div.relacionadas a", "summary": "div.nota__bajada", "tags": "div.etiquetas a"}
NORTE_B = {"title": "h1.nota__titulo", "body": "div.nota__cuerpo > p", "author": "span.nota__autor", "date": "span.nota__fecha",
           "category": "a.seccion", "images": ".nota__foto img", "images_caption": "p.pie",
           "related_links": "div.relacionadas ul li a", "summary": "div.nota__bajada", "tags": "div.etiquetas  a"}
NORTE_C = {"title": "h1", "body": "div.nota", "author": "span.nota__autor", "date": "span.nota__fecha",
           "category": "div.etiquetas a", "images": "img", "images_caption": "p.pie",
           "related_links": "div.relacionadas a, div.lo-mas-leido a", "tags": "div.etiquetas a"}
GALLERY_A = {"title": "div.galeria-head h1", "body": "div.galeria-intro", "author": "div.galeria-datos b",
             "date": "div.galeria-datos i", "category": "span.galeria-etiqueta", "images": "div.galeria-item img",
             "images_caption": "span.galeria-texto", "summary": "div.galeria-intro"}
GALLERY_B = {"title": "h1", "body": ".galeria-intro", "author": ".galeria-datos b", "date": ".galeria-datos i",
             "category": ".galeria-etiqueta", "images": ".galeria-items img", "images_caption": ".galeria-texto"}

# layout: (site, layout_id, name, template, sayfa türü, {annotatör: kurallar})
LAYOUTS = [
    ("harborherald.example", "layout-1", "Article", "article", "article",
     {"demo-annotator-a": HARBOR_A, "demo-annotator-b": HARBOR_B, "demo-annotator-c": HARBOR_C}),
    ("harborherald.example", "layout-2", "Front page & archive", "listing", "listing",
     {"demo-annotator-a": HARBOR_LIST_A, "demo-annotator-b": HARBOR_LIST_B}),
    ("pulsedaily.example", "layout-1", "Article", "article", "article",
     {"demo-annotator-a": PULSE_A, "demo-annotator-b": PULSE_B, "demo-annotator-c": PULSE_C}),
    ("noticiasdelnorte.example", "layout-1", "Nota", "article", "article",
     {"demo-annotator-a": NORTE_A, "demo-annotator-b": NORTE_B, "demo-annotator-c": NORTE_C}),
    ("noticiasdelnorte.example", "layout-2", "Galería", "article", "gallery",
     {"demo-annotator-a": GALLERY_A, "demo-annotator-b": GALLERY_B}),
]

# ── kayıtlı LLM yanıtları (replay) ──────────────────────────────────
STRONG = {
    "harborherald.example": [{"rules": {"css": {**HARBOR_A, "author": "a.author", "images_caption": "figcaption",
                                                "related_links": "section.related-posts a, aside a"}}},   # kenar çubuğu da dahil
                             {"rules": {"css": HARBOR_LIST_A}}],
    "pulsedaily.example": [{"rules": {"css": {**PULSE_A, "date": '[data-testid="timestamp"]', "images_caption": None}}}],
    "noticiasdelnorte.example": [{"rules": {"css": {**NORTE_A, "related_links": "div.relacionadas li a"}}},
                                 {"match": "galeria", "rules": {"css": GALLERY_A}}],
}
WEAK = {   # tipik hatalar: kapsayıcı yerine img yok, sıra numarası, fazla geniş seçici, eksik alan
    "harborherald.example": [{"rules": {"css": {"title": "h1", "body": "p", "author": "span a:nth-child(1)", "date": "time",
                                                "category": None, "images": "figure.wp-block-image", "images_caption": "figure",
                                                "related_links": "aside a", "summary": None, "tags": "ul li a"}}},
                             {"rules": {"css": {"links": "a", "titles": "h2", "dates": "time", "images": "img"}}}],
    "pulsedaily.example": [{"rules": {"css": {"title": "h1", "body": "div p", "author": "a:nth-child(2)", "date": "time",
                                              "category": "main a", "images": "figure", "images_caption": None,
                                              "related_links": "section a", "summary": "p", "tags": None}}}],
    "noticiasdelnorte.example": [{"rules": {"css": {"title": "h1", "body": "div.nota", "author": "span:nth-child(1)",
                                                    "date": "span.nota__fecha", "category": "a", "images": "div.nota__foto",
                                                    "images_caption": None, "related_links": "ul a", "summary": None, "tags": None}}},
                                 {"match": "galeria", "rules": {"css": {"title": "h1", "body": "div", "author": "b",
                                                                        "date": "i", "images": "div.galeria-item"}}}],
}
REGEX = {"title": r'"headline":\s*"([^"]+)"', "date": r'"datePublished":\s*"([^"]+)"',
         "author": r'"author":\s*\{[^}]*"name":\s*"([^"]+)"'}

SITES_META = [
    ("United Kingdom", "GB", "Europe", "en", "harborherald.example", "Harbor Herald (demo)"),
    ("United States", "US", "North America", "en", "pulsedaily.example", "Pulse Daily (demo)"),
    ("Mexico", "MX", "North America", "es", "noticiasdelnorte.example", "Noticias del Norte (demo)"),
]


def _iso(days_ago: float) -> str:
    return (datetime(2026, 9, 20, 10, tzinfo=timezone.utc) - timedelta(days=days_ago)).isoformat()


def _wj(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="WebRuleBench demo")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--force", action="store_true", help="replace an existing demo folder")
    args = ap.parse_args(argv)
    out = Path(args.dir).resolve()
    if out in (CODE, PROJECT):
        sys.exit("The demo folder must not be the project root.")
    if out.exists():
        if not args.force:
            sys.exit(f"{out} exists — use --force to replace it.")
        if not (out / ".llmwb-demo").exists():
            sys.exit(f"{out} does not look like a demo folder (no .llmwb-demo marker); not deleting it.")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / ".llmwb-demo").write_text("created by webrulebench/demo/setup_demo.py\n")

    os.environ["WRB_DATA_DIR"] = str(out)          # proje modülleri bundan sonra demo klasörünü kullanır
    from webrulebench.demo.generate_pages import generate

    # 1. sayfalar + indeks
    kinds = generate(out / "dataset" / "raw")
    index = {}
    for dom, files in kinds.items():
        for f in files:
            pt = "homepage" if f == "homepage.html" else ("listing" if f.startswith("listing") else "article")
            index[f"raw/{dom}/{f}"] = {"url": f"https://{dom}/{f.replace('.html', '')}", "page_type": pt, "domain": dom,
                                       "downloaded_at": _iso(30), "fetch_method": "synthetic",
                                       "size_bytes": (out / "dataset" / "raw" / dom / f).stat().st_size}
    _wj(out / "dataset" / "index.json", index)
    _wj(out / "dataset" / "download_log.json", [])
    _wj(out / "dataset" / "excluded_domains.json", [])

    # 2. yapılandırma dosyaları
    for name in ("layout_templates.json", "template_prompts.json"):
        shutil.copy(CODE / "defaults" / name, out / name)
    models = json.loads((CODE / "defaults" / "llm_models.json").read_text(encoding="utf-8"))
    models["backends"] = {"demo": {"api": "replay", "url": "llm_replay.json", "default_model": "demo-strong",
                                   "models": ["demo-strong", "demo-weak"], "hidden": [], "model_params": {},
                                   "env_key": None, "params": {},
                                   "notes": "Replays recorded responses — no LLM or API key needed (demo)"},
                          **models["backends"]}
    _wj(out / "llm_models.json", models)
    _wj(out / "mcp_config.json", {"backend": "demo", "model": "demo-strong", "strategy": "whitelist"})
    countries = [{"country": c, "code": code, "continent": cont, "language": lang,
                  "sites": [{"name": name, "url": f"https://{dom}", "notes": "synthetic demo site"}]}
                 for c, code, cont, lang, dom, name in SITES_META]
    _wj(out / "sites.json", {"meta": {"created": "2026-10-04", "criteria": "synthetic demo"}, "countries": countries})

    # 3. replay yanıtları (XPath: CSS'ten okunabilir çeviri)
    from webrulebench.rules.rule_utils import css_to_xpath_readable, css_to_xpath
    replay = {"demo-strong": {}, "demo-weak": {}}
    for model, src in (("demo-strong", STRONG), ("demo-weak", WEAK)):
        for dom, entries in src.items():
            out_entries = []
            for e in entries:
                css = e["rules"]["css"]
                rules = {"css": css,
                         "xpath": {f: (css_to_xpath_readable(r) or css_to_xpath(r)) if r else None for f, r in css.items()}}
                if model == "demo-strong":                 # sayfalardaki JSON-LD üzerinden
                    rules["regex"] = {f: REGEX.get(f) for f in css}
                out_entries.append({**({"match": e["match"]} if "match" in e else {}), "rules": rules})
            replay[model][dom] = out_entries
    _wj(out / "llm_replay.json", replay)

    # 4. kullanıcılar
    from webrulebench import users_store as U
    token = U.create("reviewer", "admin")
    for u in ("demo-annotator-a", "demo-annotator-b", "demo-annotator-c"):
        U.create(u, "user")

    # 5. annotation'lar + onaylı GT
    from webrulebench.evaluation.experiments import layout_template_id  # noqa: F401  (modül veri yolunu doğrular)
    gt_by_site, ann = {}, {}
    for dom, lid, name, tid, kind, by_user in LAYOUTS:
        pages = sorted(f for f, k in kinds[dom].items() if k == kind)
        gt = gt_by_site.setdefault(dom, {"domain": dom, "layouts": {}, "page_assignments": {},
                                         "approved_by": "reviewer", "approved_at": _iso(1)})
        gt["layouts"][lid] = {"name": name, "page_type": "listing" if tid == "listing" else "article", "template_id": tid,
                              "selectors": by_user["demo-annotator-a"],
                              "compiled": {"css": {"at": _iso(1), "by": "reviewer"}}}
        for p in pages:
            gt["page_assignments"][p] = {"layout_id": lid, "skipped": False}
        for k, (u, rules) in enumerate(by_user.items()):
            a = ann.setdefault((dom, u), {"domain": dom, "annotator": u, "layouts": {}, "page_assignments": {}})
            a["layouts"][lid] = {"name": name, "page_type": gt["layouts"][lid]["page_type"], "template_id": tid,
                                 "selectors": rules, "updated_at": _iso(3 + k), "history": []}
            if u != "demo-annotator-c":          # atama isteğe bağlıdır; C yalnızca kural yazdı
                for p in pages:
                    a["page_assignments"][p] = {"layout_id": lid, "skipped": False}
    for dom, gt in gt_by_site.items():
        if kinds[dom].get("homepage.html") == "homepage":
            gt["page_assignments"]["homepage.html"] = {"layout_id": None, "skipped": True}
        _wj(out / "ground_truth" / "approved" / f"{dom}.json", gt)
    for (dom, u), a in ann.items():
        _wj(out / "annotations" / dom / f"{u}.json", a)

    # 6. hazır deneyler (replay — saniyeler sürer)
    import threading
    from webrulebench.evaluation import experiments as X
    layouts = X.eligible_layouts()
    base = {"backend": "demo", "rule_source": "llm", "strategy": "whitelist", "sample": {"mode": "first"}}
    gid, ids = X.create_group("Demo · strong vs weak · CSS and XPath",
                              [{**base, "model": "demo-strong", "rule_type": "css"},
                               {**base, "model": "demo-weak", "rule_type": "css"},
                               {**base, "model": "demo-strong", "rule_type": "xpath"}], layouts, "reviewer")
    rx = X.create("Demo · strong · Regex (JSON-LD)", {**base, "model": "demo-strong", "rule_type": "regex"},
                  [l for l in layouts if l["template_id"] == "article"], "reviewer")
    for eid in ids + [rx["id"]]:
        X._worker(eid, threading.Event())
    results = {e["name"]: (e["status"], (e.get("summary") or {}).get("mean")) for e in map(X.load, ids + [rx["id"]])}

    log = out / "dataset" / "deletion_audit.log"
    log.write_text("".join(f"2026-09-{d:02d} 10:00:00  {a}\n" for d, a in [
        (10, "SITE_ADD  domain=harborherald.example  name=Harbor Herald (demo)  by=reviewer"),
        (17, "COMPILE  domain=harborherald.example  layout=layout-1  pages=8  fields=10  by=reviewer"),
        (19, f"EXPERIMENT_GROUP_START  id={gid}  user=reviewer")]), encoding="utf-8")

    print("\n  Demo data written to", out)
    print("  Sites:", ", ".join(kinds), f"· {sum(len(v) for v in kinds.values())} pages · {len(LAYOUTS)} layouts")
    for n, (st, mean) in results.items():
        print(f"  Experiment: {n:42} {st:8} mean={mean}")
    print("\n  Log in as:  reviewer")
    print(f"  Token:      {token}\n")
    print("  Start:  webrulebench demo      (or ./run_demo.sh)")
    print("  Open:   http://127.0.0.1:5002\n")
    (out / "REVIEWER_LOGIN.txt").write_text(f"username: reviewer\ntoken: {token}\n", encoding="utf-8")
    os.chmod(out / "REVIEWER_LOGIN.txt", 0o600)


if __name__ == "__main__":
    main()
