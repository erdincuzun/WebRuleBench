"""
skeleton.py
===========
Phase 3 — K3: HTML Skeleton Extractor

Extracts only the structural tree from cleaned HTML.
Text, src, href, style, event handlers — none of them remain.
Only tag + class + id + selected data-* attributes remain.

Class cleaning:
  ssrcss-8ytrv8-TextContainer  →  TextContainer   (split on hyphens, drop hashes)
  eys6wfo1                     →  (removed)
  text-[40px]                  →  text-[40px]     (CSS value, kept)
  kbqDDU                       →  kbqDDU          (has an uppercase letter, kept)

Token meaningfulness rule (method B):
  - Contains an uppercase letter  → keep
  - Contains a digit              → keep  (2xl, 8ytrv8, 40px)
  - Contains a CSS unit           → keep  (%, rem, vw, vh...)
  - Lowercase only, ≥5 chars      → keep  (article, container)
  - Otherwise                     → drop

Input  : cleaned HTML string (html_cleaner output)
Output : skeleton HTML string + metrics

Usage:
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

# Core attributes are always kept
KEEP_ATTRS = {"class", "id"}

# Meaningful data-* attributes are kept
KEEP_DATA_ATTRS = {
    "data-testid", "data-trackable", "data-type",
    "data-component", "data-widget", "data-id",
    "data-module", "data-section", "data-block",
    "data-article",
}

# Semantic tags are not removed even when empty
KEEP_STRUCTURAL = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "main", "article", "section", "header",
    "p", "time", "figure", "figcaption",
    "address",
}

MAX_DEPTH    = 16
MAX_SIBLINGS = 2

# CSS units — for the number+unit pattern (40px, 2rem, 100vh)
CSS_UNITS = {"px", "rem", "em", "vh", "vw", "%", "pt", "ch", "ex", "fr", "deg"}

# Base words of pure utility/style classes that carry a BEM modifier (--)
# Tokens with this prefix (e.g. box--margin-none, flex--justify-center) are removed
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

# Short but meaningful CSS words — kept even below the length threshold
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

        # 1. Remove noise tags
        self._remove_noise(soup)

        # 2. Strip all attributes (except class, id, data-*)
        self._clean_attrs(soup)

        # 3. Clean class tokens (drop hashes)
        self._clean_classes(soup)

        # 4. Remove all text (not in the text_included / enriched / hybrid strategies)
        if self.strategy not in ("text_included", "enriched", "hybrid"):
            self._remove_text(soup)

        # 5. Apply the depth limit
        pruned_depth = self._prune_depth(soup, depth=0)

        # 6. Prune repeated siblings
        pruned_siblings = self._prune_siblings(soup)

        # 7. Remove empty tags
        self._remove_empty(soup)

        # 8. Pretty-print
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

    # ── Step 1: Remove noise ──────────────────────────────────────────────
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
                # If it holds substantial text (>500 chars) it may be a content container; do not remove
                if len(tag.get_text(strip=True)) > 500:
                    continue
                tag.decompose()
        # header/footer/aside: keep if inside article/main, remove if outside
        for tag in soup.find_all(["header", "footer", "aside"]):
            if not tag.find_parent(["article", "main"]):
                tag.decompose()

        # article without p → teaser/card, remove (a full news text always has p)
        for tag in soup.find_all("article"):
            if not tag.find("p"):
                tag.decompose()

        # CSS position:fixed/sticky → UI chrome (nav, modal, banner), remove
        # Tailwind "fixed" or "sticky" class token === CSS position value
        # CSS display:none → Tailwind "hidden" class token === hidden element, remove
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

        # --- Navigation list detection ---
        # ul elements with the ul > li > a pattern repeated 5+ times → menu, remove
        # But keep tag lists inside article/main
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
        # If there is a single article tag, detect and remove the sibling
        # containers at the article's depth (sidebar, related news)
        self._prune_non_article_siblings(soup)

    def _prune_non_article_siblings(self, soup: BeautifulSoup):
        """
        If there is a single primary article, remove the heavy sibling
        containers (sidebar, news lists) in its parent containers.
        """
        articles = soup.find_all("article")
        # If there is more than one article (may be a news list page), do nothing
        if len(articles) != 1:
            return
        article = articles[0]

        # Find the article's parent chain
        parent = article.parent
        if not parent:
            return

        for sibling in list(parent.children):
            if not isinstance(sibling, Tag):
                continue
            if sibling is article:
                continue
            # Sibling container analysis
            sib_nodes = len(sibling.find_all(True))
            # Small siblings are fine
            if sib_nodes < 20:
                continue
            # For heavy siblings, check link/heading density
            sib_links    = len(sibling.find_all("a"))
            sib_headings = len(sibling.find_all(["h3", "h4", "h5"]))
            # High link or heading density means sidebar/news list
            if sib_links > 10 or sib_headings > 5:
                sibling.decompose()
                continue
            # Noise if it has far more nodes than the article
            art_nodes = len(article.find_all(True))
            if sib_nodes > art_nodes * 2:
                sibling.decompose()

    # ── Step 2: Clean attributes ──────────────────────────────────────────
    def _clean_attrs(self, soup: BeautifulSoup):
        """Keep class, id and selected data-* attributes; remove the others."""
        for tag in soup.find_all(True):
            attrs_to_keep = {}
            for attr in KEEP_ATTRS:
                val = tag.get(attr)
                if val:
                    if isinstance(val, list):
                        val = " ".join(val)
                    # Skip numeric/hash IDs (page-specific generated IDs)
                    # E.g.: bdf-1363274035, div-gpt-ad-..., wp-block-12345
                    if attr == "id" and re.search(r'\d{5,}', val):
                        continue
                    attrs_to_keep[attr] = val
            # Keep the selected data-* attributes
            for attr in KEEP_DATA_ATTRS:
                val = tag.get(attr)
                if val:
                    attrs_to_keep[attr] = val
            # Enriched / hybrid: keep size information for img tags
            if tag.name == "img" and self.strategy in ("enriched", "hybrid"):
                w = tag.get("width")
                h = tag.get("height")
                # Keep width/height if present directly as attributes
                if w:
                    attrs_to_keep["width"] = str(w)
                if h:
                    attrs_to_keep["height"] = str(h)
                # Parse the size from the src URL (such as 1170x700)
                if not w and not h:
                    src_url = tag.get("src", "")
                    m = re.search(r'(\d{3,4})[xX](\d{3,4})(?:[/_.]|$)', src_url)
                    if m:
                        attrs_to_keep["width"]  = m.group(1)
                        attrs_to_keep["height"] = m.group(2)
            tag.attrs = attrs_to_keep

    # ── Step 3: Clean class tokens ───────────────────────────────────────
    def _clean_classes(self, soup: BeautifulSoup):
        """
        Remove hash-like tokens from each tag's class.

        Token meaningfulness rule (method B):
          - Contains an uppercase letter  → keep  (TextContainer)
          - Contains a digit              → keep  (2xl, text-[40px])
          - Contains a CSS unit           → keep  (%, rem, vw)
          - Lowercase only, ≥5 chars      → keep  (article, wrapper)
          - Otherwise                     → drop  (ssrcss, eys6wfo1)

        Hyphens are first turned into spaces so the class can be split into tokens.
        Then the meaningless tokens are dropped.
        """
        for tag in soup.find_all(True):
            raw_class = tag.get("class")
            if not raw_class:
                continue
            if isinstance(raw_class, list):
                raw_class = " ".join(raw_class)

            # Process the space-separated class tokens
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
        """Is a single hyphen-separated segment meaningful?"""
        import re
        if not seg: return False
        # CSS Modules / CSS-in-JS hash detection — 4 rules:
        VOWELS = set('aeiouAEIOU')
        alpha_chars = [c for c in seg if c.isalpha()]

        # Rule 1: starts with an underscore (CSS Modules _abc123 pattern)
        if seg.startswith('_'):
            return False

        # Accept before the hash rules if it is in SEMANTIC_SHORT
        if seg in SEMANTIC_SHORT:
            return True

        if seg.isalnum() and len(seg) <= 7:
            # Rule 2: short + contains a digit → hash (Hy4HP, P4L6N, z5wPE)
            if any(c.isdigit() for c in seg):
                return False
            # Rule 3: ≥2 non-initial uppercase letters → hash (WAXFI, ALMCC, xQoVi)
            non_initial_upper = sum(1 for i, c in enumerate(seg) if c.isupper() and i > 0)
            if non_initial_upper >= 2:
                return False
            # Rule 4: short + vowel ratio < 25% → hash (wsquJ, Wskuj, cgtzj)
            if (len(seg) <= 6 and alpha_chars
                    and sum(1 for c in alpha_chars if c in VOWELS) / len(alpha_chars) < 0.25):
                return False

        if any(c.isupper() for c in seg): return True
        clean = seg.strip("[]")
        pattern = r'^\d+(\.\d+)?(' + '|'.join(CSS_UNITS) + r')$'
        if re.match(pattern, clean): return True
        has_digit = any(c.isdigit() for c in seg)
        has_alpha = any(c.isalpha() for c in seg)
        # snake_case (even with underscore + digits) → semantic BEM/naming, not a hash
        # E.g.: n3_meta_posted, article_body_text, post_details_block
        if '_' in seg and len(seg) >= 5: return True
        if has_digit and has_alpha: return False
        if seg.isdigit(): return False
        if seg in SEMANTIC_SHORT: return True
        if seg.isalpha() and len(seg) >= 5: return True
        # BEM element tokens containing underscores (article__title, c__body etc.)
        if re.match(r'^[a-zA-Z_]+$', seg) and len(seg) >= 5: return True
        return False

    def _clean_class_token(self, token: str):
        """
        Clean a class token while preserving BEM notation.
          Contains -- → remove if the base is a utility, otherwise leave as is
          No hash segment → leave as is
          Has a hash and a meaningful part → "*TextContainer*"
          All hash → None (remove)
        """
        import re
        # CSS Modules: ComponentName__hash → ComponentName
        # E.g.: Paragraph_wrapper__6w7GG → Paragraph_wrapper
        # Apply only if hash_part is fully alphanumeric (so it is not confused with BEM __element)
        # BEM: elementor-post-info__item--type-date → hash_part='item--type-date' (not alnum, leave as is)
        # CSS Modules: Paragraph_wrapper__6w7GG → hash_part='6w7GG' (alnum, strip it)
        if '__' in token:
            base, hash_part = token.rsplit('__', 1)
            if base and hash_part.isalnum() and not self._is_meaningful_segment(hash_part):
                token = base

        # Contains a BEM modifier (--): is it a utility layout/style class?
        if '--' in token:
            base = token.split('--')[0]  # grid__col, flex, box, font, ...
            # If there is a BEM element separator (__), take the last part
            base_word = base.rsplit('__', 1)[-1].rsplit('-', 1)[-1]
            if base_word in UTILITY_BEM_BASES or base in UTILITY_BEM_BASES:
                return None  # pure utility/style class — remove
            return token

        # Bootstrap/Tailwind utility class pattern: w-100, h-50, col-6, p-3, m-2
        # Short letter prefix + number suffix → keep as is
        if re.match(r'^[a-z]{1,3}-\d{1,4}$', token):
            return token

        segments = token.split('-')

        # Known BEM namespace prefixes → leave as is
        BEM_PREFIXES = {"c", "l", "u", "o", "t", "is", "has", "js", "qa"}
        if len(segments) >= 2 and segments[0] in BEM_PREFIXES:
            return token
        has_hash = any(not self._is_meaningful_segment(s) for s in segments)
        if not has_hash:
            return token

        meaningful = [s for s in segments if self._is_meaningful_segment(s)]
        if not meaningful:
            return None

        # Keep a short directional/qualifier suffix: border-b, border-t, border-x etc.
        # If the last segment is 1-2 letters and there are meaningful segments, include the suffix
        last_seg = segments[-1]
        if (not self._is_meaningful_segment(last_seg) and
                len(last_seg) <= 2 and last_seg.isalpha()):
            meaningful_before = [s for s in segments[:-1] if self._is_meaningful_segment(s)]
            if meaningful_before:
                return '*' + '-'.join(meaningful_before) + '-' + last_seg + '*'

        return '*' + '-'.join(meaningful) + '*'


    def _clean_bem_part(self, part: str):
        """Clean a single BEM part (block, element or modifier)."""
        segments = part.split('-')
        has_hash = any(not self._is_meaningful_segment(s) for s in segments)
        if not has_hash:
            return part
        meaningful = [s for s in segments if self._is_meaningful_segment(s)]
        return '-'.join(meaningful) if meaningful else None


    # ── Step 4: Remove text ───────────────────────────────────────────────
    SHORT_TEXT_TAGS = {"span", "div", "li", "td", "time", "small", "cite", "address", "a",
                       "h1", "h2", "h3", "h4", "h5", "h6", "p", "figcaption", "blockquote"}
    SHORT_TEXT_MAX  = 80

    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def _remove_text(self, soup: BeautifulSoup):
        for node in soup.find_all(string=True):
            if self.strategy in ("enriched", "hybrid"):
                parent = node.parent
                if parent and isinstance(parent, Tag):
                    # Headings: always keep the text (no length limit)
                    if parent.name in self.HEADING_TAGS:
                        text = node.strip()
                        if text:
                            continue
                    # Other short text tags: 80 char limit
                    elif parent.name in self.SHORT_TEXT_TAGS:
                        text = node.strip()
                        if text and len(text) <= self.SHORT_TEXT_MAX:
                            continue  # short text — keep
            node.extract()

    # ── Step 5: Depth limit ───────────────────────────────────────────────
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

    # Article content tags — exempt from sibling pruning inside article/main
    CONTENT_TAGS = {"p", "td", "tr", "dd", "dt", "blockquote", "figcaption"}
    # li: exempt only inside article/main — pruning applies in nav menus
    LI_CONTENT_ANCESTORS = {"article", "main"}

    # ── Step 6: Prune repeated siblings ──────────────────────────────────
    def _prune_siblings(self, soup: BeautifulSoup) -> int:
        pruned = 0
        for parent in soup.find_all(True):
            seen      = {}
            to_remove = []
            for child in list(parent.children):
                if not isinstance(child, Tag):
                    continue
                # Content tags (p etc.) are exempt from sibling pruning
                if child.name in self.CONTENT_TAGS:
                    continue
                # li: exempt only inside article/main
                if child.name == "li":
                    if child.find_parent(self.LI_CONTENT_ANCESTORS):
                        continue
                cls_list = child.get("class", [])
                if isinstance(cls_list, str):
                    cls_list = cls_list.split()
                classes  = " ".join(sorted(cls_list))
                child_id = child.get("id", "")
                # Elements with an id are always unique — do not count them as siblings
                if child_id:
                    continue
                key = f"{child.name}|{classes}"
                seen[key] = seen.get(key, 0) + 1
                if seen[key] > self.max_siblings:
                    # Do not prune if it holds substantial text (>200 chars) — may be a content container
                    if len(child.get_text(strip=True)) > 200:
                        continue
                    to_remove.append(child)
            for child in to_remove:
                child.decompose()
                pruned += 1
        return pruned

    # ── Step 7: Remove empty tags ─────────────────────────────────────────
    def _remove_empty(self, soup: BeautifulSoup):
        """
        Remove tags that are empty and have no class/id/data-* either.
        KEEP_STRUCTURAL tags (h1, h2, time etc.) are kept even when empty.
        Removed tags are noted on the parent as <!-- contains: a, span -->.
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
                # Enriched / hybrid: keep img tags that have size information
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
                    # Update the parent's contains comment
                    self._add_contains_comment(parent, tag_name, Comment)
                    changed = True

    def _add_contains_comment(self, parent, tag_name: str, Comment):
        """Add or update a 'contains: tag1, tag2' comment on the parent."""
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

    # ── Step 8: Format ────────────────────────────────────────────────────
    def _format(self, soup: BeautifulSoup) -> str:
        lines = []
        self._render(soup, lines, indent=0)
        return "\n".join(lines)

    def _render(self, node, lines: list, indent: int):
        from bs4 import Comment as BSComment
        # enriched: if the parent is in SHORT_TEXT_TAGS, render the direct text nodes
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
            # Comments left by removed tags
            comments = [str(c).strip() for c in child.children if isinstance(c, BSComment)]
            comment_str = ("<!-- " + " ".join(comments) + " -->") if comments else ""

            # img tag — in enriched / hybrid, show it if it has width/height
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
                # enriched / hybrid: headings always show their text, others only short texts
                HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
                is_heading = child.name in HEADING_TAGS
                if (self.strategy in ("enriched", "hybrid") and
                        not is_heading and
                        (child.name not in self.SHORT_TEXT_TAGS or len(text_content) >= self.SHORT_TEXT_MAX)):
                    # If over the limit, do not hide it completely — show the first 60 chars as a hint
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # direct run: src/
    from webrulebench.pipeline.html_cleaner import HTMLCleaner, CleanerConfig, STRATEGIES

    parser = argparse.ArgumentParser(description="Skeleton Extractor — K3")
    parser.add_argument("html_file",  help="Raw HTML file")
    parser.add_argument("--strategy", default="whitelist", choices=STRATEGIES,
                        help="html_cleaner strategy (default: whitelist)")
    parser.add_argument("--mode", default="enriched",
                        choices=["whitelist", "text_included", "enriched", "hybrid"],
                        help="skeleton mode (default: enriched — the format sent to the LLM in experiments; "
                             "whitelist has no text)")
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
    print(f"  Strategy : {args.strategy}  ·  skeleton mode: {args.mode}")
    print("=" * 60)
    print(f"  Raw HTML        : {len(html):>10,} chars")
    print(f"  Cleaner output  : {cleaned.cleaned_chars:>10,} chars  ({cleaned.reduction_pct:.1f}% smaller)")
    print(f"  Skeleton output : {result.output_chars:>10,} chars  ({result.reduction_pct:.1f}% smaller)")
    print(f"  Total reduction : {round((1 - result.output_chars/len(html))*100, 1):>9.1f}%")
    print(f"  Nodes           : {result.node_count:>10,}")
    print(f"  Pruned (depth)  : {result.pruned_depth:>10,}")
    print(f"  Pruned (sibling):   {result.pruned_siblings:>8,}")
    def fmt_dur(ms: float) -> str:
        if ms < 1:      return f"{ms * 1000:.0f}µs"
        elif ms < 1000: return f"{ms:.1f}ms"
        else:           return f"{ms / 1000:.2f}s"
    print(f"  Time            : {fmt_dur(result.elapsed_ms):>12}")
    print("=" * 60)

    if args.show:
        print("\n--- SKELETON ---\n")
        print(result.skeleton_html[:3000])
        if len(result.skeleton_html) > 3000:
            print(f"\n... ({len(result.skeleton_html)-3000} chars daha)")