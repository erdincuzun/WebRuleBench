"""
metrics.py
==========
Ortak değerlendirme metrikleri.

Metin alanları : word_f1_similarity  (ROUGE-1 F1)
Resim alanı   : jaccard              (set-level Jaccard similarity)
"""

from dateutil import parser as dateparser


# ---------------------------------------------------------------------------
# TEMEL METRİKLER
# ---------------------------------------------------------------------------

def word_f1_similarity(a: str, b: str) -> float:
    """Kelime bazlı F1 skoru (ROUGE-1 F1).
    Precision = tahmin kelimelerinin GT'de bulunan oranı
    Recall    = GT kelimelerinin tahminde bulunan oranı
    F1        = harmonik ortalama
    """
    if not a or not b:
        return 0.0
    gt_words  = a.strip().lower().split()
    pred_words = b.strip().lower().split()
    if not gt_words or not pred_words:
        return 0.0
    gt_counts, pred_counts = {}, {}
    for w in gt_words:
        gt_counts[w]   = gt_counts.get(w, 0)   + 1
    for w in pred_words:
        pred_counts[w] = pred_counts.get(w, 0) + 1
    common    = sum(min(gt_counts[w], pred_counts.get(w, 0)) for w in gt_counts)
    precision = common / len(pred_words)
    recall    = common / len(gt_words)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def jaccard(a: set, b: set) -> float:
    """Set-level Jaccard similarity."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# YARDIMCI
# ---------------------------------------------------------------------------

def collect_text(els) -> str:
    """BeautifulSoup eleman listesindeki tüm metinleri birleştir."""
    return " ".join(el.get_text(strip=True) for el in els).strip()


def collect_srcs(els) -> set:
    """Eleman listesindeki tüm img src URL'lerini topla."""
    srcs = set()
    for el in els:
        for img in ([el] if el.name == "img" else []) + el.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if src:
                srcs.add(src.strip())
    return srcs


# ---------------------------------------------------------------------------
# TARİH KARŞILAŞTIRMA
# ---------------------------------------------------------------------------

def _parse_date_safe(s: str):
    try:
        return dateparser.parse(str(s), fuzzy=True)
    except Exception:
        return None


def dates_match(a: str, b: str) -> bool:
    """İki tarih stringinin yıl-ay-gün'ü aynı mı?"""
    d1 = _parse_date_safe(a)
    d2 = _parse_date_safe(b)
    if d1 and d2:
        return d1.year == d2.year and d1.month == d2.month and d1.day == d2.day
    return False


# ---------------------------------------------------------------------------
# SKOR FONKSİYONLARI
# ---------------------------------------------------------------------------

def score_text(extracted: str, gt_text: str, field: str = "") -> tuple[float, str]:
    """Metin alanı skoru. Date için önce tarih parse dener, diğerleri ROUGE-1 F1."""
    if not extracted:
        return 0.0, "NULL"
    if not gt_text:
        return -1.0, "NO_GT"
    if field == "date":
        if dates_match(extracted, gt_text):
            return 1.0, "MATCH"
        sim = word_f1_similarity(extracted, gt_text)
        return (sim, "PARTIAL") if sim > 0 else (0.0, "WRONG")
    sim = word_f1_similarity(extracted, gt_text)
    if sim > 0:
        return sim, "PARTIAL"
    return 0.0, "WRONG"


def score_images(extracted_urls: set, gt_urls: set) -> tuple[float, str]:
    """Resim alanı skoru — set-level Jaccard similarity."""
    if not extracted_urls:
        return 0.0, "NULL"
    if not gt_urls:
        return -1.0, "NO_GT"
    j = jaccard(extracted_urls, gt_urls)
    if j > 0:
        return j, "PARTIAL"
    return 0.0, "WRONG"


def _collect_text_generic(els) -> str:
    """CSS (bs4 Tag), XPath (lxml element/string) veya regex (str) sonuçlarından metin topla."""
    parts = []
    for el in els:
        if isinstance(el, str):
            # regex sonucu iç HTML olabilir ("<p>…</p>") → düz metin; aksi halde CSS/XPath
            # metniyle karşılaştırmada etiketler yüzünden haksız düşük skor alır
            from webrulebench.rules.regex_generator import html_to_text
            parts.append(html_to_text(el))
        elif hasattr(el, "get_text"):
            parts.append(el.get_text(strip=True))
        elif hasattr(el, "text_content"):
            parts.append(el.text_content().strip())
        else:
            parts.append(str(el).strip())
    return " ".join(p for p in parts if p).strip()


