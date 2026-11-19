"""Precision / recall / F1 and screen-level accuracy from saved benchmark results (Phase 20).

    python -m scripts.evaluate output/benchmark/test22_benchmark
    python -m scripts.evaluate output/benchmark/test22_benchmark output/benchmark/test23_benchmark --pool

Reads results.json only (written by scripts.run_benchmark): no detector, OCR or
comparison runs. Each run gets evaluation.json + evaluation.md next to its
results.json (rebuilt from it, so a re-run gives the same files). Several runs
print side by side. --pool adds an "all" column over the runs' cases; it refuses
a screen/case (or real pair) that appears in two runs, prints each results.json
mtime so you can see they come from one code state, and writes the pooled files
to output/evaluation/testN_evaluation/. Confidence level: config.yaml evaluation.

Definitions:
- Finding level, case TP vs finding FP (the units differ: TP and FN count defect
  cases, FP counts findings).
  - lenient: TP = defect case flagged (REVIEW/FAIL) at the edited region
    (outcome "caught" or "caught as other"); FN = "missed".
  - exact: TP = "caught" (the expected spec id); FN = "caught as other" + "missed".
  - FP = false-alarm findings: findings away from the edit, plus every finding
    on an identity case. The same FP for both variants: a wrong-id finding on
    the edit is a weaker hit, not a false alarm.
  - recall = TP / (TP + FN); precision = TP / (TP + FP); F1 = 2PR / (P + R).
    Precision is n/a when there are no defect cases.
- False alarms per screen: FP / benchmark cases (every case is one screen).
- Screen level: a defect case should be flagged (REVIEW or FAIL), an identity
  case PASS. TP = defect flagged, FN = defect PASS, TN = identity PASS,
  FP = identity flagged. The screen verdict does not check where the flag is,
  so a false alarm elsewhere on a defect screen still counts as TP.
- REVIEW rate: REVIEW screens / flagged screens (how often the system is unsure).
- Real pairs: manifest expected_verdict vs the screen verdict (PASS / REVIEW /
  FAIL), plus false alarms (must_not_flag hits), misses (must_flag rules no
  finding matched), unlisted findings and tester load (REVIEW/FAIL issues) vs the budget.
- [lo, hi] = Wilson score interval at the configured confidence level.
"""
import html
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from statistics import NormalDist

import yaml

from scripts._test_utils import next_test_number

CONFIG = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
OUTPUT_ROOT = Path("output/evaluation")
FLAGGED = ("REVIEW", "FAIL")
VERDICTS = ("PASS", "REVIEW", "FAIL")
DEFINITIONS = __doc__[__doc__.index("Definitions:"):]


def z_value(level: float) -> float:
    return NormalDist().inv_cdf(0.5 + level / 2)


def wilson(k: int, n: int, z: float):
    """Wilson score interval for k successes out of n, or None when n is 0."""
    if n == 0:
        return None
    p, d = k / n, 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [max(0.0, centre - half), min(1.0, centre + half)]


def rate(k: int, n: int, z: float) -> dict:
    return {"k": k, "n": n, "value": k / n if n else None, "ci": wilson(k, n, z)}


def prf(tp: int, fp: int, fn: int, z: float, defects: int) -> dict:
    precision = rate(tp, tp + fp, z) if defects else rate(0, 0, z)
    recall = rate(tp, tp + fn, z)
    p, r = precision["value"], recall["value"]
    f1 = None if p is None or r is None else (2 * p * r / (p + r) if p + r else 0.0)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def finding_metrics(rows, z: float) -> dict:
    defects = [r for r in rows if r["expected"]]
    outcomes = [r["outcome"] for r in defects]
    fp = sum(len(r["false_alarms"]) for r in rows)
    lenient_tp = sum(o in ("caught", "caught as other") for o in outcomes)
    exact_tp = outcomes.count("caught")
    per_screen = [len(r["false_alarms"]) for r in rows]
    return {
        "cases": len(rows), "defect_cases": len(defects), "identity_cases": len(rows) - len(defects),
        "lenient": prf(lenient_tp, fp, outcomes.count("missed"), z, len(defects)),
        "exact": prf(exact_tp, fp, len(defects) - exact_tp, z, len(defects)),
        "false_alarms_per_screen": {
            "mean": fp / len(rows) if rows else None, "max": max(per_screen, default=0),
            "screens_with_false_alarm": rate(sum(n > 0 for n in per_screen), len(rows), z)},
    }


