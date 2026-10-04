"""
test_i18n.py
============
Arayüz çevirileri: sözlük dosyaları geçerli, yer tutucular iki tarafta aynı,
İngilizce tekil/çoğul kuralı ve eksik çevirinin İngilizceye düşmesi.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from webrulebench.webapp import i18n  # noqa: E402

FILES = sorted((ROOT / "webrulebench" / "webapp" / "i18n").glob("*/*.json"))
PH = re.compile(r"(?<!\{)\{(\w+)\}(?!\})")


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_catalog_is_valid_and_placeholders_match(path):
    cat = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(cat, dict) and cat
    bad = [k for k, v in cat.items() if set(PH.findall(k)) != set(PH.findall(v))]
    assert not bad, f"placeholder mismatch: {bad[:5]}"


def test_missing_translation_falls_back_to_english():
    assert i18n.translate("Some text that is not in any catalog", "tr") == "Some text that is not in any catalog"


@pytest.mark.parametrize("src,params,expected", [
    ("{n} pages", {"n": 1}, "1 page"),
    ("{n} pages", {"n": 2}, "2 pages"),
    ("{n} entries", {"n": 1}, "1 entry"),
    ("{n} matches found", {"n": 1}, "1 match found"),
    ("{n} required fields failed", {"n": 1}, "1 required field failed"),
    ("{n} sites are missing country / language info", {"n": 1}, "1 site is missing country / language info"),
])
def test_english_singular(src, params, expected):
    assert i18n.translate(src, "en", **params) == expected


def test_turkish_translation_used():
    assert i18n.translate("Log out", "tr") == "Çıkış"
