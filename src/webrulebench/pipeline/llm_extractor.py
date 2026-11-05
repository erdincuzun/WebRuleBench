"""
llm_extractor.py
================
LLM tabanlı kural üretici (CSS selector / XPath / Regex).

Skeleton HTML'i bir LLM'e gönderir, alan → kural eşlemesini JSON olarak alır.
Backend'ler llm_models.json kayıt defterindedir (llm_models.py); API tipleri:
  - ollama     — yerel (Ollama)
  - anthropic  — Claude API
  - gemini     — Google Gemini API
  - openai     — OpenAI uyumlu servisler (Groq, NVIDIA NIM, OpenRouter ...)
Çağrılar requests ile yapılır; API anahtarı ortam değişkeninden ya da .env'den okunur.

Girdi  : skeleton HTML string
Çıktı  : {"title": "h1.news-detail-title", "body": "...", ...}

Kullanım:
  from webrulebench.pipeline.llm_extractor import LLMExtractor
  extractor = LLMExtractor(backend="ollama", rule_type="css")     # model: backend varsayılanı
  result    = extractor.extract(skeleton_html, domain="hurriyet.com.tr")
  print(result.selectors)

  Deneylerde sistem/kullanıcı prompt'u ve alan listesi dışarıdan verilir
  (system_prompt=, user_prompt=, fields= — bkz. prompt_builder.py, experiments.py).

CLI:
  python -m webrulebench.pipeline.llm_extractor dataset/raw/hurriyet.com.tr/article_001.html
  python -m webrulebench.pipeline.llm_extractor dataset/raw/hurriyet.com.tr/article_001.html --backend claude --rule-type xpath
  python -m webrulebench.pipeline.llm_extractor dataset/raw/hurriyet.com.tr/article_001.html --rule-type regex --show-skeleton
"""

import json
import os
import time
import re
import argparse
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import requests
from webrulebench.pipeline.llm_models import BACKENDS, call_timeout, default_model as _default_model

# ---------------------------------------------------------------------------
# CONFIG — backend ayarları llm_models.json'da (llm_models.py); burada yalnızca yedek varsayılan
# ---------------------------------------------------------------------------
OLLAMA_MODEL = BACKENDS.get("ollama", {}).get("default_model", "qwen2.5-coder:14b")

# Çıkarılacak alanlar
from webrulebench.config import FIELDS


def _api_key(name: str) -> str:
    """API anahtarı: önce ortam değişkeni, yoksa proje kökündeki .env (KEY=değer satırları)."""
    if os.environ.get(name):
        return os.environ[name]
    from webrulebench.paths import DATA_DIR
    env_path = DATA_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                if k.strip() == name:
                    return v.strip().strip("'\"")
    return ""

# Geçerli HTML tag'leri — selector fix için
HTML_TAGS_SET = {
    "a", "abbr", "address", "article", "aside", "audio", "b", "blockquote",
    "body", "br", "button", "canvas", "caption", "cite", "code", "col",
    "data", "dd", "del", "details", "dfn", "div", "dl", "dt", "em", "embed",
    "fieldset", "figcaption", "figure", "footer", "form",
    "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hr", "html",
    "i", "iframe", "img", "input", "ins", "kbd", "label", "legend", "li",
    "link", "main", "map", "mark", "menu", "meta", "meter", "nav",
    "noscript", "object", "ol", "optgroup", "option", "output",
    "p", "picture", "pre", "progress", "q", "rp", "rt", "ruby",
    "s", "samp", "script", "section", "select", "small", "source", "span",
    "strong", "style", "sub", "summary", "sup",
    "table", "tbody", "td", "template", "textarea", "tfoot", "th", "thead",
    "time", "title", "tr", "track", "u", "ul", "var", "video", "wbr",
}


def _split_top(s: str, sep: str | None = None) -> list[str]:
    """Yalnızca en üst düzeyde böl: tırnak, (...) ve [...] içindekiler bölünmez.
    sep=None → boşluklarda (boş parçalar atılır); aksi halde bu karakterde."""
    parts, buf, depth, quote = [], [], 0, None
    for ch in s:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and (ch.isspace() if sep is None else ch == sep):
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return [p for p in parts if p] if sep is None else parts


def _class_names(html: str) -> set:
    """HTML'deki bütün class adları."""
    return {c for v in re.findall(r"""\bclass\s*=\s*(?:"([^"]*)"|'([^']*)')""", html) for c in "".join(v).split()}

# ---------------------------------------------------------------------------
# PROMPT
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert web scraping assistant specialized in structural HTML analysis.
Your task is to extract CSS selectors from an HTML skeleton to locate news article fields.

The skeleton contains only tag names, class names, and IDs — no text content.
Return ONLY a valid JSON object. No prose, no markdown, no code blocks, no explanation.

SELECTOR RULES:
1. Depth: Use SHORT selectors — maximum 4 levels (e.g. "div.meta time", "article div.body p")
2. Prefer class selectors: "h1.article-title", "div.article-body"
3. Prefer ID selectors when available: "main#main-content", "article#post-123"
4. Body: prefer the narrowest single container that wraps the full story text
   - If <main> or <article> has an id → always use it: "main#content"
   - Otherwise use the most specific wrapper: "div.article-body"
   - Prefer LOW link density: avoid containers where <a> tags outnumber <p> tags
   - Prefer <article> over <main> when both exist — <main> often includes navigation and related links
   - If only <main> exists, look for a child container (div, section, article) with fewer links
