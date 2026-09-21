from types import SimpleNamespace

from src.comparison.differ import Difference
from src.reporting.report import ReportGenerator, screen_verdict


def _doc(*ids):
    return SimpleNamespace(
        screen_id="s1",
        elements=[SimpleNamespace(id=i, class_="button", text=i) for i in ids],
    )


def test_screen_verdict_precedence():
    minor_fail = Difference("TEXT", "p1", "c1", {}, "FAIL", "Minor")
    review = Difference("MISSING", "p2", None, {}, "REVIEW", "Major")
    major_fail = Difference("MISSING", "p3", None, {}, "FAIL", "Major")

    assert screen_verdict([]) == "PASS"
    assert screen_verdict([minor_fail]) == "PASS"
    assert screen_verdict([minor_fail, review]) == "REVIEW"
    assert screen_verdict([review, major_fail]) == "FAIL"


def test_report_lists_only_non_pass_findings():
    diffs = [
        Difference("MATCH", "p1", "c1", {}),
        Difference("TEXT", "p2", "c2", {"prod": "a", "client": "b"}, "FAIL", "Minor"),
    ]
    report = ReportGenerator().generate(_doc("p1", "p2"), _doc("c1", "c2"), diffs)

    assert report["verdict"] == "PASS"
    assert report["warnings"] == 1
    assert report["similarity_percent"] == 50.0
    assert report["summary"] == {"total_compared": 2, "MATCH": 1, "TEXT": 1}
    assert [f["client_id"] for f in report["findings"]] == ["c2"]
