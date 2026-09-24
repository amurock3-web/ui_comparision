"""Score the pipeline on the known-defect benchmark from scripts.make_benchmark.

    python -m scripts.run_benchmark                 # every screen in input/benchmark/
    python -m scripts.run_benchmark ss031 ss012

For each case: detector + OCR + fusion + layout graph (src/pipeline.py) on
the edited "production" image, compared with the untouched client image.
Each case is scored against what its manifest says it should trigger:

  caught           a REVIEW/FAIL finding with the expected test-case id on
                   the edited region
  caught as other  something was flagged on the edited region, but under
                   another test id (e.g. swapped tabs reported as C1 moves)
  missed           nothing flagged there
  pass ok          identity case with no findings
  false alarms     findings away from the edited region (for identity: all)

A miss is attributed to the stage most likely at fault:
  check not built  the test id is not implemented (report.IMPLEMENTED)
  not detected     no element was extracted on the edited region
  comparison       it was extracted, but matching/thresholds let it pass

Output in output/benchmark/testN_benchmark/:
  scorecard.html     the summary page: totals, per-test accuracy, per case
  results.json       the same, machine-readable
  cases/<screen>_<case>.html   the full comparison report of every case
Takes about a minute per case on CPU (OCR dominates).
"""
import html
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from scripts._test_utils import next_test_number
from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import ElementMatcher
from src.pipeline import build_document
from src.reporting.html_report import CSS, VERDICT_COLORS, write_html_report
from src.reporting.report import IMPLEMENTED, ReportGenerator

BENCH_DIR = Path("input/benchmark")
OUTPUT_ROOT = Path("output/benchmark")
OUTCOME_COLORS = {"caught": "#1f9d55", "pass ok": "#1f9d55", "caught as other": "#d97706",
                  "missed": "#dc2626", "false alarm": "#dc2626"}


def near(bbox, el) -> bool:
    """Element's centre inside the edited region (grown by 20% of its size)."""
    if el is None or el.bbox is None:
        return False
    x, y, w, h = bbox
    gx, gy = 0.2 * w, 0.2 * h
    cx, cy = el.bbox[0] + el.bbox[2] / 2, el.bbox[1] + el.bbox[3] / 2
    return x - gx <= cx <= x + w + gx and y - gy <= cy <= y + h + gy


def score(case, report, prod_doc, client_doc) -> dict:
    prod_by_id = {e.id: e for e in prod_doc.elements}
    client_by_id = {e.id: e for e in client_doc.elements}
    findings = report["findings"]
    expected = case["spec_id"]

    if expected is None:
        return {"outcome": "pass ok" if not findings else "false alarm", "cause": None,
                "hit": [], "false_alarms": findings}

    if case["bbox"] is None:  # screen-level defect: anything flagged counts as on-target
        on_target = findings
    else:
        on_target = [f for f in findings
                     if near(case["bbox"], prod_by_id.get(f["production_id"]))
                     or near(case["bbox"], client_by_id.get(f["client_id"]))]
    hit = [f for f in on_target if f["spec_id"] == expected]
    outcome = "caught" if hit else ("caught as other" if on_target else "missed")

    cause = None
    if outcome != "caught":
        extracted = case["bbox"] is None or any(
            near(case["bbox"], e) for e in prod_doc.elements + client_doc.elements
            if not e.metadata.get("ignored"))
        cause = ("check not built" if expected not in IMPLEMENTED
                 else "not detected" if not extracted else "comparison")
    return {"outcome": outcome, "cause": cause, "hit": hit,
            "false_alarms": [f for f in findings if f not in on_target]}