5. Dynamic classes marked with asterisks → use attribute selector: div[class*="TextContainer"]
6. Avoid hash/generated classes (e.g. sc-f98b1ad2-0, ey6wfo1) — they are unstable
7. Semantic fallback when no class: "article h1", "main p", "article time"
8. Prefer data-* attributes and IDs over class names when available:
   GOOD: div[data-testid="body-content"], section[data-testid="article-body"]
   BAD:  div.wsquJ, div.Hy4HP
9. When an element has multiple classes, prefer human-readable ones over hash-like ones:
   If classes include both "news-single" and "wsquJ", use div.news-single (not div.wsquJ)
   Hash-like = short (4-6 chars), mixed-case, no hyphens, no meaning (e.g. xQoVi, z5wPE)

ANNOTATION RULES (skeleton marks dynamic values with asterisks):
- Tokens wrapped in asterisks (*Lora-Regular*, *[30px]*, *col*, *primary*) are informational hints — NOT CSS class names
- NEVER include *annotation* tokens in selectors
- For Tailwind bracket classes use attribute selector: div[class*="text-[19px]"]

COMMENT RULES (<!-- contains: X --> means child tags exist but were pruned):
- <!-- contains: a -->    → append " a" to selector    (e.g. "div.byline a")
- <!-- contains: span --> → append " span" to selector (e.g. "div.date span")
- <!-- contains: img -->  → append " img" to selector  (e.g. "figure img")
- Only use the comment hint if no explicit child tag is already shown in skeleton

SELECTOR ANTI-PATTERNS (NEVER use these):
- NEVER use style attribute selectors: span[style*='...'] is ALWAYS WRONG
- NEVER use text content in selectors: no :contains(), no [text*=...]
- NEVER use # for a CSS class — # means id, . means class. "div#foo" means id="foo", "div.foo" means class="foo"
- For annotated classes like *leading*, use attribute selector: div[class*="leading"]

FIELDS (return null if not found):
- title   : main article headline (h1 inside article or main)
- date    : publication timestamp (time tag, span, or div near article header with a date-like class such as "date", "time", "published", "created", "leading", "meta")
             If date text is visible in skeleton as a span/div child, select the nearest named container: div[class*="leading"] span
- author  : author/byline — look for containers near date with <!-- contains: a --> or <!-- contains: span -->
- body    : main article text container — the narrowest wrapper around paragraphs
- images  : article images — goal is ALL article images (hero + inline body)
             NEVER use bare `img` alone — always anchor to a container
             1. If img has an article-specific class → use `img.classname`
                WARNING: utility classes like `img-fluid`, `img-responsive`, `w-100` appear on sidebar/avatar/ad images too — never use them alone; anchor to container instead
             2. If img has no class or only utility classes → use its container: `div.article-body img`, `figure img`
                Look for `<!-- contains: img -->` in the skeleton — that marks the image container
             3. For broader coverage: `article figure img` or `{body_selector} img`
             4. If hero and inline body images differ in structure, combine: "figure.hero img, div.article-body figure img"
- tags    : article tags/categories — look for containers with class "tags", "topics", "category", "categories", "labels", "breadcrumb" or id containing "tag".
            Also check inside breadcrumb containers (e.g. div.breadcrumbs div.topics, div.category-links).
            Prefer the primary section/category label first (breadcrumb near article header), then keyword tags.
            If multiple tag areas exist, combine with comma: "div.category a, div.tags a"

Example output:
{"title": "h1.headline", "date": "div.meta time", "author": "div.byline a", "body": "div.article-body", "images": "img.article-photo", "tags": "div.tags a, div.category a"}"""

# ---------------------------------------------------------------------------
# XPATH PROMPT
# ---------------------------------------------------------------------------
XPATH_SYSTEM_PROMPT = """You are an expert web scraping assistant specialized in structural HTML analysis.
Your task is to extract XPath expressions from an HTML skeleton to locate news article fields.

The skeleton contains only tag names, class names, and IDs — no text content.
Return ONLY a valid JSON object. No prose, no markdown, no code blocks, no explanation.

XPATH RULES:
1. Depth: Use SHORT paths — prefer //tag[@class="x"] over long absolute paths
2. Prefer class match: //h1[contains(@class,"headline")]
3. Prefer ID match when available: //main[@id="main-content"]
4. Use contains(@class, "...") instead of @class="..." — elements often have multiple classes
5. Body: prefer the narrowest single container that wraps the full story text
   - If <main> or <article> has an id → always use it: //main[@id="content"]
   - Otherwise use the most specific wrapper: //div[contains(@class,"article-body")]
   - Prefer <article> over <main> when both exist
6. Dynamic classes marked with asterisks → use contains(): //div[contains(@class,"TextContainer")]
7. Avoid hash/generated classes (e.g. sc-f98b1ad2-0, ey6wfo1) — they are unstable
8. Semantic fallback when no class: //article//h1, //main//p, //article//time
9. Prefer data-* attributes and IDs over class names when available:
   GOOD: //div[@data-testid="body-content"]
   BAD:  //div[contains(@class,"wsquJ")]
10. Combine alternatives with the union operator " | ": //div[contains(@class,"tags")]//a | //div[contains(@class,"category")]//a

ANNOTATION RULES (skeleton marks dynamic values with asterisks):
- Tokens wrapped in asterisks (*Lora-Regular*, *[30px]*, *col*, *primary*) are informational hints — NOT CSS class names
- NEVER include *annotation* tokens in XPath expressions

COMMENT RULES (<!-- contains: X --> means child tags exist but were pruned):
- <!-- contains: a -->    → append "//a" to the path
- <!-- contains: span --> → append "//span" to the path
- <!-- contains: img -->  → append "//img" to the path
- Only use the comment hint if no explicit child tag is already shown in skeleton

