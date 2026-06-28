#!/usr/bin/env python3
"""
Generate a PDF report comparing every candidate strategy against the sway
baseline. Reads cache/results.pkl produced by backtest_harness.py.

Output: strategies/STRATEGY_REPORT.pdf
"""

import os
import pickle

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)

_DIR = os.path.dirname(os.path.abspath(__file__))
REMAINING_TIMES = [60, 30, 20, 15, 10]
BASELINE = "Sway (baseline)"


def load():
    with open(os.path.join(_DIR, "cache", "results.pkl"), "rb") as f:
        return pickle.load(f)


# ----------------------------------------------------------------------
# Charts
# ----------------------------------------------------------------------

def chart_accuracy_brier(results, meta, path):
    names = list(results.keys())
    accs = [results[n]["overall"]["accuracy"] for n in names]
    briers = [results[n]["overall"]["brier"] for n in names]
    order = np.argsort(accs)
    names = [names[i] for i in order]
    accs = [accs[i] for i in order]
    briers = [briers[i] for i in order]
    colors_b = ["#d62728" if n == BASELINE else "#1f77b4" for n in names]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))
    ax1.barh(names, accs, color=colors_b)
    ax1.axvline(meta["base_rate_up"] if meta["base_rate_up"] > 0.5 else 1 - meta["base_rate_up"],
                color="gray", ls="--", lw=1, label="majority-class")
    ax1.set_xlim(0.45, max(accs) + 0.03)
    ax1.set_title("Overall Directional Accuracy")
    ax1.set_xlabel("accuracy")
    for i, v in enumerate(accs):
        ax1.text(v + 0.002, i, f"{v:.1%}", va="center", fontsize=8)
    ax1.legend(fontsize=8)

    ax2.barh(names, briers, color=colors_b)
    ax2.set_title("Overall Brier Score (lower = better)")
    ax2.set_xlabel("brier")
    for i, v in enumerate(briers):
        ax2.text(v + 0.0005, i, f"{v:.4f}", va="center", fontsize=8)
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_pnl(results, path):
    names = list(results.keys())
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

    # equity curves
    for n in names:
        eq = results[n]["trading"]["equity_curve"]
        if eq:
            ax1.plot(eq, label=f"{n} (${eq[-1]:+.0f})",
                     lw=2 if n == BASELINE else 1.3,
                     ls="--" if n == BASELINE else "-")
    ax1.axhline(0, color="gray", lw=0.8)
    ax1.set_title("Cumulative Trading P&L (equity curve)")
    ax1.set_xlabel("bet #")
    ax1.set_ylabel("cumulative profit ($)")
    ax1.legend(fontsize=7, loc="upper left")

    # ROI bar
    rois = [results[n]["trading"]["roi"] for n in names]
    order = np.argsort(rois)
    nn = [names[i] for i in order]
    rr = [rois[i] for i in order]
    cb = ["#d62728" if n == BASELINE else ("#2ca02c" if rois[names.index(n)] > 0 else "#ff7f0e") for n in nn]
    ax2.barh(nn, rr, color=cb)
    ax2.axvline(0, color="gray", lw=0.8)
    ax2.set_title("Trading ROI (profit / total staked)")
    ax2.set_xlabel("ROI")
    for i, v in enumerate(rr):
        ax2.text(v, i, f" {v:+.1%}", va="center", fontsize=8)
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_margin_sweep(results, path):
    """ROI vs EV-margin threshold for the strategies that actually trade."""
    fig, ax = plt.subplots(figsize=(11, 4.6))
    # only plot strategies with meaningful bet counts
    plotted = 0
    for n in results:
        ms = results[n].get("margin_sweep")
        if not ms:
            continue
        margins = sorted(ms.keys())
        if max(ms[m]["n_bets"] for m in margins) < 20:
            continue
        rois = [ms[m]["roi"] for m in margins]
        ax.plot([f"{m:.0%}" for m in margins], rois, marker="o",
                lw=2.4 if n == BASELINE else 1.5,
                ls="--" if n == BASELINE else "-", label=n)
        plotted += 1
    ax.axhline(0, color="gray", lw=0.8)
    ax.set_title("Trading ROI vs Expected-Value Margin Threshold")
    ax.set_xlabel("minimum edge over crowd price required to bet")
    ax.set_ylabel("ROI")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_acc_by_slot(results, path):
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in results:
        ys = []
        for r in REMAINING_TIMES:
            s = results[n]["slots"].get(r)
            ys.append(s["accuracy"] if s else np.nan)
        ax.plot([str(r) for r in REMAINING_TIMES], ys, marker="o",
                lw=2.4 if n == BASELINE else 1.4,
                ls="--" if n == BASELINE else "-", label=n)
    ax.set_title("Accuracy by Seconds Remaining")
    ax.set_xlabel("seconds remaining at prediction")
    ax.set_ylabel("accuracy")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------

