"""
webrulebench/demo/generate_pages.py
======================
Hakem demosu için sentetik haber sayfaları (telifsiz, belirlenimci).

Üç kurgusal site, gerçek sitelerde sık görülen üç farklı yapıyı taklit eder:

  harborherald.example        İngilizce · anlamlı etiketler, WordPress benzeri sınıflar
                              (article + listing layout)
  pulsedaily.example          İngilizce · CSS-in-JS hash sınıfları, data-testid öznitelikleri
  noticiasdelnorte.example    İspanyolca · iç içe div'ler, gövdede reklam bloğu, iki article
                              layout'u (haber + galeri)

Her sayfada gürültü vardır (menü, çerez bandı, "en çok okunanlar", reklam, script),
article sayfalarında JSON-LD bulunur (regex kuralları için). Görseller veri URI'li küçük
SVG'lerdir (dış istek yok). Aynı seed her zaman aynı sayfaları üretir.

    python webrulebench/demo/generate_pages.py OUT_DIR      # OUT_DIR/<domain>/{homepage,listing_NNN,article_NNN}.html
"""

from __future__ import annotations

import base64
import html
import json
import random
import sys
from pathlib import Path

SEED = 20261004

EN_WORDS = ("council harbour plan river bridge market energy school transport budget housing museum festival "
            "storm coast rail port tourism research hospital water library election funding project district "
            "community fishing island trade weather garden ferry factory jobs culture heritage climate").split()
ES_WORDS = ("ciudad puerto plan río puente mercado energía escuela transporte presupuesto vivienda museo festival "
            "tormenta costa tren turismo investigación hospital agua biblioteca elección proyecto barrio comunidad "
            "pesca isla comercio clima jardín fábrica empleo cultura patrimonio").split()
EN_NAMES = ["Alice Morgan", "Daniel Price", "Hannah Lee", "Omar Haddad", "Sofia Rossi", "Liam Carter"]
ES_NAMES = ["Lucía Ramírez", "Mateo Herrera", "Valentina Cruz", "Diego Morales", "Camila Ortiz"]
EN_CATS = ["Local", "Business", "Environment", "Culture", "Sport"]
ES_CATS = ["Regional", "Economía", "Medio ambiente", "Cultura", "Deportes"]


def _img(label: str, w: int = 640, h: int = 360) -> str:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><rect width="100%" height="100%" '
           f'fill="#cfd8dc"/><text x="50%" y="50%" font-size="24" text-anchor="middle" fill="#37474f">'
           f'{html.escape(label)}</text></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _sentence(rng, words, n=None):
    n = n or rng.randint(9, 16)
    s = " ".join(rng.choice(words) for _ in range(n))
    return s[0].upper() + s[1:] + "."


def _title(rng, words):
    return " ".join(w.capitalize() for w in (rng.choice(words) for _ in range(rng.randint(5, 8))))


def _article(rng, lang, i):
    words, names, cats = (EN_WORDS, EN_NAMES, EN_CATS) if lang == "en" else (ES_WORDS, ES_NAMES, ES_CATS)
    day = 1 + (i * 3) % 27
    return {
        "title": _title(rng, words),
        "summary": _sentence(rng, words, 18),
        "author": rng.choice(names),
        "date": f"2026-0{1 + i % 8}-{day:02d}",
        "category": rng.choice(cats),
        "paras": [_sentence(rng, words) + " " + _sentence(rng, words) for _ in range(rng.randint(4, 7))],
        "tags": rng.sample(words, 3),
        "caption": _sentence(rng, words, 7),
        "related": [(_title(rng, words), f"/news/{rng.randint(1000, 9999)}") for _ in range(3)],
        "images": rng.randint(1, 3),
    }


def _jsonld(a, site):
    return ('<script type="application/ld+json">' + json.dumps({
        "@context": "https://schema.org", "@type": "NewsArticle", "headline": a["title"],
        "datePublished": a["date"], "author": {"@type": "Person", "name": a["author"]},
        "publisher": {"@type": "Organization", "name": site}}, ensure_ascii=False) + "</script>")


