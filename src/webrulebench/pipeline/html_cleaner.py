"""
html_cleaner.py
===============
Phase 3 — HTML Skeleton / Reduction for AdaptiveScraper

Girdi  : ham HTML string
Çıktı  : küçültülmüş HTML string + metrikler (süre, token azalma)

Ön-işleme (tüm stratejilere sabit uygulanır):
  - script, style, iframe, noscript kaldır
  - display:none / visibility:hidden kaldır
  - HTML yorumları kaldır

Stratejiler:
  1. raw_regex        — regex tabanlı, DOM parse yok         → html2text (Swartz, 2011) benzeri baseline
  2. whitelist        — sadece semantic tag'leri tut          → Readability (Arcavi, 2009) +
                                                                trafilatura (Barbaresi, 2021) benzeri
  3. dom_formula      — truncation score (derinliksiz)        → Boilerpipe (Kohlschütter et al., 2010) benzeri
                                                                CETR (Wang et al., AAAI 2012) ile örtüşüyor
  4. dom_depth_abs    — truncation score (mutlak derinlik)    → Dragnet (Peters & Lecocq, 2013) benzeri
  5. dom_depth_rel    — truncation score (normalize derinlik) → CETR (Wang et al., 2012) normalize varyantı
  6. entropy          — karakter entropisi tabanlı            → Özgün katkı; LLM pre-training veri
                                                                temizliğindeki perplexity filtering ile
                                                                kavramsal ilişki (Wenzek et al., 2020)
  7. hybrid           — whitelist (soft-strip) +              → Bu çalışmanın katkısı: iki stratejinin
                        enriched skeleton modu                   avantajlarını birleştiren melez yaklaşım.
                                                                soft-strip: bilinmeyen tag attrs silinir ama
                                                                  tag kaldırılmaz → container hiyerarşisi korunur
                                                                enriched modu: orijinal metin annotation (date ↑)

Truncation score formülü (stratejiler 3-5):
  score = α × text_ratio + β × log(text_length) + γ × (1/depth)
  score < θ1  → none     (dokunma)
  θ1–θ2       → sentence (ilk cümle)
  θ2–θ3       → fixed    (ilk N karakter)
  θ3+         → placeholder [CONTENT]

Kullanım:
  from webrulebench.pipeline.html_cleaner import HTMLCleaner, CleanerConfig
  config  = CleanerConfig()
  cleaner = HTMLCleaner(config)
  result  = cleaner.clean(html, strategy="dom_formula")
  print(result.cleaned_html)
  print(result.metrics())
"""

import re
import math
import time
import logging
from dataclasses import dataclass, field
from typing import Literal

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TYPES
# ---------------------------------------------------------------------------
Strategy = Literal[
    "raw_regex",
    "whitelist",
    "dom_formula",
    "dom_depth_abs",
    "dom_depth_rel",
    "entropy",
    "hybrid",
]

STRATEGIES: list[Strategy] = [
    "raw_regex",
    "whitelist",
    "dom_formula",
    "dom_depth_abs",
    "dom_depth_rel",
    "entropy",
    "hybrid",
]


# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
@dataclass
class CleanerConfig:
    """
    Tüm parametreler tek yerde.
    Farklı config nesneleri ile farklı deneyler çalıştırılabilir.
    """

    # ── Truncation score ağırlıkları (stratejiler 3-5) ────────────────────
    alpha: float = 0.5    # text_ratio ağırlığı
    beta:  float = 0.3    # log(text_length) ağırlığı
    gamma: float = 0.2    # depth bileşeni ağırlığı

    # ── Truncation eşikleri ───────────────────────────────────────────────
    theta1: float = 0.3   # altında → none
    theta2: float = 0.5   # altında → sentence
    theta3: float = 0.7   # altında → fixed(N), üstünde → placeholder

    # ── Sabit truncation uzunluğu ─────────────────────────────────────────
    fixed_n: int = 80

    # ── Entropy eşiği (strateji 6) ────────────────────────────────────────
    entropy_threshold: float = 3.5   # altında → düşük bilgi → kes

    # ── Whitelist (strateji 2) ────────────────────────────────────────────
    keep_tags: list = field(default_factory=lambda: [
        "article", "main", "section", "header",
        "h1", "h2", "h3", "h4",
        "p", "a", "time", "figure", "figcaption",
        "ul", "ol", "li",
        "blockquote", "cite",
        "span", "div",
        "address", "img",
    ])

    # ── Ön-işleme ─────────────────────────────────────────────────────────
    remove_scripts:  bool = True
    remove_hidden:   bool = True
    remove_comments: bool = True


