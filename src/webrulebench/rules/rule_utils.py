"""
rule_utils.py
=============
CSS selector, XPath ve Regex kurallarını ortak bir arayüzden çalıştırma.

Amaç: llm_extractor.py ve web uygulaması (webapp/), alan çıkarımını üç farklı kural
diliyle yapabilsin — CSS her zaman olduğu gibi BeautifulSoup ile, XPath
lxml ile, Regex ise ham HTML/metin üzerinde re ile çalışır.

Kullanım:
  from webrulebench.rules.rule_utils import run_rule, css_to_xpath

  elems = run_rule(soup, ".article-title", "css")
  elems = run_rule(html_string, "//h1[@class='title']", "xpath")
  texts = run_rule(html_string, r'"datePublished":"([^"]+)"', "regex")
"""

import re
import threading
from typing import Literal

RuleType = Literal["css", "xpath", "regex"]


def css_to_xpath(css: str) -> str | None:
    """CSS selector'ı XPath'e çevir. Çeviremezse None döner."""
    if not css or not css.strip():
        return None
    try:
        from cssselect import GenericTranslator
    except ImportError:
        return None

    parts = [p.strip() for p in css.split(",") if p.strip()]
    xpaths = []
    for part in parts:
        try:
            xpaths.append(GenericTranslator().css_to_xpath(part))
        except Exception:
            continue
    if not xpaths:
        return None
    return " | ".join(xpaths)