def per_spec(rows) -> dict:
    """Per spec id: n, caught, as other, missed, and false alarms flagged as that id."""
    table = {}
    blank = lambda: {"n": 0, "caught": 0, "caught as other": 0, "missed": 0, "false_alarms": 0}
    for r in rows:
        if r["expected"]:
            t = table.setdefault(r["expected"], blank())
            t["n"] += 1
            t[r["outcome"]] += 1
        for f in r["false_alarms"]:
            table.setdefault(f["spec_id"], blank())["false_alarms"] += 1
    return dict(sorted(table.items()))


def screen_metrics(rows, z: float, min_identity: int) -> dict:
    flagged = lambda r: r["verdict"] in FLAGGED
    defects = [r for r in rows if r["expected"]]
    identity = [r for r in rows if not r["expected"]]
    tp = sum(map(flagged, defects))
    tn = sum(not flagged(r) for r in identity)
    flagged_rows = [r for r in rows if flagged(r)]
    return {
        "tp": tp, "fn": len(defects) - tp, "tn": tn, "fp": len(identity) - tn,
        "accuracy": rate(tp + tn, len(rows), z),
        "sensitivity": rate(tp, len(defects), z),
        "specificity": rate(tn, len(identity), z),
        "review_rate": rate(sum(r["verdict"] == "REVIEW" for r in flagged_rows), len(flagged_rows), z),
        "warning": (f"only {len(identity)} identity case(s): specificity is weak evidence"
                    if rows and len(identity) < min_identity else None),
    }


def real_metrics(real_rows, z: float, budget) -> dict:
    matrix = {e: {g: 0 for g in VERDICTS} for e in VERDICTS}
    for r in real_rows:
        matrix[r["expected_verdict"]][r["verdict"]] += 1
    loads = [r["tester_load"] for r in real_rows if r.get("tester_load") is not None]
    return {
        "pairs": len(real_rows),
        "verdict_exact": rate(sum(r["verdict"] == r["expected_verdict"] for r in real_rows), len(real_rows), z),
        "confusion": matrix,
        "false_alarms": sum(len(r["violations"]) for r in real_rows),
        "misses": sum(len(r["misses"]) for r in real_rows),
        "unlisted": sum(len(r["unlisted"]) for r in real_rows),
        "budget": budget,
        "tester_load": {"mean": sum(loads) / len(loads) if loads else None, "max": max(loads, default=None),
                        "over_budget": sum(budget is not None and n > budget for n in loads)},
        "rows": [{"case": r["case"], "expected": r["expected_verdict"], "verdict": r["verdict"],
                  "false_alarms": len(r["violations"]), "misses": len(r["misses"]),
                  "unlisted": len(r["unlisted"]), "tester_load": r.get("tester_load")} for r in real_rows],
    }


def evaluate(results: dict, z: float, min_identity: int, default_budget=None) -> dict:
    rows, real_rows = results.get("cases", []), results.get("real", [])
    budget = (results.get("real_summary") or {}).get("budget", default_budget)
    return {"findings": finding_metrics(rows, z), "per_spec": per_spec(rows),
            "screen": screen_metrics(rows, z, min_identity), "real": real_metrics(real_rows, z, budget)}


def pool(named_results: dict) -> dict:
    """One results dict from several runs. A screen/case or real pair seen in two runs is an error."""
    seen, cases, real, budgets = {}, [], [], set()
    for name, results in named_results.items():
        keys = [(r["screen"], r["case"]) for r in results.get("cases", [])]
        keys += [("real", r["case"]) for r in results.get("real", [])]
        for key in keys:
            if key in seen:
                raise SystemExit(f"--pool: {'/'.join(key)} is in both {seen[key]} and {name}")
            seen[key] = name
        cases += results.get("cases", [])
        real += results.get("real", [])
        if results.get("real"):
            budgets.add((results.get("real_summary") or {}).get("budget"))
    if len(budgets) > 1:
        raise SystemExit(f"--pool: real pairs scored against different budgets {sorted(budgets, key=str)}")
    return {"cases": cases, "real": real, "real_summary": {"budget": budgets.pop() if budgets else None}}