# ---------------------------------------------------------------------------
# RESULT
# ---------------------------------------------------------------------------
@dataclass
class CleanResult:
    strategy:       str
    cleaned_html:   str
    original_chars: int
    cleaned_chars:  int
    elapsed_ms:     float

    @property
    def reduction_pct(self) -> float:
        if self.original_chars == 0:
            return 0.0
        return round((1 - self.cleaned_chars / self.original_chars) * 100, 2)

    def metrics(self) -> dict:
        return {
            "strategy":       self.strategy,
            "original_chars": self.original_chars,
            "cleaned_chars":  self.cleaned_chars,
            "reduction_pct":  self.reduction_pct,
            "elapsed_ms":     round(self.elapsed_ms, 2),
        }


# ---------------------------------------------------------------------------
# CLEANER
# ---------------------------------------------------------------------------
class HTMLCleaner:

    def __init__(self, config: CleanerConfig = None):
        self.cfg = config or CleanerConfig()

    # ── Public API ────────────────────────────────────────────────────────
    def clean(self, html: str, strategy: Strategy = "dom_formula") -> CleanResult:
        """Belirtilen strateji ile HTML temizle. CleanResult döndür."""
        if strategy not in STRATEGIES:
            raise ValueError(f"Bilinmeyen strateji: {strategy}. Seçenekler: {STRATEGIES}")

        original_chars = len(html)
        t0 = time.perf_counter()

        if strategy == "raw_regex":
            cleaned = self._strategy_raw_regex(html)
        else:
            soup = BeautifulSoup(html, "html.parser")
            self._preprocess(soup)

            if strategy == "whitelist":
                cleaned = self._strategy_whitelist(soup)
            elif strategy == "dom_formula":
                cleaned = self._strategy_dom_formula(soup, use_depth=False)
            elif strategy == "dom_depth_abs":
                cleaned = self._strategy_dom_formula(soup, use_depth=True, relative=False)
            elif strategy == "dom_depth_rel":
                cleaned = self._strategy_dom_formula(soup, use_depth=True, relative=True)
            elif strategy == "entropy":
                cleaned = self._strategy_entropy(soup)
            elif strategy == "hybrid":
                cleaned = self._strategy_hybrid(soup)
            else:
                cleaned = str(soup)

        elapsed_ms = (time.perf_counter() - t0) * 1000

        return CleanResult(
            strategy       = strategy,
            cleaned_html   = cleaned,
            original_chars = original_chars,
            cleaned_chars  = len(cleaned),
            elapsed_ms     = elapsed_ms,
        )

    def clean_all(self, html: str) -> dict:
        """Tüm stratejileri çalıştır. Benchmark için kullanılır."""
        return {s: self.clean(html, strategy=s) for s in STRATEGIES}

    # ── Ön-işleme (tüm DOM stratejileri için sabit) ───────────────────────
    def _preprocess(self, soup: BeautifulSoup):
        """
        Gürültü elemanları kaldır.
        Tüm stratejilere eşit uygulanır — strateji karşılaştırması adil olsun.
        """
        if self.cfg.remove_scripts:
            for tag in soup.find_all(["script", "style", "iframe", "noscript"]):
                tag.decompose()

        if self.cfg.remove_comments:
            from bs4 import Comment
            for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
                comment.extract()

        if self.cfg.remove_hidden:
            for tag in soup.find_all(True):
                try:
                    style = tag.get("style", "")
                    if ("display:none" in style.replace(" ", "") or
                            "visibility:hidden" in style.replace(" ", "")):
                        tag.decompose()
                except Exception:
                    pass

    # ══════════════════════════════════════════════════════════════════════
    # STRATEJİ 1 — Raw Regex
    # Literatür: html2text (Aaron Swartz, 2011) benzeri naive baseline.
    #            Boilerpipe ile KARIŞTIRILMAMALI — Boilerpipe metin
    #            yoğunluğu + ML kullanır; bu strateji saf regex'tir.
    # Farkımız : Haber domain'ine özel nav/footer/aside pattern listesi
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_raw_regex(self, html: str) -> str:
        """
        Saf regex temizleme — DOM parse yok.
        En hızlı strateji, baseline görevi görür.
        """
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>",   "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<iframe[^>]*>.*?</iframe>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->",                "", html, flags=re.DOTALL)
        for tag in ["nav", "aside", "form", "noscript"]:
            html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html,
                          flags=re.DOTALL | re.IGNORECASE)
        # footer: raw_regex'te hepsini sil (DOM bağlamı yok), diğer stratejiler DOM'da kontrol eder
        html = re.sub(r"<header[^>]*>.*?</header>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'\s+on\w+="[^"]*"',   "", html)
        html = re.sub(r'\s+data-[^=]+="[^"]*"', "", html)
        html = re.sub(r"\s{2,}", " ", html)
        return html.strip()

    # ══════════════════════════════════════════════════════════════════════
    # STRATEJİ 2 — Tag Whitelist
    # Literatür: Readability (Arcavi, 2009; Mozilla Reader Mode olarak
    #            Firefox'a entegre edildi) ve trafilatura (Barbaresi, 2021).
    #            trafilatura daha modern, çok dilli ve aktif olarak
    #            sürdürülüyor; karşılaştırma için önerilen referans.
    # Farkımız : Tag listesi LLM selector üretimi için optimize edildi;
    #            skor tabanlı içerik seçimi yerine deterministik whitelist.
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_whitelist(self, soup: BeautifulSoup) -> str:
        """
        Sadece bilinen semantic tag'leri tut.
        Hibrit: bilinen tag'ler kuralla, bilinmeyenler kaldırılır.
        """
        keep      = set(self.cfg.keep_tags)
        # Yapısal gürültü → decompose (içerik hiç beklenmez)
        hard_remove = {"nav", "form", "menu"}
        # Form kontrolleri → unwrap (BS4 mis-parse durumunda child içerik kaybolmasın)
        soft_remove = {"button", "input", "select", "textarea"}

        # header/footer/aside: article/main içindeyse koru, dışındaysa sil
        for tag in soup.find_all(["header", "footer", "aside"]):
            if not tag.find_parent(["article", "main"]):
                tag.decompose()

        for tag in soup.find_all(True):
            if not tag.parent:   # zaten kaldırılmış
                continue
            if tag.name in hard_remove:
                tag.decompose()
            elif tag.name in soft_remove:
                try:
                    tag.unwrap()
                except Exception:
                    pass
            elif tag.name not in keep:
                try:
                    tag.unwrap()
                except Exception:
                    pass

        return str(soup)

    # ══════════════════════════════════════════════════════════════════════
    # STRATEJİ 7 — Hybrid
    # Whitelist cleaner: blacklisted → decompose, bilinmeyen → attrs temizle
    # (unwrap() yok → image/tag container hiyerarşisi korunur).
    # Skeleton aşamasında enriched modu uygulanır (metin annotation'ı).
    # Böylece yapısal bütünlük (dom_depth_rel avantajı) + orijinal metin
    # sinyalleri (enriched avantajı) aynı anda elde edilir.
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_hybrid(self, soup: BeautifulSoup) -> str:
        keep        = set(self.cfg.keep_tags)
        hard_remove = {"nav", "form", "menu"}
        soft_remove = {"button", "input", "select", "textarea"}

        for tag in soup.find_all(["header", "footer", "aside"]):
            if not tag.find_parent(["article", "main"]):
                tag.decompose()

        for tag in soup.find_all(True):
            if not tag.parent:
                continue
            if tag.name in hard_remove:
                tag.decompose()
            elif tag.name in soft_remove:
                try:
                    tag.unwrap()
                except Exception:
                    pass
            elif tag.name not in keep:
                # unwrap() yerine sadece attribute'ları sıfırla:
                # tag yapısı (ve dolayısıyla container hiyerarşisi) bozulmaz,
                # metin dokunulmadan kalır → enriched skeleton modu ham metni görebilir
                tag.attrs = {}

        return str(soup)

    # ══════════════════════════════════════════════════════════════════════
    # STRATEJİ 3-5 — DOM Formula (üç varyant)
    #
    # dom_formula (derinliksiz):
    #   Literatür: Boilerpipe (Kohlschütter et al., ACM CIKM 2010).
    #              Metin yoğunluğu (text/markup oranı) Boilerpipe'ın çekirdeği.
    #              CETR (Wang et al., AAAI 2012) tag oranlarını benzer şekilde
    #              kullanır. Justext (Pomikálek, 2011) paragraf sınıflandırması
    #              yapar — stop-word bağımlılığı nedeniyle daha az uygun referans.
    #
    # dom_depth_abs (mutlak derinlik):
    #   Literatür: Dragnet (Peters & Lecocq, WWW 2013). DOM yapısı +
    #              içerik modeli + CRF; derinlik özelliğini açıkça kullanır.
    #              SimpDOM (Zhou et al., 2021) ile KARIŞTIRILMAMALI —
    #              SimpDOM graph neural network tabanlı DOM sadeleştirmedir.
    #
    # dom_depth_rel (normalize derinlik):
    #   Literatür: CETR (Wang et al., 2012) normalize tag ratio varyantı.
    #              Web2Text (Vogels et al., EMNLP 2018) ile KARIŞTIRILMAMALI —
    #              Web2Text derin öğrenme tabanlı sekans modelidir.
    #
    # Ortak farkımız: Multi-parametrik α β γ θ ile LLM token
    #                 optimizasyonuna odaklı truncation kararı.
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_dom_formula(self, soup: BeautifulSoup,
                               use_depth: bool = False,
                               relative: bool = False) -> str:
        """
        Truncation score formülü:
          score = α×text_ratio + β×log(text_length) + γ×depth_component

        Eşikler:
          score < θ1  → none     (dokunma)
          θ1–θ2       → sentence
          θ2–θ3       → fixed(N)
          θ3+         → [CONTENT]
        """
        cfg       = self.cfg
        max_depth = self._max_depth(soup) if (use_depth and relative) else 1

        # Normalize için max text uzunluğunu önceden hesapla
        all_texts = [len(t.get_text(strip=True)) for t in soup.find_all(True) if t.parent]
        max_tlen  = max(all_texts) if all_texts else 1
        log_max   = math.log(max_tlen + 1)

        for tag in soup.find_all(True):
            if not tag.parent:
                continue

            # Sadece text içeren node'lara uygula
            # (child tag'i olan container'lara dokunma — parent-child çakışması önlenir)
            direct_text = "".join(
                str(c) for c in tag.children
                if isinstance(c, __import__('bs4').NavigableString)
            ).strip()
            if not direct_text:
                continue

            text = tag.get_text(separator=" ", strip=True)
            if not text:
                continue

            text_length = len(text)
            tag_length  = len(str(tag))
            if tag_length == 0:
                continue

            text_ratio = text_length / tag_length
            log_length = math.log(text_length + 1) / log_max  # normalize 0-1

            if use_depth:
                depth = self._get_depth(tag)
                depth_component = (depth / max_depth) if (relative and max_depth > 0) else depth
                depth_val = 1 / (depth_component + 1)
            else:
                depth_val = 0.0

            score = (cfg.alpha * text_ratio +
                     cfg.beta  * log_length +
                     cfg.gamma * depth_val)

            if score < cfg.theta1:
                pass  # none — dokunma
            elif score < cfg.theta2:
                self._truncate_tag(tag, self._first_sentence(text))
            elif score < cfg.theta3:
                self._truncate_tag(tag, text[:cfg.fixed_n] + "…")
            else:
                self._truncate_tag(tag, "[CONTENT]")

        return str(soup)

    # ══════════════════════════════════════════════════════════════════════
    # STRATEJİ 6 — Entropy
    # Literatür: Doğrudan karşılığı yok — özgün katkı.
    #            Kavramsal ilişki: Shannon (1948) karakter entropisi.
    #            LLM pre-training veri temizliğinde kullanılan perplexity
    #            filtering ile ruh yakın: Wenzek et al., "CCNet: Extracting
    #            High Quality Monolingual Datasets from Web Crawl Data",
    #            LREC 2020. Fark: biz karakter-düzeyi entropi kullanırken
    #            CCNet kelime-düzeyi perplexity kullanır.
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_entropy(self, soup: BeautifulSoup) -> str:
        """
        Karakter entropisi tabanlı truncation.
        Düşük entropi → tekrarlayan/navigasyon metni → kes.
        Yüksek entropi → zengin içerik → koru.

        entropy = -Σ p(c) × log2(p(c))
        """
        for tag in soup.find_all(True):
            if not tag.parent:
                continue
            text = tag.get_text(separator=" ", strip=True)
            if not text or len(text) < 20:
                continue
            if self._char_entropy(text) < self.cfg.entropy_threshold:
                self._truncate_tag(tag, "[CONTENT]")

        return str(soup)

    # ── Yardımcılar ───────────────────────────────────────────────────────
    def _get_depth(self, tag: Tag) -> int:
        depth, parent = 0, tag.parent
        while parent:
            depth += 1
            parent = parent.parent
        return depth

    def _max_depth(self, soup: BeautifulSoup) -> int:
        depths = [self._get_depth(t) for t in soup.find_all(True)]
        return max(depths) if depths else 1

    def _truncate_tag(self, tag: Tag, replacement: str):
        try:
            for child in list(tag.children):
                child.extract()
            tag.append(replacement)
        except Exception:
            pass

    def _first_sentence(self, text: str) -> str:
        match = re.search(r"[.!?]", text)
        return text[:match.start() + 1] if match else text[:80] + "…"

    def _char_entropy(self, text: str) -> float:
        if not text:
            return 0.0
        freq  = {}
        for c in text:
            freq[c] = freq.get(c, 0) + 1
        total = len(text)
        return -sum((f / total) * math.log2(f / total) for f in freq.values())


# ---------------------------------------------------------------------------
# CLI — tek HTML dosyası üzerinde tüm stratejileri çalıştır
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse, pathlib

    parser = argparse.ArgumentParser(description="HTML Cleaner — strateji karşılaştırması")
    parser.add_argument("html_file", help="Temizlenecek HTML dosyası")
    parser.add_argument("--strategy", default="all",
                        help=f"Strateji: all veya {STRATEGIES}")
    parser.add_argument("--alpha",  type=float, default=0.5)
    parser.add_argument("--beta",   type=float, default=0.3)
    parser.add_argument("--gamma",  type=float, default=0.2)
    parser.add_argument("--theta1", type=float, default=0.3)
    parser.add_argument("--theta2", type=float, default=0.5)
    parser.add_argument("--theta3", type=float, default=0.7)
    parser.add_argument("--entropy-threshold", type=float, default=3.5)
    args = parser.parse_args()

    html = pathlib.Path(args.html_file).read_text(encoding="utf-8")
    cfg  = CleanerConfig(
        alpha=args.alpha, beta=args.beta, gamma=args.gamma,
        theta1=args.theta1, theta2=args.theta2, theta3=args.theta3,
        entropy_threshold=args.entropy_threshold,
    )
    cleaner = HTMLCleaner(cfg)

    print("=" * 60)
    print("  HTML Cleaner — Strateji Karşılaştırması")
    print(f"  Orijinal boyut: {len(html):,} karakter")
    print("=" * 60)

    def fmt_dur(ms: float) -> str:
        if ms < 1:      return f"{ms * 1000:.0f}µs"
        elif ms < 1000: return f"{ms:.1f}ms"
        else:           return f"{ms / 1000:.2f}s"

    strategies = STRATEGIES if args.strategy == "all" else [args.strategy]
    results = []
    for s in strategies:
        r = cleaner.clean(html, strategy=s)
        results.append(r.metrics())
        print(f"  {s:<20} {r.cleaned_chars:>8,} chars  "
              f"{r.reduction_pct:>6.1f}%  {fmt_dur(r.elapsed_ms)}")

    print("=" * 60)