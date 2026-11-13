"""
rule_agreement.py
=================
Rule agreement between annotators (GT Approval · Layer 1, reports).

- normalize_rule(): strips a rule of writing differences that do not change its meaning
  (CSS: whitespace, whitespace around combinators, order of id/class/attribute in a compound
  selector, attribute quotes, tag letter case, order of comma-separated alternatives).
  Differences that may change the meaning (e.g. `a > b` vs `a b`, `h1` vs `h1.title`) are kept —
  these are evaluated at the content level (Layer 2).
- observed_agreement(): observed pairwise agreement P_o for a single layout × field (share of
  annotator pairs that wrote the same rule). None if fewer than 2 annotators wrote a rule.
- fleiss_kappa(): Fleiss κ for a field, with layouts as subjects, annotators as raters and normalized
  rules as categories (the number of raters per subject may vary).
  κ is undefined with a single subject (chance agreement cannot be estimated from one subject); therefore
  P_o is reported at the layout level and κ at the dataset level.

_normalizeRule / _observedAgreement in static/compile.js apply exactly the same rules.
"""

from __future__ import annotations

import re

_ATTR_RE = re.compile(r'''\[\s*([^\s~|^$*=\]]+)\s*(?:([~|^$*]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\s\]]+))\s*(i|s)?\s*)?\]''')
_PART_RE = re.compile(r'''#[\w-]+|\.[\w-]+|\[[^\]]*\]|::?[\w-]+(?:\([^)]*\))?''')
_TAG_RE  = re.compile(r'^(\*|[a-zA-Z][\w-]*)')


def _split_top(s: str, seps: str) -> list:
    """Split at separators outside square brackets, parentheses and quotes (separators are kept)."""
    out, cur, depth, quote = [], "", 0, ""
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = ""
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and ch in seps:
            out.append(cur)
            out.append(ch)
            cur = ""
            continue
        cur += ch
    out.append(cur)
    return out


def _norm_attr(a: str) -> str:
    m = _ATTR_RE.fullmatch(a)
    if not m:
        return a
    name, op, v1, v2, v3, flag = m.groups()
    if not op:
        return f"[{name.lower()}]"
    val = v1 if v1 is not None else v2 if v2 is not None else v3
    return f'[{name.lower()}{op}"{val}"' + (f" {flag}" if flag else "") + "]"


def _norm_compound(c: str) -> str | None:
    m = _TAG_RE.match(c)
    tag = m.group(1).lower() if m else ""
    rest = c[len(m.group(1)):] if m else c
    parts = _PART_RE.findall(rest)
    if "".join(parts) != rest:
        return None                                       # could not be parsed → do not normalize
    ids     = [p for p in parts if p.startswith("#")]
    classes = sorted(p for p in parts if p.startswith("."))
    attrs   = sorted(_norm_attr(p) for p in parts if p.startswith("["))
    pseudos = [p for p in parts if p.startswith(":")]
    if tag == "*" and (ids or classes or attrs or pseudos):
        tag = ""
    return tag + "".join(ids) + "".join(classes) + "".join(attrs) + "".join(pseudos)


def _norm_css_one(sel: str) -> str:
    orig = re.sub(r"\s+", " ", sel.strip())
    # whitespace around combinators (top level only; values such as [href~="x"] are not broken)
    s = re.sub(r"\s+", " ", "".join(f" {t} " if t in (">", "+", "~") else t
                                      for t in _split_top(orig, ">+~"))).strip()
    out = []
    for t in _split_top(s, " "):
        if t == " " or not t:
            continue
        if t in (">", "+", "~"):
            out.append(t)
            continue
        n = _norm_compound(t)
        if n is None:
            return orig
        out.append(n)
    return " ".join(out)


def normalize_rule(rule, lang: str = "css", merge: bool = False) -> str | None:
    """Rule without the writing differences that do not change what it extracts.

    The order of the comma-separated alternatives of a CSS rule is kept unless the field is merged:
    without merging, the first alternative that matches is used, so 'h1, h2' and 'h2, h1' can extract
    different text and are different rules. With merge=True all alternatives are combined, the order
    does not change the extracted set, and the alternatives are sorted.
    """
    if not isinstance(rule, str) or not rule.strip():
        return None
    if lang != "css":
        return rule.strip()
    alts = [a for a in _split_top(rule, ",") if a != ","]
    alts = [_norm_css_one(a) for a in alts if a.strip()]
    if merge:
        alts = sorted(alts)
    return ", ".join(alts) if alts else None


def observed_agreement(ratings: list) -> float | None:
    """Share of pairs that wrote the same rule among the non-empty ratings (P_o)."""
    r = [x for x in ratings if x]
    n = len(r)
    if n < 2:
        return None
    pairs = n * (n - 1) / 2
    agree = sum(1 for i in range(n) for j in range(i + 1, n) if r[i] == r[j])
    return agree / pairs


def fleiss_kappa(subjects: list) -> dict | None:
    """subjects: list of ratings per subject (layout). Empty ones are dropped; subjects with < 2 ratings are excluded.
    Returns: {kappa, po, pe, n_subjects} or None; with a single subject kappa is None (only po is meaningful)."""
    subs = [[x for x in s if x] for s in subjects]
    subs = [s for s in subs if len(s) >= 2]
    if not subs:
        return None
    totals, p_i, n_total = {}, [], 0
    for s in subs:
        counts = {}
        for x in s:
            counts[x] = counts.get(x, 0) + 1
        n = len(s)
        p_i.append((sum(c * c for c in counts.values()) - n) / (n * (n - 1)))
        for k, c in counts.items():
            totals[k] = totals.get(k, 0) + c
        n_total += n
    po = sum(p_i) / len(p_i)
    pe = sum((c / n_total) ** 2 for c in totals.values())
    # with one subject, chance agreement is estimated from that subject itself → κ is forced to ≤ 0; treat as undefined
    kappa = None if len(subs) < 2 else 1.0 if pe >= 1 else (po - pe) / (1 - pe)
    return {"kappa": kappa, "po": po, "pe": pe, "n_subjects": len(subs)}


def krippendorff_alpha(units: list, dist, max_pairs: int = 20000, seed: int = 0) -> dict | None:
    """Content-level agreement: Krippendorff α = 1 − D_o / D_e.

    units: the annotators' values for each unit (layout × page × field); an annotator without a value
           (no rule written) is not put in the list — if a rule was written but found nothing on the
           page, the value enters as an empty list.
    dist:  distance between two values (0 = identical, 1 = completely different), e.g. 1 − ROUGE-1 F1.
    D_o:   mean distance of the within-unit pairs (units with fewer than 2 values are excluded).
    D_e:   mean distance of pairs drawn at random from the values in all units (also across units);
           estimated with max_pairs pairs when the number of values is large.
    """
    import random
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None
    within, w = 0.0, 0.0
    for u in units:
        m = len(u)
        s = sum(dist(u[i], u[j]) for i in range(m) for j in range(i + 1, m))
        within += 2 * s / (m - 1)          # Krippendorff weight: within-unit pairs 1/(m_u − 1)
        w += m
    d_o = within / w
    pool = [v for u in units for v in u]
    n = len(pool)
    rng = random.Random(seed)
    if n * (n - 1) // 2 <= max_pairs:
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    else:
        pairs = [tuple(rng.sample(range(n), 2)) for _ in range(max_pairs)]
    d_e = sum(dist(pool[i], pool[j]) for i, j in pairs) / len(pairs)
    alpha = 1.0 if d_e == 0 else 1 - d_o / d_e
    return {"alpha": alpha, "d_o": d_o, "d_e": d_e, "units": len(units), "values": n}