def fmt_rate(r: dict) -> str:
    if r["value"] is None:
        return f"n/a ({r['k']}/{r['n']})"
    lo, hi = r["ci"]
    return f"{r['value']:.3f} [{lo:.3f}, {hi:.3f}] ({r['k']}/{r['n']})"


def fmt_num(v, digits=3) -> str:
    return "n/a" if v is None else (f"{v:.{digits}f}" if isinstance(v, float) else str(v))


SUMMARY_ROWS = [
    ("benchmark cases (defect / identity)",
     lambda e: f"{e['findings']['cases']} ({e['findings']['defect_cases']} / {e['findings']['identity_cases']})"),
    ("lenient TP / FN / FP", lambda e: "{tp} / {fn} / {fp}".format(**e["findings"]["lenient"])),
    ("lenient recall (flagged at edit)", lambda e: fmt_rate(e["findings"]["lenient"]["recall"])),
    ("lenient precision (case TP vs finding FP)", lambda e: fmt_rate(e["findings"]["lenient"]["precision"])),
    ("lenient F1", lambda e: fmt_num(e["findings"]["lenient"]["f1"])),
    ("exact TP / FN / FP", lambda e: "{tp} / {fn} / {fp}".format(**e["findings"]["exact"])),
    ("exact recall (right spec id)", lambda e: fmt_rate(e["findings"]["exact"]["recall"])),
    ("exact precision (case TP vs finding FP)", lambda e: fmt_rate(e["findings"]["exact"]["precision"])),
    ("exact F1", lambda e: fmt_num(e["findings"]["exact"]["f1"])),
    ("false alarms per screen, mean / max",
     lambda e: f"{fmt_num(e['findings']['false_alarms_per_screen']['mean'], 2)} / "
               f"{e['findings']['false_alarms_per_screen']['max']}"),
    ("screens with a false alarm", lambda e: fmt_rate(e["findings"]["false_alarms_per_screen"]["screens_with_false_alarm"])),
    ("screen TP / FN / TN / FP", lambda e: "{tp} / {fn} / {tn} / {fp}".format(**e["screen"])),
    ("screen accuracy", lambda e: fmt_rate(e["screen"]["accuracy"])),
    ("screen sensitivity", lambda e: fmt_rate(e["screen"]["sensitivity"])),
    ("screen specificity", lambda e: fmt_rate(e["screen"]["specificity"])),
    ("REVIEW rate (of flagged screens)", lambda e: fmt_rate(e["screen"]["review_rate"])),
    ("real pairs: verdict exact", lambda e: fmt_rate(e["real"]["verdict_exact"])),
    ("real pairs: false alarms / misses / unlisted",
     lambda e: "{false_alarms} / {misses} / {unlisted}".format(**e["real"])),
    ("real pairs: tester load mean / max (budget), over budget",
     lambda e: f"{fmt_num(e['real']['tester_load']['mean'], 1)} / {fmt_num(e['real']['tester_load']['max'])} "
               f"({fmt_num(e['real']['budget'])}), {e['real']['tester_load']['over_budget']}/{e['real']['pairs']}"),
]


def warnings(ev: dict) -> list:
    return [w for w in [ev["screen"]["warning"]] if w]


def side_by_side(named_evals: dict, level: float) -> list:
    names = list(named_evals)
    header = [f"metric (CI {round(level * 100)}%)"] + names
    cells = [header] + [[label] + [get(named_evals[n]) for n in names] for label, get in SUMMARY_ROWS]
    widths = [max(len(row[i]) for row in cells) for i in range(len(header))]
    line = lambda row: "  ".join(c.ljust(w) for c, w in zip(row, widths))
    out = [line(cells[0]), line(["-" * w for w in widths])] + [line(row) for row in cells[1:]]
    out += [f"warning ({n}): {w}" for n in names for w in warnings(named_evals[n])]
    return out


