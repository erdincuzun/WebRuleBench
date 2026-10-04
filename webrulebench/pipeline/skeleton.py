"""
skeleton.py
===========
Phase 3 — K3: HTML Skeleton Extractor

Temizlenmiş HTML'den sadece yapısal ağaç çıkarır.
Metin, src, href, style, event handler — hiçbiri kalmaz.
Sadece tag + class + id + belirli data-* attribute'lar kalır.

Class temizleme:
  ssrcss-8ytrv8-TextContainer  →  TextContainer   (tire ile böl, hash'leri sil)
  eys6wfo1                     →  (silinir)
  text-[40px]                  →  text-[40px]     (CSS değeri, korunur)
  kbqDDU                       →  kbqDDU          (büyük harf var, korunur)

Token anlamlılık kuralı (B yöntemi):
  - Büyük harf içeriyorsa       → kalsın
  - Rakam içeriyorsa            → kalsın  (2xl, 8ytrv8, 40px)
  - CSS birimi içeriyorsa       → kalsın  (%, rem, vw, vh...)
  - Sadece küçük harf, ≥5 char  → kalsın  (article, container)
  - Diğerleri                   → sil

Girdi  : temizlenmiş HTML string (html_cleaner çıktısı)
Çıktı  : skeleton HTML string + metrikler

Kullanım:
  from webrulebench.pipeline.skeleton import Skeleton
  sk     = Skeleton()
  result = sk.extract(cleaned_html)
  print(result.skeleton_html)

CLI:
  python -m webrulebench.pipeline.skeleton dataset/raw/hurriyet.com.tr/article_001.html
  python -m webrulebench.pipeline.skeleton dataset/raw/hurriyet.com.tr/article_001.html --strategy whitelist
"""

import re
import time
import argparse
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Tag, NavigableString

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

REMOVE_TAGS = {
    "script", "style", "iframe", "noscript",
    "nav",
    "form", "button", "input", "select", "textarea",
    "svg", "canvas", "video", "audio",
}

REMOVE_CLASS_PATTERNS = {
    "adv", "adRenderer", "medyanet", "dfp", "adservice",
    "advertisement", "banner", "sponsor", "promo",
    "cookie", "popup", "modal", "overlay", "gdpr",
    "social-share", "share-bar", "newsletter",
    "related-articles", "recommended",
}

# Temel attribute'lar her zaman korunur
KEEP_ATTRS = {"class", "id"}

# data-* attribute'lardan anlamlı olanlar korunur
KEEP_DATA_ATTRS = {
    "data-testid", "data-trackable", "data-type",
    "data-component", "data-widget", "data-id",
    "data-module", "data-section", "data-block",
    "data-article",
}

# Semantic tag'ler boş olsa bile silinmez
KEEP_STRUCTURAL = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "main", "article", "section", "header",
    "p", "time", "figure", "figcaption",
    "address",
}

MAX_DEPTH    = 16
MAX_SIBLINGS = 2

# CSS birimleri — sayı+birim pattern'i için (40px, 2rem, 100vh)
CSS_UNITS = {"px", "rem", "em", "vh", "vw", "%", "pt", "ch", "ex", "fr", "deg"}

# BEM modifier (--) içeren saf utility/style class'ların base kelimeleri
# Bu prefix'e sahip token'lar (ör: box--margin-none, flex--justify-center) silinir
UTILITY_BEM_BASES = {
    # Layout / spacing
    "flex", "box", "width", "height", "col", "row", "gap",
    # Typography
    "font", "text",
    # Decorative
    "bg", "color", "opacity", "shadow", "border", "rounded",
    # Motion
    "transition", "transform",
    # Position / display
    "display", "position", "overflow", "cursor", "align", "justify",
    # Generic layout tokens (e.g. layout--bg, layout--sidebar)
    "layout",
}

