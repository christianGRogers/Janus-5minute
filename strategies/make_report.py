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

# Curated subset for line charts (keeping all 19 in tables / bar charts).
FEATURED = ["Sway (baseline)", "MarketPrice", "LogisticMicro",
            "Combined-GBM", "SpotBarrier", "SpotBarrier-Late", "Ensemble-Spot"]


def _featured(results):
    return [n for n in FEATURED if n in results]


def load():
    with open(os.path.join(_DIR, "cache", "results.pkl"), "rb") as f:
        return pickle.load(f)


def load_validation():
    p = os.path.join(_DIR, "cache", "validation.pkl")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return pickle.load(f)


def load_robust3():
    p = os.path.join(_DIR, "cache", "robustness3.pkl")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return pickle.load(f)


def load_walkforward():
    p = os.path.join(_DIR, "cache", "walkforward.pkl")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return pickle.load(f)


def chart_walkforward(wf, r3, path):
    """Walk-forward ROI across 3 windows, plus oos3 stale-vs-fresh comparison."""
    wn = ["test", "val", "oos3"]
    names = sorted(wf.keys(), key=lambda n: -min(wf[n][w]["roi"] for w in wn))
    y = np.arange(len(names))
    h = 0.26
    cols = {"test": "#1b9e77", "val": "#7570b3", "oos3": "#d95f02"}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5.2),
                                   gridspec_kw={"width_ratios": [2, 1]})
    for i, w in enumerate(wn):
        ax1.barh(y + (1 - i) * h, [wf[n][w]["roi"] for n in names], h,
                 label=f"{w}", color=cols[w])
    ax1.axvline(0, color="black", lw=0.9)
    ax1.set_yticks(y); ax1.set_yticklabels(names, fontsize=9); ax1.invert_yaxis()
    ax1.set_title("Walk-forward ROI (production-style retraining)")
    ax1.set_xlabel("ROI"); ax1.legend(fontsize=8, loc="lower right")
    for n in names:
        allpos = all(wf[n][w]["roi"] > 0 and wf[n][w]["n_bets"] > 10 for w in wn)
        lbl = ax1.get_yticklabels()[list(names).index(n)]
        if allpos:
            lbl.set_color("#2ca02c"); lbl.set_fontweight("bold")
        if n == "Sway (baseline)":
            lbl.set_color("#d62728")

    # oos3: stale vs fresh
    if r3 is not None:
        common = [n for n in names if n in r3]
        yy = np.arange(len(common))
        stale = [r3[n]["oos3"]["roi"] for n in common]
        fresh = [wf[n]["oos3"]["roi"] for n in common]
        ax2.barh(yy + 0.2, stale, 0.4, label="stale global", color="#bbbbbb")
        ax2.barh(yy - 0.2, fresh, 0.4, label="fresh retrain", color="#1f77b4")
        ax2.axvline(0, color="black", lw=0.9)
        ax2.set_yticks(yy); ax2.set_yticklabels(common, fontsize=8); ax2.invert_yaxis()
        ax2.set_title("oos3: stale vs fresh training")
        ax2.set_xlabel("ROI"); ax2.legend(fontsize=8, loc="lower right")
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def load_kelly():
    p = os.path.join(_DIR, "cache", "kelly.pkl")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        return pickle.load(f)


