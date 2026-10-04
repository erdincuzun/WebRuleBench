"""
regex_generator.py
==================
CSS selector → regular expression üretici.

Uzun, E. (2020). "A regular expression generator based on CSS selectors for
efficient extraction from HTML pages". Turkish Journal of Electrical
Engineering & Computer Sciences 28(6): 3389-3401. doi:10.3906/elk-2004-67
(REGEXN) yaklaşımının sıfırdan yazılmış, genişletilmiş hali.

REGEXN'e göre genişletmeler
---------------------------
1. Açılış etiketi nitelik sırasından bağımsızdır: her koşul (id, class token'ı,
   [attr] operatörleri) ayrı bir lookahead'tir; class tam token olarak eşlenir
   (".content1", "content10"u yakalamaz).
2. Kapanış etiketi için üç strateji (Algoritma 1 / 2-3 karşılığı ve ek):
     simple    — ( .*? )</tag>                       (REGEXN adım 1)
     balanced  — derinlik sınırlı iç içe aynı etiket  (örnek sayfadan bağımsız)
     anchored  — kapanıştan sonraki etiket dizisiyle bitiş çıpası
                 (REGEXN adım 2-3; metin değil yalnızca etiketler kullanılır
                 ki aynı layout'un diğer sayfalarına genellenebilsin)
3. Birleştiriciler (boşluk, >): hedef bileşik tek başına ya da ata bağlamıyla
   ("A .*? B") denenir.
4. image / url alanlarında içerik yerine src / href değeri yakalanır.
5. Virgüllü alternatifler "|" ile birleştirilir.
6. Aday seçimi tek örnek sayfaya değil, verilen sayfaların tümünde CSS ile
   karşılaştırmaya göre yapılır (bkz. generate()).

Desteklenmeyenler (None döner): pseudo-class (:first-child…), kardeş
birleştiricileri (+, ~), CSS kaçışları (\\:), void etiketin içeriği.

Kullanım:
    from webrulebench.rules.regex_generator import generate
    r = generate("div.article-body", pages=[html1, html2], kind="text")
    r["regex"], r["strategy"], r["passed"], r["total"]
"""

import html as _html
import re

from webrulebench.rules.rule_utils import run_regex

# CSS kaçışları da tanımlayıcıya dahil: Tailwind ".text-\[40px\]", ".sm\:flex"
_IDENT = re.compile(r"-?(?:[A-Za-z_]|\\.)(?:[\w-]|\\.)*")
_UNESC = re.compile(r"\\(.)")
_ATTR  = re.compile(r"\[\s*([\w:-]+)\s*(?:([*^$~|]?=)\s*(\"[^\"]*\"|'[^']*'|[^\]\s]+)\s*)?\]")
_VOID  = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_FLAGS = re.IGNORECASE | re.DOTALL
BALANCE_DEPTH = 10

# alan tipi → yakalama biçimi
KIND_OF_TYPE = {"image": "image", "url": "url"}


# ---------------------------------------------------------------------------
# Metin normalleştirme (regex sonucu iç HTML'dir; karşılaştırma için metne çevrilir)
# ---------------------------------------------------------------------------
_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>|<!--.*?-->", _FLAGS)
_TAG_RE    = re.compile(r"<[^>]+>")


def html_to_text(s: str) -> str:
    """İç HTML → düz metin: script/style ve etiketler atılır, entity'ler çözülür, boşluk sadeleşir."""
    if not s:
        return ""
    s = _SCRIPT_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    return " ".join(_html.unescape(s).split())


# ---------------------------------------------------------------------------
# CSS ayrıştırma
# ---------------------------------------------------------------------------
def _parse_compound(comp: str) -> dict | None:
    """'div#a.b.c[x="y"]' → {tag, id, classes, attrs}. Desteklenmeyen sözdizimi → None."""
    out = {"tag": "*", "id": None, "classes": [], "attrs": []}
    i = 0
    if comp.startswith("*"):
        i = 1
    else:
        m = _IDENT.match(comp)
        if m:
            out["tag"], i = m.group().lower(), m.end()
    while i < len(comp):
        ch = comp[i]
        if ch in "#.":
            m = _IDENT.match(comp, i + 1)
            if not m:
                return None
            ident = _UNESC.sub(r"\1", m.group())
            if ch == "#":
                out["id"] = ident
            else:
                out["classes"].append(ident)
            i = m.end()
        elif ch == "[":
            m = _ATTR.match(comp, i)
            if not m:
                return None
            val = m.group(3) or ""
            if val[:1] in "\"'":
                val = val[1:-1]
            out["attrs"].append((m.group(1).lower(), m.group(2) or "", val))
            i = m.end()
        else:
            return None
    return out


