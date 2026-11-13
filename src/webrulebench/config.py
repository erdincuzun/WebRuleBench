"""
config.py
=========
Default news fields used by the command-line tools (llm_extractor.py)
when no template is given. The web application and the experiments
take the fields from the template (layout_templates.json).
"""

FIELDS          = ["title", "date", "author", "body", "images", "tags"]
REQUIRED_FIELDS = {"title", "body"}