def chart_kelly(kelly, path):
    """Bankroll curves (log scale) for each window, plus a growth-multiple table feel."""
    res = kelly["results"]
    wn = ["test", "val", "oos3"]
    feat = [n for n in ["Combined-Logistic", "LogisticMicro", "SpotBarrier",
                        "TemperedBarrier(w=0.5)", "Sway (baseline)"] if n in res]
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), sharey=True)
    colmap = {"Combined-Logistic": "#1f77b4", "LogisticMicro": "#2ca02c",
              "SpotBarrier": "#9467bd", "TemperedBarrier(w=0.5)": "#ff7f0e",
              "Sway (baseline)": "#d62728"}
    for ax, w in zip(axes, wn):
        for n in feat:
            curve = res[n][w]["curve"]
            ax.plot(curve, label=n, color=colmap.get(n),
                    lw=2.0 if n == "Sway (baseline)" else 1.4,
                    ls="--" if n == "Sway (baseline)" else "-")
        ax.axhline(kelly["params"]["start"], color="gray", lw=0.7)
        ax.set_yscale("log")
        ax.set_title(f"{w} window")
        ax.set_xlabel("bet #")
        ax.grid(alpha=0.3, which="both")
    axes[0].set_ylabel("bankroll $ (log)")
    axes[-1].legend(fontsize=7, loc="lower left")
    p = kelly["params"]
    fig.suptitle(f"Fractional-Kelly bankroll growth ({p['kelly_frac']}x Kelly, "
                 f"{p['max_bet_frac']:.0%} cap, ${p['start']:.0f} start)", y=1.02)
    plt.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)


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

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 6.8))
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

    # equity curves (curated subset for readability)
    for n in _featured(results):
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
    for n in _featured(results):
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


def chart_robust3(r3, path):
    """Grouped horizontal bars: ROI across three independent windows per strategy."""
    wnames = ["test", "val", "oos3"]
    names = sorted(r3.keys(), key=lambda n: -min(r3[n][w]["roi"] for w in wnames))
    y = np.arange(len(names))
    h = 0.26
    cols = {"test": "#1b9e77", "val": "#7570b3", "oos3": "#d95f02"}
    fig, ax = plt.subplots(figsize=(11, 6.2))
    for i, w in enumerate(wnames):
        vals = [r3[n][w]["roi"] for n in names]
        ax.barh(y + (1 - i) * h, vals, h, label=f"{w} window", color=cols[w])
    ax.axvline(0, color="black", lw=0.9)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=9)
    ax.invert_yaxis()
    ax.set_title("Trading ROI across THREE independent windows (all-positive = robust edge)")
    ax.set_xlabel("ROI")
    ax.legend(fontsize=9, loc="lower right")
    # mark strategies positive on all three
    for n, yy in zip(names, y):
        allpos = all(r3[n][w]["roi"] > 0 and r3[n][w]["n_bets"] > 10 for w in wnames)
        if allpos:
            ax.get_yticklabels()[list(names).index(n)].set_color("#2ca02c")
            ax.get_yticklabels()[list(names).index(n)].set_fontweight("bold")
        if n == "Sway (baseline)":
            ax.get_yticklabels()[list(names).index(n)].set_color("#d62728")
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_validation(val, path):
    """Side-by-side test vs val for accuracy and ROI across two windows."""
    tw = val["windows"]["test"]
    vw = val["windows"]["val"]
    names = sorted(tw.keys(), key=lambda n: -tw[n]["overall"]["accuracy"])
    y = np.arange(len(names))
    h = 0.4

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 7.5))

    ta = [tw[n]["overall"]["accuracy"] for n in names]
    va = [vw[n]["overall"]["accuracy"] for n in names]
    ax1.barh(y + h / 2, ta, h, label="test window", color="#1f77b4")
    ax1.barh(y - h / 2, va, h, label="val window", color="#9ecae1")
    ax1.set_yticks(y); ax1.set_yticklabels(names, fontsize=8)
    ax1.set_xlim(0.45, 0.95)
    ax1.set_title("Accuracy — both windows")
    ax1.legend(fontsize=8)
    for n, yy in zip(names, y):
        if n == BASELINE:
            ax1.get_yticklabels()[list(names).index(n)].set_color("#d62728")

    tr = [tw[n]["trading"]["roi"] for n in names]
    vr = [vw[n]["trading"]["roi"] for n in names]
    ax2.barh(y + h / 2, tr, h, label="test ROI", color="#2ca02c")
    ax2.barh(y - h / 2, vr, h, label="val ROI", color="#98df8a")
    ax2.axvline(0, color="gray", lw=0.8)
    ax2.set_yticks(y); ax2.set_yticklabels([])
    ax2.set_title("Trading ROI — both windows (sign flips = noise)")
    ax2.legend(fontsize=8)
    plt.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_acc_by_slot(results, path):
    fig, ax = plt.subplots(figsize=(11, 5))
    for n in _featured(results):
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