NOISE_HEAD = """<script>window.dataLayer=[];function track(){}</script>
<style>.cookie{position:fixed;bottom:0}</style>"""


# ── harborherald.example: anlamlı etiketler ─────────────────────────
def harbor_article(a, idx, domain):
    imgs = "".join(f'<figure class="wp-block-image"><img src="{_img(f"Harbor {idx}-{k}")}" alt="photo {k}" width="640" height="360">'
                   f'<figcaption>{html.escape(a["caption"])}</figcaption></figure>' for k in range(1, a["images"] + 1))
    paras = "".join(f"<p>{html.escape(p)}</p>" for p in a["paras"])
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(a['title'])} | Harbor Herald</title>
<meta property="article:published_time" content="{a['date']}T08:00:00Z">{_jsonld(a, 'Harbor Herald')}{NOISE_HEAD}</head>
<body class="single-post">
<header class="site-header"><a class="logo" href="/">Harbor Herald</a>
<nav class="main-menu"><ul><li><a href="/local">Local</a></li><li><a href="/business">Business</a></li><li><a href="/culture">Culture</a></li></ul></nav></header>
<div class="cookie" style="display:none">We use cookies. <button>OK</button></div>
<main id="content" class="site-main">
<nav class="breadcrumbs"><a href="/">Home</a> › <a class="crumb-section" href="/{a['category'].lower()}">{a['category']}</a></nav>
<article class="post">
<header class="entry-header"><h1 class="entry-title">{html.escape(a['title'])}</h1>
<div class="entry-meta"><span class="byline">By <a class="author" href="/author/{idx}">{a['author']}</a></span>
<time class="published" datetime="{a['date']}">{a['date']}</time></div></header>
<p class="entry-summary">{html.escape(a['summary'])}</p>
{imgs}
<div class="entry-content">{paras}</div>
<footer class="entry-footer"><ul class="post-tags">{''.join(f'<li><a href="/tag/{t}">{t}</a></li>' for t in a['tags'])}</ul></footer>
</article>
<section class="related-posts"><h2>Related</h2><ul>{''.join(f'<li><a href="{u}">{html.escape(t)}</a></li>' for t, u in a['related'])}</ul></section>
</main>
<aside class="sidebar"><h3>Most read</h3><ol class="most-read"><li><a href="/news/1">Ferry timetable changes</a></li><li><a href="/news/2">New library opens</a></li></ol>
<div class="ad-slot">Advertisement</div></aside>
<footer class="site-footer"><p>© 2026 Harbor Herald</p></footer></body></html>"""


def harbor_listing(rng, idx, items):
    cards = "".join(f"""<div class="story-card"><img class="thumb" src="{_img(f'Thumb {idx}-{k}', 320, 180)}" alt="">
<h2 class="story-title"><a href="/news/{1000 + idx * 10 + k}">{html.escape(t)}</a></h2><time datetime="{d}">{d}</time></div>"""
                    for k, (t, d) in enumerate(items))
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Latest news | Harbor Herald</title>{NOISE_HEAD}</head>
<body class="archive"><header class="site-header"><a class="logo" href="/">Harbor Herald</a>
<nav class="main-menu"><ul><li><a href="/local">Local</a></li><li><a href="/business">Business</a></li></ul></nav></header>
<main id="content" class="site-main"><h1 class="archive-title">Latest news</h1><div class="story-grid">{cards}</div>
<nav class="pagination"><a href="?page=2">Next</a></nav></main>
<footer class="site-footer"><p>© 2026 Harbor Herald</p></footer></body></html>"""


