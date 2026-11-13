"""
regex_generator.py
==================
CSS selector → regular expression generator.

Uzun, E. (2020). "A regular expression generator based on CSS selectors for
efficient extraction from HTML pages". Turkish Journal of Electrical
Engineering & Computer Sciences 28(6): 3389-3401. doi:10.3906/elk-2004-67
(REGEXN): an extended version of that approach, written from scratch.

Extensions over REGEXN
---------------------------
1. The opening tag is independent of attribute order: every condition (id, class token,
   [attr] operators) is a separate lookahead; a class is matched as a whole token
   (".content1" does not match "content10").
2. Three strategies for the closing tag (counterparts of Algorithm 1 / 2-3, plus one more):
     simple    — ( .*? )</tag>                       (REGEXN step 1)
     balanced  — depth-limited nesting of the same tag (independent of the sample page)
     anchored  — end anchor made of the tag sequence after the closing tag
                 (REGEXN steps 2-3; only tags are used, not text,
                 so that it generalizes to the other pages of the same layout)
3. Combinators (space, >): the target compound is tried alone or with its ancestor context
   ("A .*? B").
4. For image / url fields the src / href value is captured instead of the content.
5. Comma-separated alternatives are joined with "|".
6. The candidate is chosen not on a single sample page but by comparison with CSS on all the
   given pages (see generate()).

Not supported (returns None): pseudo-classes (:first-child…), sibling
combinators (+, ~), CSS escapes (\\:), content of void tags.

Usage:
    from webrulebench.rules.regex_generator import generate
    r = generate("div.article-body", pages=[html1, html2], kind="text")
    r["regex"], r["strategy"], r["passed"], r["total"]
"""

import html as _html
import re

from webrulebench.rules.rule_utils import run_regex, split_selector_list

# CSS escapes are part of the identifier too: Tailwind ".text-\[40px\]", ".sm\:flex"
_IDENT = re.compile(r"-?(?:[A-Za-z_]|\\.)(?:[\w-]|\\.)*")
_UNESC = re.compile(r"\\(.)")
_ATTR  = re.compile(r"\[\s*([\w:-]+)\s*(?:([*^$~|]?=)\s*(\"[^\"]*\"|'[^']*'|[^\]\s]+)\s*)?\]")
_VOID  = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_FLAGS = re.IGNORECASE | re.DOTALL
BALANCE_DEPTH = 10

# field type → capture form
KIND_OF_TYPE = {"image": "image", "url": "url"}


# ---------------------------------------------------------------------------
# Text normalization (the regex result is inner HTML; it is converted to text for comparison)
# ---------------------------------------------------------------------------
_SCRIPT_RE = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>|<!--.*?-->", _FLAGS)
_TAG_RE    = re.compile(r"<[^>]+>")


def html_to_text(s: str) -> str:
    """Inner HTML → plain text: script/style and tags are removed, entities are decoded, whitespace is collapsed."""
    if not s:
        return ""
    s = _SCRIPT_RE.sub(" ", s)
    s = _TAG_RE.sub(" ", s)
    return " ".join(_html.unescape(s).split())


# ---------------------------------------------------------------------------
# CSS parsing
# ---------------------------------------------------------------------------
def _parse_compound(comp: str) -> dict | None:
    """'div#a.b.c[x="y"]' → {tag, id, classes, attrs}. Unsupported syntax → None."""
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
    """'div.a > p b' → [compound, compound, compound] (the combinator type does not matter in the regex)."""
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
# Regex pieces
# ---------------------------------------------------------------------------
_VALUE_END = r"""(?=["'\s/>])"""
# Inside a tag: quoted attribute values are skipped as a whole (a value may contain '>':
# title="a <b>b</b>"); so searches such as \sclass= do not match inside another value.
_ATTRS = r"""(?:[^>"']|"[^"]*"|'[^']*')*?"""


def _token_look(attr: str, token: str) -> str:
    # attr="... token ..." — at the start of the value or after a space, followed by space/quote/>
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
    """Opening tag; if capture_attr is given, the value of that attribute is captured (src/href)."""
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
    """Content pattern that balances nesting of the same tag up to `depth` levels (no capturing group)."""
    inner = rf"(?:[^<]|<(?!/?{tag}[\s/>]))*"
    for _ in range(depth):
        inner = rf"(?:[^<]|<(?!/?{tag}[\s/>])|<{tag}(?:[\s/][^>]*)?>{inner}</{tag}\s*>)*"
    return inner


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------
def _structural_suffix(html: str, pos: int, n_tags: int) -> str | None:
    """End anchor containing the first n tags after pos ([^<]* instead of text)."""
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
    """Counterpart of Algorithm 2: the real closing-tag ends of the open_re matches (counting nesting)."""
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
    """Compound without a tag ("#id", ".x"): the real tag of the first match on the sample page is used."""
    if c["tag"] != "*" or not example_html:
        return c
    m = re.search(_open_tag(c), example_html, _FLAGS)
    return {**c, "tag": re.match(r"<([a-zA-Z][\w:-]*)", m.group()).group(1).lower()} if m else c


