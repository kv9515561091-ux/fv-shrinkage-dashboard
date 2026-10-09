"""Render the dashboard views to PNG for the README.

The workbook itself is the deliverable; these images exist so the README shows
the analysis without requiring a clone. They are generated from the same
`reports/kpi_summary.csv` and `data/processed/*.csv` that feed the PivotTables,
so a picture and the workbook can never drift apart -- re-running the pipeline
re-renders both.

Charts are matplotlib rather than Excel exports on purpose: the pipeline must
run on any machine with Python, whereas the Excel stage needs Excel installed.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
SHOTS = ROOT / "docs" / "screenshots"

INK = "#1F3864"
GREY = "#8A8A8A"
ACCENT = "#C55A11"
GOOD = "#548235"
WARN = "#BF8F00"
BAD = "#C00000"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": "#BFBFBF",
    "axes.labelcolor": "#404040",
    "text.color": "#262626",
    "xtick.color": "#595959",
    "ytick.color": "#595959",
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def finish(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote {path.relative_to(ROOT)}")


def shot_01_dashboard(kpi: pd.Series) -> None:
    fig = plt.figure(figsize=(12, 6.9))
    fig.suptitle("F&V PROCESSING CENTRE -- SHRINKAGE & FEFO DIAGNOSTIC",
                 fontsize=15, fontweight="bold", color=INK, x=0.015, ha="left", y=0.982)
    fig.text(0.015, 0.945, "Simulated operations week 05-11 Oct 2026  |  24 SKUs  |  "
                           "synthetic seeded data", fontsize=9, color=GREY, ha="left")

    cards = [
        ("RECEIVED", f"{kpi.qty_received_kg:,.0f} kg", "#D9E1F2"),
        ("LOSS VALUE", f"Rs {kpi.shrink_value_inr:,.0f}", "#F8CBAD"),
        ("SHRINK %", f"{kpi.shrink_pct_of_received:.2f}%", "#FFE699"),
        ("SELL-THROUGH", f"{kpi.sell_through_pct_of_granted:.2f}%", "#C6E0B4"),
        ("FEFO COMPLIANCE", f"{kpi.fefo_compliance_pct:.2f}%", "#F4B183"),
        ("PRODUCT IN-STOCK", f"{kpi.product_in_stock_pct:.2f}%", "#FFE699"),
        ("RVP (2-DAY WINDOW)", f"Rs {kpi.rvp_total_inr:,.0f}", "#FFE699"),
        ("EXPIRY FROM ROTATION FAILURE", f"{kpi.cf_pct_of_expiry_caused_by_rotation_failure:.1f}%", "#F4B183"),
    ]
    for i, (label, value, fill) in enumerate(cards):
        r, c = divmod(i, 4)
        ax = fig.add_axes([0.015 + c * 0.2455, 0.745 - r * 0.175, 0.228, 0.135])
        ax.set_facecolor(fill)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#FFFFFF")
        ax.text(0.5, 0.66, label, ha="center", va="center",
                fontsize=7.5, color="#404040", transform=ax.transAxes)
        ax.text(0.5, 0.30, value, ha="center", va="center",
                fontsize=14, fontweight="bold", color=INK, transform=ax.transAxes)

    pareto = pd.read_csv(PROC / "shrinkage_pareto.csv")
    pareto = pareto[pareto.shrink_kg > 0]
    ax = fig.add_axes([0.045, 0.095, 0.40, 0.40])
    colors = [ACCENT if c == "SR-EXP" else "#8FAADC" for c in pareto.reason_code]
    labels = [r[:30] for r in pareto.reason_desc]
    ax.barh(labels[::-1], pareto.shrink_value_inr[::-1], color=colors[::-1])
    ax.set_xlabel("Value lost (Rs)", fontsize=9)
    ax.set_title("Shrinkage Pareto by reason code", fontsize=10.5,
                 fontweight="bold", color=INK, loc="left")
    for i, v in enumerate(pareto.shrink_value_inr[::-1]):
        ax.text(v + max(pareto.shrink_value_inr) * 0.02, i, f"Rs {v:,.0f}",
                va="center", fontsize=8, color="#404040")
    ax.set_xlim(0, max(pareto.shrink_value_inr) * 1.28)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=8)

    fefo = pd.read_csv(PROC / "PQ_FEFO_Agg.csv")
    sh = fefo.groupby("shift", as_index=False).agg(
        picks=("picks_count", "sum"), viol=("violations", "sum"),
        gap=("expiry_gap_sum", "sum"))
    sh["compliance"] = 100 * (1 - sh.viol / sh.picks)
    sh["avg_gap"] = sh.gap / sh.viol.replace(0, 1)
    ax2 = fig.add_axes([0.575, 0.095, 0.40, 0.40])
    short = [s.split(" (")[0] for s in sh["shift"]]
    bars = ax2.bar(short, sh.compliance,
                   color=[BAD if v < 65 else WARN if v < 75 else GOOD
                          for v in sh.compliance], width=0.5)
    ax2.axhline(95, color=GREY, ls="--", lw=1)
    ax2.text(2.45, 96.2, "95% target", fontsize=7.5, color=GREY, ha="right")
    for b, v, g in zip(bars, sh.compliance, sh.avg_gap):
        ax2.text(b.get_x() + b.get_width() / 2, v + 1.4,
                 f"{v:.1f}%\n{g:.2f}d skipped", ha="center", fontsize=8, color="#404040")
    ax2.set_ylim(0, 110)
    ax2.set_ylabel("FEFO compliance %", fontsize=9)
    ax2.set_title("FEFO compliance by shift -- night shift is the gap",
                  fontsize=10.5, fontweight="bold", color=INK, loc="left")
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.tick_params(labelsize=8.5)
    finish(fig, SHOTS / "01_dashboard_overview.png")


def shot_02_pareto() -> None:
    pareto = pd.read_csv(PROC / "shrinkage_pareto.csv")
    cat = pd.read_csv(PROC / "PQ_Category_Agg.csv")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.4, 5.0),
                                 gridspec_kw={"width_ratios": [1, 1.15]})
    fig.suptitle("Where the value is lost", fontsize=14, fontweight="bold",
                 color=INK, x=0.02, ha="left", y=0.99)

    p = pareto[pareto.shrink_kg > 0].iloc[::-1]
    cum = p.pct_of_shrink.cumsum()[::-1]
    a1.barh(p.reason_desc.str.slice(0, 36), p.shrink_value_inr,
            color=[ACCENT if c == "SR-EXP" else "#8FAADC" for c in p.reason_code])
    a1.set_xlabel("Value lost (Rs)", fontsize=9)
    a1.set_title("Loss by reason code", fontsize=10.5, fontweight="bold",
                 color=INK, loc="left")
    for i, (v, c) in enumerate(zip(p.shrink_value_inr, p.pct_of_shrink)):
        a1.text(v + max(p.shrink_value_inr) * 0.02, i, f"Rs {v:,.0f}  ({c:.0f}%)",
                va="center", fontsize=8, color="#404040")
    a1.set_xlim(0, max(p.shrink_value_inr) * 1.32)
    a1.spines[["top", "right"]].set_visible(False)
    a1.tick_params(labelsize=8)

    a2b = a2.twinx()
    # Group by category only. The category table's own grain is
    # category x perishability, which would render Fruit and Root Vegetables
    # twice on the x-axis and misread as two separate losses.
    by_cat = (cat.groupby("category", as_index=False)
              .agg(received_value_inr=("received_value_inr", "sum"),
                   qty_received_kg=("qty_received_kg", "sum"),
                   qty_shrunk_kg=("qty_shrunk_kg", "sum"),
                   shrink_exp_kg=("shrink_exp_kg", "sum"),
                   shrink_qlt_kg=("shrink_qlt_kg", "sum"),
                   shrink_hdl_kg=("shrink_hdl_kg", "sum"),
                   shrink_pil_kg=("shrink_pil_kg", "sum"),
                   shrink_tmp_kg=("shrink_tmp_kg", "sum")))
    by_cat["shrink_pct"] = (100 * by_cat.qty_shrunk_kg
                            / by_cat.qty_received_kg).round(2)
    by_cat = by_cat.sort_values("shrink_pct", ascending=False).reset_index(drop=True)

    cols = ["shrink_exp_kg", "shrink_qlt_kg", "shrink_hdl_kg", "shrink_pil_kg", "shrink_tmp_kg"]
    labels = ["Expiry", "Grading reject", "Handling", "Pilferage", "Cold chain"]
    palette = ["#C00000", "#ED7D31", "#FFC000", "#A5A5A5", "#2E75B6"]
    x = np.arange(len(by_cat))
    bottom = np.zeros(len(by_cat))
    for col, lab, colr in zip(cols, labels, palette):
        vals = (by_cat[col] * (by_cat.received_value_inr
                               / by_cat.qty_received_kg)).values
        a2.bar(x, vals, 0.6, bottom=bottom, label=lab, color=colr)
        bottom += vals
    a2.set_xticks(x)
    a2.set_xticklabels(by_cat["category"], rotation=18, ha="right", fontsize=8)
    a2.set_ylabel("Value lost (Rs)", fontsize=9)
    a2.set_title("Loss by category and cause", fontsize=10.5, fontweight="bold",
                 color=INK, loc="left")
    a2.spines[["top"]].set_visible(False)
    a2.tick_params(labelsize=8)
    a2b.set_ylim(0, 100)
    a2b.plot(x, by_cat.shrink_pct, "o-", color=INK, lw=1.6, ms=5)
    for xi, v in zip(x, by_cat.shrink_pct):
        a2b.annotate(f"{v:.1f}%", (xi, v), textcoords="offset points",
                     xytext=(0, 8), ha="center", fontsize=8, color=INK)
    a2b.set_ylabel("Shrink % of received", fontsize=9, color=INK)
    a2b.spines[["top"]].set_visible(False)
    a2b.tick_params(labelsize=8, colors=INK)
    a2.legend(fontsize=7.5, loc="upper right", frameon=False, ncol=2)
    finish(fig, SHOTS / "02_shrinkage_pareto.png")


def shot_03_fefo() -> None:
    picks = pd.read_csv(PROC / "PQ_Picks.csv")
    picks["fefo_compliant"] = picks.fefo_compliant.astype(str).str.upper().eq("TRUE")
    cat = pd.read_csv(PROC / "PQ_Category_Agg.csv")

    fig = plt.figure(figsize=(12.4, 7.4))
    fig.suptitle("FEFO bottleneck -- where rotation fails and what it costs",
                 fontsize=14, fontweight="bold", color=INK, x=0.02, ha="left", y=0.985)

    a1 = fig.add_axes([0.04, 0.60, 0.44, 0.30])
    comp = picks.groupby("perishable_class").fefo_compliant.mean() * 100
    class_labels = {"Highly Perishable": "Highly perish.",
                    "Perishable": "Perishable", "Hardy": "Hardy"}
    order = ["Hardy", "Perishable", "Highly Perishable"]
    comp = comp.reindex([c for c in order if c in comp.index])
    bars = a1.bar([class_labels.get(c, c) for c in comp.index], comp.values,
                  color=[BAD if v < 65 else WARN if v < 80 else GOOD for v in comp.values],
                  width=0.5)
    a1.axhline(95, color=GREY, ls="--", lw=1)
    a1.text(2.4, 96, "95% target", fontsize=7.5, color=GREY, ha="right")
    for b, v in zip(bars, comp.values):
        a1.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.1f}%", ha="center",
                fontsize=8.5, color="#404040")
    a1.set_ylim(0, 108)
    a1.set_ylabel("FEFO compliance %", fontsize=9)
    a1.set_title("Adherence by perishability class", fontsize=10.5, fontweight="bold",
                 color=INK, loc="left")
    a1.spines[["top", "right"]].set_visible(False)
    a1.tick_params(labelsize=8.5)

    a2 = fig.add_axes([0.55, 0.60, 0.42, 0.30])
    viol = picks[~picks.fefo_compliant]
    rules = viol.pick_rule_applied.value_counts()
    rules = rules[~rules.index.isin(["fefo"])]
    a2.barh([r.replace("_", " ") for r in rules.index][::-1], rules.values[::-1],
            color="#C55A11")
    a2.set_xlabel("Violating picks", fontsize=9)
    a2.set_title("Which wrong rule the picker fell back on", fontsize=10.5,
                 fontweight="bold", color=INK, loc="left")
    tot = rules.sum()
    for i, v in enumerate(rules.values[::-1]):
        a2.text(v + tot * 0.015, i, f"{v}  ({100*v/tot:.0f}%)", va="center",
                fontsize=8, color="#404040")
    a2.set_xlim(0, max(rules.values) * 1.3)
    a2.spines[["top", "right"]].set_visible(False)
    a2.tick_params(labelsize=8)

    ax3 = fig.add_axes([0.04, 0.11, 0.30, 0.34])
    cat_agg = pd.read_csv(PROC / "PQ_Category_Agg.csv")
    by_cat = cat_agg.groupby("category", as_index=False).shrink_value_inr.sum()
    top = by_cat.nlargest(6, "shrink_value_inr").iloc[::-1]
    ax3.barh(top["category"], top.shrink_value_inr, color="#8FAADC")
    ax3.set_xlabel("Value lost (Rs)", fontsize=9)
    ax3.set_title("Loss concentration by category", fontsize=10.5,
                  fontweight="bold", color=INK, loc="left")
    for i, v in enumerate(top.shrink_value_inr):
        ax3.text(v + top.shrink_value_inr.max() * 0.02, i, f"Rs {v:,.0f}",
                 va="center", fontsize=7.5, color="#404040")
    ax3.set_xlim(0, top.shrink_value_inr.max() * 1.32)
    ax3.spines[["top", "right"]].set_visible(False)
    ax3.tick_params(labelsize=7.5)

    ax4 = fig.add_axes([0.40, 0.11, 0.27, 0.34])
    sn = picks[picks.category == "Leafy Greens"]
    ax4.hist(sn.expiry_gap_days, bins=18, color="#C55A11", alpha=0.85)
    ax4.set_xlabel("Days of shelf life skipped", fontsize=9)
    ax4.set_ylabel("Violating picks", fontsize=9)
    ax4.set_title("Severity: leafy greens", fontsize=10.5, fontweight="bold",
                  color=INK, loc="left")
    ax4.spines[["top", "right"]].set_visible(False)
    ax4.tick_params(labelsize=8)

    ax5 = fig.add_axes([0.74, 0.11, 0.23, 0.34])
    ax5.axis("off")
    bn = pd.read_csv(PROC / "PQ_SKUBottleneck.csv").head(6)
    ax5.set_title("Top SKUs by value lost", fontsize=10.5, fontweight="bold",
                  color=INK, loc="left")
    y = 0.94
    for r in bn.itertuples(index=False):
        ax5.text(0.0, y, f"{r.sku_name[:28]}", fontsize=8, color=INK,
                 fontweight="bold", transform=ax5.transAxes)
        ax5.text(0.0, y - 0.055,
                 f"Rs {r.shrink_value_inr:,.0f}  |  {r.shrink_pct:.1f}%  |  "
                 f"FEFO {r.fefo_compliance_pct:.0f}%",
                 fontsize=7.5, color="#595959", transform=ax5.transAxes)
        ax5.text(0.0, y - 0.105, str(r.primary_driver), fontsize=7.5,
                 color=ACCENT, transform=ax5.transAxes)
        y -= 0.165
    finish(fig, SHOTS / "03_fefo_bottleneck.png")


def shot_04_counterfactual(kpi: pd.Series) -> None:
    import json
    cf = json.loads((REPORTS / "analysis_findings.json").read_text(encoding="utf-8"))
    k = cf["kpis"]

    obs_exp = float(k["cf_expiry_kg_observed"])
    cf_exp = float(k["cf_expiry_kg_counterfactual"])
    total_exp = obs_exp
    obs_share = obs_exp / total_exp
    cf_share = cf_exp / total_exp
    avoidable = obs_share - cf_share

    fig = plt.figure(figsize=(12.4, 5.8))
    fig.suptitle("Counterfactual: what enforcing FEFO actually buys",
                 fontsize=14, fontweight="bold", color=INK, x=0.015, ha="left", y=0.975)
    fig.text(0.015, 0.925,
             "Same arrivals, same demand, same seed. The only thing that changes is "
             "that every pick is forced to take the earliest-expiry batch.",
             fontsize=9, color=GREY, ha="left")

    a1 = fig.add_axes([0.015, 0.22, 0.30, 0.58])
    a1.pie([avoidable, max(cf_share, 0.0001)],
           labels=["Expiry caused by\nrotation failure",
                   "Expiry regardless\\nof pick order"],
           colors=[ACCENT, "#D9D9D9"], startangle=120,
           autopct=lambda p: f"{p:.1f}%", pctdistance=0.62,
           labeldistance=1.14, textprops={"fontsize": 9},
           wedgeprops={"edgecolor": "white", "linewidth": 1.5})
    a1.set_title(f"{avoidable*100:.0f}% of all expiry is a rotation failure",
                 fontsize=10.5, fontweight="bold", color=INK, pad=6)
    a1.text(0, -1.30,
            f"Expiry {obs_exp:,.0f} kg -> {cf_exp:,.0f} kg\n"
            f"Rs {k['cf_shrink_value_avoided_inr']:,.0f} of avoidable loss in one week",
            ha="center", fontsize=8.5, color="#595959")

    pareto = pd.read_csv(PROC / "counterfactual_pareto.csv")
    p = pareto[pareto.shrink_kg > 0]
    labels = [f"{r.reason_code}  {r.reason_desc[:28]}" for r in p.itertuples()][::-1]
    vals = p.shrink_value_inr[::-1]
    pcts = p.pct_of_shrink[::-1]
    codes = p.reason_code[::-1]
    a2 = fig.add_axes([0.50, 0.24, 0.47, 0.58])
    a2.barh(labels, vals, color=[ACCENT if c == "SR-EXP" else "#8FAADC" for c in codes])
    for i, (v, pc) in enumerate(zip(vals, pcts)):
        a2.text(v + vals.max() * 0.02, i, f"Rs {v:,.0f}  ({pc:.0f}%)",
                va="center", fontsize=8, color="#404040")
    a2.set_xlim(0, vals.max() * 1.34)
    a2.set_xlabel("Value lost (Rs)", fontsize=9)
    a2.set_title("Residual loss once FEFO is enforced -- grading is the next target",
                 fontsize=10.5, fontweight="bold", color=INK, loc="left")
    a2.spines[["top", "right"]].set_visible(False)
    a2.tick_params(labelsize=8)

    fig.text(0.03, 0.045,
             f"Shrink moves {k['shrink_pct_of_received']:.2f}% -> "
             f"{k['cf_counterfactual_shrink_pct_of_received']:.2f}% of received"
             f"     |     published F&V DC benchmark is 2-3%",
             fontsize=9.5, color=INK, fontweight="bold")
    finish(fig, SHOTS / "04_counterfactual.png")


def main() -> None:
    kpi = pd.read_csv(REPORTS / "kpi_summary.csv").iloc[0]
    print("[make_screenshots] rendering dashboard views")
    shot_01_dashboard(kpi)
    shot_02_pareto()
    shot_03_fefo()
    shot_04_counterfactual(kpi)
    print("[make_screenshots] done")


if __name__ == "__main__":
    main()