# ── pulsedaily.example: CSS-in-JS ───────────────────────────────────
def pulse_article(a, idx, domain):
    imgs = "".join(f'<img class="css-9k2l1x e1img0" src="{_img(f"Pulse {idx}-{k}")}" alt="">' for k in range(1, a["images"] + 1))
    paras = "".join(f'<p class="css-7q1z8w ebody2">{html.escape(p)}</p>' for p in a["paras"])
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(a['title'])} — Pulse Daily</title>
{_jsonld(a, 'Pulse Daily')}{NOISE_HEAD}</head><body>
<div id="__next"><div class="css-1d3w5wq e1layout0">
<header class="css-xq8m2a e1hdr0"><nav class="css-3kt9ov"><a class="css-1p4d2nn" href="/">Pulse Daily</a><a class="css-1p4d2nn" href="/world">World</a></nav></header>
<main class="css-1jx2l9h e1main0">
<div class="css-5t8o2v e1sec0"><a data-testid="section-link" class="css-2b9x4c" href="/{a['category'].lower()}">{a['category']}</a></div>
<h1 data-testid="headline" class="css-1qk7f0x e1h0">{html.escape(a['title'])}</h1>
<p data-testid="standfirst" class="css-8u1v3m">{html.escape(a['summary'])}</p>
<div data-testid="byline" class="css-6y2z1q e1by0"><span class="css-0">by </span><a class="css-4r8t2p" href="/people/{idx}">{a['author']}</a></div>
<div data-testid="timestamp" class="css-3g7h1k"><time datetime="{a['date']}T09:30:00Z">{a['date']}</time></div>
<figure data-testid="hero-image" class="css-9m3n2b e1fig0">{imgs}<figcaption class="css-2x7c4v">{html.escape(a['caption'])}</figcaption></figure>
<div data-testid="article-body" class="css-1u8w5t e1body0">{paras}<div class="css-ad0 promo">Subscribe to Pulse Daily</div></div>
<div data-testid="tag-list" class="css-7p2q9r">{''.join(f'<a class="css-1t5y8u" href="/topic/{t}">{t}</a>' for t in a['tags'])}</div>
<section data-testid="related" class="css-4w6e2r"><h2 class="css-0">Read next</h2>{''.join(f'<a class="css-8i1o3p" href="{u}">{html.escape(t)}</a>' for t, u in a['related'])}</section>
</main><footer class="css-2l4k6j"><span>© Pulse Daily</span></footer></div></div></body></html>"""


# ── noticiasdelnorte.example: iç içe div'ler, iki layout ────────────
def norte_article(a, idx, domain):
    imgs = "".join(f'<img src="{_img(f"Norte {idx}-{k}")}" alt="">' for k in range(1, a["images"] + 1))
    paras = [f"<p>{html.escape(p)}</p>" for p in a["paras"]]
    paras.insert(2, '<div class="publicidad">PUBLICIDAD</div>')
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>{html.escape(a['title'])} - Noticias del Norte</title>
{_jsonld(a, 'Noticias del Norte')}{NOISE_HEAD}</head><body>
<div class="contenedor"><div class="cabecera-sitio"><div class="logo">Noticias del Norte</div>
<div class="menu"><a href="/regional">Regional</a> <a href="/economia">Economía</a></div></div>
<div class="principal"><div class="columna-izq">
<div class="migas"><a href="/">Inicio</a> / <a class="seccion" href="/{a['category'].lower()}">{a['category']}</a></div>
<div class="nota"><div class="nota__cabecera"><h1 class="nota__titulo">{html.escape(a['title'])}</h1>
<div class="nota__bajada">{html.escape(a['summary'])}</div>
<div class="nota__datos"><span class="nota__autor">Por {a['author']}</span> · <span class="nota__fecha">{a['date']}</span></div></div>
<div class="nota__foto">{imgs}<p class="pie">{html.escape(a['caption'])}</p></div>
<div class="nota__cuerpo">{''.join(paras)}</div>
<div class="etiquetas">{''.join(f'<a href="/tema/{t}">{t}</a>' for t in a['tags'])}</div>
<div class="relacionadas"><div class="titulo-bloque">Te puede interesar</div><ul>{''.join(f'<li><a href="{u}">{html.escape(t)}</a></li>' for t, u in a['related'])}</ul></div>
</div></div>
<div class="columna-der"><div class="lo-mas-leido"><div class="titulo-bloque">Lo más leído</div><ul><li><a href="/n/1">Nuevo puente</a></li></ul></div></div>
</div><div class="pie-sitio">© 2026 Noticias del Norte</div></div></body></html>"""