def to_markdown(title: str, ev: dict, sources: list, level: float) -> str:
    out = [f"# Evaluation: {title}", "", "Sources:"] + [f"- `{p}` (mtime {m})" for p, m in sources]
    out += ["", f"## Summary (Wilson {round(level * 100)}% intervals)", "", "| metric | value |", "|---|---|"]
    out += [f"| {label} | {get(ev)} |" for label, get in SUMMARY_ROWS]
    out += [f"\n**Warning:** {w}" for w in warnings(ev)]
    out += ["", "## Per spec id", "", "| spec id | n | caught | as other | missed | false alarms as this id |",
            "|---|---|---|---|---|---|"]
    out += [f"| {k} | {t['n']} | {t['caught']} | {t['caught as other']} | {t['missed']} | {t['false_alarms']} |"
            for k, t in ev["per_spec"].items()]
    real = ev["real"]
    if real["pairs"]:
        out += ["", "## Real pairs", "", "Verdict confusion (rows: expected, columns: got):", "",
                "| expected \\ got | " + " | ".join(VERDICTS) + " |", "|---|---|---|---|"]
        out += [f"| {e} | " + " | ".join(str(real["confusion"][e][g]) for g in VERDICTS) + " |" for e in VERDICTS]
        out += ["", "| pair | expected | verdict | false alarms | misses | unlisted | tester load |",
                "|---|---|---|---|---|---|---|"]
        out += [f"| {r['case']} | {r['expected']} | {r['verdict']} | {r['false_alarms']} | {r['misses']} | "
                f"{r['unlisted']} | {fmt_num(r['tester_load'])} |" for r in real["rows"]]
    out += ["", "## Definitions", "", DEFINITIONS]
    return "\n".join(out) + "\n"


# --- evaluation.html: inline SVG, no JS, no CDN; same numbers as evaluation.md ----------------
# Colours: the dataviz skill's default palette (validated light + dark). Runs take categorical
# slots in fixed order; the pooled "all" column is drawn in primary ink. Outcomes are states, so
# they use the status palette, always beside a text label. Every mark also has a text value and
# a native <title> tooltip, and the summary table below the charts is the table view.
HTML_CSS = """
:root { color-scheme: light; --bg:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --zero:#f0efec; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300; --s7:#6250d6;
  --s8:#e34948; --good:#0ca30c; --warning:#fab219; --critical:#d03b3b; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark;
  --bg:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --grid:#2c2c2a; --axis:#383835;
  --zero:#383835; --border:rgba(255,255,255,.10); --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --s4:#c98500; --s5:#d55181; --s6:#0ca30c; --s7:#9085e9; --s8:#e66767; } }
:root[data-theme="dark"] { color-scheme: dark; --bg:#0d0d0d; --surface:#1a1a19; --ink:#f0efec;
  --ink2:#c3c2b7; --grid:#2c2c2a; --axis:#383835; --zero:#383835; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#0ca30c; --s7:#9085e9;
  --s8:#e66767; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--ink);
  font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
main { max-width:860px; margin:0 auto; }
h1 { font-size:20px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 4px; }
.muted { color:var(--ink2); font-size:13px; } .warn { color:var(--ink); font-size:13px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:8px; padding:12px; margin-top:8px; }
svg { width:100%; height:auto; display:block; } svg text { font:12px system-ui,-apple-system,"Segoe UI",sans-serif; }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:13px; color:var(--ink2); margin:8px 0 0; }
.legend i { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; vertical-align:-1px; }
table { border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:4px 8px; border-bottom:1px solid var(--grid); vertical-align:top; }
pre { white-space:pre-wrap; font-size:12px; color:var(--ink2); }
"""

INTERVAL_ROWS = [
    ("lenient recall", lambda e: e["findings"]["lenient"]["recall"]),
    ("lenient precision", lambda e: e["findings"]["lenient"]["precision"]),
    ("exact recall", lambda e: e["findings"]["exact"]["recall"]),
    ("exact precision", lambda e: e["findings"]["exact"]["precision"]),
    ("screens with a false alarm", lambda e: e["findings"]["false_alarms_per_screen"]["screens_with_false_alarm"]),
    ("screen sensitivity", lambda e: e["screen"]["sensitivity"]),
    ("screen specificity", lambda e: e["screen"]["specificity"]),
    ("REVIEW rate", lambda e: e["screen"]["review_rate"]),
    ("real pairs: verdict exact", lambda e: e["real"]["verdict_exact"]),
]
OUTCOMES = [("caught", "--good", "caught (right spec id)"), ("caught as other", "--warning", "caught as other id"),
            ("missed", "--critical", "missed")]


def _series_color(names: list, name: str) -> str:
    # ponytail: past 8 runs every lane is still text-labelled, but the colours stop at slot 8.
    if name == "all":
        return "var(--ink)"
    runs = [n for n in names if n != "all"]
    i = runs.index(name)
    return f"var(--s{i + 1})" if i < 8 else "var(--muted)"


