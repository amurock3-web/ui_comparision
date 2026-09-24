"""Charts for the class refiner experiment (train_class_refiner.py, compare_yolo_vs_refiner.py).

Static PNGs + one report.html per run folder that puts them on a single page.
Colours: fixed categorical order (blue, orange, aqua), one-hue blue ramp for matrices,
blue/red diverging for signed weights; text stays in ink colours, never series colours.
"""
import html

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]          # categorical slots 1-3
NEG, POS = "#e34948", "#2a78d6"                      # diverging poles
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
FOCUS = "#b3261e"                                    # confusable-group tick labels (text accent)
BLUES = LinearSegmentedColormap.from_list("blues", ["#fcfcfb", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False,
})


def _mark_group(labels, group):
    for lbl in labels:
        if lbl.get_text().rstrip(" *") in group:
            lbl.set_color(FOCUS)
            lbl.set_fontweight("bold")


def confusion(cm, row_labels, col_labels, title, path, group=(), figsize=None):
    """Counts in the cells, colour = share of the true class (row-normalised)."""
    cm = np.asarray(cm)
    norm = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=figsize or (1.0 + 0.55 * len(col_labels), 1.0 + 0.5 * len(row_labels)))
    im = ax.imshow(norm, cmap=BLUES, vmin=0, vmax=1)
    ax.grid(False)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            if cm[i, j]:
                ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=8,
                        color="white" if norm[i, j] > 0.55 else INK)
    ax.set_xticks(range(len(col_labels)), col_labels, rotation=55, ha="right")
    ax.set_yticks(range(len(row_labels)), row_labels)
    _mark_group(ax.get_xticklabels() + ax.get_yticklabels(), group)
    ax.set_xlabel("predicted")
    ax.set_ylabel("truth")
    ax.set_title(title)
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("share of true class", color=INK2)
    cb.outline.set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def grouped_bars(labels, series, title, path, xlabel, annotate=None, group=(), xlim=(0, 1.05)):
    """Horizontal grouped bars. series = {name: values}; annotate = per-label text on the right."""
    names = list(series)
    n, k = len(labels), len(names)
    h = 0.8 / k
    fig, ax = plt.subplots(figsize=(8, 1.2 + 0.42 * n * max(1, k / 2)))
    y = np.arange(n)
    for s, name in enumerate(names):
        vals = np.nan_to_num(np.asarray(series[name], float))
        ax.barh(y - 0.4 + h * (s + 0.5), vals, height=h * 0.85, color=SERIES[s], label=name)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlim(*xlim)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(xlabel)
    if annotate:
        for i, t in enumerate(annotate):
            ax.text(xlim[1], i, f" {t}", va="center", fontsize=8, color=INK2)
    _mark_group(ax.get_yticklabels(), group)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=k)
    ax.set_title(title, pad=24)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def reliability(bins, conf, ece, title, path):
    """Reliability curve above a histogram of top-label confidence (two panels, shared x)."""
    fig, (top, bot) = plt.subplots(2, 1, figsize=(6, 6.4), sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    top.plot([0, 1], [0, 1], "--", color=INK2, linewidth=1, label="perfectly calibrated")
    xs = [b["confidence"] for b in bins]
    ys = [b["accuracy"] for b in bins]
    top.plot(xs, ys, "-", color=SERIES[0], linewidth=2)
    top.scatter(xs, ys, s=40, color=SERIES[0], edgecolor=SURFACE, linewidth=2, zorder=3, label="refiner")
    for b in bins:
        top.annotate(f"n={b['n']}", (b["confidence"], b["accuracy"]), fontsize=7, color=INK2,
                     xytext=(4, -11), textcoords="offset points")
    top.set_ylim(0, 1.02)
    top.set_ylabel("accuracy")
    top.set_title(f"{title}  (ECE {ece:.3f})")
    top.legend(loc="upper left")
    bot.hist(conf, bins=20, range=(0, 1), color=SERIES[0], edgecolor=SURFACE)
    bot.set_xlabel("predicted probability of the chosen class")
    bot.set_ylabel("boxes")
    bot.set_xlim(0, 1)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def weight_panels(weights, classes, title, path):
    """Small multiples: top signed logistic-regression weights for each class."""
    cols = 3 if len(classes) > 4 else 2
    rows = int(np.ceil(len(classes) / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 3.3 * rows), squeeze=False)
    for ax, c in zip(axes.flat, classes):
        w = weights[weights["class"] == c].sort_values("weight")
        ax.barh(w["feature"], w["weight"], color=[POS if v > 0 else NEG for v in w["weight"]], height=0.7)
        ax.axvline(0, color=INK2, linewidth=0.8)
        ax.grid(axis="y", visible=False)
        ax.set_title(c, fontsize=10)
        ax.tick_params(axis="y", labelsize=8)
    for ax in list(axes.flat)[len(classes):]:
        ax.set_visible(False)
    fig.suptitle(f"{title}\nblue pushes towards the class, red pushes away (standardised features)",
                 x=0.01, ha="left", fontsize=11, fontweight="bold", color=INK)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def outcome_bar(counts, title, path):
    """One stacked 100% bar: how the matched boxes split between YOLO and the refiner."""
    colors = {"both right": "#c3c2b7", "refiner fixes YOLO": SERIES[0],
              "refiner breaks YOLO": SERIES[1], "both wrong": "#52514e"}
    total = max(sum(counts.values()), 1)
    fig, ax = plt.subplots(figsize=(9, 2.3))
    left = 0
    for name, v in counts.items():
        ax.barh(0, v, left=left, color=colors[name], edgecolor=SURFACE, linewidth=2, label=f"{name} ({v})")
        if v / total > 0.06:
            ax.text(left + v / 2, 0, f"{v / total:.0%}", ha="center", va="center", fontsize=9,
                    color="white" if name != "both right" else INK)
        left += v
    ax.set_xlim(0, total)
    ax.set_yticks([])
    ax.grid(False)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="x", labelsize=8)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.35), ncol=2)
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def html_report(path, title, summary, images, tables):
    """summary = [(label, value)], images = [(file, caption)], tables = [(heading, header, rows)]."""
    tiles = "".join(f'<div class="tile"><div class="v">{html.escape(str(v))}</div>'
                    f'<div class="k">{html.escape(k)}</div></div>' for k, v in summary)
    figs = "".join(f'<figure><img src="{f}" alt="{html.escape(c)}"><figcaption>{html.escape(c)}</figcaption></figure>'
                   for f, c in images)
    tabs = ""
    for heading, header, rows in tables:
        head = "".join(f"<th>{html.escape(str(h))}</th>" for h in header)
        body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
        tabs += f"<h2>{html.escape(heading)}</h2><div class='scroll'><table><tr>{head}</tr>{body}</table></div>"
    path.write_text(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
body{{font-family:system-ui,Segoe UI,sans-serif;background:#fcfcfb;color:#0b0b0b;margin:0 auto;max-width:1100px;padding:24px 16px}}
h1{{font-size:22px}} h2{{font-size:16px;margin-top:32px}}
.tiles{{display:flex;flex-wrap:wrap;gap:12px}} .tile{{border:1px solid #e6e5e1;border-radius:8px;padding:12px 16px;min-width:140px}}
.v{{font-size:24px;font-weight:600}} .k{{color:#52514e;font-size:12px}}
figure{{margin:24px 0}} img{{max-width:100%;border:1px solid #e6e5e1;border-radius:6px}} figcaption{{color:#52514e;font-size:13px}}
.scroll{{overflow-x:auto}} table{{border-collapse:collapse;font-size:13px}} td,th{{border-bottom:1px solid #e6e5e1;padding:4px 10px;text-align:left}}
th{{color:#52514e}}
</style></head><body><h1>{html.escape(title)}</h1><div class="tiles">{tiles}</div>{figs}{tabs}</body></html>""",
                    encoding="utf-8")