# Kısa ama anlamlı CSS kelimeleri — eşik altında olsa bile korunur
SEMANTIC_SHORT = {
    "text", "body", "main", "col", "row", "nav", "tag",
    "date", "img", "btn", "top", "sub", "box", "bar",
    "tab", "bio", "map", "by", "list", "all", "for",
    "new", "set", "get", "use", "add", "app", "end",
    "rich", "open", "left", "read", "dark", "hide",
    "show", "next", "prev", "last", "item", "card",
    "hero", "page", "link", "wrap", "ads", "cta",
    "src", "alt", "rel", "ref", "wp",
    "name", "post", "type", "form", "data", "grid", "card",
    "side", "full", "meta", "info", "user", "logo", "icon",
    "feed", "more", "back", "site", "head", "foot", "menu",
    # News-specific semantic classes
    "tags", "cats", "meta", "byline", "author",
    # CSS directional abbreviations (border-b, border-t, gap-x, gap-y, etc.)
    "b", "t", "x", "y",
}


# ---------------------------------------------------------------------------
# RESULT
# ---------------------------------------------------------------------------
@dataclass
class SkeletonResult:
    skeleton_html:   str
    input_chars:     int
    output_chars:    int
    elapsed_ms:      float
    node_count:      int
    pruned_siblings: int
    pruned_depth:    int

    @property
    def reduction_pct(self) -> float:
        if self.input_chars == 0:
            return 0.0
        return round((1 - self.output_chars / self.input_chars) * 100, 2)

    def metrics(self) -> dict:
        return {
            "input_chars":     self.input_chars,
            "output_chars":    self.output_chars,
            "reduction_pct":   self.reduction_pct,
            "elapsed_ms":      round(self.elapsed_ms, 2),
            "node_count":      self.node_count,
            "pruned_siblings": self.pruned_siblings,
            "pruned_depth":    self.pruned_depth,
        }