def _svg_intervals(named_evals: dict) -> str:
    """Dot = rate, line = Wilson interval; one lane per run under each metric."""
    esc, names = html.escape, list(named_evals)
    x0, x1, lane, gap, top = 330, 560, 18, 10, 26
    sx = lambda v: x0 + v * (x1 - x0)
    height = top + len(INTERVAL_ROWS) * (len(names) * lane + gap)
    out = [f"<svg viewBox='0 0 860 {height}' role='img' aria-label='Rates with confidence intervals'>"]
    for t in (0, 0.25, 0.5, 0.75, 1):
        out.append(f"<line x1='{sx(t)}' y1='{top - 6}' x2='{sx(t)}' y2='{height - gap}' "
                   f"style='stroke:var(--grid)' stroke-width='1'/>"
                   f"<text x='{sx(t)}' y='{top - 12}' text-anchor='middle' style='fill:var(--muted)'>{t:g}</text>")
    y = top
    for label, get in INTERVAL_ROWS:
        out.append(f"<text x='0' y='{y + 13}' style='fill:var(--ink)'>{esc(label)}</text>")
        for name in names:
            r, cy, color = get(named_evals[name]), y + lane / 2, _series_color(names, name)
            out.append(f"<text x='{x0 - 12}' y='{cy + 4}' text-anchor='end' style='fill:var(--ink2)'>{esc(name)}</text>")
            if r["value"] is None:
                out.append(f"<text x='{x0}' y='{cy + 4}' style='fill:var(--muted)'>n/a</text>")
            else:
                lo, hi = r["ci"]
                out.append(f"<g><title>{esc(name)}: {esc(label)} {esc(fmt_rate(r))}</title>"
                           f"<line x1='{sx(lo)}' y1='{cy}' x2='{sx(hi)}' y2='{cy}' style='stroke:{color}' "
                           f"stroke-width='2' stroke-linecap='round'/>"
                           f"<circle cx='{sx(r['value'])}' cy='{cy}' r='4' style='fill:{color};stroke:var(--surface)' "
                           f"stroke-width='2'/><rect x='{sx(lo) - 6}' y='{cy - 9}' width='{sx(hi) - sx(lo) + 12}' "
                           f"height='18' fill='transparent'/></g>")
            out.append(f"<text x='{x1 + 14}' y='{cy + 4}' style='fill:var(--ink2)'>{esc(fmt_rate(r))}</text>")
            y += lane
        y += gap
    return "\n".join(out + ["</svg>"])


def _bar(x, y, w, h, color, round_end, tip) -> str:
    """A bar segment, 4px rounded on its data end only when it is the last segment."""
    r = min(4, w / 2, h / 2) if round_end else 0
    d = (f"M{x},{y} h{w - r} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r} a{r},{r} 0 0 1 {-r},{r} h{-(w - r)} z"
         if r else f"M{x},{y} h{w} v{h} h{-w} z")
    return f"<path d='{d}' style='fill:{color}'><title>{html.escape(tip)}</title></path>"