def run_screen(screen_dir: Path, cases_dir: Path) -> list:
    manifest = json.loads((screen_dir / "manifest.json").read_text(encoding="utf-8"))
    screen = manifest["screen"]
    client_image = screen_dir / manifest["client"]
    client_doc, client_graph = build_document(client_image, screen, "client")
    rows = []
    for case in manifest["cases"]:
        print(f"\n=== {screen} / {case['id']} (expect {case['spec_id'] or 'PASS'}) ===")
        prod_image = screen_dir / case["production"]
        prod_doc, prod_graph = build_document(prod_image, f"{screen}_{case['id']}", "production")
        match = ElementMatcher().match(prod_doc, client_doc, prod_graph, client_graph)
        differences = DifferenceEngine().compare(prod_doc, client_doc, prod_graph, client_graph, match)
        report = ReportGenerator().generate(prod_doc, client_doc, differences)
        report_path = write_html_report(report, prod_image, client_image, prod_doc, client_doc,
                                        differences, cases_dir / f"{screen}_{case['id']}.html",
                                        prod_graph, client_graph)
        s = score(case, report, prod_doc, client_doc)
        rows.append({"screen": screen, "case": case["id"], "expected": case["spec_id"],
                     "note": case["note"], "verdict": report["verdict"],
                     "outcome": s["outcome"], "cause": s["cause"],
                     "flagged_as": sorted({f["spec_id"] for f in report["findings"]}),
                     "false_alarms": [{"spec_id": f["spec_id"], "type": f["type"], "class": f["class"],
                                       "text": f["text"], "verdict": f["verdict"]} for f in s["false_alarms"]],
                     "report": str(report_path.relative_to(cases_dir.parent))})
        print(f"-> {s['outcome']}" + (f" ({s['cause']})" if s["cause"] else "")
              + f", {len(s['false_alarms'])} false alarm(s)")
    return rows


def summarise(rows) -> dict:
    defects = [r for r in rows if r["expected"]]
    by_spec = defaultdict(Counter)
    for r in defects:
        by_spec[r["expected"]][r["outcome"]] += 1
    return {
        "cases": len(rows),
        "defect_cases": len(defects),
        "caught": sum(r["outcome"] == "caught" for r in defects),
        "caught_as_other": sum(r["outcome"] == "caught as other" for r in defects),
        "missed": sum(r["outcome"] == "missed" for r in defects),
        "identity_clean": sum(r["outcome"] == "pass ok" for r in rows),
        "identity_cases": sum(1 for r in rows if not r["expected"]),
        "false_alarms": sum(len(r["false_alarms"]) for r in rows),
        "miss_causes": dict(Counter(r["cause"] for r in defects if r["cause"])),
        "by_spec": {k: dict(v) for k, v in sorted(by_spec.items())},
        "false_alarm_types": dict(Counter(f["spec_id"] for r in rows for f in r["false_alarms"])),
    }


