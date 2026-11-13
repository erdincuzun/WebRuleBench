"""
html_cleaner.py
===============
Phase 3 — HTML Skeleton / Reduction for AdaptiveScraper

Input  : raw HTML string
Output : reduced HTML string + metrics (time, token reduction)

Preprocessing (applied identically to all strategies):
  - remove script, style, iframe, noscript
  - remove display:none / visibility:hidden
  - remove HTML comments

Strategies:
  1. raw_regex        — regex-based, no DOM parse            → baseline similar to html2text (Swartz, 2011)
  2. whitelist        — keep only semantic tags              → similar to Readability (Arcavi, 2009) +
                                                                trafilatura (Barbaresi, 2021)
  3. dom_formula      — truncation score (no depth)          → similar to Boilerpipe (Kohlschütter et al., 2010)
                                                                overlaps with CETR (Wang et al., AAAI 2012)
  4. dom_depth_abs    — truncation score (absolute depth)    → similar to Dragnet (Peters & Lecocq, 2013)
  5. dom_depth_rel    — truncation score (normalized depth)  → normalized variant of CETR (Wang et al., 2012)
  6. entropy          — character-entropy based              → Original contribution; conceptually related
                                                                to perplexity filtering in LLM pre-training
                                                                data cleaning (Wenzek et al., 2020)
  7. hybrid           — whitelist (soft-strip) +              → Contribution of this work: a hybrid approach
                        enriched skeleton mode                   combining the strengths of two strategies.
                                                                soft-strip: unknown tag attrs are removed but
                                                                  the tag is kept → container hierarchy preserved
                                                                enriched mode: original text annotation (date ↑)

Truncation score formula (strategies 3-5):
  score = α × text_ratio + β × log(text_length) + γ × (1/depth)
  score < θ1  → none     (leave as is)
  θ1–θ2       → sentence (first sentence)
  θ2–θ3       → fixed    (first N characters)
  θ3+         → placeholder [CONTENT]

Usage:
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
    "none",
    "raw_regex",
    "whitelist",
    "dom_formula",
    "dom_depth_abs",
    "dom_depth_rel",
    "entropy",
    "hybrid",
]

STRATEGIES: list[Strategy] = [
    "none",
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
    All parameters in one place.
    Different experiments can be run with different config objects.
    """

    # ── Truncation score weights (strategies 3-5) ─────────────────────────
    alpha: float = 0.5    # text_ratio weight
    beta:  float = 0.3    # log(text_length) weight
    gamma: float = 0.2    # depth component weight

    # ── Truncation thresholds ─────────────────────────────────────────────
    theta1: float = 0.3   # below → none
    theta2: float = 0.5   # below → sentence
    theta3: float = 0.7   # below → fixed(N), above → placeholder

    # ── Fixed truncation length ───────────────────────────────────────────
    fixed_n: int = 80

    # ── Entropy threshold (strategy 6) ────────────────────────────────────
    entropy_threshold: float = 3.5   # below → low information → truncate

    # ── Whitelist (strategy 2) ────────────────────────────────────────────
    keep_tags: list = field(default_factory=lambda: [
        "article", "main", "section", "header",
        "h1", "h2", "h3", "h4",
        "p", "a", "time", "figure", "figcaption",
        "ul", "ol", "li",
        "blockquote", "cite",
        "span", "div",
        "address", "img",
    ])

    # ── Preprocessing ─────────────────────────────────────────────────────
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
        """Clean the HTML with the given strategy. Return a CleanResult."""
        if strategy not in STRATEGIES:
            raise ValueError(f"Unknown strategy: {strategy}. Options: {STRATEGIES}")

        original_chars = len(html)
        t0 = time.perf_counter()

        if strategy == "none":                 # no cleaning: the page as is (full-HTML experiments)
            cleaned = html
        elif strategy == "raw_regex":
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
        """Run all strategies. Used for benchmarking."""
        return {s: self.clean(html, strategy=s) for s in STRATEGIES}

    # ── Preprocessing (identical for all DOM strategies) ──────────────────
    def _preprocess(self, soup: BeautifulSoup):
        """
        Remove noise elements.
        Applied equally to all strategies — so the strategy comparison is fair.
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
    # STRATEGY 1 — Raw Regex
    # Literature: naive baseline similar to html2text (Aaron Swartz, 2011).
    #            NOT TO BE CONFUSED with Boilerpipe — Boilerpipe uses text
    #            density + ML; this strategy is pure regex.
    # Our difference: a nav/footer/aside pattern list specific to the news domain
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_raw_regex(self, html: str) -> str:
        """
        Pure regex cleaning — no DOM parse.
        The fastest strategy; serves as the baseline.
        """
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>",   "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<iframe[^>]*>.*?</iframe>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->",                "", html, flags=re.DOTALL)
        for tag in ["nav", "aside", "form", "noscript"]:
            html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", "", html,
                          flags=re.DOTALL | re.IGNORECASE)
        # footer: remove all of them in raw_regex (no DOM context); the other strategies check in the DOM
        html = re.sub(r"<header[^>]*>.*?</header>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'\s+on\w+="[^"]*"',   "", html)
        html = re.sub(r'\s+data-[^=]+="[^"]*"', "", html)
        html = re.sub(r"\s{2,}", " ", html)
        return html.strip()

    # ══════════════════════════════════════════════════════════════════════
    # STRATEGY 2 — Tag Whitelist
    # Literature: Readability (Arcavi, 2009; integrated into Firefox as
    #            Mozilla Reader Mode) and trafilatura (Barbaresi, 2021).
    #            trafilatura is more modern, multilingual and actively
    #            maintained; the recommended reference for comparison.
    # Our difference: the tag list is optimized for LLM selector generation;
    #            a deterministic whitelist instead of score-based content selection.
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_whitelist(self, soup: BeautifulSoup) -> str:
        """
        Keep only known semantic tags.
        Hybrid: known tags are handled by rule, unknown ones are removed.
        """
        keep      = set(self.cfg.keep_tags)
        # Structural noise → decompose (no content expected)
        hard_remove = {"nav", "form", "menu"}
        # Form controls → unwrap (so child content is not lost if BS4 mis-parses)
        soft_remove = {"button", "input", "select", "textarea"}

        # header/footer/aside: keep if inside article/main, remove if outside
        for tag in soup.find_all(["header", "footer", "aside"]):
            if not tag.find_parent(["article", "main"]):
                tag.decompose()

        for tag in soup.find_all(True):
            if not tag.parent:   # already removed
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
    # STRATEGY 7 — Hybrid
    # Whitelist cleaner: blacklisted → decompose, unknown → clear attrs
    # (no unwrap() → the image/tag container hierarchy is preserved).
    # The enriched mode is applied in the skeleton stage (text annotation).
    # This gives structural integrity (the dom_depth_rel advantage) and original
    # text signals (the enriched advantage) at the same time.
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
                # Instead of unwrap(), only reset the attributes:
                # the tag structure (and hence the container hierarchy) stays intact,
                # the text is left untouched → the enriched skeleton mode can see the raw text
                tag.attrs = {}

        return str(soup)

    # ══════════════════════════════════════════════════════════════════════
    # STRATEGY 3-5 — DOM Formula (three variants)
    #
    # dom_formula (no depth):
    #   Literature: Boilerpipe (Kohlschütter et al., ACM CIKM 2010).
    #              Text density (text/markup ratio) is the core of Boilerpipe.
    #              CETR (Wang et al., AAAI 2012) uses tag ratios in a similar
    #              way. Justext (Pomikálek, 2011) classifies paragraphs
    #              — a less suitable reference because it depends on stop words.
    #
    # dom_depth_abs (absolute depth):
    #   Literature: Dragnet (Peters & Lecocq, WWW 2013). DOM structure +
    #              content model + CRF; uses the depth feature explicitly.
    #              NOT TO BE CONFUSED with SimpDOM (Zhou et al., 2021) —
    #              SimpDOM is DOM simplification based on a graph neural network.
    #
    # dom_depth_rel (normalized depth):
    #   Literature: the normalized tag ratio variant of CETR (Wang et al., 2012).
    #              NOT TO BE CONFUSED with Web2Text (Vogels et al., EMNLP 2018) —
    #              Web2Text is a deep-learning sequence model.
    #
    # Our common difference: a truncation decision with multi-parameter α β γ θ,
    #                 focused on LLM token optimization.
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_dom_formula(self, soup: BeautifulSoup,
                               use_depth: bool = False,
                               relative: bool = False) -> str:
        """
        Truncation score formula:
          score = α×text_ratio + β×log(text_length) + γ×depth_component

        Thresholds:
          score < θ1  → none     (leave as is)
          θ1–θ2       → sentence
          θ2–θ3       → fixed(N)
          θ3+         → [CONTENT]
        """
        cfg       = self.cfg
        max_depth = self._max_depth(soup) if (use_depth and relative) else 1

        # Precompute the max text length for normalization
        all_texts = [len(t.get_text(strip=True)) for t in soup.find_all(True) if t.parent]
        max_tlen  = max(all_texts) if all_texts else 1
        log_max   = math.log(max_tlen + 1)

        for tag in soup.find_all(True):
            if not tag.parent:
                continue

            # Apply only to nodes that contain text
            # (leave containers with child tags alone — avoids parent-child conflicts)
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
                pass  # none — leave as is
            elif score < cfg.theta2:
                self._truncate_tag(tag, self._first_sentence(text))
            elif score < cfg.theta3:
                self._truncate_tag(tag, text[:cfg.fixed_n] + "…")
            else:
                self._truncate_tag(tag, "[CONTENT]")

        return str(soup)

    # ══════════════════════════════════════════════════════════════════════
    # STRATEGY 6 — Entropy
    # Literature: No direct counterpart — original contribution.
    #            Conceptual link: Shannon (1948) character entropy.
    #            Close in spirit to the perplexity filtering used in LLM
    #            pre-training data cleaning: Wenzek et al., "CCNet: Extracting
    #            High Quality Monolingual Datasets from Web Crawl Data",
    #            LREC 2020. Difference: we use character-level entropy while
    #            CCNet uses word-level perplexity.
    # ══════════════════════════════════════════════════════════════════════
    def _strategy_entropy(self, soup: BeautifulSoup) -> str:
        """
        Truncation based on character entropy.
        Low entropy → repetitive/navigation text → truncate.
        High entropy → rich content → keep.

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

    # ── Helpers ───────────────────────────────────────────────────────────
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
# CLI — run all strategies on a single HTML file
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse, pathlib

    parser = argparse.ArgumentParser(description="HTML Cleaner — comparison of strategies")
    parser.add_argument("html_file", help="HTML file to clean")
    parser.add_argument("--strategy", default="all",
                        help=f"Strategy: all or one of {STRATEGIES}")
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
    print("  HTML Cleaner — comparison of strategies")
    print(f"  Original size: {len(html):,} characters")
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