# ---------------------------------------------------------------------------
# SKELETON
# ---------------------------------------------------------------------------
class Skeleton:

    def __init__(self,
                 max_depth: int = MAX_DEPTH,
                 max_siblings: int = MAX_SIBLINGS,
                 strategy: str = "whitelist"):
        self.max_depth    = max_depth
        self.max_siblings = max_siblings
        self.strategy     = strategy

    def extract(self, html: str) -> SkeletonResult:
        input_chars = len(html)
        t0 = time.perf_counter()

        soup = BeautifulSoup(html, "html.parser")

        # 1. Gürültü tag'lerini kaldır
        self._remove_noise(soup)

        # 2. Tüm attribute'ları temizle (class, id, data-* hariç)
        self._clean_attrs(soup)

        # 3. Class token'larını temizle (hash'leri sil)
        self._clean_classes(soup)

        # 4. Tüm metinleri sil (text_included / enriched / hybrid stratejisinde silme)
        if self.strategy not in ("text_included", "enriched", "hybrid"):
            self._remove_text(soup)

        # 5. Derinlik sınırı uygula
        pruned_depth = self._prune_depth(soup, depth=0)

        # 6. Tekrar eden kardeşleri kırp
        pruned_siblings = self._prune_siblings(soup)

        # 7. Boş tag'leri temizle
        self._remove_empty(soup)

        # 8. Güzel formatla
        skeleton = self._format(soup)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        node_count = len(soup.find_all(True))

        return SkeletonResult(
            skeleton_html   = skeleton,
            input_chars     = input_chars,
            output_chars    = len(skeleton),
            elapsed_ms      = elapsed_ms,
            node_count      = node_count,
            pruned_siblings = pruned_siblings,
            pruned_depth    = pruned_depth,
        )

    # ── Adım 1: Gürültü kaldır ────────────────────────────────────────────
    def _remove_noise(self, soup: BeautifulSoup):
        for tag in soup.find_all(REMOVE_TAGS):
            tag.decompose()
        for tag in soup.find_all(True):
            if not tag.parent:
                continue
            classes  = " ".join(tag.get("class", []) if isinstance(tag.get("class"), list) else [tag.get("class", "")])
            tag_id   = tag.get("id", "")
            combined = (classes + " " + tag_id).lower()
            if any(p in combined for p in REMOVE_CLASS_PATTERNS):
                # İçinde önemli metin varsa (>500 char) içerik kapsayıcısı olabilir, silme
                if len(tag.get_text(strip=True)) > 500:
                    continue
                tag.decompose()
        # header/footer/aside: article/main içindeyse koru, dışındaysa sil
        for tag in soup.find_all(["header", "footer", "aside"]):
            if not tag.find_parent(["article", "main"]):
                tag.decompose()

        # p içermeyen article → teaser/card, sil (tam haber metninde p zorunlu)
        for tag in soup.find_all("article"):
            if not tag.find("p"):
                tag.decompose()

        # CSS position:fixed/sticky → UI chrome (nav, modal, banner), sil
        # Tailwind "fixed" veya "sticky" class token'u === CSS position değeri
        # CSS display:none → Tailwind "hidden" class token'u === gizli eleman, sil
        for tag in list(soup.find_all(True)):
            if not tag.parent:
                continue
            cls_list = tag.get("class", [])
            if isinstance(cls_list, str):
                cls_list = cls_list.split()
            if "fixed" in cls_list or "sticky" in cls_list or "hidden" in cls_list:
                tag.decompose()

        for tag in soup.find_all(True):
            try:
                style = tag.get("style", "")
                if ("display:none" in style.replace(" ", "") or
                        "visibility:hidden" in style.replace(" ", "")):
                    tag.decompose()
            except Exception:
                pass

        # --- Navigasyon listesi tespiti ---
        # ul > li > a pattern'i 5+ tekrar eden ul'ler → menü, sil
        # Ama article/main içindeki tag listelerini koru
        for ul in list(soup.find_all("ul")):
            if not ul.parent:
                continue
            if ul.find_parent(["article"]):
                continue
            li_items = ul.find_all("li", recursive=False)
            if len(li_items) >= 5:
                link_items = sum(1 for li in li_items if li.find("a", recursive=False))
                if link_items / len(li_items) >= 0.8:
                    ul.decompose()

        # --- Article-focus pruning ---
        # Eğer tek bir article tag'i varsa, article'ın derinliğindeki
        # kardeş container'ları (sidebar, related news) tespit edip sil
        self._prune_non_article_siblings(soup)

    def _prune_non_article_siblings(self, soup: BeautifulSoup):
        """
        Tek bir birincil article varsa, onun üst kapsayıcılarındaki
        ağır kardeş container'ları (sidebar, haber listeleri) sil.
        """
        articles = soup.find_all("article")
        # Birden fazla article varsa (haber listesi sayfası olabilir), dokunma
        if len(articles) != 1:
            return
        article = articles[0]

        # article'ın parent zincirini bul
        parent = article.parent
        if not parent:
            return

        for sibling in list(parent.children):
            if not isinstance(sibling, Tag):
                continue
            if sibling is article:
                continue
            # Kardeş container analizi
            sib_nodes = len(sibling.find_all(True))
            # Küçük kardeşler sorun değil
            if sib_nodes < 20:
                continue
            # Ağır kardeşlerde link/heading yoğunluğuna bak
            sib_links    = len(sibling.find_all("a"))
            sib_headings = len(sibling.find_all(["h3", "h4", "h5"]))
            # Link veya heading yoğunluğu yüksekse sidebar/haber listesi
            if sib_links > 10 or sib_headings > 5:
                sibling.decompose()
                continue
            # Node sayısı article'dan çok fazlaysa gürültü
            art_nodes = len(article.find_all(True))
            if sib_nodes > art_nodes * 2:
                sibling.decompose()

    # ── Adım 2: Attribute temizle ─────────────────────────────────────────
    def _clean_attrs(self, soup: BeautifulSoup):
        """class, id ve seçili data-* attribute'ları koru, diğerlerini sil."""
        for tag in soup.find_all(True):
            attrs_to_keep = {}
            for attr in KEEP_ATTRS:
                val = tag.get(attr)
                if val:
                    if isinstance(val, list):
                        val = " ".join(val)
                    # Sayısal/hash ID'leri atla (sayfa-spesifik generated ID'ler)
                    # Örn: bdf-1363274035, div-gpt-ad-..., wp-block-12345
                    if attr == "id" and re.search(r'\d{5,}', val):
                        continue
                    attrs_to_keep[attr] = val
            # Seçili data-* attribute'ları koru
            for attr in KEEP_DATA_ATTRS:
                val = tag.get(attr)
                if val:
                    attrs_to_keep[attr] = val
            # Enriched / hybrid: img tag'leri için boyut bilgisi koru
            if tag.name == "img" and self.strategy in ("enriched", "hybrid"):
                w = tag.get("width")
                h = tag.get("height")
                # width/height doğrudan attribute'da varsa koru
                if w:
                    attrs_to_keep["width"] = str(w)
                if h:
                    attrs_to_keep["height"] = str(h)
                # src URL'den boyut parse et (1170x700 gibi)
                if not w and not h:
                    src_url = tag.get("src", "")
                    m = re.search(r'(\d{3,4})[xX](\d{3,4})(?:[/_.]|$)', src_url)
                    if m:
                        attrs_to_keep["width"]  = m.group(1)
                        attrs_to_keep["height"] = m.group(2)
            tag.attrs = attrs_to_keep

    # ── Adım 3: Class token temizleme ────────────────────────────────────
    def _clean_classes(self, soup: BeautifulSoup):
        """
        Her tag'in class'ındaki hash benzeri token'ları sil.

        Token anlamlılık kuralı (B yöntemi):
          - Büyük harf içeriyorsa       → kalsın  (TextContainer)
          - Rakam içeriyorsa            → kalsın  (2xl, text-[40px])
          - CSS birimi içeriyorsa       → kalsın  (%, rem, vw)
          - Sadece küçük harf, ≥5 char  → kalsın  (article, wrapper)
          - Diğerleri                   → sil     (ssrcss, eys6wfo1)

        Tire önce boşluğa çevrilir ki token'lara ayrılabilsin.
        Sonra anlamsız token'lar düşürülür.
        """
        for tag in soup.find_all(True):
            raw_class = tag.get("class")
            if not raw_class:
                continue
            if isinstance(raw_class, list):
                raw_class = " ".join(raw_class)

            # Boşlukla ayrılmış class token'larını işle
            tokens = raw_class.split()
            kept = []
            for token in tokens:
                result = self._clean_class_token(token)
                if result is not None:
                    kept.append(result)

            if kept:
                tag["class"] = " ".join(kept)
            else:
                del tag["class"]

    def _is_meaningful_segment(self, seg: str) -> bool:
        """Tire ile bölünmüş tek segment anlamlı mı?"""
        import re
        if not seg: return False
        # CSS Modules / CSS-in-JS hash tespiti — 4 kural:
        VOWELS = set('aeiouAEIOU')
        alpha_chars = [c for c in seg if c.isalpha()]

        # Kural 1: alt çizgi ile başlıyor (CSS Modules _abc123 pattern)
        if seg.startswith('_'):
            return False

        # SEMANTIC_SHORT listesinde ise hash kurallarından önce kabul et
        if seg in SEMANTIC_SHORT:
            return True

        if seg.isalnum() and len(seg) <= 7:
            # Kural 2: kısa + rakam içeriyor → hash (Hy4HP, P4L6N, z5wPE)
            if any(c.isdigit() for c in seg):
                return False
            # Kural 3: ≥2 baş-dışı büyük harf → hash (WAXFI, ALMCC, xQoVi)
            non_initial_upper = sum(1 for i, c in enumerate(seg) if c.isupper() and i > 0)
            if non_initial_upper >= 2:
                return False
            # Kural 4: kısa + ünlü yoğunluğu < %25 → hash (wsquJ, Wskuj, cgtzj)
            if (len(seg) <= 6 and alpha_chars
                    and sum(1 for c in alpha_chars if c in VOWELS) / len(alpha_chars) < 0.25):
                return False

        if any(c.isupper() for c in seg): return True
        clean = seg.strip("[]")
        pattern = r'^\d+(\.\d+)?(' + '|'.join(CSS_UNITS) + r')$'
        if re.match(pattern, clean): return True
        has_digit = any(c.isdigit() for c in seg)
        has_alpha = any(c.isalpha() for c in seg)
        # snake_case (alt çizgi + rakam içerse bile) → semantic BEM/naming, hash değil
        # Örn: n3_meta_posted, article_body_text, post_details_block
        if '_' in seg and len(seg) >= 5: return True
        if has_digit and has_alpha: return False
        if seg.isdigit(): return False
        if seg in SEMANTIC_SHORT: return True
        if seg.isalpha() and len(seg) >= 5: return True
        # alt çizgi içeren BEM element token'ları (article__title, c__body vb.)
        if re.match(r'^[a-zA-Z_]+$', seg) and len(seg) >= 5: return True
        return False

    def _clean_class_token(self, token: str):
        """
        BEM notasyonunu koruyarak class token'ı temizle.
          -- içeriyorsa → utility base ise sil, değilse dokunma
          Hash segment yoksa → dokunma
          Hash var, anlamlı kısım var → "*TextContainer*"
          Tümü hash → None (sil)
        """
        import re
        # CSS Modules: ComponentName__hash → ComponentName
        # Örn: Paragraph_wrapper__6w7GG → Paragraph_wrapper
        # Sadece hash_part tamamen alphanumeric ise uygula (BEM __element ile karışmasın)
        # BEM: elementor-post-info__item--type-date → hash_part='item--type-date' (alnum değil, dokunma)
        # CSS Modules: Paragraph_wrapper__6w7GG → hash_part='6w7GG' (alnum, strip et)
        if '__' in token:
            base, hash_part = token.rsplit('__', 1)
            if base and hash_part.isalnum() and not self._is_meaningful_segment(hash_part):
                token = base

        # BEM modifier (--) içeriyorsa: utility layout/style class mı?
        if '--' in token:
            base = token.split('--')[0]  # grid__col, flex, box, font, ...
            # BEM element ayracı (__) varsa en son parçayı al
            base_word = base.rsplit('__', 1)[-1].rsplit('-', 1)[-1]
            if base_word in UTILITY_BEM_BASES or base in UTILITY_BEM_BASES:
                return None  # saf utility/style class — sil
            return token

        # Bootstrap/Tailwind utility class pattern: w-100, h-50, col-6, p-3, m-2
        # Kısa harf prefix + sayı suffix → olduğu gibi koru
        if re.match(r'^[a-z]{1,3}-\d{1,4}$', token):
            return token

        segments = token.split('-')

        # Bilinen BEM namespace prefix'leri → dokunma
        BEM_PREFIXES = {"c", "l", "u", "o", "t", "is", "has", "js", "qa"}
        if len(segments) >= 2 and segments[0] in BEM_PREFIXES:
            return token
        has_hash = any(not self._is_meaningful_segment(s) for s in segments)
        if not has_hash:
            return token

        meaningful = [s for s in segments if self._is_meaningful_segment(s)]
        if not meaningful:
            return None

        # Kısa yönsel/niteleyici suffix koru: border-b, border-t, border-x vb.
        # Son segment 1-2 harf ise ve anlamlı segmentler varsa suffix'i dahil et
        last_seg = segments[-1]
        if (not self._is_meaningful_segment(last_seg) and
                len(last_seg) <= 2 and last_seg.isalpha()):
            meaningful_before = [s for s in segments[:-1] if self._is_meaningful_segment(s)]
            if meaningful_before:
                return '*' + '-'.join(meaningful_before) + '-' + last_seg + '*'

        return '*' + '-'.join(meaningful) + '*'


    def _clean_bem_part(self, part: str):
        """Tek BEM parçasını (block, element veya modifier) temizle."""
        segments = part.split('-')
        has_hash = any(not self._is_meaningful_segment(s) for s in segments)
        if not has_hash:
            return part
        meaningful = [s for s in segments if self._is_meaningful_segment(s)]
        return '-'.join(meaningful) if meaningful else None


    # ── Adım 4: Metin sil ─────────────────────────────────────────────────
    SHORT_TEXT_TAGS = {"span", "div", "li", "td", "time", "small", "cite", "address", "a",
                       "h1", "h2", "h3", "h4", "h5", "h6", "p", "figcaption", "blockquote"}
    SHORT_TEXT_MAX  = 80

    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def _remove_text(self, soup: BeautifulSoup):
        for node in soup.find_all(string=True):
            if self.strategy in ("enriched", "hybrid"):
                parent = node.parent
                if parent and isinstance(parent, Tag):
                    # Başlıklar: her zaman metni koru (uzunluk sınırı yok)
                    if parent.name in self.HEADING_TAGS:
                        text = node.strip()
                        if text:
                            continue
                    # Diğer kısa text tag'leri: 80 char sınırı
                    elif parent.name in self.SHORT_TEXT_TAGS:
                        text = node.strip()
                        if text and len(text) <= self.SHORT_TEXT_MAX:
                            continue  # kısa text — koru
            node.extract()

    # ── Adım 5: Derinlik sınırı ───────────────────────────────────────────
    def _prune_depth(self, tag, depth: int) -> int:
        pruned = 0
        if not hasattr(tag, 'children'):
            return 0
        for child in list(tag.children):
            if not isinstance(child, Tag):
                continue
            if depth >= self.max_depth:
                child.decompose()
                pruned += 1
            else:
                pruned += self._prune_depth(child, depth + 1)
        return pruned

    # Makale içeriği tag'leri — article/main içindeyken sibling kırpmadan muaf
    CONTENT_TAGS = {"p", "td", "tr", "dd", "dt", "blockquote", "figcaption"}
    # li: sadece article/main içindeyse muaf — nav menülerinde pruning uygulanır
    LI_CONTENT_ANCESTORS = {"article", "main"}

    # ── Adım 6: Tekrar eden kardeşleri kırp ──────────────────────────────
    def _prune_siblings(self, soup: BeautifulSoup) -> int:
        pruned = 0
        for parent in soup.find_all(True):
            seen      = {}
            to_remove = []
            for child in list(parent.children):
                if not isinstance(child, Tag):
                    continue
                # İçerik tag'leri (p vb.) sibling kırpmadan muaf
                if child.name in self.CONTENT_TAGS:
                    continue
                # li: sadece article/main içindeyse muaf
                if child.name == "li":
                    if child.find_parent(self.LI_CONTENT_ANCESTORS):
                        continue
                cls_list = child.get("class", [])
                if isinstance(cls_list, str):
                    cls_list = cls_list.split()
                classes  = " ".join(sorted(cls_list))
                child_id = child.get("id", "")
                # id'si olan elementler her zaman unique — sibling sayımına dahil etme
                if child_id:
                    continue
                key = f"{child.name}|{classes}"
                seen[key] = seen.get(key, 0) + 1
                if seen[key] > self.max_siblings:
                    # Önemli metin içeriyorsa (>200 char) kırpma — içerik kapsayıcısı olabilir
                    if len(child.get_text(strip=True)) > 200:
                        continue
                    to_remove.append(child)
            for child in to_remove:
                child.decompose()
                pruned += 1
        return pruned

    # ── Adım 7: Boş tag temizle ───────────────────────────────────────────
    def _remove_empty(self, soup: BeautifulSoup):
        """
        İçi boş ve class/id/data-*'si de olmayan tag'leri kaldır.
        KEEP_STRUCTURAL tag'leri (h1, h2, time vb.) boş olsa bile korunur.
        Silinen tag'ler parent'a <!-- contains: a, span --> olarak not düşülür.
        """
        from bs4 import Comment
        changed = True
        while changed:
            changed = False
            for tag in list(soup.find_all(True)):
                if not tag.parent:
                    continue
                if tag.name in KEEP_STRUCTURAL:
                    continue
                # Enriched / hybrid: img tag'leri boyut bilgisi varsa koru
                if tag.name == "img" and self.strategy in ("enriched", "hybrid"):
                    if tag.get("width") or tag.get("height"):
                        continue
                from bs4 import Comment as _Comment
                has_children = any(isinstance(c, (Tag, _Comment)) for c in tag.children)
                has_data     = any(tag.get(a) for a in KEEP_DATA_ATTRS)
                has_identity = tag.get("class") or tag.get("id") or has_data
                has_text     = bool(tag.get_text(strip=True)) if self.strategy in ("text_included", "enriched", "hybrid") else False

                if not has_children and not has_identity and not has_data and not has_text:
                    parent   = tag.parent
                    tag_name = tag.name
                    tag.decompose()
                    # Parent'ın contains comment'ını güncelle
                    self._add_contains_comment(parent, tag_name, Comment)
                    changed = True

    def _add_contains_comment(self, parent, tag_name: str, Comment):
        """Parent'a 'contains: tag1, tag2' comment'ı ekle ya da güncelle."""
        from bs4 import Comment as BSComment
        for c in list(parent.children):
            if isinstance(c, BSComment):
                text = str(c).strip()
                if text.startswith('contains:'):
                    tags = [t.strip() for t in text[len('contains:'):].strip().split(',')]
                    if tag_name not in tags:
                        tags.append(tag_name)
                    c.replace_with(BSComment(f' contains: {", ".join(tags)} '))
                    return
        parent.append(BSComment(f' contains: {tag_name} '))

    # ── Adım 8: Formatla ──────────────────────────────────────────────────
    def _format(self, soup: BeautifulSoup) -> str:
        lines = []
        self._render(soup, lines, indent=0)
        return "\n".join(lines)

    def _render(self, node, lines: list, indent: int):
        from bs4 import Comment as BSComment
        # enriched: parent SHORT_TEXT_TAGS ise direct text node'ları render et
        node_is_short = (self.strategy in ("text_included", "enriched", "hybrid") and
                         isinstance(node, Tag) and
                         node.name in self.SHORT_TEXT_TAGS)
        for child in node.children:
            if not isinstance(child, Tag):
                if node_is_short and isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text and len(text) <= self.SHORT_TEXT_MAX:
                        lines.append(f"{'  ' * indent}{text}")
                continue
            attrs = ""
            if child.get("id"):
                attrs += f' id="{child["id"]}"'
            if child.get("class"):
                attrs += f' class="{child["class"]}"'
            for data_attr in KEEP_DATA_ATTRS:
                val = child.get(data_attr)
                if val:
                    attrs += f' {data_attr}="{val}"'
            pad = "  " * indent

            has_tag_children = any(isinstance(c, Tag) for c in child.children)
            has_text         = any(isinstance(c, str) and c.strip() for c in child.children)
            # Silinen tag'lerin bıraktığı comment'lar
            comments = [str(c).strip() for c in child.children if isinstance(c, BSComment)]
            comment_str = ("<!-- " + " ".join(comments) + " -->") if comments else ""

            # img tag'i — enriched / hybrid'da width/height varsa göster
            if child.name == "img" and self.strategy in ("enriched", "hybrid"):
                img_attrs = ""
                if child.get("width"):
                    img_attrs += f' width="{child["width"]}"'
                if child.get("height"):
                    img_attrs += f' height="{child["height"]}"'
                if child.get("class"):
                    img_attrs += f' class="{child["class"]}"'
                if img_attrs:
                    lines.append(f"{pad}<img{img_attrs}>")
            elif has_tag_children:
                lines.append(f"{pad}<{child.name}{attrs}>{comment_str}")
                self._render(child, lines, indent + 1)
                lines.append(f"{pad}</{child.name}>")
            elif has_text and self.strategy in ("text_included", "enriched", "hybrid"):
                text_content = child.get_text(separator=" ", strip=True)
                # enriched / hybrid: başlıklar her zaman metin göster, diğerleri kısa olanlar
                HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
                is_heading = child.name in HEADING_TAGS
                if (self.strategy in ("enriched", "hybrid") and
                        not is_heading and
                        (child.name not in self.SHORT_TEXT_TAGS or len(text_content) >= self.SHORT_TEXT_MAX)):
                    # Limit aşıldıysa tamamen gizleme — ilk 60 char'ı ipucu olarak göster
                    if child.name in self.SHORT_TEXT_TAGS and len(text_content) >= self.SHORT_TEXT_MAX:
                        preview = text_content[:60].rstrip() + "…"
                        lines.append(f"{pad}<{child.name}{attrs}>{preview}</{child.name}>")
                    else:
                        lines.append(f"{pad}<{child.name}{attrs}>{comment_str}</{child.name}>")
                else:
                    lines.append(f"{pad}<{child.name}{attrs}>{text_content}</{child.name}>")
            else:
                lines.append(f"{pad}<{child.name}{attrs}>{comment_str}</{child.name}>")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # doğrudan çalıştırma: depo kökü
    from webrulebench.pipeline.html_cleaner import HTMLCleaner, CleanerConfig, STRATEGIES

    parser = argparse.ArgumentParser(description="Skeleton Extractor — K3")
    parser.add_argument("html_file",  help="Ham HTML dosyası")
    parser.add_argument("--strategy", default="whitelist", choices=STRATEGIES,
                        help="html_cleaner stratejisi (default: whitelist)")
    parser.add_argument("--mode", default="enriched",
                        choices=["whitelist", "text_included", "enriched", "hybrid"],
                        help="iskelet modu (default: enriched — deneylerde LLM'e gönderilen biçim; "
                             "whitelist metinsizdir)")
    parser.add_argument("--max-depth",    type=int, default=MAX_DEPTH)
    parser.add_argument("--max-siblings", type=int, default=MAX_SIBLINGS)
    parser.add_argument("--show",   action="store_true")
    parser.add_argument("--entropy-threshold", type=float, default=4.2)
    args = parser.parse_args()

    html = Path(args.html_file).read_text(encoding="utf-8", errors="ignore")

    cfg     = CleanerConfig(entropy_threshold=args.entropy_threshold)
    cleaner = HTMLCleaner(cfg)
    cleaned = cleaner.clean(html, strategy=args.strategy)

    sk     = Skeleton(max_depth=args.max_depth, max_siblings=args.max_siblings, strategy=args.mode)
    result = sk.extract(cleaned.cleaned_html)

    print("=" * 60)
    print("  Skeleton Extractor — K3")
    print(f"  Strateji : {args.strategy}  ·  iskelet modu: {args.mode}")
    print("=" * 60)
    print(f"  Ham HTML        : {len(html):>10,} chars")
    print(f"  Cleaner çıktısı : {cleaned.cleaned_chars:>10,} chars  ({cleaned.reduction_pct:.1f}% azaldı)")
    print(f"  Skeleton çıktısı: {result.output_chars:>10,} chars  ({result.reduction_pct:.1f}% azaldı)")
    print(f"  Toplam azalma   : {round((1 - result.output_chars/len(html))*100, 1):>9.1f}%")
    print(f"  Node sayısı     : {result.node_count:>10,}")
    print(f"  Kırpılan (depth): {result.pruned_depth:>10,}")
    print(f"  Kırpılan (sibling): {result.pruned_siblings:>8,}")
    def fmt_dur(ms: float) -> str:
        if ms < 1:      return f"{ms * 1000:.0f}µs"
        elif ms < 1000: return f"{ms:.1f}ms"
        else:           return f"{ms / 1000:.2f}s"
    print(f"  Süre            : {fmt_dur(result.elapsed_ms):>12}")
    print("=" * 60)

    if args.show:
        print("\n--- SKELETON ---\n")
        print(result.skeleton_html[:3000])
        if len(result.skeleton_html) > 3000:
            print(f"\n... ({len(result.skeleton_html)-3000} chars daha)")