def write_scorecard(summary, rows, path: Path):
    esc = html.escape
    pill = lambda text, color: f"<span class='pill' style='background:{color}'>{esc(text)}</span>"
    s = summary
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
           f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Benchmark Scorecard</title><style>{CSS}</style></head><body>",
           "<h1>Benchmark scorecard</h1>",
           f"<div class='muted'>{datetime.now():%Y-%m-%d %H:%M} &middot; {s['cases']} cases on "
           f"{len({r['screen'] for r in rows})} screens. Each case is a copy of a screenshot with one "
           f"known defect (scripts/make_benchmark.py), compared against the untouched screenshot.</div>",
           "<div class='stats'>"
           f"<div class='stat'><b>{s['caught']}/{s['defect_cases']}</b>defects caught</div>"
           f"<div class='stat'><b>{s['caught_as_other']}</b>caught as another test</div>"
           f"<div class='stat'><b>{s['missed']}</b>missed</div>"
           f"<div class='stat'><b>{s['identity_clean']}/{s['identity_cases']}</b>unchanged copies clean</div>"
           f"<div class='stat'><b>{s['false_alarms']}</b>false alarms</div></div>"]

    out.append("<h2>Why defects were missed</h2><table><tr><th>Cause</th><th>Cases</th><th>Meaning</th></tr>")
    meaning = {"check not built": "The test case is not implemented yet; build it.",
               "not detected": "Detector/OCR/fusion produced no element there; fix extraction or retrain.",
               "comparison": "The element was extracted, but matching or thresholds let the change pass."}
    for cause, n in sorted(s["miss_causes"].items(), key=lambda kv: -kv[1]):
        out.append(f"<tr><td>{esc(cause)}</td><td>{n}</td><td>{esc(meaning.get(cause, ''))}</td></tr>")
    out.append("</table>")

    out.append("<h2>Per test case</h2><table><tr><th>Test</th><th>Built</th><th>Caught</th>"
               "<th>As other test</th><th>Missed</th></tr>")
    for spec, c in s["by_spec"].items():
        out.append(f"<tr><td><b>{esc(spec)}</b></td><td>{'yes' if spec in IMPLEMENTED else 'no'}</td>"
                   f"<td>{c.get('caught', 0)}</td><td>{c.get('caught as other', 0)}</td>"
                   f"<td>{c.get('missed', 0)}</td></tr>")
    out.append("</table>")

    if s["false_alarm_types"]:
        out.append("<h2>False alarms by test</h2><p class='muted'>Findings away from the edited region: "
                   "noise the pipeline adds on its own.</p><table><tr><th>Flagged as</th><th>Count</th></tr>")
        for spec, n in sorted(s["false_alarm_types"].items(), key=lambda kv: -kv[1]):
            out.append(f"<tr><td>{esc(str(spec))}</td><td>{n}</td></tr>")
        out.append("</table>")

    out.append("<h2>Every case</h2><table><tr><th>Screen</th><th>Defect</th><th>Expected</th>"
               "<th>Outcome</th><th>Verdict</th><th>Flagged as</th><th>False alarms</th><th>Report</th></tr>")
    for r in rows:
        outcome = r["outcome"] + (f" ({r['cause']})" if r["cause"] else "")
        fa = "<br>".join(esc(f"{f['spec_id']} {f['class']} {f['text'] or ''}".strip())
                         for f in r["false_alarms"]) or "-"
        out.append(f"<tr><td>{esc(r['screen'])}</td><td>{esc(r['case'])}<br>"
                   f"<span class='muted'>{esc(r['note'])}</span></td><td>{esc(r['expected'] or 'PASS')}</td>"
                   f"<td>{pill(outcome, OUTCOME_COLORS[r['outcome']])}</td>"
                   f"<td>{pill(r['verdict'], VERDICT_COLORS[r['verdict']])}</td>"
                   f"<td>{esc(', '.join(map(str, r['flagged_as'])) or '-')}</td><td>{fa}</td>"
                   f"<td><a href='{esc(r['report'])}'>open</a></td></tr>")
    out.append("</table></body></html>")
    path.write_text("\n".join(out), encoding="utf-8")


def main():
    screens = sys.argv[1:] or sorted(p.name for p in BENCH_DIR.iterdir() if (p / "manifest.json").is_file())
    if not screens:
        raise SystemExit(f"no benchmark in {BENCH_DIR} - run: python -m scripts.make_benchmark")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_dir = OUTPUT_ROOT / f"test{next_test_number(OUTPUT_ROOT)}_benchmark"
    cases_dir = out_dir / "cases"
    cases_dir.mkdir(parents=True)

    rows = []
    for screen in screens:
        rows += run_screen(BENCH_DIR / screen, cases_dir)

    summary = summarise(rows)
    (out_dir / "results.json").write_text(json.dumps({"summary": summary, "cases": rows}, indent=2,
                                                     ensure_ascii=False), encoding="utf-8")
    write_scorecard(summary, rows, out_dir / "scorecard.html")
    print(f"\nCaught {summary['caught']}/{summary['defect_cases']}, "
          f"as other {summary['caught_as_other']}, missed {summary['missed']}, "
          f"false alarms {summary['false_alarms']}")
    print(f"Scorecard: {out_dir / 'scorecard.html'}")


if __name__ == "__main__":
    main()
