import csv
import json

from src.reporting.export import DEFAULT_COLUMNS, to_ticket_rows, write_csv


def _f(verdict="FAIL", text="Home", details=None):
    return {"type": "colour", "spec_id": "C-01", "verdict": verdict, "severity": "Major",
            "production_id": "p1", "client_id": "c1", "class": "tab_item", "text": text, "details": details or {}}


def _report(tmp_path, findings, issues=None):
    report = {"screen": "home", "verdict": "FAIL", "similarity_percent": 80.0, "summary": {}, "findings": findings}
    if issues is not None:
        report["issues"] = issues
    run = tmp_path / "run7"
    run.mkdir(exist_ok=True)
    path = run / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return report, str(path)


def _issue(n, idx, verdict="FAIL"):
    return {"issue_id": f"issue_{n:03d}", "type": "colour", "spec_id": "C-01", "class": "tab_item",
            "count": len(idx), "verdict": verdict, "severity": "Major", "finding_indices": idx, "summary": f"{len(idx)} x tab_item colour"}


def test_one_row_per_issue(tmp_path):
    report, path = _report(tmp_path, [_f(), _f(), _f()], [_issue(1, [0, 1]), _issue(2, [2])])
    rows = to_ticket_rows(report, path, DEFAULT_COLUMNS)
    assert len(rows) == 2
    assert rows[0]["run_id"] == "run7" and rows[0]["count"] == 2 and len(rows[0]["date"]) == 10


def test_accepted_finding_excluded(tmp_path):
    report, path = _report(tmp_path, [_f(), _f(details={"accepted": {"by": "qa"}}), _f(details={"ignored": "dynamic"})],
                           [_issue(1, [0, 1]), _issue(2, [2])])
    rows = to_ticket_rows(report, path, DEFAULT_COLUMNS)
    assert len(rows) == 1 and rows[0]["count"] == 1


def test_pass_excluded(tmp_path):
    report, path = _report(tmp_path, [_f("PASS"), _f("REVIEW")], [_issue(1, [0], "PASS"), _issue(2, [1], "REVIEW")])
    rows = to_ticket_rows(report, path, DEFAULT_COLUMNS)
    assert [r["verdict"] for r in rows] == ["REVIEW"]


def test_fallback_to_findings(tmp_path):
    report, path = _report(tmp_path, [_f(), _f("PASS"), _f("REVIEW", text="Movies")])
    rows = to_ticket_rows(report, path, DEFAULT_COLUMNS)
    assert [r["element_text"] for r in rows] == ["Home", "Movies"]
    assert all(r["count"] == 1 for r in rows)


def test_tamil_and_rupee_round_trip(tmp_path):
    text = "முகப்பு ₹149"
    report, path = _report(tmp_path, [_f(text=text)], [_issue(1, [0])])
    rows = to_ticket_rows(report, path, DEFAULT_COLUMNS)
    out = tmp_path / "t.csv"
    write_csv(rows, DEFAULT_COLUMNS, out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")
    with open(out, encoding="utf-8-sig", newline="") as f:
        assert next(csv.DictReader(f))["element_text"] == text


def test_column_order(tmp_path):
    report, path = _report(tmp_path, [_f()], [_issue(1, [0])])
    cols = ["description", "severity", "screen"]
    rows = to_ticket_rows(report, path, cols)
    assert list(rows[0]) == cols
    out = tmp_path / "t.csv"
    write_csv(rows, cols, out)
    assert out.read_text(encoding="utf-8-sig").splitlines()[0] == "description,severity,screen"