def _parse_chain(part: str) -> list | None:
    """'div.a > p b' → [compound, compound, compound] (birleştirici türü regex'te önemsizleşir)."""
    if "+" in part or "~" in part.replace("~=", "") or ":" in _UNESC.sub("", part):
        return None
    tokens, buf, depth = [], "", 0
    for ch in part.strip():
        depth += (ch == "[") - (ch == "]")
        if depth == 0 and ch in " >":
            if buf:
                tokens.append(buf)
                buf = ""
            continue
        buf += ch
    if buf:
        tokens.append(buf)
    chain = [_parse_compound(t) for t in tokens]
    return chain if chain and all(chain) else None


# ---------------------------------------------------------------------------
# Regex parçaları
# ---------------------------------------------------------------------------
_VALUE_END = r"""(?=["'\s/>])"""
# Etiket içi: tırnaklı nitelik değerleri bütün olarak atlanır (değerde '>' olabilir:
# title="a <b>b</b>"); böylece \sclass= gibi aramalar başka bir değerin içinde eşleşmez.
_ATTRS = r"""(?:[^>"']|"[^"]*"|'[^']*')*?"""


def _token_look(attr: str, token: str) -> str:
    # attr="... token ..." — değer başında ya da boşluktan sonra, ardından boşluk/tırnak/>
    return rf"""(?={_ATTRS}\s{attr}\s*=\s*["']?(?:[^"'>]*?\s)?{re.escape(token)}{_VALUE_END})"""


def _attr_look(name: str, op: str, val: str) -> str:
    n, v = re.escape(name), re.escape(val)
    if not op:
        return rf"(?={_ATTRS}\s{n}(?=[\s=/>]))"
    if op == "=":
        return rf"""(?={_ATTRS}\s{n}\s*=\s*["']?{v}{_VALUE_END})"""
    if op == "*=":
        return rf"""(?={_ATTRS}\s{n}\s*=\s*["'][^"']*?{v})"""
    if op == "^=":
        return rf"""(?={_ATTRS}\s{n}\s*=\s*["']{v})"""
    if op == "$=":
        return rf"""(?={_ATTRS}\s{n}\s*=\s*["'][^"']*?{v}["'])"""
    if op == "~=":
        return _token_look(n, val)
    if op == "|=":
        return rf"""(?={_ATTRS}\s{n}\s*=\s*["']{v}(?:-|["']))"""
    raise ValueError(op)


def _tag_name(c: dict) -> str:
    return re.escape(c["tag"]) if c["tag"] != "*" else r"[a-zA-Z][\w:-]*"


def _open_tag(c: dict, capture_attr: str | None = None) -> str:
    """Açılış etiketi; capture_attr verilirse o niteliğin değeri yakalanır (src/href)."""
    looks = []
    if c["id"]:
        looks.append(_token_look("id", c["id"]))
    looks += [_token_look("class", cls) for cls in c["classes"]]
    looks += [_attr_look(*a) for a in c["attrs"]]
    head = f"<{_tag_name(c)}(?=[\\s/>])" + "".join(looks)
    if capture_attr:
        return head + rf"""{_ATTRS}\s{capture_attr}\s*=\s*["']?([^"'\s>]+)"""
    return head + _ATTRS + ">"


def _balanced(tag: str, depth: int) -> str:
    """İç içe aynı etiketi `depth` seviyeye kadar dengeleyen içerik kalıbı (grup yakalamaz)."""
    inner = rf"(?:[^<]|<(?!/?{tag}[\s/>]))*"
    for _ in range(depth):
        inner = rf"(?:[^<]|<(?!/?{tag}[\s/>])|<{tag}(?:[\s/][^>]*)?>{inner}</{tag}\s*>)*"
    return inner


# ---------------------------------------------------------------------------
# Aday üretimi
# ---------------------------------------------------------------------------
def _structural_suffix(html: str, pos: int, n_tags: int) -> str | None:
    """pos'tan sonraki ilk n etiketi (metin yerine [^<]*) içeren bitiş çıpası."""
    tags = list(re.finditer(r"<[^>]+>", html[pos:pos + 4000]))[:n_tags]
    if len(tags) < n_tags:
        return None
    parts = []
    for t in tags:
        m = re.match(r"</?\s*([a-zA-Z][\w:-]*)", t.group())
        if not m:
            return None
        parts.append(("</" if t.group().startswith("</") else "<") + re.escape(m.group(1).lower())
                     + (r"\s*>" if t.group().startswith("</") else r"(?=[\s/>])[^>]*>"))
    return r"[^<]*?".join(parts)


