"""
config.py
=========
Komut satırı araçlarının (llm_extractor.py)
şablon verilmediğinde kullandığı varsayılan haber alanları. Web uygulaması ve deneyler
alanları şablondan (layout_templates.json) alır.
"""

FIELDS          = ["title", "date", "author", "body", "images", "tags"]
REQUIRED_FIELDS = {"title", "body"}
