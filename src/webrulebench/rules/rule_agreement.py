"""
rule_agreement.py
=================
Annotatörler arası kural uyumu (GT Onayı · Katman 1, raporlar).

- normalize_rule(): kuralı, anlamı değiştirmeyen yazım farklarından arındırır
  (CSS: boşluklar, birleştirici etrafındaki boşluk, bileşik seçicide id/sınıf/öznitelik
  sırası, öznitelik tırnakları, etiket harf büyüklüğü, virgüllü alternatiflerin sırası).
  Anlamı değiştirebilecek farklar (ör. `a > b` ile `a b`, `h1` ile `h1.title`) korunur —
  bunlar içerik düzeyinde (Katman 2) değerlendirilir.
- observed_agreement(): tek layout × alan için gözlenen ikili uyum P_o (aynı kuralı
  yazan annotatör çiftlerinin oranı). Kural yazan annotatör sayısı 2'den azsa None.
- fleiss_kappa(): bir alan için layout'lar konu, annotatörler puanlayıcı, normalize
  kurallar kategori olarak Fleiss κ (konu başına puanlayıcı sayısı değişebilir).
  Tek konulu κ tanımsızdır (şans uyumu tek konudan kestirilemez); bu yüzden layout
  düzeyinde P_o, veri seti düzeyinde κ raporlanır.

static/compile.js'teki _normalizeRule / _observedAgreement birebir aynı kuralları uygular.
"""

from __future__ import annotations

import re

_ATTR_RE = re.compile(r'''\[\s*([^\s~|^$*=\]]+)\s*(?:([~|^$*]?=)\s*(?:"([^"]*)"|'([^']*)'|([^\s\]]+))\s*(i|s)?\s*)?\]''')
_PART_RE = re.compile(r'''#[\w-]+|\.[\w-]+|\[[^\]]*\]|::?[\w-]+(?:\([^)]*\))?''')
_TAG_RE  = re.compile(r'^(\*|[a-zA-Z][\w-]*)')


def _split_top(s: str, seps: str) -> list:
    """Köşeli parantez, normal parantez ve tırnak dışındaki ayırıcılardan böl (ayırıcılar korunur)."""
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
        return None                                       # çözümlenemedi → normalize etme
    ids     = [p for p in parts if p.startswith("#")]
    classes = sorted(p for p in parts if p.startswith("."))
    attrs   = sorted(_norm_attr(p) for p in parts if p.startswith("["))
    pseudos = [p for p in parts if p.startswith(":")]
    if tag == "*" and (ids or classes or attrs or pseudos):
        tag = ""
    return tag + "".join(ids) + "".join(classes) + "".join(attrs) + "".join(pseudos)


def _norm_css_one(sel: str) -> str:
    orig = re.sub(r"\s+", " ", sel.strip())
    # birleştiricilerin etrafındaki boşluk (yalnızca üst düzeyde; [href~="x"] gibi değerler bozulmaz)
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


def normalize_rule(rule, lang: str = "css") -> str | None:
    if not isinstance(rule, str) or not rule.strip():
        return None
    if lang != "css":
        return rule.strip()
    alts = [a for a in _split_top(rule, ",") if a != ","]
    alts = [_norm_css_one(a) for a in alts if a.strip()]
    return ", ".join(sorted(alts)) if alts else None


def observed_agreement(ratings: list) -> float | None:
    """Boş olmayan puanlar arasında aynı kuralı yazan çiftlerin oranı (P_o)."""
    r = [x for x in ratings if x]
    n = len(r)
    if n < 2:
        return None
    pairs = n * (n - 1) / 2
    agree = sum(1 for i in range(n) for j in range(i + 1, n) if r[i] == r[j])
    return agree / pairs


def fleiss_kappa(subjects: list) -> dict | None:
    """subjects: her konu (layout) için puan listesi. Boşlar atılır, 2'den az puanlı konu dışlanır.
    Döner: {kappa, po, pe, n_subjects} ya da None; tek konuda kappa None (yalnızca po anlamlıdır)."""
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
    # tek konuda şans uyumu o konunun kendisinden kestirilir → κ ≤ 0'a zorlanır; tanımsız say
    kappa = None if len(subs) < 2 else 1.0 if pe >= 1 else (po - pe) / (1 - pe)
    return {"kappa": kappa, "po": po, "pe": pe, "n_subjects": len(subs)}


def krippendorff_alpha(units: list, dist, max_pairs: int = 20000, seed: int = 0) -> dict | None:
    """İçerik düzeyinde uyum: Krippendorff α = 1 − D_o / D_e.

    units: her birim (layout × sayfa × alan) için annotatörlerin değerleri; değeri olmayan
           (kuralı yazılmamış) annotatör listeye konmaz — kural yazılmış ama sayfada bir şey
           bulamamışsa değer boş liste olarak girer.
    dist:  iki değer arasındaki uzaklık (0 = aynı, 1 = tamamen farklı), ör. 1 − ROUGE-1 F1.
    D_o:   birim içi çiftlerin ortalama uzaklığı (2'den az değerli birimler dışlanır).
    D_e:   bütün birimlerdeki değerlerden rastgele çekilen çiftlerin (farklı birimlerden de)
           ortalama uzaklığı; değer sayısı büyük olduğunda max_pairs çiftle kestirilir.
    """
    import random
    units = [u for u in units if len(u) >= 2]
    if not units:
        return None
    within, w = 0.0, 0.0
    for u in units:
        m = len(u)
        s = sum(dist(u[i], u[j]) for i in range(m) for j in range(i + 1, m))
        within += 2 * s / (m - 1)          # Krippendorff ağırlığı: birim içi çiftler 1/(m_u − 1)
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
