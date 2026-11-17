"""Make the package importable from a checkout without installing it (src layout), also in subprocesses."""
import os
import sys
from pathlib import Path

SRC = str(Path(__file__).resolve().parent.parent / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)
os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (SRC, os.environ.get("PYTHONPATH")) if p)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_local_ollama(monkeypatch):
    """The tests must not depend on the machine: validate_config asks a local Ollama which models are installed.
    Without this, a machine running Ollama without the default model would fail tests that pass elsewhere."""
    from webrulebench.pipeline import llm_models
    monkeypatch.setattr(llm_models, "model_catalog", lambda *a, **k: {"reachable": False, "models": []})