def _collect_srcs_generic(els) -> set:
    """CSS/XPath sonuçlarından img src kümesi topla (regex sonuçları zaten string kabul edilir)."""
    srcs = set()
    for el in els:
        if isinstance(el, str):
            if el.strip():
                srcs.add(el.strip())
            continue
        if hasattr(el, "get"):  # bs4 Tag
            if el.name == "img":
                src = el.get("src") or el.get("data-src") or ""
                if src:
                    srcs.add(src.strip())
            for img in el.find_all("img"):
                src = img.get("src") or img.get("data-src") or ""
                if src:
                    srcs.add(src.strip())
        elif hasattr(el, "xpath"):  # lxml element
            candidates = [el] + el.xpath(".//img")
            for img in candidates:
                if getattr(img, "tag", None) == "img":
                    src = img.get("src") or img.get("data-src") or ""
                    if src:
                        srcs.add(src.strip())
    return srcs


def score_selector(soup, gt_selector, llm_selector,
                   optional=False, field=None, skeleton_soup=None,
                   similarity_metric: str = "f1",
                   rule_type: str = "css", gt_rule_type: str = None,
                   raw_html: str = None):
    """Kural bazlı skor (benchmark_llm için) — CSS, XPath veya Regex destekler.

    rule_type    : llm_selector'ın tipi ('css', 'xpath', 'regex')
    gt_rule_type : gt_selector'ın tipi — verilmezse rule_type ile aynı kabul edilir
    raw_html     : xpath/regex çalıştırmak için ham HTML string (soup'tan re-parse
                   yerine kullanılır); verilmezse str(soup) ile türetilir
    similarity_metric: 'f1' (ROUGE-1 F1) veya 'seq' (SequenceMatcher)
    """
    from difflib import SequenceMatcher as _SM
    from webrulebench.rules.rule_utils import run_rule

    gt_rule_type = gt_rule_type or rule_type

    if not llm_selector:
        return (-1.0, "OPT_NULL") if optional else (0.0, "NULL")

    html_source = raw_html if raw_html is not None else str(soup)

    def _run(rule, rtype, target_soup):
        if rtype == "css":
            try:
                return target_soup.select(rule)
            except Exception:
                return None
        try:
            return run_rule(html_source, rule, rtype)
        except Exception:
            return None

    llm_els = _run(llm_selector, rule_type, soup)
    if llm_els is None:
        return 0.0, "INVALID"
    if not llm_els and skeleton_soup is not None and rule_type == "css":
        try:
            llm_els = skeleton_soup.select(llm_selector)
        except Exception:
            pass
    if not llm_els:
        return (-1.0, "OPT_MISS") if optional else (0.0, "MISS")
    if not gt_selector:
        return -1.0, "NO_GT"

    if gt_rule_type == "css":
        gt_parts = [p.strip() for p in gt_selector.split(",") if p.strip()]
        if len(gt_parts) > 1:
            best_score, best_label = 0.0, "WRONG"
            for part in gt_parts:
                s, lbl = score_selector(soup, part, llm_selector,
                                        optional=False, field=field,
                                        skeleton_soup=skeleton_soup,
                                        similarity_metric=similarity_metric,
                                        rule_type=rule_type, gt_rule_type=gt_rule_type,
                                        raw_html=raw_html)
                if s > best_score or (s == best_score and lbl not in ("GT_MISS", "GT_ERROR")):
                    best_score, best_label = s, lbl
            return best_score, best_label

    gt_els = _run(gt_selector, gt_rule_type, soup)
    if gt_els is None:
        return -1.0, "GT_ERROR"
    if not gt_els:
        return -1.0, "GT_MISS"

    is_image_field = field in ("images", "image", "img", "photos")

    if is_image_field:
        sim = jaccard(_collect_srcs_generic(gt_els), _collect_srcs_generic(llm_els))
    else:
        gt_text  = _collect_text_generic(gt_els)
        llm_text = _collect_text_generic(llm_els)
        if not gt_text and not llm_text:
            sim = jaccard(set(id(e) for e in gt_els), set(id(e) for e in llm_els))
        elif similarity_metric == "seq":
            sim = _SM(None, gt_text[:5000], llm_text[:5000]).ratio()
        else:
            sim = word_f1_similarity(gt_text[:5000], llm_text[:5000])

    gt_count, llm_count = len(gt_els), len(llm_els)
    is_container = (sim < 1.0 and gt_count != llm_count and
                    ((gt_count == 1 and llm_count > 1) or (llm_count == 1 and gt_count > 1)))

    if sim > 0:
        return sim, "CONTAINER" if is_container else "PARTIAL"
    return 0.0, "CONTAINER" if is_container else "WRONG"
