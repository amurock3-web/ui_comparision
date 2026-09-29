"""Score the pipeline on the known-defect benchmark from scripts.make_benchmark.

    python -m scripts.run_benchmark                 # every screen in input/benchmark/
    python -m scripts.run_benchmark ss031 ss012     # those screens only (no real pairs)
    python -m scripts.run_benchmark --real-only     # real pairs only: seconds, cached fused JSONs
    python -m scripts.run_benchmark --cached test3_benchmark   # re-score a saved run: seconds, no OCR

Real pairs (input/benchmark/real/<name>/): a genuine production/client
screenshot pair with production.<ext>, client.<ext>, manifest.json and the
cached production_fused.json / client_fused.json (built once, and saved, when
missing). The manifest lists rules {"spec_id", optional "class", "verdict",
"text_contains"}: must_not_flag (a hit is a false alarm), must_flag (no hit is
a miss), may_flag (tolerated); findings matching none of them are "unlisted"
(counted, not penalised). Plus expected_verdict.

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
from src.graph.layout import LayoutGraphBuilder
from src.pipeline import build_document, compare_documents
from src.reporting.html_report import CSS, VERDICT_COLORS, write_html_report
from src.reporting.report import IMPLEMENTED, ReportGenerator
from src.schema.ui_element import UIDocument

BENCH_DIR = Path("input/benchmark")
REAL_DIR = BENCH_DIR / "real"
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


def _document(image: Path, screen_id: str, side: str, cached: Path | None, name: str):
    """build_document, or with --cached the fused JSON an earlier run saved as `name`.
    A missing file is an error: silently falling back would pay for OCR."""
    if cached is None:
        return build_document(image, screen_id, side)
    path = cached / name
    if not path.is_file():
        raise SystemExit(f"--cached: {path} missing (that run predates the case or the manifest changed)")
    doc = UIDocument.model_validate_json(path.read_text(encoding="utf-8"))
    return doc, LayoutGraphBuilder().build(doc)


def run_screen(screen_dir: Path, cases_dir: Path, cached: Path | None = None) -> list:
    manifest = json.loads((screen_dir / "manifest.json").read_text(encoding="utf-8"))
    screen = manifest["screen"]
    client_image = screen_dir / manifest["client"]
    client_doc, client_graph = _document(client_image, screen, "client", cached, f"{screen}_client_fused.json")
    # Saved so a scoring change can be re-checked with scripts.rematch in
    # seconds instead of paying the ~50 s OCR pass per case all over again.
    client_doc.save_json(cases_dir / f"{screen}_client_fused.json")
    rows = []
    for case in manifest["cases"]:
        print(f"\n=== {screen} / {case['id']} (expect {case['spec_id'] or 'PASS'}) ===")
        prod_image = screen_dir / case["production"]
        prod_doc, prod_graph = _document(prod_image, f"{screen}_{case['id']}", "production", cached,
                                         f"{screen}_{case['id']}_production_fused.json")
        prod_doc.save_json(cases_dir / f"{screen}_{case['id']}_production_fused.json")
        match = ElementMatcher().match(prod_doc, client_doc, prod_graph, client_graph)
        # The images carry the screen-level (A1/A2/A3/A5) and colour (D1/D2/D5)
        # checks; without them a rotated case cannot report A1 at all.
        differences = DifferenceEngine().compare(prod_doc, client_doc, prod_graph, client_graph, match,
                                                 production_image=prod_image, client_image=client_image)
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


def rule_matches(rule: dict, finding: dict) -> bool:
    """Every field the rule gives must match; text_contains is a case-insensitive substring."""
    return (all(rule[k] == finding.get(k) for k in ("spec_id", "class", "verdict") if k in rule)
            and ("text_contains" not in rule
                 or rule["text_contains"].lower() in (finding.get("text") or "").lower()))


def score_real(manifest: dict, report: dict) -> dict:
    findings = report["findings"]
    hits = lambda key, f: any(rule_matches(r, f) for r in manifest.get(key, []))
    return {
        "verdict_ok": report["verdict"] == manifest["expected_verdict"],
        "violations": [f for f in findings if hits("must_not_flag", f)],
        "misses": [r for r in manifest.get("must_flag", []) if not any(rule_matches(r, f) for f in findings)],
        "unlisted": [f for f in findings
                     if not any(hits(k, f) for k in ("must_not_flag", "may_flag", "must_flag"))],
    }


def _real_side(case_dir: Path, side: str):
    """(fused doc, screenshot) for one side; the cached fused JSON skips detector + OCR."""
    image = next(p for p in sorted(case_dir.glob(f"{side}.*")) if p.suffix.lower() != ".json")
    cache = case_dir / f"{side}_fused.json"
    if cache.is_file():
        return UIDocument.model_validate_json(cache.read_text(encoding="utf-8")), image
    doc, _ = build_document(image, case_dir.name, side)
    doc.save_json(cache)
    return doc, image


def run_real(cases_dir: Path) -> list:
    rows = []
    brief = lambda f: {k: f[k] for k in ("spec_id", "verdict", "class", "text")}
    for case_dir in sorted(p for p in REAL_DIR.glob("*") if (p / "manifest.json").is_file()):
        manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
        prod_doc, prod_image = _real_side(case_dir, "production")
        client_doc, client_image = _real_side(case_dir, "client")
        result = compare_documents(prod_doc, client_doc, prod_image, client_image, cases_dir,
                                   f"real_{case_dir.name}")
        report = result["report"]
        s = score_real(manifest, report)
        rows.append({"case": case_dir.name, "note": manifest.get("note", ""),
                     "expected_verdict": manifest["expected_verdict"], "verdict": report["verdict"],
                     "verdict_ok": s["verdict_ok"], "findings": len(report["findings"]),
                     "violations": [brief(f) for f in s["violations"]], "misses": s["misses"],
                     "unlisted": [brief(f) for f in s["unlisted"]],
                     "report": str(Path(result["html_path"]).relative_to(cases_dir.parent))})
        print(f"\n=== real / {case_dir.name}: verdict {report['verdict']} "
              f"(expect {manifest['expected_verdict']}), {len(s['violations'])} false alarm(s), "
              f"{len(s['misses'])} miss(es), {len(s['unlisted'])} unlisted")
        for f in s["violations"]:
            print(f"  false alarm: {f['spec_id']} {f['verdict']} {f['class']} {f['text'] or ''}")
        for r in s["misses"]:
            print(f"  missed: {r}")
        for f in s["unlisted"]:
            print(f"  unlisted: {f['spec_id']} {f['verdict']} {f['class']} {f['text'] or ''}")
    return rows


def summarise_real(rows) -> dict:
    return {"cases": len(rows), "verdict_ok": sum(r["verdict_ok"] for r in rows),
            "false_alarms": sum(len(r["violations"]) for r in rows),
            "misses": sum(len(r["misses"]) for r in rows),
            "unlisted": sum(len(r["unlisted"]) for r in rows)}


def real_section(summary, rows) -> list:
    esc = html.escape
    fmt = lambda f: esc(f"{f['spec_id']} {f.get('verdict') or ''} {f.get('class') or ''} "
                        f"{f.get('text') or f.get('text_contains') or ''}".strip())
    out = ["<h2>Real pairs</h2><p class='muted'>Genuine production/client pairs "
           "(input/benchmark/real/). False alarm = a finding the manifest says must not be flagged; "
           "miss = a must_flag rule nothing matched; unlisted findings are not penalised.</p>",
           "<div class='stats'>"
           f"<div class='stat'><b>{summary['verdict_ok']}/{summary['cases']}</b>verdicts right</div>"
           f"<div class='stat'><b>{summary['false_alarms']}</b>false alarms</div>"
           f"<div class='stat'><b>{summary['misses']}</b>misses</div>"
           f"<div class='stat'><b>{summary['unlisted']}</b>unlisted findings</div></div>",
           "<table><tr><th>Pair</th><th>Verdict</th><th>False alarms</th><th>Misses</th>"
           "<th>Unlisted</th><th>Report</th></tr>"]
    for r in rows:
        out.append(f"<tr><td>{esc(r['case'])}<br><span class='muted'>{esc(r['note'])}</span></td>"
                   f"<td><span class='pill' style='background:{VERDICT_COLORS[r['verdict']]}'>"
                   f"{esc(r['verdict'])}</span> expected {esc(r['expected_verdict'])}"
                   f"{'' if r['verdict_ok'] else ' <b>(wrong)</b>'}</td>"
                   f"<td>{'<br>'.join(map(fmt, r['violations'])) or '-'}</td>"
                   f"<td>{'<br>'.join(map(fmt, r['misses'])) or '-'}</td>"
                   f"<td>{'<br>'.join(map(fmt, r['unlisted'])) or '-'}</td>"
                   f"<td><a href='{esc(r['report'])}'>open</a></td></tr>")
    out.append("</table>")
    return out


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


def write_scorecard(summary, rows, path: Path, real_summary=None, real_rows=()):
    esc = html.escape
    pill = lambda text, color: f"<span class='pill' style='background:{color}'>{esc(text)}</span>"
    s = summary
    head = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Benchmark Scorecard</title><style>{CSS}</style></head><body>",
            "<h1>Benchmark scorecard</h1>"]
    if not rows:  # --real-only
        out = head + [f"<div class='muted'>{datetime.now():%Y-%m-%d %H:%M}</div>"]
        out += real_section(real_summary, real_rows) + ["</body></html>"]
        path.write_text("\n".join(out), encoding="utf-8")
        return
    out = head + [
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
    out.append("</table>")
    if real_rows:
        out += real_section(real_summary, real_rows)
    out.append("</body></html>")
    path.write_text("\n".join(out), encoding="utf-8")


def main():
    argv = sys.argv[1:]
    cached = None
    if "--cached" in argv:
        i = argv.index("--cached")
        cached = OUTPUT_ROOT / argv[i + 1] / "cases"
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if a != "--real-only"]
    real_only = "--real-only" in argv
    screens = [] if real_only else args or sorted(
        p.name for p in BENCH_DIR.iterdir() if (p / "manifest.json").is_file())
    if not screens and not real_only:
        raise SystemExit(f"no benchmark in {BENCH_DIR} - run: python -m scripts.make_benchmark")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    out_dir = OUTPUT_ROOT / f"test{next_test_number(OUTPUT_ROOT)}_benchmark"
    cases_dir = out_dir / "cases"
    cases_dir.mkdir(parents=True)

    rows = []
    for screen in screens:
        rows += run_screen(BENCH_DIR / screen, cases_dir, cached)
    real_rows = run_real(cases_dir) if real_only or not args else []

    summary = summarise(rows)
    real_summary = summarise_real(real_rows)
    (out_dir / "results.json").write_text(json.dumps({"summary": summary, "cases": rows,
                                                      "real_summary": real_summary, "real": real_rows},
                                                     indent=2, ensure_ascii=False), encoding="utf-8")
    write_scorecard(summary, rows, out_dir / "scorecard.html", real_summary, real_rows)
    if rows:
        print(f"\nCaught {summary['caught']}/{summary['defect_cases']}, "
              f"as other {summary['caught_as_other']}, missed {summary['missed']}, "
              f"false alarms {summary['false_alarms']}")
    if real_rows:
        print(f"Real pairs: verdicts right {real_summary['verdict_ok']}/{real_summary['cases']}, "
              f"false alarms {real_summary['false_alarms']}, misses {real_summary['misses']}, "
              f"unlisted {real_summary['unlisted']}")
    print(f"Scorecard: {out_dir / 'scorecard.html'}")


if __name__ == "__main__":
    main()