def xpath_literal(s: str) -> str:
    """Bir string'i XPath 1.0 literal'ine çevir (tırnak kaçışı yoktur, concat gerekir)."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in s.split("'")) + ")"


def _xpath_class_test(cls: str, strict: bool) -> str:
    # contains(@class,'x') okunaklıdır ama 'subtitle' içinde 'title'ı da bulur;
    # strict biçim class'ı tam token olarak eşler (CSS .x ile birebir aynı).
    if strict:
        return f"contains(concat(' ', normalize-space(@class), ' '), {xpath_literal(' ' + cls + ' ')})"
    return f"contains(@class, {xpath_literal(cls)})"


def _xpath_attr_test(name: str, op: str, val: str) -> str:
    a, v = f"@{name}", xpath_literal(val)
    if not op:
        return a
    if op == "=":
        return f"{a}={v}"
    if op == "*=":
        return f"contains({a}, {v})"
    if op == "^=":
        return f"starts-with({a}, {v})"
    if op == "$=":
        return f"substring({a}, string-length({a}) - string-length({v}) + 1)={v}"
    if op == "~=":
        return f"contains(concat(' ', normalize-space({a}), ' '), {xpath_literal(' ' + val + ' ')})"
    raise ValueError(op)


_IDENT = re.compile(r"-?[A-Za-z_][\w-]*")
_ATTR  = re.compile(r"\[\s*([\w:-]+)\s*(?:([*^$~]?=)\s*(\"[^\"]*\"|'[^']*'|[^\]\s]+)\s*)?\]")


def _compound_to_xpath(comp: str, strict: bool) -> str | None:
    """'div.a#b[x="y"]' → 'div[@id='b'][contains(@class,'a')][@x='y']'. Desteklenmeyen sözdizimi → None."""
    i, tag, tests = 0, "*", []
    m = _IDENT.match(comp)
    if comp.startswith("*"):
        i = 1
    elif m:
        tag, i = m.group().lower(), m.end()
    while i < len(comp):
        ch = comp[i]
        if ch in "#.":
            m = _IDENT.match(comp, i + 1)
            if not m:
                return None
            tests.append(f"@id={xpath_literal(m.group())}" if ch == "#" else _xpath_class_test(m.group(), strict))
            i = m.end()
        elif ch == "[":
            m = _ATTR.match(comp, i)
            if not m:
                return None
            name, op, val = m.group(1), m.group(2) or "", m.group(3) or ""
            if val[:1] in "\"'":
                val = val[1:-1]
            tests.append(_xpath_attr_test(name, op, val))
            i = m.end()
        else:
            return None   # :pseudo, \\escape, +, ~ ... → desteklenmiyor
    return tag + "".join(f"[{t}]" for t in tests)


def css_to_xpath_readable(css: str, strict_classes: bool = False) -> str | None:
    """Basit CSS selector'ları (tag, #id, .class, [attr], ' ' ve '>' birleştiricileri)
    okunaklı XPath'e çevirir: 'div.body > p' → '//div[contains(@class, 'body')]/p'.
    Desteklenmeyen bir parça varsa None döner (çağıran css_to_xpath'e düşebilir)."""
    if not css or not css.strip() or "\\" in css:
        return None
    out = []
    for part in (p.strip() for p in css.split(",")):
        if not part:
            continue
        # birleştiricileri ayır; attribute değerleri içindeki boşluk/'>' korunur
        tokens, buf, depth = [], "", 0
        for ch in part:
            depth += (ch == "[") - (ch == "]")
            if depth == 0 and ch in " >":
                if buf:
                    tokens.append(buf)
                    buf = ""
                if ch == ">":
                    tokens.append(">")
                continue
            buf += ch
        if buf:
            tokens.append(buf)
        path, axis = "", "//"
        for tok in tokens:
            if tok == ">":
                if axis == "/" or not path:
                    return None
                axis = "/"
                continue
            step = _compound_to_xpath(tok, strict_classes)
            if step is None:
                return None
            path += axis + step
            axis = "//"
        if not path or axis == "/":
            return None
        out.append(path)
    return " | ".join(out) if out else None


def _to_lxml_tree(html_or_soup):
    """BeautifulSoup nesnesi veya HTML string'i lxml ağacına çevir."""
    from lxml import html as lxml_html

    if isinstance(html_or_soup, str):
        return lxml_html.fromstring(html_or_soup)

    # BeautifulSoup nesnesi verildiyse tekrar parse et (lxml kendi ağacını ister)
    return lxml_html.fromstring(str(html_or_soup))


def run_css(soup, selector: str) -> list:
    """CSS selector'ı BeautifulSoup ağacında çalıştır, virgüllü parçaları birleştirir."""
    parts = [p.strip() for p in selector.split(",") if p.strip()]
    seen, elems = set(), []
    for part in parts:
        try:
            found = soup.select(part)
        except Exception:
            continue
        for el in found:
            if id(el) not in seen:
                seen.add(id(el))
                elems.append(el)
    return elems


def run_xpath(html_or_soup, xpath: str) -> list:
    """XPath'i lxml ağacında çalıştır. Element listesi döner (lxml elements)."""
    try:
        tree = _to_lxml_tree(html_or_soup)
        result = tree.xpath(xpath)
    except Exception:
        return []
    # xpath text()/attribute() sorguları string döndürebilir — element'lere sarmıyoruz,
    # çağıran taraf (metrics.py) bunları ayrıca ele alır.
    return result if isinstance(result, list) else [result]


# ── Regex süre sınırı ─────────────────────────────────────────────────────
# LLM'in yazdığı bir regex (ör. iç içe .*? ile) "felaket geri izleme"ye girip saatlerce sürebilir ve re
# kesilemez. Regex bu yüzden ayrı bir işlemde, yine re ile çalışır; süreyi aşarsa işlem kapatılır, sonuç boş
# sayılır ve desen regex_timeouts() listesine yazılır (çağıran thread'e özel).
REGEX_TIMEOUT_S = 5.0
_FLAGS = re.IGNORECASE | re.DOTALL
_worker = {"proc": None, "send": None, "recv": None, "text": None}
_worker_lock = threading.Lock()
_local = threading.local()


def _regex_serve():
    """Yardımcı işlemin döngüsü: (desen, metin | None) alır, re.findall sonucunu yollar."""
    import os
    from multiprocessing.connection import Connection
    inp, out = Connection(os.dup(0), writable=False), Connection(os.dup(1), readable=False)
    out.send(("ready", None))
    text = ""
    while True:
        try:
            pattern, new_text = inp.recv()
        except EOFError:
            return
        if new_text is not None:      # metin yalnızca değiştiğinde gönderilir
            text = new_text
        try:
            out.send(("ok", re.findall(pattern, text, flags=_FLAGS)))
        except re.error:
            out.send(("error", None))


def _start_worker(w):
    import os
    import subprocess
    import sys
    from multiprocessing.connection import Connection
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}
    w["proc"] = subprocess.Popen(
        [sys.executable, "-c", "from webrulebench.rules.rule_utils import _regex_serve; _regex_serve()"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
    w["send"] = Connection(os.dup(w["proc"].stdin.fileno()), readable=False)
    w["recv"] = Connection(os.dup(w["proc"].stdout.fileno()), writable=False)
    w["text"] = None
    if not w["recv"].poll(60):        # yorumlayıcının açılışı süre sınırına sayılmaz
        _stop_worker(w)
        raise RuntimeError("regex worker did not start")
    w["recv"].recv()


def _stop_worker(w):
    w["proc"].kill()
    w["proc"].wait()
    for c in (w["send"], w["recv"], w["proc"].stdin, w["proc"].stdout):
        c.close()
    w["proc"] = None


def _findall_limited(pattern: str, text: str):
    """re.findall'ın sonucu; geçersiz desen → []; süre aşımı → None (işlem yeniden başlatılır)."""
    import os
    if os.name != "posix":            # Windows: süre sınırı yok
        try:
            return re.findall(pattern, text, flags=_FLAGS)
        except re.error:
            return []
    with _worker_lock:
        w = _worker
        if w["proc"] is None or w["proc"].poll() is not None:
            _start_worker(w)
        same = w["text"] is not None and w["text"] is text
        try:
            w["send"].send((pattern, None if same else text))
        except OSError:               # işlem kapanmış: yeniden başlat, bir kez daha dene
            _stop_worker(w)
            _start_worker(w)
            w["send"].send((pattern, text))
        w["text"] = text
        if w["recv"].poll(REGEX_TIMEOUT_S):
            status, matches = w["recv"].recv()
            return matches if status == "ok" else []
        _stop_worker(w)
        return None


def regex_timeouts(reset: bool = False) -> list[str]:
    """Bu thread'de süreyi aşan desenler (reset=True: listeyi boşaltır ve önceki içeriği döndürür)."""
    out = getattr(_local, "timeouts", [])
    if reset:
        _local.timeouts = []
    return out


def run_regex(html_or_soup, pattern: str) -> list[str]:
    """Regex'i ham HTML/metin üzerinde çalıştır, eşleşen grupları/tam eşleşmeleri döndürür."""
    text = html_or_soup if isinstance(html_or_soup, str) else str(html_or_soup)
    try:
        re.compile(pattern, _FLAGS)
    except re.error:
        return []
    matches = _findall_limited(pattern, text)
    if matches is None:
        if not hasattr(_local, "timeouts"):
            _local.timeouts = []
        if pattern not in _local.timeouts:
            _local.timeouts.append(pattern)
        return []
    results = []
    for m in matches:
        if isinstance(m, tuple):
            # Birden çok grup varsa ilk boş olmayanı al
            m = next((g for g in m if g), "")
        if m:
            results.append(m)
    return results


def run_rule(html_or_soup, rule: str, rule_type: RuleType) -> list:
    """
    Kural tipine göre uygun çalıştırıcıyı seçer.

    - css   : BeautifulSoup select — element listesi döner
    - xpath : lxml xpath — element/string listesi döner
    - regex : re.findall — string listesi döner
    """
    if not rule:
        return []
    if rule_type == "css":
        return run_css(html_or_soup, rule)
    if rule_type == "xpath":
        return run_xpath(html_or_soup, rule)
    if rule_type == "regex":
        return run_regex(html_or_soup, rule)
    raise ValueError(f"Bilinmeyen rule_type: {rule_type}")