XPATH ANTI-PATTERNS (NEVER use these):
- NEVER match on style attributes
- NEVER match on text content unless explicitly using contains(text(), ...) for a stable label (e.g. breadcrumb "Home")
- NEVER produce invalid XPath (unbalanced brackets/quotes)

FIELDS (return null if not found):
- title   : main article headline (h1 inside article or main)
- date    : publication timestamp (time tag, span, or div near article header with a date-like class such as "date", "time", "published", "created", "leading", "meta")
- author  : author/byline — look for containers near date with <!-- contains: a --> or <!-- contains: span -->
- body    : main article text container — the narrowest wrapper around paragraphs
- images  : article images — goal is ALL article images (hero + inline body); never use bare //img alone — always anchor to a container
- tags    : article tags/categories — look for containers with class "tags", "topics", "category", "categories", "labels", "breadcrumb" or id containing "tag"

Example output:
{"title": "//h1[contains(@class,\\"headline\\")]", "date": "//div[contains(@class,\\"meta\\")]//time", "author": "//div[contains(@class,\\"byline\\")]//a", "body": "//div[contains(@class,\\"article-body\\")]", "images": "//img[contains(@class,\\"article-photo\\")]", "tags": "//div[contains(@class,\\"tags\\")]//a | //div[contains(@class,\\"category\\")]//a"}"""

# ---------------------------------------------------------------------------
# REGEX PROMPT
# ---------------------------------------------------------------------------
REGEX_SYSTEM_PROMPT = """You are an expert web scraping assistant specialized in pattern-based text extraction.
Your task is to write Python regular expressions that extract news article fields directly from raw HTML text
(not via DOM structure — the pattern is matched against the page's HTML source as plain text).

Return ONLY a valid JSON object. No prose, no markdown, no code blocks, no explanation.

REGEX RULES:
1. Prefer matching stable, structured markers over free text:
   - JSON-LD / meta tags: "datePublished":"([^"]+)", <meta[^>]+property="article:author"[^>]+content="([^"]+)"
   - Data attributes: data-published-date="([^"]+)"