def _svg_per_spec(per_spec: dict) -> str:
    """Left: defect cases per spec id by outcome. Right, own scale: false-alarm findings as that id."""
    esc, rows = html.escape, list(per_spec.items())
    left, lw, right, rw, row_h, bar_h, top = 60, 270, 520, 220, 26, 14, 28
    max_n = max((t["n"] for _, t in rows), default=0) or 1
    max_fa = max((t["false_alarms"] for _, t in rows), default=0) or 1
    height = top + len(rows) * row_h
    out = [f"<svg viewBox='0 0 860 {height}' role='img' aria-label='Outcomes and false alarms per spec id'>",
           f"<text x='{left}' y='14' style='fill:var(--ink2)'>defect cases by outcome</text>",
           f"<text x='{right}' y='14' style='fill:var(--ink2)'>false alarms flagged as this id (findings)</text>"]
    for i, (spec, t) in enumerate(rows):
        y = top + i * row_h
        out.append(f"<text x='0' y='{y + 11}' style='fill:var(--ink)'>{esc(spec)}</text>")
        segments = [(key, var, t[key]) for key, var, _ in OUTCOMES if t[key]]
        x = left
        for j, (key, var, count) in enumerate(segments):
            w = max(1.0, count / max_n * lw - (2 if j < len(segments) - 1 else 0))  # 2px surface gap
            out.append(_bar(x, y, w, bar_h, f"var({var})", j == len(segments) - 1, f"{spec}: {count} {key}"))
            x += w + 2
        tip = f"{t['caught']}/{t['n']} exact" if t["n"] else "no defect case"
        out.append(f"<text x='{x + 6 if segments else left}' y='{y + 11}' style='fill:var(--ink2)'>{esc(tip)}</text>")
        out.append(f"<line x1='{right}' y1='{y - 3}' x2='{right}' y2='{y + bar_h + 3}' style='stroke:var(--axis)'/>")
        if t["false_alarms"]:
            w = t["false_alarms"] / max_fa * rw
            out.append(_bar(right, y, w, bar_h, "var(--muted)", True, f"{spec}: {t['false_alarms']} false alarm(s)"))
            out.append(f"<text x='{right + w + 6}' y='{y + 11}' style='fill:var(--ink2)'>{t['false_alarms']}</text>")
        else:
            out.append(f"<text x='{right + 6}' y='{y + 11}' style='fill:var(--muted)'>0</text>")
    return "\n".join(out + ["</svg>"])


def _svg_confusion(real: dict) -> str:
    """Real pairs: expected verdict (rows) vs got (columns), count per cell, blue by count."""
    steps = [("#86b6ef", "#0b0b0b"), ("#3987e5", "#ffffff"), ("#1c5cab", "#ffffff")]
    peak = max(n for row in real["confusion"].values() for n in row.values()) or 1
    cw, ch, x0, y0 = 90, 40, 110, 40
    out = [f"<svg viewBox='0 0 {x0 + 3 * cw + 10} {y0 + 3 * ch + 10}' style='max-width:420px' role='img' "
           f"aria-label='Real-pair verdict confusion'>",
           f"<text x='{x0}' y='14' style='fill:var(--ink2)'>got →</text>",
           f"<text x='0' y='{y0 - 8}' style='fill:var(--ink2)'>expected ↓</text>"]
    for j, got in enumerate(VERDICTS):
        out.append(f"<text x='{x0 + j * cw + cw / 2}' y='{y0 - 8}' text-anchor='middle' style='fill:var(--ink)'>{got}</text>")
    for i, exp in enumerate(VERDICTS):
        y = y0 + i * ch
        out.append(f"<text x='0' y='{y + ch / 2 + 4}' style='fill:var(--ink)'>{exp}</text>")
        for j, got in enumerate(VERDICTS):
            n, x = real["confusion"][exp][got], x0 + j * cw
            fill, ink = steps[min(2, math.ceil(n / peak * 3) - 1)] if n else ("var(--zero)", "var(--muted)")
            out.append(f"<g><title>expected {exp}, got {got}: {n}</title><rect x='{x + 1}' y='{y + 1}' "
                       f"width='{cw - 2}' height='{ch - 2}' rx='4' style='fill:{fill}'/><text x='{x + cw / 2}' "
                       f"y='{y + ch / 2 + 4}' text-anchor='middle' style='fill:{ink}'>{n}</text></g>")
    return "\n".join(out + ["</svg>"])