def _close_positions(html: str, open_re: str, tag: str, limit: int = 3) -> list:
    """Algoritma 2 karşılığı: open_re eşleşmelerinin gerçek kapanış etiketi sonları (iç içe sayarak)."""
    out = []
    tok = re.compile(rf"<(/?){tag}(?=[\s/>]){_ATTRS}>", re.IGNORECASE)
    for m in re.finditer(open_re, html, _FLAGS):
        depth, i = 1, m.end()
        for t in tok.finditer(html, i):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                out.append(t.end())
                break
        if len(out) >= limit:
            break
    return out


def _resolve_tag(c: dict, example_html: str | None) -> dict:
    """Etiketsiz bileşik ("#id", ".x"): örnek sayfadaki ilk eşleşmenin gerçek etiketi kullanılır."""
    if c["tag"] != "*" or not example_html:
        return c
    m = re.search(_open_tag(c), example_html, _FLAGS)
    return {**c, "tag": re.match(r"<([a-zA-Z][\w:-]*)", m.group()).group(1).lower()} if m else c


def _candidates_for_alt(chain: list, kind: str, example_html: str | None, containers: bool = True) -> list:
    """Bir virgül alternatifi için (strateji, regex) adayları, basitten karmaşığa."""
    chain  = [_resolve_tag(c, example_html) for c in chain]
    target = chain[-1]
    tag    = target["tag"]
    # ata bağlamı: her atadan sonra, o atanın kapanışını geçmeden ilerle (tempered token)
    # → "h2.title a" h2 içinde link yoksa h2'den sonraki ilk linki yakalamaz.
    # Regex her eşleşmede dıştaki atayı da tüketir (ata başına tek sonuç); çok değerli alanlar
    # için en yakın atadan başlayarak kademeli ekle: "li a" → "ul li a".
    def gap(c):
        if c["tag"] == "*" or c["tag"] in _VOID:
            return _open_tag(c) + r".*?"
        return _open_tag(c) + rf"(?:(?!</{re.escape(c['tag'])}\s*>).)*?"
    ancestors = chain[:-1]
    prefixes = [("", "")] + [(f"+ata{k}" if k < len(ancestors) else "+ata", "".join(gap(c) for c in ancestors[-k:]))
                             for k in range(1, len(ancestors) + 1)]

    out = []
    for pname, prefix in prefixes:
        if kind in ("image", "url"):
            attr = "src" if kind == "image" else "href"
            if kind == "image" and tag not in ("img", "*", "source"):
                continue
            if kind == "url" and tag not in ("a", "*", "link", "area"):
                continue
            out.append((f"attr{pname}", prefix + _open_tag(target, capture_attr=attr)))
            continue
        if tag in _VOID or tag == "*":
            continue
        open_re = _open_tag(target)
        close   = rf"</{re.escape(tag)}\s*>"
        out.append((f"simple{pname}", prefix + open_re + r"(.*?)" + close))
        out.append((f"balanced{pname}", prefix + open_re + "(" + _balanced(re.escape(tag), BALANCE_DEPTH) + ")" + close))
        if example_html:
            for end in _close_positions(example_html, open_re, re.escape(tag), limit=1):
                for n in (1, 2, 3, 5):
                    suf = _structural_suffix(example_html, end, n)
                    if suf:
                        out.append((f"anchored{n}{pname}", prefix + open_re + r"(.*?)" + close + r"[^<]*?" + suf))
    # metin alanı, niteliksiz çocuklar ("ul.breadcrumbs li"): regex kapsayıcıdaki tüm çocukları
    # ayrı ayrı sayamaz — birleşik metin karşılaştırıldığı için kapsayıcının içeriği aynı sonucu verir
    # Her üst seviye denenir ("ul.x li a" → "ul.x li", "ul.x").
    if containers and kind == "text" and len(chain) > 1:
        for depth in range(len(chain) - 1, 0, -1):
            sub = [(s, rx) for s, rx in _candidates_for_alt(chain[:depth], kind, example_html, containers=False)]
            out += [(f"container{len(chain) - depth}:{s}", rx) for s, rx in sub]
    return out


def candidates(css: str, kind: str = "text", example_html: str | None = None) -> list:
    """CSS selector → [(strateji, regex)] adayları. Desteklenmeyen seçicide []."""
    alts = [a.strip() for a in (css or "").split(",") if a.strip()]
    chains = [_parse_chain(a) for a in alts]
    if not chains or not all(chains):
        return []
    per_alt = [_candidates_for_alt(ch, kind, example_html) for ch in chains]
    if not all(per_alt):
        return []
    if len(per_alt) == 1:
        return per_alt[0]
    # alternatifler: aynı stratejiyi tüm alternatiflere uygula, "|" ile birleştir (merge=True karşılığı)
    out = []
    for strat, _ in per_alt[0]:
        picked = [dict(c).get(strat) for c in per_alt]
        if all(picked):
            out.append((strat, "|".join(f"(?:{p})" for p in picked)))
    # merge=False'ta CSS yalnızca ilk eşleşen alternatifi kullanır; regex bunu ifade edemez →
    # alternatifleri tek başına da dene (sayfalarda hep aynı alternatif eşleşiyorsa doğrulanır)
    for i, cands in enumerate(per_alt, 1):
        out += [(f"{strat} (alt{i})", rx) for strat, rx in cands]
    return out