2. Use exactly ONE capturing group per field — that group is the extracted value
3. Escape special regex characters that appear literally (., (, ), [, ], etc.)
4. Prefer non-greedy quantifiers ([^"]+ or .+?) to avoid over-matching across tags
5. Do NOT rely on exact whitespace/newline formatting — HTML minification varies
6. Anchor around unique, recognizable substrings (class names, meta property names, JSON keys)
   rather than raw positional patterns
7. For fields that may appear multiple times (images, tags), the pattern should be usable with
   re.findall — write it so each match yields one item (e.g. one image URL, one tag)

ANNOTATION RULES (skeleton marks dynamic values with asterisks):
- The provided skeleton is structural context only, to help you guess where fields live in the
  real page — do NOT include *annotation* tokens in the regex itself

FIELDS (return null if not found — a field may not be reliably extractable via regex):
- title   : main article headline — check <title>, og:title meta, or JSON-LD "headline"
- date    : publication timestamp — check JSON-LD "datePublished", meta property="article:published_time"
- author  : author/byline — check JSON-LD "author":{"name":"..."}, meta name="author"
- body    : main article text — regex is usually a poor fit for body; only attempt if there is a
             clear structured marker (e.g. a single JSON field with escaped HTML); otherwise return null
- images  : article image URLs — check og:image meta, JSON-LD "image", or <img src="..."> near article markers
- tags    : article tags/categories — check JSON-LD "keywords", meta name="keywords" (comma-separated)

Example output:
{"title": "<title>([^<]+)</title>", "date": "\\"datePublished\\"\\s*:\\s*\\"([^\\"]+)\\"", "author": "\\"author\\"\\s*:\\s*\\{[^}]*\\"name\\"\\s*:\\s*\\"([^\\"]+)\\"", "body": null, "images": "<meta property=\\"og:image\\" content=\\"([^\\"]+)\\"", "tags": "\\"keywords\\"\\s*:\\s*\\"([^\\"]+)\\""}"""

SYSTEM_PROMPTS_BY_RULE_TYPE = {
    "css":   SYSTEM_PROMPT,
    "xpath": XPATH_SYSTEM_PROMPT,
    "regex": REGEX_SYSTEM_PROMPT,
}

USER_PROMPT_TEMPLATE = """Analyze this HTML skeleton from {domain} and return CSS selectors as JSON:

{skeleton}

Return only the JSON object."""

USER_PROMPT_TEMPLATES_BY_RULE_TYPE = {
    "css": USER_PROMPT_TEMPLATE,
    "xpath": """Analyze this HTML skeleton from {domain} and return XPath expressions as JSON:

{skeleton}

Return only the JSON object.""",
    "regex": """Analyze this HTML skeleton from {domain} (structural context only — the regex you
write will run against the page's raw HTML text, not this skeleton) and return regex patterns as JSON:

{skeleton}

Return only the JSON object.""",
}

# İskelet yerine sayfanın HTML'i verildiğinde (deney ayarı skeleton = none)
USER_PROMPT_TEMPLATES_HTML_BY_RULE_TYPE = {
    "css": """Analyze this HTML page from {domain} and return CSS selectors as JSON:

{skeleton}

Return only the JSON object.""",
    "xpath": """Analyze this HTML page from {domain} and return XPath expressions as JSON:

{skeleton}

Return only the JSON object.""",
    "regex": """Analyze this HTML page from {domain} (the regex you write will run against the page's raw HTML
text, which may differ from the HTML shown if it was cleaned) and return regex patterns as JSON:

{skeleton}

Return only the JSON object.""",
}


# ---------------------------------------------------------------------------
# GİRDİ KESİLMESİ
# Bağlam penceresini aşan girdiyi bazı sunucular (Ollama) hata vermeden kısaltır: model sayfanın yalnızca
# bir bölümünü görür ve kural yine üretilir. Sunucunun bildirdiği girdi token sayısından anlaşılır.
# ---------------------------------------------------------------------------
TRUNCATION_MAX_CHARS_PER_TOKEN = 6.0   # HTML ≈ 2–3.5, iskelet ≈ 3.5–5 karakter/token
OUTPUT_LIMIT_REASONS = {"length", "max_tokens"}   # OpenAI/Ollama, Anthropic, Gemini (küçük harfe çevrilmiş)

# Geçici HTTP hataları: 429 hız/kota sınırı, 503 sunucu (model) dolu — beklenip yeniden denenir (_post)
RETRY_STATUSES     = {429, 503}
MAX_RETRIES        = 5
RETRY_WAIT_S       = 10     # ilk bekleme; her denemede ikiye katlanır (10, 20, 40, 60, 60)
RETRY_WAIT_MAX_S   = 60     # tek bekleme en fazla


def _retry_wait(retry_after: str | None, body: str, attempt: int = 0) -> float:
    """Yeniden denemeden önce beklenecek süre (sn): RETRY_WAIT_S · 2^attempt; sağlayıcı daha uzun bir süre
    bildirirse o — Retry-After başlığı (saniye), yoksa hata gövdesindeki error.evren.resets_at anı (EVREN).
    Sağlayıcının bildirdiği süre kısa kalabilir (EVREN: model dolu iken birkaç saniye), bu yüzden alt sınır
    katlanan süredir. En fazla RETRY_WAIT_MAX_S."""
    wait = None
    try:
        wait = float(retry_after)
    except (TypeError, ValueError):
        try:
            from datetime import datetime, timezone
            reset = json.loads(body)["error"]["evren"]["resets_at"]
            wait = (datetime.fromisoformat(reset.replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds()
        except Exception:
            pass
    return min(max(wait or 0.0, RETRY_WAIT_S * 2 ** attempt), RETRY_WAIT_MAX_S)


def input_truncation(prompt_chars: int, prompt_tokens: int) -> str:
    """Girdi kesilmiş görünüyorsa nedenini, görünmüyorsa "" döndürür.
    - Ollama, sığmayan girdiyi pencerenin yarısına indirir: prompt_tokens = 2^k + birkaç başlangıç token'ı
      (Qwen, gpt-oss: +2 → 16k'da 8194, 32k'da 16386; gemma4: +3 → 128k'da 65539).
    - Genel: karakter/token oranı metnin tamamının sayılamayacağı kadar yüksek."""
    if prompt_tokens <= 0:
        return ""
    for extra in range(2, 5):
        half = prompt_tokens - extra
        if half >= 1024 and half & (half - 1) == 0:
            return (f"Input truncated by the server: {prompt_tokens} input tokens is half of a "
                    f"{2 * half}-token context window — the input did not fit")
    ratio = prompt_chars / prompt_tokens
    if ratio > TRUNCATION_MAX_CHARS_PER_TOKEN:
        return (f"Input truncated by the server: {prompt_chars} characters counted as {prompt_tokens} "
                f"tokens ({ratio:.1f} characters/token)")
    return ""


# ---------------------------------------------------------------------------
# RESULT
# ---------------------------------------------------------------------------
@dataclass
class ExtractResult:
    domain:        str
    backend:       str
    model:         str
    strategy:      str
    selectors:     dict
    raw_response:  str
    elapsed_ms:    float
    success:       bool
    rule_type:     str = "css"
    error:         str = ""
    prompt_tokens: int = 0   # LLM girdi token sayısı (API'den)
    gen_tokens:    int = 0   # LLM çıktı token sayısı (API'den)
    truncated:     str = ""  # girdi kesilmesi (input_truncation) — boşsa yok
    finish_reason: str = ""  # sağlayıcının bildirdiği durma nedeni (stop, length, max_tokens …) — bildirilmezse boş
    retries:       int = 0   # 429/503 sonrası yeniden deneme sayısı (bekleme süresi elapsed_ms'e girmez)

    def metrics(self) -> dict:
        return {
            "domain":        self.domain,
            "backend":       self.backend,
            "model":         self.model,
            "strategy":      self.strategy,
            "rule_type":     self.rule_type,
            "success":       self.success,
            "fields_found":  sum(1 for v in self.selectors.values() if v),
            "elapsed_ms":    round(self.elapsed_ms, 2),
            "prompt_tokens": self.prompt_tokens,
            "gen_tokens":    self.gen_tokens,
            "truncated":     self.truncated,
            "finish_reason": self.finish_reason,
            "retries":       self.retries,
            "error":         self.error,
        }


# ---------------------------------------------------------------------------
# EXTRACTOR
# ---------------------------------------------------------------------------
class LLMExtractor:

    def __init__(self,
                 backend: Literal["ollama", "claude", "gemini", "groq", "nvidia"] = "ollama",
                 model: str = None,
                 timeout: int = None,
                 rule_type: Literal["css", "xpath", "regex"] = "css",
                 system_prompt: str = None,
                 user_prompt: str = None,
                 fields: list = None,
                 repair_css: bool = False):
        """fields: yanıttan okunacak alanlar (şablonun alanları). Verilmezse config.FIELDS.
        repair_css: CSS kurallarına sezgisel onarımlar uygulanır (_fix_selector, _fix_body_from_skeleton);
        kapalıyken kurallar modelin yazdığı gibi döner — deneylerde bir değişkendir (config.css_repair)."""
        self.fields        = list(fields) if fields else list(FIELDS)
        self.repair_css    = repair_css
        self._classes      = set()          # iskeletteki class adları (onarım, extract'ta doldurulur)
        self._finish       = ""             # son çağrının durma nedeni (_call_llm)
        self._retries      = 0              # son çağrıda 429/503 sonrası yeniden deneme sayısı (_post)
        self._waited       = 0.0            # bu denemeler için beklenen süre (sn)
        self.backend       = backend
        self.timeout       = timeout or call_timeout(backend)   # verilmezse backend ayarı
        self.rule_type     = rule_type
        self.model         = model or _default_model(backend) or OLLAMA_MODEL
        self._system_prompt = system_prompt or SYSTEM_PROMPTS_BY_RULE_TYPE[rule_type]
        self._user_prompt   = user_prompt   or USER_PROMPT_TEMPLATES_BY_RULE_TYPE[rule_type]

    def extract(self, skeleton_html: str, domain: str = "unknown", annotated: bool = True) -> ExtractResult:
        """Skeleton HTML'den kural (CSS selector / XPath / Regex) çıkar.
        annotated=False: girdi iskelet değil sayfanın HTML'idir; *annotation* temizliği yapılmaz."""
        # *annotation* token'larını class attribute'larından temizle
        # Örnek: class="text-[19px] *Lora-Regular* *[30px]*" → class="text-[19px]"
        import re as _re
        clean_skeleton = _re.sub(r'\s*\*[^*]+\*', '', skeleton_html) if annotated else skeleton_html
        self._domain   = domain             # replay backend yanıtı alan adına göre seçer
        self._classes  = _class_names(clean_skeleton)

        prompt     = self._user_prompt.format(
            domain=domain,
            skeleton=clean_skeleton,
        )
        t0                            = time.perf_counter()
        raw, error, ptok, gtok        = self._call_llm(prompt)
        elapsed_ms                    = (time.perf_counter() - t0 - self._waited) * 1000   # 429/503 beklemesi hariç

        selectors, success, parse_error = self._parse_response(raw)
        if parse_error:
            error = error or parse_error     # yanıt boşsa çağrı hatası (zaman aşımı vb.) korunur
        if not success and self._finish in OUTPUT_LIMIT_REASONS:
            error += f" — output limit reached ({gtok} tokens, finish_reason {self._finish}): raise max_tokens"

        # CSS'e özel onarımlar (isteğe bağlı) — XPath/Regex'te selector söz dizimi farklı olduğundan uygulanmaz
        if self.rule_type == "css" and self.repair_css and "body" in self.fields:
            selectors["body"] = self._fix_body_from_skeleton(
                selectors.get("body"), skeleton_html
            )

        return ExtractResult(
            domain         = domain,
            backend        = self.backend,
            model          = self.model,
            strategy       = "",
            rule_type      = self.rule_type,
            selectors      = selectors,
            raw_response   = raw,
            elapsed_ms     = elapsed_ms,
            success        = success,
            error          = error,
            prompt_tokens  = ptok,
            gen_tokens     = gtok,
            truncated      = input_truncation(len(self._system_prompt) + len(prompt), ptok),
            finish_reason  = self._finish,
            retries        = self._retries,
        )

    # ── LLM çağrıları ─────────────────────────────────────────────────────
    def _call_llm(self, prompt: str) -> tuple[str, str, int, int]:
        """(text, error, prompt_tokens, gen_tokens) döndürür.
        Çağrı biçimi backend'in API tipine göre seçilir (llm_models.json); URL ve üretim
        parametreleri çağrı anında okunur — ayar sayfasındaki değişiklik hemen geçerlidir.
        Sağlayıcının durma nedeni self._finish'e yazılır."""
        self._finish = ""
        self._retries, self._waited = 0, 0.0
        cfg = BACKENDS.get(self.backend)
        if not cfg:
            return "", f"Bilinmeyen backend: {self.backend}", 0, 0
        api = cfg.get("api") or {"ollama": "ollama", "claude": "anthropic", "gemini": "gemini"}.get(self.backend, "openai")
        key = ""
        if cfg.get("env_key"):
            key = _api_key(cfg["env_key"])
            if not key:
                return "", f"{cfg['env_key']} is not set (environment variable or .env)", 0, 0
        try:
            call = {"ollama": self._call_ollama, "anthropic": self._call_anthropic,
                    "gemini": self._call_gemini, "openai": self._call_openai,
                    "replay": self._call_replay}.get(api)
            if not call:
                return "", f"Unknown API type: {api}", 0, 0
            # backend varsayılanları + bu modele özel ayarlar (llm_models.json → model_params)
            params = {**(cfg.get("params") or {}), **((cfg.get("model_params") or {}).get(self.model) or {})}
            return call(prompt, cfg, key, params)
        except requests.Timeout:
            return "", f"Timeout ({self.timeout} s)", 0, 0
        except requests.ConnectionError as e:
            return "", f"Server unreachable: {cfg.get('url')} ({type(e).__name__})", 0, 0
        except Exception as e:
            return "", str(e), 0, 0

    def _call_replay(self, prompt, cfg, key, p) -> tuple[str, str, int, int]:
        """Kayıtlı yanıtları geri oynatır (LLM gerekmez).
        Dosya: {model: {domain: [{match?: metin, rules: {css|xpath|regex: {alan: kural}}}]}}. Bir sitede birden fazla
        kayıt varsa "match" metni prompt'ta (iskelette) geçenler arasından, alanları bu çağrının alanlarıyla en çok
        örtüşen kayıt seçilir."""
        from webrulebench.paths import DATA_DIR
        path = DATA_DIR / (cfg.get("url") or "llm_replay.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        if self.model not in data:
            return "", f"No recorded responses for model {self.model} in {path.name}", 0, 0
        if not getattr(self, "_domain", ""):          # bağlantı testi (alan adı yok): dosya ve model mevcut
            return "OK", "", 0, 1
        entries = data[self.model].get(self._domain, [])
        best, overlap = None, -1
        matched = [e for e in entries if e.get("match") and e["match"] in prompt]   # ayırt edici metni iskelette geçen kayıt
        for e in matched or [e for e in entries if not e.get("match")]:              # öncelikli; yoksa koşulsuz kayıtlar
            rules = (e.get("rules") or {}).get(self.rule_type) or {}
            o = len(set(rules) & set(self.fields))
            if o > overlap:
                best, overlap = rules, o
        if best is None:
            return "", f"No recorded response for {self.model} / {getattr(self, '_domain', '')}", 0, 0
        text = json.dumps({f: best.get(f) for f in self.fields}, ensure_ascii=False)
        return text, "", len(self._system_prompt + prompt) // 4, len(text) // 4

    def _post(self, url: str, **kw):
        """POST; HTTP hatasında sağlayıcının açıklamasını da içeren istisna.
        self.timeout bir denemenin toplam süresidir (_attempt): yanıt başlıkları hiç gelmese de aşılınca deneme
        bırakılır.
        429 (hız/kota sınırı) ve 503 (sunucu dolu) geçicidir: sağlayıcının söylediği kadar beklenip en fazla
        MAX_RETRIES kez yeniden denenir. Deneme sayısı self._retries'e, bekleme süresi self._waited'a yazılır."""
        for attempt in range(MAX_RETRIES + 1):
            status, headers, body = self._attempt(url, **kw)
            if status in RETRY_STATUSES and attempt < MAX_RETRIES:
                t0 = time.perf_counter()
                time.sleep(_retry_wait(headers.get("Retry-After"), body, attempt))
                self._retries += 1
                self._waited  += time.perf_counter() - t0
                continue
            if status >= 400:
                body = body.strip().replace("\n", " ")
                raise RuntimeError(f"HTTP {status}: {body[:300]}")
            return json.loads(body)

    def _attempt(self, url: str, **kw) -> tuple[int, dict, str]:
        """Tek POST denemesi, toplam süresi self.timeout: (durum, başlıklar, gövde).
        requests'in timeout'u yalnızca iki okuma arasındaki beklemeyi sınırlar; bağlantıyı ara ara gelen baytlarla
        canlı tutan bir sunucu onu hiç doldurmaz. Gövde bu yüzden parça parça okunur, süre aşılınca bağlantı
        kapatılır. Başlıklar gelmeden takılan bir istek (ör. bilgisayar uykudan dönünce) bu döngüye hiç ulaşmaz:
        istek ayrı bir thread'de yapılır ve süre dolunca beklenmeden Timeout verilir."""
        deadline = time.monotonic() + self.timeout
        out = {}

        def run():
            try:
                with requests.post(url, timeout=self.timeout, stream=True, **kw) as resp:
                    chunks = []
                    for chunk in resp.iter_content(chunk_size=1):   # büyük parça, dolana kadar bekler
                        chunks.append(chunk)
                        if time.monotonic() > deadline:
                            raise requests.Timeout()
                    body = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
                out["result"] = resp.status_code, resp.headers, body
            except BaseException as e:                          # çağıran thread'de yeniden fırlatılır
                out["error"] = e

        t = threading.Thread(target=run, daemon=True)           # süre dolunca bırakılır, soket zaman aşımıyla biter
        t.start()
        t.join(self.timeout)
        if t.is_alive() or time.monotonic() > deadline:
            raise requests.Timeout()
        if "error" in out:
            raise out["error"]
        return out["result"]

    def _messages(self, prompt: str) -> list:
        return [{"role": "system", "content": self._system_prompt}, {"role": "user", "content": prompt}]

    def _call_ollama(self, prompt, cfg, key, p) -> tuple[str, str, int, int]:
        opts = {"temperature": p.get("temperature", 0.0), "num_predict": p.get("max_tokens", 512)}
        for k in ("seed", "num_ctx", "top_p"):
            if p.get(k) is not None:
                opts[k] = p[k]
        body = {"model": self.model, "messages": self._messages(prompt), "stream": False, "options": opts}
        if p.get("think") is not None:      # düşünen modeller (ör. gemma4): false → doğrudan yanıt
            body["think"] = bool(p["think"])
        data = self._post(cfg["url"].replace("/generate", "/chat"), json=body)
        msg = data.get("message") or {}
        self._finish = data.get("done_reason") or ""
        text, ptok, gtok = msg.get("content") or "", data.get("prompt_eval_count", 0), data.get("eval_count", 0)
        if not text.strip() and msg.get("thinking"):
            return "", "Empty response: the model spent its output tokens on thinking (set think = false)", ptok, gtok
        return text, "", ptok, gtok

    def _call_anthropic(self, prompt, cfg, key, p) -> tuple[str, str, int, int]:
        payload = {"model": self.model, "max_tokens": p.get("max_tokens", 512), "system": self._system_prompt,
                   "messages": [{"role": "user", "content": prompt}]}
        for k in ("temperature", "top_p"):
            if p.get(k) is not None:
                payload[k] = p[k]
        data = self._post(cfg["url"], json=payload,
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        text  = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type", "text") == "text")
        self._finish = data.get("stop_reason") or ""
        usage = data.get("usage", {})
        return text, "", usage.get("input_tokens", 0), usage.get("output_tokens", 0)

    def _call_gemini(self, prompt, cfg, key, p) -> tuple[str, str, int, int]:
        gen = {"maxOutputTokens": p.get("max_tokens", 512)}
        for k, gk in (("temperature", "temperature"), ("top_p", "topP")):
            if p.get(k) is not None:
                gen[gk] = p[k]
        data = self._post(cfg["url"].format(model=self.model) + f"?key={key}", json={
            "system_instruction": {"parts": [{"text": self._system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": gen})
        self._finish = ((data.get("candidates") or [{}])[0].get("finishReason") or "").lower()
        try:
            text  = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            return "", f"Gemini response parse error: {e} — {str(data)[:200]}", 0, 0
        usage = data.get("usageMetadata", {})
        return text, "", usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)

    def _call_openai(self, prompt, cfg, key, p) -> tuple[str, str, int, int]:
        url = cfg["url"].rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        payload = {"model": self.model, "messages": self._messages(prompt), "max_tokens": p.get("max_tokens", 512)}
        for k in ("temperature", "top_p", "seed"):
            if p.get(k) is not None:
                payload[k] = p[k]
        if p.get("think") is not None:      # düşünen modeller (ör. EVREN): false → doğrudan yanıt; standart dışı alan, yalnızca verilince
            payload["thinking"] = bool(p["think"])
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        data  = self._post(url, json=payload, headers=headers)
        choice = (data.get("choices") or [{}])[0]
        msg    = choice.get("message") or {}
        text   = msg.get("content") or ""
        self._finish = choice.get("finish_reason") or ""
        usage  = data.get("usage") or {}
        ptok, gtok = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        if not text.strip() and (msg.get("reasoning") or msg.get("reasoning_content")):
            return "", "Empty response: the model spent its output tokens on thinking (set think = false)", ptok, gtok
        return text, "", ptok, gtok

    # ── JSON parse ────────────────────────────────────────────────────────
    def _parse_response(self, raw: str) -> tuple[dict, bool, str]:
        if not raw:
            return self._empty_selectors(), False, "Empty response"

        text = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        text = re.sub(r"```\s*$", "", text).strip()

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return self._empty_selectors(), False, f"No JSON found: {raw[:100]}"

        try:
            data = json.loads(match.group())
            if self.rule_type == "css" and self.repair_css:
                selectors = {f: self._fix_selector(data.get(f), field=f) for f in self.fields}
            else:
                selectors = {f: (data.get(f).strip() if isinstance(data.get(f), str) else data.get(f)) for f in self.fields}
            return selectors, True, ""
        except json.JSONDecodeError as e:
            return self._empty_selectors(), False, f"JSON parse error: {e}"

    def _fix_selector(self, selector: str, field: str = None) -> str:
        """
        LLM çıktısındaki yaygın selector hatalarını düzelt.

        1. Eksik nokta: "div.wysiwyg wysiwyg--all-content p"
                      → "div.wysiwyg.wysiwyg--all-content p"
           Kural: ardışık iki token, ikincisi harf ile başlıyor ve bilinen HTML
                  tag'i değil → önceki token'a nokta ile birleştir

        2. body field için main/article#id varsa tercih et
           Kural: selector içinde main#... veya article#... geçiyorsa
                  sadece onu kullan
        """
        if not selector or not isinstance(selector, str):
            return selector

        selector = selector.strip()

        # Fix 0: virgüllü selector — her parçayı ayrı fix et (tırnak ve parantez içindeki virgüller hariç)
        parts = _split_top(selector, ',')
        if len(parts) > 1:
            parts = [self._fix_selector(p.strip(), field) for p in parts]
            return ', '.join(p for p in parts if p)

        # Fix 4: "token.tagname" → "token tagname"
        # Örnek: "div.c-detail__category.a" → "div.c-detail__category a"
        # İskelette bu adla bir class varsa (ör. "div.meta", "h1.title") class olarak kalır
        fixed_tokens = []
        for tok in _split_top(selector):
            dot_idx = tok.rfind('.')
            if dot_idx > 0 and not any(c in tok for c in "'\"(["):
                suffix = tok[dot_idx+1:]
                if suffix in HTML_TAGS_SET and suffix not in self._classes:
                    fixed_tokens.append(tok[:dot_idx])
                    fixed_tokens.append(suffix)
                    continue
            fixed_tokens.append(tok)
        selector = ' '.join(fixed_tokens)

        # Fix 1: eksik nokta
        tokens = _split_top(selector)
        fixed  = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            # Sonraki token var mı ve tag adı değil mi ve . veya # ile başlamıyor mu?
            if (i + 1 < len(tokens)
                    and not tokens[i+1][0] in '.#:>[+~'
                    and tokens[i+1].split('.')[0].split('#')[0].split('[')[0].split(':')[0] not in HTML_TAGS_SET
                    and tokens[i+1][0].isalpha()):
                # Birleştir — önceki token'a nokta ekle
                token = token + '.' + tokens[i+1]
                i += 2
            else:
                i += 1
            fixed.append(token)
        selector = ' '.join(fixed)

        # Fix 2: body field — main#id veya article#id varsa sadece onu al
        if field == 'body':
            parts = _split_top(selector)
            for part in parts:
                if re.match(r'^(main|article)#\S+', part):
                    return part

        # Fix 3: "div.X__Y leaf" → "leaf.X__Y" — BEM element class, tag yanlış tahmin
        # Örnek: "div.c-detail__date span" → "span.c-detail__date"
        # Sadece __ içeren (BEM element) class'larda uygula
        import re as _re3
        parts = _split_top(selector)
        if len(parts) == 2:
            head, leaf_tag = parts
            head_m = _re3.match("^(\\w+)\\.(.+)$", head)
            # Sadece inline/leaf tag'ler için uygula (span, time, em, strong)
            # p, a, div gibi block/structural tag'lerde uygulama
            SWAP_LEAF_TAGS = {"span", "time", "em", "strong", "small", "cite"}
            BEM_PREFIXES = {"c", "l", "u", "o", "t", "is", "has", "js"}
            cls = head_m.group(2) if head_m else ""
            cls_prefix = cls.split("-")[0].split("_")[0] if cls else ""
            if (head_m
                    and leaf_tag in SWAP_LEAF_TAGS
                    and head_m.group(1) != leaf_tag
                    and "__" in cls
                    and cls_prefix in BEM_PREFIXES):
                selector = leaf_tag + "." + cls

        # Fix Tailwind: text-[40px] → tag[class*="text-[40px]"]
        if '[' in selector:
            tokens = _split_top(selector)
            result = []
            for tok in tokens:
                if '[' in tok and not tok.startswith('['):
                    bracket_idx = tok.find('[')
                    dot_idx = tok.rfind('.', 0, bracket_idx)
                    if dot_idx > 0:
                        tag_cls = tok[:dot_idx]
                        tw_cls  = tok[dot_idx+1:]
                        tok = f'{tag_cls}[class*="{tw_cls}"]'
                result.append(tok)
            selector = ' '.join(result)

        return selector

    def _fix_body_from_skeleton(self, selector, skeleton_html):
        """
        Body selector zayıfsa (2+ token veya boş) skeleton'dan main#id / article#id bul.
        """
        if not selector:
            selector = ""
        import re as _re  # noqa
        if not skeleton_html:
            return selector

        # Sadece boş veya çok genel (class/id yok) selector'ı override et
        tokens = (selector or "").split()
        has_specific = any("." in t or "#" in t or "[" in t for t in tokens)
        is_weak = (not selector) or (not has_specific)
        if not is_weak:
            return selector

        m = _re.search(r'<(main|article)\s+id="([^"]+)"', skeleton_html)
        if m:
            return m.group(1) + "#" + m.group(2)

        if _re.search("<main[\\s>]", skeleton_html):
            return "main"
        if _re.search("<article[\\s>]", skeleton_html):
            return "article"

        return selector


    def _empty_selectors(self) -> dict:
        return {f: None for f in self.fields}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # doğrudan çalıştırma: src/
    from webrulebench.pipeline.html_cleaner import HTMLCleaner, CleanerConfig, STRATEGIES
    from webrulebench.pipeline.skeleton import Skeleton

    parser = argparse.ArgumentParser(description="LLM Extractor — K4")
    parser.add_argument("html_file", help="Raw HTML file")
    parser.add_argument("--backend",  default="ollama",
                        choices=list(BACKENDS))          # llm_models.json'daki backend'ler
    parser.add_argument("--model",    default=None)
    parser.add_argument("--strategy", default="whitelist", choices=STRATEGIES)
    parser.add_argument("--rule-type", default="css", choices=["css", "xpath", "regex"],
                        help="Rule language to generate")
    parser.add_argument("--entropy-threshold", type=float, default=4.2)
    parser.add_argument("--show-skeleton", action="store_true")
    args = parser.parse_args()

    html   = Path(args.html_file).read_text(encoding="utf-8", errors="ignore")
    domain = Path(args.html_file).parts[-2]

    cfg     = CleanerConfig(entropy_threshold=args.entropy_threshold)
    cleaner = HTMLCleaner(cfg)
    cleaned = cleaner.clean(html, strategy=args.strategy)

    sk   = Skeleton(strategy="enriched")             # deneylerle aynı iskelet biçimi
    skel = sk.extract(cleaned.cleaned_html)

    if args.show_skeleton:
        print("--- SKELETON ---")
        print(skel.skeleton_html[:2000])
        print("---")

    print("=" * 60)
    print("  LLM Extractor — K4")
    print(f"  Domain   : {domain}")
    print(f"  Backend  : {args.backend} / {args.model or '(default)'}")
    print(f"  Strateji : {args.strategy}")
    print(f"  Kural tipi: {args.rule_type}")
    print(f"  Skeleton : {skel.output_chars:,} chars / {skel.node_count} node")
    print("=" * 60)
    print("  Sending to the LLM...")

    extractor = LLMExtractor(backend=args.backend, model=args.model, rule_type=args.rule_type)
    result    = extractor.extract(skel.skeleton_html, domain=domain)
    result.strategy = args.strategy

    print(f"  Time     : {result.elapsed_ms:.0f} ms")
    print(f"  Success  : {'✅' if result.success else '❌'}")
    if result.error:
        print(f"  Hata     : {result.error}")
    print()
    print(f"  Kurallar ({args.rule_type}):")
    print("  " + "-" * 40)
    for field, selector in result.selectors.items():
        status = "✅" if selector else "❌"
        print(f"  {status} {field:<10} : {selector or 'not found'}")

    if not result.success:
        print(f"\n  Raw response:\n  {result.raw_response[:300]}")