"""
test_skeleton.py
=================
Skeleton çıkarımının (html_cleaner sonrası) örnek sayfalarda çökmeden
çalıştığını ve temel yapısal beklentileri (metin/script/style kalmaması,
boyut küçültme) karşıladığını doğrular.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from webrulebench.pipeline.html_cleaner import HTMLCleaner, CleanerConfig
from webrulebench.pipeline.skeleton import Skeleton

FIXTURES_DIR = Path(__file__).parent / "fixtures"
FIXTURE_DOMAINS = ["harborherald.example", "pulsedaily.example", "noticiasdelnorte.example"]   # sentetik (demo/make_fixtures.py)


def _load_html(domain: str) -> str:
    return (FIXTURES_DIR / domain / "article_001.html").read_text(encoding="utf-8", errors="ignore")


@pytest.mark.parametrize("domain", FIXTURE_DOMAINS)
def test_skeleton_shrinks_and_strips_text(domain):
    html = _load_html(domain)
    cleaned = HTMLCleaner(CleanerConfig()).clean(html, strategy="whitelist").cleaned_html

    sk = Skeleton(strategy="whitelist")
    result = sk.extract(cleaned)

    assert result.output_chars > 0
    assert result.output_chars < result.input_chars
    assert "<script" not in result.skeleton_html
    assert "<style" not in result.skeleton_html


@pytest.mark.parametrize("domain", FIXTURE_DOMAINS)
def test_skeleton_keeps_only_class_id_and_known_data_attrs(domain):
    """Skeleton çıktısında src/href/style gibi orijinal-veri taşıyan attribute'lar olmamalı."""
    html = _load_html(domain)
    cleaned = HTMLCleaner(CleanerConfig()).clean(html, strategy="whitelist").cleaned_html
    result = Skeleton(strategy="whitelist").extract(cleaned)

    for forbidden in (' href="', ' src="', ' style="', ' onclick="'):
        assert forbidden not in result.skeleton_html


def test_meaningful_segment_keeps_readable_class_names():
    sk = Skeleton()
    assert sk._is_meaningful_segment("article") is True
    assert sk._is_meaningful_segment("wrapper") is True


def test_meaningful_segment_drops_hash_like_tokens():
    sk = Skeleton()
    # Kısa, rakam içeren, düşük ünlü yoğunluklu — CSS-in-JS hash imzası
    assert sk._is_meaningful_segment("wsquJ") is False
    assert sk._is_meaningful_segment("8ytrv8") is False
