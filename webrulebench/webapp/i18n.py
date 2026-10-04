"""
i18n.py
=======
Arayüz dili (İngilizce varsayılan, Türkçe).

Kaynak koddaki metinler İngilizcedir; çeviriler webrulebench/webapp/i18n/<dil>/*.json
dosyalarında {"İngilizce metin": "çeviri"} biçiminde tutulur (dosyalar sayfa
gruplarına göre bölünmüştür, yüklenirken birleştirilir). Sözlükte olmayan metin
İngilizce gösterilir. Yer tutucular {ad} biçimindedir: T("{n} pages", {n: 3}).

Sunucu tarafı: webrulebench/webapp/core.py'deki _t("...") ve Jinja şablonlarındaki {{ T("...") }}.
Tarayıcı tarafı: static/i18n.js'teki T("...") — sözlük /i18n/<dil>.js ile gelir.
Yeni dil: webrulebench/webapp/i18n/<kod>/ klasörü ve LANGS'e kod eklemek yeterlidir.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

LANGS   = ("en", "tr")
DEFAULT = "en"
LOCALES = {"en": "en-GB", "tr": "tr-TR"}
I18N_DIR = Path(__file__).resolve().parent / "i18n"

_lock  = threading.Lock()
_cache: dict = {}          # dil → {"sig": ..., "cat": {...}}


def _signature(lang: str) -> tuple:
    d = I18N_DIR / lang
    return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in d.glob("*.json"))) if d.is_dir() else ()


def catalog(lang: str) -> dict:
    """Dilin birleşik sözlüğü; dosyalar değişince yeniden okunur (debug'da yeniden başlatmadan)."""
    if lang == DEFAULT or lang not in LANGS:
        return {}
    sig = _signature(lang)
    with _lock:
        c = _cache.get(lang)
        if c and c["sig"] == sig:
            return c["cat"]
        cat = {}
        for p in sorted((I18N_DIR / lang).glob("*.json")):
            try:
                cat.update(json.loads(p.read_text(encoding="utf-8")))
            except ValueError as ex:
                print(f"[i18n] {p} okunamadı: {ex}")
        _cache[lang] = {"sig": sig, "cat": cat}
        return cat


def version(lang: str) -> str:
    """Tarayıcı önbelleği için sözlük sürümü."""
    return hashlib.md5(repr(_signature(lang)).encode()).hexdigest()[:10]


_SINGULAR_EXCEPT = {"is", "has", "was", "this", "bus", "gas", "ms", "s"}


def _singular(w: str) -> str:
    lw = w.lower()
    if lw in _SINGULAR_EXCEPT or len(w) < 3:
        return w
    if lw.endswith("ies"):
        return w[:-3] + ("Y" if w[-1].isupper() else "y")
    if re.search(r"(ch|sh|x|ss)es$", lw):
        return w[:-2]
    if lw.endswith("s") and not lw.endswith("ss"):
        return w[:-1]
    return w


def english_plurals(text: str, params: dict) -> str:
    """İngilizce kaynakta yer tutucu 1 ise ardındaki çoğul ismi tekile çevirir:
    "{n} pages" → "1 page", "{n} required fields" → "1 required field", "{n} sites are" → "1 site is".
    Yalnızca kaynak dil (İngilizce) için; çevirilerde dilin kendi biçimi kullanılır.
    static/i18n.js'teki T() aynı kuralı uygular."""
    for k, v in params.items():
        if str(v).strip() != "1":
            continue
        def fix(m):
            w1, sp, w2, sp2, w3 = m.group(1), m.group(2), m.group(3) or "", m.group(4) or "", m.group(5) or ""
            s1 = _singular(w1)
            if s1 != w1:                                   # "{n} pages", "{n} sites are"
                return "{%s} %s%s%s%s%s" % (k, s1, sp, "is" if w2 == "are" else w2, sp2, w3)
            s2 = _singular(w2) if w2 else w2               # "{n} required fields"
            if s2 != w2:
                return "{%s} %s%s%s%s%s" % (k, w1, sp, s2, sp2, "is" if w3 == "are" else w3)
            return m.group(0)
        text = re.sub(r"\{" + re.escape(k) + r"\} ([A-Za-z-]+)(\s*)([A-Za-z-]+)?(\s*)([A-Za-z]+)?", fix, text, count=1)
    return text


def translate(text: str, lang: str, **params) -> str:
    cat = catalog(lang)
    s = cat.get(text, text)
    if params and s is text:                      # çeviri yoksa İngilizce kaynak
        s = english_plurals(s, params)
    if params:
        try:
            s = s.format(**params)
        except (KeyError, IndexError, ValueError):
            pass
    return s


def norm(lang: str | None) -> str:
    return lang if lang in LANGS else DEFAULT