def build_pdf(data, val=None, r3=None, kelly=None, wf=None):
    meta = data["meta"]
    # Prefer the validation run's test window so the table covers all strategies
    # consistently with the cross-window section (same test markets & evaluate()).
    if val is not None:
        results = val["windows"]["test"]
        meta = {**meta, "generated": val["meta"]["generated"],
                "n_train": val["meta"]["n_train"], "n_test": val["meta"]["n_test"]}
    else:
        results = data["results"]
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
        summ += (f" The <b>Sway baseline is the weakest model</b> ({base_acc:.1%} "
                 f"accuracy) — worse than simply trusting the live market price "
                 f"({results['MarketPrice']['overall']['accuracy']:.1%}).")
    el.append(Paragraph(summ, body))
    el.append(Spacer(1, 4))
    if val is not None:
        tw, vw = val["windows"]["test"], val["windows"]["val"]
        both_pos = [n for n in tw if tw[n]["trading"]["n_bets"] > 30
                    and tw[n]["trading"]["roi"] > 0 and vw[n]["trading"]["roi"] > 0]
        # rank robust winners by worst-case (min) ROI across the two windows
        both_pos.sort(key=lambda n: -min(tw[n]["trading"]["roi"], vw[n]["trading"]["roi"]))
        if r3 is not None:
            wn = ["test", "val", "oos3"]
            allpos = [n for n in r3
                      if all(r3[n][w]["roi"] > 0 and r3[n][w]["n_bets"] > 10 for w in wn)]
            allpos.sort(key=lambda n: -min(r3[n][w]["roi"] for w in wn))
            champ = allpos[0] if allpos else None
            champ_txt = (f"<b>{champ}</b> ("
                         + " / ".join(f"+{r3[champ][w]['roi']:.1%}" for w in wn)
                         + " across test/val/oos3)") if champ else "none"
            el.append(Paragraph(
                "<b>Headline result (after three independent windows).</b> Reading the "
                "<b>underlying BTC spot price</b> (Binance 1s data) — which the "
                "prediction-market models never see — produces a large trading edge: an "
                "analytic first-passage 'barrier' probability returns +20% on two "
                "windows. <b>But a third, older window exposes it as partly "
                "period-specific</b> (it goes slightly negative there) — a reminder that "
                "even two-window results can mislead. Under that harsh stale-model test "
                f"the only strategies profitable on <b>all three</b> windows are: "
                f"{', '.join(allpos) if allpos else 'none'}. "
                "<b>But the realistic picture is stronger:</b> when models are retrained "
                "on recent data as the live bot does (see Realistic Walk-Forward), the "
                "spot+market fusion models (Combined-GBM, Combined-Logistic) are robustly "
                "profitable on all three windows (+13% to +24% ROI) — the recommended "
                "live candidates. The training-free raw barrier and the Sway baseline "
                "(broken throughout, -37% on oos3) are not.", body))
        else:
            champ = both_pos[0] if both_pos else None
            el.append(Paragraph(
                "<b>Headline.</b> Strategies profitable on both windows: "
                f"{', '.join(both_pos) if both_pos else 'none'}. Sway is consistently last.",
                body))
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
    el.append(Image(c1, width=6.6 * inch, height=4.08 * inch))
    el.append(Spacer(1, 6))
    el.append(Image(c3, width=7.0 * inch, height=3.18 * inch))

    el.append(PageBreak())
    el.append(Paragraph("Trading Performance", h2))
    el.append(Paragraph(
        "The sway model ignores the absolute market price, so its statistical "
        "edge does not convert into trading profit (it loses the most). The "
        "equity curves below show realised P&amp;L when each model bets on "
        "positive-EV divergences from the crowd price. The spot-driven models "
        "dominate. <b>SpotBarrier-Late</b> further concentrates the spot edge in "
        "the final 20 seconds — where the spot lead is most predictive yet the "
        "crowd still prices residual caution — roughly doubling test ROI (+44.9%) "
        "while cutting max drawdown by ~60%.", body))
    el.append(Spacer(1, 6))
    el.append(Image(c2, width=7.2 * inch, height=3.27 * inch))
    el.append(Spacer(1, 6))
    el.append(Image(c4, width=7.2 * inch, height=3.0 * inch))

    # ---- Cross-window robustness ----
    if val is not None:
        c5 = os.path.join(cdir, "_c_validation.png")
        chart_validation(val, c5)
        vm = val["meta"]
        tw, vw = val["windows"]["test"], val["windows"]["val"]
        # strategies positive on BOTH windows (excluding the no-bet MarketPrice)
        both_pos = [n for n in tw
                    if tw[n]["trading"]["n_bets"] > 30
                    and tw[n]["trading"]["roi"] > 0 and vw[n]["trading"]["roi"] > 0]
        both_pos.sort(key=lambda n: -min(tw[n]["trading"]["roi"], vw[n]["trading"]["roi"]))
        el.append(PageBreak())
        el.append(Paragraph("Cross-Window Robustness", h2))
        el.append(Paragraph(
            f"To separate genuine edge from luck, every strategy is re-evaluated on a "
            f"second, fully independent and time-disjoint window of "
            f"<b>{vm['n_val']}</b> older markets, in a different regime "
            f"(45.7% UP vs 53.2% in the recent test window).", body))
        el.append(Spacer(1, 4))
        el.append(Paragraph(
            "<b>Two clear conclusions:</b> (1) Statistical quality is robust — the "
            "Sway baseline is the least accurate model in <i>both</i> windows by a "
            "wide margin. (2) Single-window trading ROI is largely noise: most "
            "prediction-market-only strategies flip sign between windows (e.g. "
            "Edge-GBM from -14% to +25%). (3) The spot-driven strategies are "
            "different: they are profitable in <i>both</i> windows. Strategies with "
            f"<b>positive ROI on both</b> windows (ranked by worst-case ROI): "
            f"<b>{', '.join(both_pos) if both_pos else 'none'}</b>. The analytic "
            "SpotBarrier model leads — a repeatable, sizeable trading edge.", body))
        el.append(Spacer(1, 6))
        el.append(Image(c5, width=6.7 * inch, height=4.57 * inch))

    # ---- Three-window robustness (the decisive test) ----
    if r3 is not None:
        wn = ["test", "val", "oos3"]
        allpos = [n for n in r3
                  if all(r3[n][w]["roi"] > 0 and r3[n][w]["n_bets"] > 10 for w in wn)]
        allpos.sort(key=lambda n: -min(r3[n][w]["roi"] for w in wn))
        c6 = os.path.join(cdir, "_c_robust3.png")
        chart_robust3(r3, c6)
        el.append(PageBreak())
        el.append(Paragraph("Three-Window Robustness — the decisive test", h2))
        el.append(Paragraph(
            "Two windows are not enough. The spot-barrier strategies looked like clear "
            "winners on the test and val windows (~+20% ROI each), but a <b>third</b> "
            "independent and older window (oos3, 300 markets) tells a different story: "
            "their edge largely disappears there. This is the single most important "
            "result in the study — a strategy must clear <i>all three</i> windows to be "
            "trusted.", body))
        el.append(Spacer(1, 4))
        rows = [["Strategy", "test ROI", "val ROI", "oos3 ROI", "min ROI", "all +?"]]
        order = sorted(r3.keys(), key=lambda n: -min(r3[n][w]["roi"] for w in wn))
        for n in order:
            rois = [r3[n][w]["roi"] for w in wn]
            ap = all(r > 0 for r in rois) and all(r3[n][w]["n_bets"] > 10 for w in wn)
            rows.append([n] + [f"{r:+.1%}" for r in rois]
                        + [f"{min(rois):+.1%}", "YES" if ap else ""])
        t3 = Table(rows, repeatRows=1, hAlign="LEFT")
        st = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ]
        for i, n in enumerate(order, start=1):
            rois = [r3[n][w]["roi"] for w in wn]
            if all(r > 0 for r in rois) and all(r3[n][w]["n_bets"] > 10 for w in wn):
                st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#d9f2d9")))
                st.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
            if n == "Sway (baseline)":
                st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fde0dc")))
        t3.setStyle(TableStyle(st))
        el.append(t3)
        el.append(Spacer(1, 6))
        el.append(Image(c6, width=7.0 * inch, height=3.95 * inch))
        el.append(Spacer(1, 4))
        el.append(Paragraph(
            f"<b>Conclusion:</b> the only strategies profitable on all three windows are "
            f"<b>{', '.join(allpos) if allpos else 'none'}</b>. "
            "The recommended live candidate is the top of that list — a regularised "
            "blend of spot and prediction-market features that keeps a real edge without "
            "over-relying on any single period. The spot signal is valuable, but must be "
            "tempered with the crowd price rather than trusted outright.", body))

    # ---- Realistic walk-forward (production retraining) ----
    if wf is not None:
        wn = ["test", "val", "oos3"]
        wf_allpos = [n for n in wf
                     if all(wf[n][w]["roi"] > 0 and wf[n][w]["n_bets"] > 10 for w in wn)]
        wf_allpos.sort(key=lambda n: -min(wf[n][w]["roi"] for w in wn))
        c8 = os.path.join(cdir, "_c_walkforward.png")
        chart_walkforward(wf, r3, c8)
        el.append(PageBreak())
        el.append(Paragraph("Realistic Walk-Forward — production-style retraining", h2))
        el.append(Paragraph(
            "The three-window test above used a single stale model applied across very "
            "different periods — a harsh stress test. The live bot, however, retrains on "
            "the latest markets (retrain.py). Here each window is instead evaluated with "
            "a model trained on the 600 markets <i>immediately preceding</i> it, which "
            "mirrors production.", body))
        el.append(Spacer(1, 4))
        el.append(Paragraph(
            "<b>This rehabilitates the spot+market models.</b> Their oos3 weakness was "
            "largely a stale-training artifact: with fresh training, Combined-GBM goes "
            "from -3.9% to <b>+22.2%</b> and Combined-Logistic from +8.1% to "
            "<b>+17.2%</b> on oos3. Under realistic retraining the genuinely robust "
            f"strategies (positive on all three windows) are: "
            f"<b>{', '.join(wf_allpos) if wf_allpos else 'none'}</b>. The training-free "
            "raw SpotBarrier still fails on oos3 (its edge is truly period-dependent), "
            "and the Sway baseline stays broken regardless of retraining (-37.5% on "
            "oos3).", body))
        el.append(Spacer(1, 4))
        rows = [["Strategy"] + [f"{w} ROI" for w in wn] + ["min", "all +?"]]
        order = sorted(wf.keys(), key=lambda n: -min(wf[n][w]["roi"] for w in wn))
        for n in order:
            rois = [wf[n][w]["roi"] for w in wn]
            ap = all(r > 0 for r in rois) and all(wf[n][w]["n_bets"] > 10 for w in wn)
            rows.append([n] + [f"{r:+.1%}" for r in rois]
                        + [f"{min(rois):+.1%}", "YES" if ap else ""])
        twf = Table(rows, repeatRows=1, hAlign="LEFT")
        s2 = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ]
        for i, n in enumerate(order, start=1):
            rois = [wf[n][w]["roi"] for w in wn]
            if all(r > 0 for r in rois) and all(wf[n][w]["n_bets"] > 10 for w in wn):
                s2.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#d9f2d9")))
                s2.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
            if n == "Sway (baseline)":
                s2.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fde0dc")))
        twf.setStyle(TableStyle(s2))
        el.append(twf)
        el.append(Spacer(1, 6))
        el.append(Image(c8, width=7.2 * inch, height=3.12 * inch))

    # ---- Money management / bankroll ----
    if kelly is not None:
        res = kelly["results"]; p = kelly["params"]; wn = ["test", "val", "oos3"]
        c7 = os.path.join(cdir, "_c_kelly.png")
        chart_kelly(kelly, c7)
        el.append(PageBreak())
        el.append(Paragraph("Money Management — bankroll growth &amp; ruin", h2))
        el.append(Paragraph(
            f"Per-bet ROI ignores compounding and risk. Here each strategy plays its "
            f"bets in time order with conservative fractional-Kelly sizing "
            f"({p['kelly_frac']}x Kelly, {p['max_bet_frac']:.0%} max stake, "
            f"${p['start']:.0f} start). The robust strategies compound positively on "
            f"all three windows; the <b>Sway baseline is driven to ruin</b> "
            f"(bankroll &#8594; ~$0) on two of three.", body))
        el.append(Spacer(1, 4))
        rows = [["Strategy"] + [f"{w} final" for w in wn] + ["worst maxDD"]]
        order = sorted(res.keys(), key=lambda n: -min(res[n][w]["mult"] for w in wn))
        for n in order:
            finals = [res[n][w]["final"] for w in wn]
            dd = max(res[n][w]["max_dd_pct"] for w in wn)
            rows.append([n] + [f"${v:,.0f} ({res[n][w]['mult']:.1f}x)"
                               for v, w in zip(finals, wn)] + [f"{dd:.0%}"])
        tk = Table(rows, repeatRows=1, hAlign="LEFT")
        stk = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#34495e")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ]
        for i, n in enumerate(order, start=1):
            if n == "Sway (baseline)":
                stk.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#fde0dc")))
        tk.setStyle(TableStyle(stk))
        el.append(tk)
        el.append(Spacer(1, 6))
        el.append(Image(c7, width=7.2 * inch, height=2.52 * inch))
        el.append(Spacer(1, 4))
        el.append(Paragraph(
            "<i>Caveat: drawdowns are large (40-60%) — this edge is real but noisy, "
            "so position sizing must stay conservative. LogisticMicro has the gentlest "
            "drawdown; Combined-Logistic the highest growth.</i>", body))

    el.append(PageBreak())
    el.append(Paragraph("Methodology", h2))
    el.append(Paragraph(
        "All strategies use only trade data available up to the prediction time "
        "(no look-ahead). Predictions are made at 60, 30, 20, 15 and 10 seconds "
        "remaining. The Sway baseline is a faithful reproduction of the repo's "
        "per-slot GradientBoosting model on the 29 channel-sway features. "
        "Prediction-market candidates add the absolute price level, VWAP, "
        "multi-horizon momentum/volatility and order-flow imbalance. "
        "<b>Spot-driven candidates</b> additionally read the underlying BTC price "
        "(Binance 1s klines): the SpotBarrier model computes an analytic "
        "first-passage probability P(close &gt; open) = &#934;(lead / "
        "(&#963;&#8730;t_remaining)) from the live spot lead and realised "
        "volatility; the Combined models feed spot + market features into a "
        "classifier. Metrics: directional accuracy, Brier score and log-loss "
        "(probability quality), plus a fee-aware Polymarket P&amp;L simulation that "
        "only bets on positive-EV divergences from the crowd price.", body))

    doc.build(el)
    print(f"Wrote {out_pdf}")
    return out_pdf


if __name__ == "__main__":
    build_pdf(load(), load_validation(), load_robust3(), load_kelly(),
              load_walkforward())