def build_pdf(data):
    results = data["results"]
    meta = data["meta"]
    out_pdf = os.path.join(_DIR, "STRATEGY_REPORT.pdf")
    cdir = os.path.join(_DIR, "cache")

    c1 = os.path.join(cdir, "_c_accbrier.png")
    c2 = os.path.join(cdir, "_c_pnl.png")
    c3 = os.path.join(cdir, "_c_slot.png")
    c4 = os.path.join(cdir, "_c_margin.png")
    chart_accuracy_brier(results, meta, c1)
    chart_pnl(results, c2)
    chart_acc_by_slot(results, c3)
    chart_margin_sweep(results, c4)

    styles = getSampleStyleSheet()
    h1 = styles["Title"]
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], spaceBefore=10)
    body = styles["BodyText"]

    doc = SimpleDocTemplate(out_pdf, pagesize=letter,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    el = []

    el.append(Paragraph("BTC 5-Minute Strategy Research Report", h1))
    el.append(Paragraph(
        f"Candidate strategies benchmarked against the existing <b>Sway model</b>. "
        f"Generated {meta['generated']}.", body))
    el.append(Spacer(1, 8))

    # ranking
    ranking = sorted(results.items(),
                     key=lambda kv: (-kv[1]["overall"]["accuracy"], kv[1]["overall"]["brier"]))
    best = ranking[0][0]
    base_acc = results[BASELINE]["overall"]["accuracy"] if BASELINE in results else None

    el.append(Paragraph("Executive Summary", h2))
    summ = (f"Trained on <b>{meta['n_train']}</b> historical markets, tested out-of-sample on "
            f"<b>{meta['n_test']}</b> more-recent markets (test base rate "
            f"{meta['base_rate_up']:.1%} UP). Best by accuracy: <b>{best}</b> "
            f"({results[best]['overall']['accuracy']:.1%}).")
    if base_acc is not None:
        summ += (f" Sway baseline accuracy: {base_acc:.1%}. Best trading ROI: "
                 f"<b>{max(results.items(), key=lambda kv: kv[1]['trading']['roi'])[0]}</b>.")
    el.append(Paragraph(summ, body))
    el.append(Spacer(1, 6))

    # main metrics table
    el.append(Paragraph("Overall metrics (out-of-sample)", h2))
    header = ["Strategy", "Accuracy", "Brier", "LogLoss", "Bets", "ROI", "P&L $", "WinRate", "MaxDD$"]
    rows = [header]
    for name, r in ranking:
        ov, tr = r["overall"], r["trading"]
        rows.append([
            name,
            f"{ov['accuracy']:.1%}",
            f"{ov['brier']:.4f}",
            f"{ov['logloss']:.4f}",
            str(tr["n_bets"]),
            f"{tr['roi']:+.1%}",
            f"{tr['total_profit']:+.1f}",
            f"{tr['win_rate']:.1%}",
            f"{tr['max_drawdown']:.1f}",
        ])
    t = Table(rows, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f5")]),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
    ]
    for i, (name, _) in enumerate(ranking, start=1):
        if name == BASELINE:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fde0dc")))
        if name == best:
            style.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    el.append(t)
    el.append(Spacer(1, 6))
    el.append(Paragraph(
        "<i>Sway baseline highlighted in red; best strategy in bold. Trading "
        f"simulation bets $1 whenever a model's probability diverges from the "
        f"live market price by &gt; {meta['ev_margin']:.0%} (positive expected "
        f"value), including Polymarket fees.</i>", body))

    el.append(PageBreak())
    el.append(Paragraph("Accuracy &amp; Calibration", h2))
    el.append(Image(c1, width=7.2 * inch, height=3.27 * inch))
    el.append(Spacer(1, 6))
    el.append(Image(c3, width=7.2 * inch, height=3.27 * inch))

    el.append(PageBreak())
    el.append(Paragraph("Trading Performance", h2))
    el.append(Paragraph(
        "The sway model ignores the absolute market price, so its statistical "
        "edge does not always convert into trading profit. The equity curves "
        "below show realised P&amp;L when each model only bets on positive-EV "
        "divergences from the crowd price.", body))
    el.append(Spacer(1, 6))
    el.append(Image(c2, width=7.2 * inch, height=3.27 * inch))
    el.append(Spacer(1, 6))
    el.append(Image(c4, width=7.2 * inch, height=3.0 * inch))

    el.append(PageBreak())
    el.append(Paragraph("Methodology", h2))
    el.append(Paragraph(
        "All strategies use only trade data available up to the prediction time "
        "(no look-ahead). Predictions are made at 60, 30, 20, 15 and 10 seconds "
        "remaining. The Sway baseline is a faithful reproduction of the repo's "
        "per-slot GradientBoosting model on the 29 channel-sway features. "
        "Candidate models add the absolute price level, VWAP, multi-horizon "
        "momentum/volatility and order-flow imbalance features. Metrics: "
        "directional accuracy, Brier score and log-loss (probability quality), "
        "plus a fee-aware Polymarket P&amp;L simulation.", body))

    doc.build(el)
    print(f"Wrote {out_pdf}")
    return out_pdf


if __name__ == "__main__":
    build_pdf(load())
