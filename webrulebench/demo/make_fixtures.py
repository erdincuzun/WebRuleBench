"""
webrulebench/demo/make_fixtures.py — test fixture'larını sentetik demo sayfalarından üretir
(telifsiz; gerçek haber sitelerinin HTML'i depoda yeniden dağıtılmaz).

    python -m webrulebench.demo.make_fixtures        # tests/fixtures/<domain>/{article_001.html, ground_truth.json}
"""
import json
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
from webrulebench.demo.generate_pages import generate                      # noqa: E402
from webrulebench.demo.setup_demo import HARBOR_A, PULSE_A, NORTE_A        # noqa: E402

RULES = {"harborherald.example": HARBOR_A, "pulsedaily.example": PULSE_A, "noticiasdelnorte.example": NORTE_A}


def main():
    out = HERE.parents[1] / "tests" / "fixtures"
    with tempfile.TemporaryDirectory() as tmp:
        generate(Path(tmp))
        if out.exists():
            shutil.rmtree(out)
        for dom, rules in RULES.items():
            (out / dom).mkdir(parents=True)
            shutil.copy(Path(tmp) / dom / "article_001.html", out / dom / "article_001.html")
            (out / dom / "ground_truth.json").write_text(json.dumps(
                {"domain": dom, "file": "article_001.html", "page_type": "article", "selectors": rules},
                ensure_ascii=False, indent=2), encoding="utf-8")
    print("fixtures:", ", ".join(RULES))


if __name__ == "__main__":
    main()