def norte_gallery(a, idx, domain):
    items = "".join(f'<div class="galeria-item"><img src="{_img(f"Galería {idx}-{k}")}" alt=""><span class="galeria-texto">{html.escape(a["caption"])} ({k})</span></div>'
                    for k in range(1, 5))
    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><title>Galería: {html.escape(a['title'])}</title>
{_jsonld(a, 'Noticias del Norte')}{NOISE_HEAD}</head><body>
<div class="contenedor"><div class="cabecera-sitio"><div class="logo">Noticias del Norte</div></div>
<div class="galeria"><div class="galeria-head"><span class="galeria-etiqueta">{a['category']}</span><h1>{html.escape(a['title'])}</h1>
<div class="galeria-datos"><b>{a['author']}</b> <i>{a['date']}</i></div></div>
<div class="galeria-intro">{html.escape(a['summary'])}</div><div class="galeria-items">{items}</div></div>
<div class="pie-sitio">© 2026 Noticias del Norte</div></div></body></html>"""


SITES = {
    "harborherald.example": {"lang": "en", "article": harbor_article, "n_article": 8, "listing": harbor_listing, "n_listing": 3},
    "pulsedaily.example": {"lang": "en", "article": pulse_article, "n_article": 7},
    "noticiasdelnorte.example": {"lang": "es", "article": norte_article, "n_article": 7, "gallery": norte_gallery, "n_gallery": 3},
}


def generate(out_dir: Path) -> dict:
    """Sayfaları yazar; {domain: {file: page_kind}} döndürür (page_kind: article | listing | gallery | homepage)."""
    rng = random.Random(SEED)
    manifest = {}
    for domain, spec in SITES.items():
        d = out_dir / domain
        d.mkdir(parents=True, exist_ok=True)
        kinds = {}
        n = 0
        for i in range(spec["n_article"]):
            n += 1
            (d / f"article_{n:03d}.html").write_text(spec["article"](_article(rng, spec["lang"], n), n, domain), encoding="utf-8")
            kinds[f"article_{n:03d}.html"] = "article"
        for i in range(spec.get("n_gallery", 0)):
            n += 1
            (d / f"article_{n:03d}.html").write_text(spec["gallery"](_article(rng, spec["lang"], n), n, domain), encoding="utf-8")
            kinds[f"article_{n:03d}.html"] = "gallery"
        if spec.get("listing"):
            for i in range(1, spec["n_listing"] + 1):
                items = [(_title(rng, EN_WORDS), f"2026-0{1 + k % 8}-1{k}") for k in range(6)]
                (d / f"listing_{i:03d}.html").write_text(spec["listing"](rng, i, items), encoding="utf-8")
                kinds[f"listing_{i:03d}.html"] = "listing"
            items = [(_title(rng, EN_WORDS), "2026-03-01") for _ in range(6)]
            (d / "homepage.html").write_text(spec["listing"](rng, 0, items), encoding="utf-8")
            kinds["homepage.html"] = "listing"
        else:
            first = sorted(kinds)[0]
            (d / "homepage.html").write_text((d / first).read_text(encoding="utf-8"), encoding="utf-8")
            kinds["homepage.html"] = "homepage"
        manifest[domain] = kinds
    return manifest


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_pages")
    m = generate(out)
    print({k: len(v) for k, v in m.items()}, "→", out)
