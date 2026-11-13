"""
rule_utils.py
=============
Running CSS selector, XPath and Regex rules through a common interface.

Purpose: let llm_extractor.py and the web application (webapp/) extract fields with three different rule
languages — CSS runs with BeautifulSoup as always, XPath
with lxml, and Regex with re on the raw HTML/text.

Usage:
  from webrulebench.rules.rule_utils import run_rule, css_to_xpath

  elems = run_rule(soup, ".article-title", "css")
  elems = run_rule(html_string, "//h1[@class='title']", "xpath")
  texts = run_rule(html_string, r'"datePublished":"([^"]+)"', "regex")
"""

import re
import threading
from typing import Literal

RuleType = Literal["css", "xpath", "regex"]


def split_selector_list(selector: str) -> list:
    """Split a CSS selector list at its top-level commas: 'h1, h2' -> ['h1', 'h2'].

    Commas inside parentheses, square brackets or quotes belong to one selector and are kept, so
    ':is(h1, h2)', ':not(.a, .b)' and '[title="a, b"]' are not split. Parts are stripped; empty
    parts are dropped. Every place that runs or translates a CSS rule uses this function.
    """
    parts, cur, depth, quote, esc = [], "", 0, "", False
    for ch in selector or "":
        if esc:
            cur, esc = cur + ch, False
        elif ch == "\\":
            cur, esc = cur + ch, True
        elif quote:
            cur += ch
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote, cur = ch, cur + ch
        elif ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            depth += (ch in "([") - (ch in ")]")
            cur += ch
    parts.append(cur)
    return [x.strip() for x in parts if x.strip()]


def css_to_xpath(css: str) -> str | None:
    """Translate a CSS selector to XPath. Returns None if it cannot be translated."""
    if not css or not css.strip():
        return None
    try:
        from cssselect import GenericTranslator
    except ImportError:
        return None

    parts = split_selector_list(css)
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
    """Turn a string into an XPath 1.0 literal (there is no quote escaping, concat is needed)."""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in s.split("'")) + ")"


def _xpath_class_test(cls: str, strict: bool) -> str:
    # contains(@class,'x') is readable but also finds 'title' inside 'subtitle';
    # the strict form matches the class as a whole token (exactly like CSS .x).
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
    """'div.a#b[x="y"]' → 'div[@id='b'][contains(@class,'a')][@x='y']'. Unsupported syntax → None."""
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
            return None   # :pseudo, \\escape, +, ~ ... → not supported
    return tag + "".join(f"[{t}]" for t in tests)


def css_to_xpath_readable(css: str, strict_classes: bool = False) -> str | None:
    """Translates simple CSS selectors (tag, #id, .class, [attr], ' ' and '>' combinators)
    into readable XPath: 'div.body > p' → '//div[contains(@class, 'body')]/p'.
    Returns None if there is an unsupported part (the caller can fall back to css_to_xpath)."""
    if not css or not css.strip() or "\\" in css:
        return None
    out = []
    for part in split_selector_list(css):
        # split off the combinators; spaces/'>' inside attribute values are kept
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
    """Convert a BeautifulSoup object or an HTML string into an lxml tree."""
    from lxml import html as lxml_html

    if isinstance(html_or_soup, str):
        return lxml_html.fromstring(html_or_soup)

    # if a BeautifulSoup object was given, parse it again (lxml needs its own tree)
    return lxml_html.fromstring(str(html_or_soup))


def run_css(soup, selector: str) -> list:
    """Run a CSS selector on the BeautifulSoup tree, joining the comma-separated parts."""
    parts = split_selector_list(selector)
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
    """Run XPath on the lxml tree. Returns a list of elements (lxml elements)."""
    try:
        tree = _to_lxml_tree(html_or_soup)
        result = tree.xpath(xpath)
    except Exception:
        return []
    # xpath text()/attribute() queries may return strings — we do not wrap them into elements,
    # the caller (metrics.py) handles them separately.
    return result if isinstance(result, list) else [result]


# ── Regex time limit ──────────────────────────────────────────────────────
# A regex written by an LLM (e.g. with nested .*?) can run into "catastrophic backtracking" and take hours, and re
# cannot be interrupted. The regex therefore runs in a separate process, still with re; if it exceeds the time limit,
# the process is killed, the result counts as empty and the pattern is recorded in regex_timeouts() (per calling thread).
REGEX_TIMEOUT_S = 5.0
_FLAGS = re.IGNORECASE | re.DOTALL
_worker = {"proc": None, "send": None, "recv": None, "text": None}
_worker_lock = threading.Lock()
_local = threading.local()


def _regex_serve():
    """Loop of the helper process: receives (pattern, text | None), sends back the re.findall result."""
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
        if new_text is not None:      # the text is sent only when it changes
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
    if not w["recv"].poll(60):        # interpreter start-up does not count toward the time limit
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
    """Result of re.findall; invalid pattern → []; timeout → None (the process is restarted)."""
    import os
    if os.name != "posix":            # Windows: no time limit
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
        except OSError:               # the process has closed: restart it and try once more
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
    """Patterns that timed out in this thread (reset=True: empties the list and returns its previous content)."""
    out = getattr(_local, "timeouts", [])
    if reset:
        _local.timeouts = []
    return out


def run_regex(html_or_soup, pattern: str) -> list[str]:
    """Run a regex on the raw HTML/text, returning the matching groups/full matches."""
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
            # If there are several groups, take the first non-empty one
            m = next((g for g in m if g), "")
        if m:
            results.append(m)
    return results


def run_rule(html_or_soup, rule: str, rule_type: RuleType) -> list:
    """
    Chooses the appropriate runner by rule type.

    - css   : BeautifulSoup select — returns a list of elements
    - xpath : lxml xpath — returns a list of elements/strings
    - regex : re.findall — returns a list of strings
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