def _candidates_for_alt(chain: list, kind: str, example_html: str | None, containers: bool = True) -> list:
    """(strategy, regex) candidates for one comma alternative, from simple to complex."""
    chain  = [_resolve_tag(c, example_html) for c in chain]
    target = chain[-1]
    tag    = target["tag"]
    # ancestor context: after each ancestor, advance without passing that ancestor's closing tag (tempered token)
    # → "h2.title a" does not capture the first link after the h2 if there is no link inside the h2.
    # The regex also consumes the outer ancestor on each match (one result per ancestor); for multi-valued
    # fields, add ancestors step by step starting from the nearest: "li a" → "ul li a".
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
    # text field, children without attributes ("ul.breadcrumbs li"): a regex cannot count all children in the
    # container separately — since the joined text is compared, the content of the container gives the same result
    # Every upper level is tried ("ul.x li a" → "ul.x li", "ul.x").
    if containers and kind == "text" and len(chain) > 1:
        for depth in range(len(chain) - 1, 0, -1):
            sub = [(s, rx) for s, rx in _candidates_for_alt(chain[:depth], kind, example_html, containers=False)]
            out += [(f"container{len(chain) - depth}:{s}", rx) for s, rx in sub]
    return out


def candidates(css: str, kind: str = "text", example_html: str | None = None) -> list:
    """CSS selector → [(strategy, regex)] candidates. [] for an unsupported selector."""
    alts = split_selector_list(css or "")
    chains = [_parse_chain(a) for a in alts]
    if not chains or not all(chains):
        return []
    per_alt = [_candidates_for_alt(ch, kind, example_html) for ch in chains]
    if not all(per_alt):
        return []
    if len(per_alt) == 1:
        return per_alt[0]
    # alternatives: apply the same strategy to all alternatives, join with "|" (counterpart of merge=True)
    out = []
    for strat, _ in per_alt[0]:
        picked = [dict(c).get(strat) for c in per_alt]
        if all(picked):
            out.append((strat, "|".join(f"(?:{p})" for p in picked)))
    # with merge=False, CSS uses only the first matching alternative; a regex cannot express this →
    # also try the alternatives alone (validated if the same alternative always matches on the pages)
    for i, cands in enumerate(per_alt, 1):
        out += [(f"{strat} (alt{i})", rx) for strat, rx in cands]
    return out


# ---------------------------------------------------------------------------
# Validation and selection
# ---------------------------------------------------------------------------
def regex_values(html: str, pattern: str, kind: str = "text") -> list:
    """Run the regex and return comparable values: text field → plain text, image/url → attribute."""
    vals = run_regex(html, pattern)
    if kind in ("image", "url"):
        return [_html.unescape(v).strip() for v in vals if v.strip()]
    return [t for t in (html_to_text(v) for v in vals) if t]


def _norm(vals: list, kind: str = "text"):
    """Comparison key. Text fields are scored as joined text in the evaluation
    (metrics._collect_text_generic) → whitespace-independent joined text; image/url → ordered list."""
    if kind in ("image", "url"):
        return sorted("".join(v.split()) for v in vals)
    return "".join("".join(vals).split())


def generate(css: str, pages: list, expected: list, kind: str = "text") -> dict | None:
    """Among the candidates, choose the regex that gives the same values as CSS on the most pages.

    pages    : list of raw HTML (the first is the sample page — 'anchored' candidates are derived from it)
    expected : the values extracted by CSS for each page (same order; text or a list of src/href)
    Returns  : {regex, strategy, passed, total, tried}, or None if there is no candidate.
    On a tie the simpler strategy / shorter regex is preferred.
    """
    cands = candidates(css, kind, pages[0] if pages else None)
    if not cands:
        return None
    exp_norm = [_norm(e, kind) for e in expected]

    def similarity(html, exp_vals):
        # if there is no exact match, which candidate is closer: text → word F1, list → Jaccard
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
                    break      # this candidate can no longer beat the best
        sim = 0.0
        if passed < len(pages) and (best is None or passed >= best[3]):
            sim = sum(similarity(h, e) for h, e in zip(pages, expected))
        key = (passed, round(sim, 4), -rank, -len(rx))
        if best is None or key > best[0]:
            best = (key, strat, rx, passed)
        if passed == len(pages):
            break      # ordered from simple to complex: the first fully successful candidate is enough
    if best is None:
        return None
    _, strat, rx, passed = best
    return {"regex": rx, "strategy": strat, "passed": passed, "total": len(pages), "tried": len(cands)}


def css_values(html_or_soup, css: str, kind: str = "text", merge: bool = False) -> list:
    """Comparable values extracted by CSS (same merge rule as annotator._run_selector:
    merge=False → the first matching comma alternative, True → the union of all)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_or_soup, "html.parser") if isinstance(html_or_soup, str) else html_or_soup
    els, seen = [], set()
    for part in split_selector_list(css):
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
    # same normalization as on the regex side: script/style/noscript text and comments excluded
    return [t for t in (html_to_text(str(el)) for el in els) if t]