def to_html(title: str, named_evals: dict, main_name: str, sources: list, level: float) -> str:
    esc, ev, names = html.escape, named_evals[main_name], list(named_evals)
    pct = round(level * 100)
    legend = ("" if len(names) < 2 else "<div class='legend'>" + "".join(
        f"<span><i style='background:{_series_color(names, n)}'></i>{esc(n)}</span>" for n in names) + "</div>")
    outcome_legend = "<div class='legend'>" + "".join(
        f"<span><i style='background:var({var});border-radius:2px'></i>{esc(text)}</span>"
        for _, var, text in OUTCOMES) + "<span><i style='background:var(--muted);border-radius:2px'></i>false alarms</span></div>"
    table = ("<table><tr><th>metric</th>" + "".join(f"<th>{esc(n)}</th>" for n in names) + "</tr>"
             + "".join(f"<tr><td>{esc(label)}</td>" + "".join(f"<td>{esc(get(named_evals[n]))}</td>" for n in names)
                       + "</tr>" for label, get in SUMMARY_ROWS) + "</table>")
    warns = "".join(f"<p class='warn'><b>Warning ({esc(n)}):</b> {esc(w)}</p>"
                    for n in names for w in warnings(named_evals[n]))
    out = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           f"<title>Evaluation {esc(title)}</title><style>{HTML_CSS}</style></head><body><main>",
           f"<h1>Evaluation: {esc(title)}</h1>",
           "<p class='muted'>" + "<br>".join(f"{esc(p)} (mtime {esc(m)})" for p, m in sources) + "</p>", warns,
           f"<h2>Rates with Wilson {pct}% intervals</h2><p class='muted'>Dot = the rate, line = its interval. "
           "Precision is case TP vs finding FP. Hover a mark for its counts.</p>",
           legend, f"<div class='card'>{_svg_intervals(named_evals)}</div>",
           f"<h2>Per spec id ({esc(main_name)})</h2>", outcome_legend,
           f"<div class='card'>{_svg_per_spec(ev['per_spec'])}</div>"]
    if ev["real"]["pairs"]:
        out += [f"<h2>Real pairs: verdict confusion ({esc(main_name)})</h2>",
                f"<p class='muted'>{ev['real']['verdict_exact']['k']}/{ev['real']['pairs']} verdicts exact; "
                f"{ev['real']['false_alarms']} false alarms, {ev['real']['misses']} misses, "
                f"{ev['real']['unlisted']} unlisted.</p>", f"<div class='card'>{_svg_confusion(ev['real'])}</div>"]
    out += ["<h2>Table</h2>", f"<div class='card'>{table}</div>",
            f"<h2>Definitions</h2><pre>{esc(DEFINITIONS)}</pre></main></body></html>"]
    return "\n".join(o for o in out if o)


def _write(folder: Path, title: str, ev: dict, sources: list, level: float, compare: dict | None = None):
    """compare: the evaluations drawn side by side in the interval chart (default: just this one)."""
    (folder / "evaluation.json").write_text(json.dumps({"sources": sources, "confidence_level": level, **ev},
                                                       indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "evaluation.md").write_text(to_markdown(title, ev, sources, level), encoding="utf-8")
    compare = compare or {title: ev}
    main_name = next(n for n, e in compare.items() if e is ev)
    (folder / "evaluation.html").write_text(to_html(title, compare, main_name, sources, level), encoding="utf-8")


def main():
    argv = sys.argv[1:]
    do_pool = "--pool" in argv
    dirs = [Path(a) for a in argv if a != "--pool"]
    if not dirs:
        raise SystemExit(__doc__.split("Reads")[0])
    missing = [d for d in dirs if not (d / "results.json").is_file()]
    if missing:  # before any work or writing
        raise SystemExit("no results.json in: " + ", ".join(map(str, missing)))
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    level = cfg["evaluation"]["confidence_level"]
    min_identity = cfg["evaluation"]["min_identity_cases"]
    budget = cfg["benchmark"]["review_budget_per_screen"]
    z = z_value(level)

    if len({d.name for d in dirs}) < len(dirs):
        raise SystemExit("two run dirs share a name: " + ", ".join(map(str, dirs)))
    named_results, sources, evals = {}, {}, {}
    for d in dirs:
        path = d / "results.json"
        named_results[d.name] = json.loads(path.read_text(encoding="utf-8"))
        sources[d.name] = (str(path), datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"))
        print(f"{d.name}: {path} (mtime {sources[d.name][1]})")
    pooled = pool(named_results) if do_pool else None  # refuses duplicates before anything is written
    for d in dirs:
        evals[d.name] = evaluate(named_results[d.name], z, min_identity, budget)
        _write(d, d.name, evals[d.name], [sources[d.name]], level)
    if pooled is not None:
        evals["all"] = evaluate(pooled, z, min_identity, budget)
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        out = OUTPUT_ROOT / f"test{next_test_number(OUTPUT_ROOT)}_evaluation"
        out.mkdir()
        _write(out, "pooled: " + ", ".join(named_results), evals["all"], list(sources.values()), level, evals)
    print()
    print("\n".join(side_by_side(evals, level)))
    print("\nFiles: evaluation.json, .md and .html next to each results.json"
          + (f"; pooled in {out}" if pooled is not None else ""))


if __name__ == "__main__":
    main()
