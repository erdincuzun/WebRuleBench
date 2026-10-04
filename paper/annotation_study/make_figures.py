"""
make_figures.py — annotatör uyumu çalışmasının şekli ve tablosu
===============================================================
results/agreement.json'dan (analyze.py) üretir:
  results/fig_agreement.pdf / .png  — alan başına kural κ ile içerik α (dumbbell)
  results/table_agreement.tex       — booktabs tablo (makale)

Kullanım:  python paper/annotation_study/make_figures.py [--min-layouts 3]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
RULE, CONTENT = "#eb6834", "#2a78d6"          # doğrulanmış 2'li palet (CVD ΔE 24.7)
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-layouts", type=int, default=3, help="şekle girmek için en az layout sayısı")
    args = ap.parse_args()
    res = json.loads((OUT / "agreement.json").read_text(encoding="utf-8"))
    rows = [r for r in res["per_field"] if r["rule_kappa"] is not None and r["content_alpha"] is not None]
    fig_rows = sorted([r for r in rows if r["layouts"] >= args.min_layouts], key=lambda r: r["content_alpha"])

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": MUTED,
                         "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": INK})
    fig, ax = plt.subplots(figsize=(5.2, 0.34 * len(fig_rows) + 0.9), dpi=200)
    for i, r in enumerate(fig_rows):
        ax.plot([r["rule_kappa"], r["content_alpha"]], [i, i], color=GRID, lw=2, zorder=1, solid_capstyle="round")
    ys = range(len(fig_rows))
    ax.scatter([r["rule_kappa"] for r in fig_rows], ys, s=42, marker="s", color=RULE, edgecolor="white",
               linewidth=1.5, zorder=3, label="Rule level (Fleiss κ, normalized CSS)")
    ax.scatter([r["content_alpha"] for r in fig_rows], ys, s=48, marker="o", color=CONTENT, edgecolor="white",
               linewidth=1.5, zorder=3, label="Content level (Krippendorff α)")
    for i, r in enumerate(fig_rows):          # içerik değeri doğrudan etiketli
        ax.text(r["content_alpha"] + 0.03, i, f"{r['content_alpha']:.2f}", va="center", fontsize=7.5, color=MUTED)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([f"{r['field']}  (n={r['layouts']})" for r in fig_rows], family="DejaVu Sans Mono", fontsize=8)
    ax.axvline(0, color=MUTED, lw=0.8, zorder=0)
    ax.set_xlim(min(-0.1, min(r["rule_kappa"] for r in fig_rows) - 0.08), 1.12)
    ax.set_xlabel("Agreement")
    ax.grid(axis="x", color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(loc="lower center", bbox_to_anchor=(0.45, 1.0), ncol=2, frameon=False, fontsize=7.5,
              handletextpad=0.3, columnspacing=1.2)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(OUT / f"fig_agreement.{ext}", bbox_inches="tight")

    # booktabs tablo (en iyi = sütundaki en yüksek; tablo bütün alanları içerir)
    tab = sorted(rows, key=lambda r: -r["content_alpha"])
    lines = [r"% \usepackage{booktabs}", r"\begin{table}[t]", r"  \centering", r"  \small",
             r"  \caption{Inter-annotator agreement on " + str(len(res['sample']['sites'])) + r" layouts ("
             + str(len(res["annotators"])) + r" annotators). Rule level: Fleiss' $\kappa$ over layouts on normalized CSS rules and the "
             r"share of identical rules; content level: Krippendorff's $\alpha$ on the values each annotator's rule extracts from all "
             r"ground-truth pages (distance $= 1 -$ field metric).}",
             r"  \label{tab:agreement}", r"  \begin{tabular}{llrrrr}", r"    \toprule",
             r"    Field & Metric & Layouts & Rule $\kappa$ & Identical rules & Content $\alpha$ \\", r"    \midrule"]
    for r in tab:
        f = r["field"].replace("_", r"\_")
        lines.append(f"    \\texttt{{{f}}} & {r['metric'].replace('_', ' ')} & {r['layouts']} & {r['rule_kappa']:.2f} & "
                     f"{100 * r['rule_exact_share']:.0f}\\% & {r['content_alpha']:.2f} \\\\")
    lines += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}"]
    (OUT / "table_agreement.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("written:", *(p.name for p in sorted(OUT.glob("fig_agreement.*"))), "table_agreement.tex")


if __name__ == "__main__":
    main()