# ---------------------------------------------------------------------------
# Doğrulama ve seçim
# ---------------------------------------------------------------------------
def regex_values(html: str, pattern: str, kind: str = "text") -> list:
    """Regex'i çalıştırıp karşılaştırılabilir değerler: metin alanı → düz metin, image/url → nitelik."""
    vals = run_regex(html, pattern)
    if kind in ("image", "url"):
        return [_html.unescape(v).strip() for v in vals if v.strip()]
    return [t for t in (html_to_text(v) for v in vals) if t]


def _norm(vals: list, kind: str = "text"):
    """Karşılaştırma anahtarı. Metin alanları değerlendirmede birleşik metin olarak skorlanır
    (metrics._collect_text_generic) → boşluklardan bağımsız birleşik metin; image/url → sıralı liste."""
    if kind in ("image", "url"):
        return sorted("".join(v.split()) for v in vals)
    return "".join("".join(vals).split())


def generate(css: str, pages: list, expected: list, kind: str = "text") -> dict | None:
    """Adaylar arasından, sayfaların en çoğunda CSS ile aynı değerleri veren regex'i seç.

    pages    : ham HTML listesi (ilki örnek sayfa — 'anchored' adayları ondan türetilir)
    expected : her sayfa için CSS'in çıkardığı değerler (aynı sıra; metin ya da src/href listesi)
    Döner    : {regex, strategy, passed, total, tried} ya da aday yoksa None.
    Eşitlikte daha basit strateji / daha kısa regex tercih edilir.
    """
    cands = candidates(css, kind, pages[0] if pages else None)
    if not cands:
        return None
    exp_norm = [_norm(e, kind) for e in expected]

    def similarity(html, exp_vals):
        # tam eşleşme yoksa hangi aday daha yakın: metin → kelime F1, liste → Jaccard
        got = regex_values(html, rx, kind)
        if kind in ("image", "url"):
            a, b = set(_norm(exp_vals, kind)), set(_norm(got, kind))
            return len(a & b) / len(a | b) if a | b else 1.0
        from webrulebench.evaluation.metrics import word_f1_similarity
        return word_f1_similarity(" ".join(exp_vals), " ".join(got))

    best = None
    for rank, (strat, rx) in enumerate(cands):
        try:
            re.compile(rx, _FLAGS)
        except re.error:
            continue
        passed, failed = 0, 0
        for html, exp in zip(pages, exp_norm):
            if _norm(regex_values(html, rx, kind), kind) == exp:
                passed += 1
            else:
                failed += 1
                if best and len(pages) - failed < best[3]:
                    break      # bu aday en iyiyi artık geçemez
        sim = 0.0
        if passed < len(pages) and (best is None or passed >= best[3]):
            sim = sum(similarity(h, e) for h, e in zip(pages, expected))
        key = (passed, round(sim, 4), -rank, -len(rx))
        if best is None or key > best[0]:
            best = (key, strat, rx, passed)
        if passed == len(pages):
            break      # basitten karmaşığa sıralı: ilk tam başarılı aday yeterli
    if best is None:
        return None
    _, strat, rx, passed = best
    return {"regex": rx, "strategy": strat, "passed": passed, "total": len(pages), "tried": len(cands)}


def css_values(html_or_soup, css: str, kind: str = "text", merge: bool = False) -> list:
    """CSS'in çıkardığı karşılaştırılabilir değerler (annotator._run_selector ile aynı merge kuralı:
    merge=False → virgüllü alternatiflerden ilk eşleşen, True → hepsinin birleşimi)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_or_soup, "html.parser") if isinstance(html_or_soup, str) else html_or_soup
    els, seen = [], set()
    for part in (p.strip() for p in css.split(",") if p.strip()):
        try:
            found = soup.select(part)
        except Exception:
            continue
        if not merge and found:
            els = found
            break
        for el in found:
            if id(el) not in seen:
                seen.add(id(el))
                els.append(el)
    if kind == "image":
        return [el.get("src").strip() for el in els if el.get("src") and el.get("src").strip()]
    if kind == "url":
        return [el.get("href").strip() for el in els if el.get("href") and el.get("href").strip()]
    # regex tarafıyla aynı normalleştirme: script/style/noscript metni ve yorumlar hariç
    return [t for t in (html_to_text(str(el)) for el in els) if t]
