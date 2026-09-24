# Tests for src/reporting/report.py — screen verdict, findings filter and the
# element-count summary (matched pairs, not Difference records; design.md §12).

from src.comparison.differ import Difference
from src.reporting.report import ReportGenerator, screen_verdict
from src.schema.ui_element import UIDocument, UIElement

W, H = 1000, 1000


def _el(id_, cls="button", bbox=(10, 10, 100, 40), text=None):
    x, y, w, h = bbox
    return UIElement(
        id=id_,
        **{"class": cls},
        text=text,
        bbox=[float(v) for v in bbox],
        normalized_bbox=[x / W, y / H, w / W, h / H],
        center=[x + w / 2, y + h / 2],
        confidence=0.9,
        confidence_tier="high",
        source="fused",
    )


def _doc(ids, source="production"):
    return UIDocument(screen_id="ss_test", source=source, image_width=W, image_height=H,
                      elements=[_el(i) for i in ids])


def _summary(differences, prod_ids=(), client_ids=()):
    report = ReportGenerator().generate(_doc(prod_ids), _doc(client_ids, source="client"), differences)
    return report["summary"]


# ---- screen verdict / findings ------------------------------------------


def test_screen_verdict_precedence():
    minor_fail = Difference("TEXT_DIFFERENCE", "p1", "c1", {}, "FAIL", "Minor")
    review = Difference("MISSING_IN_PRODUCTION", None, "c2", {}, "REVIEW", "Major")
    major_fail = Difference("MISSING_IN_PRODUCTION", None, "c3", {}, "FAIL", "Major")

    assert screen_verdict([]) == "PASS"
    assert screen_verdict([minor_fail]) == "PASS"
    assert screen_verdict([minor_fail, review]) == "REVIEW"
    assert screen_verdict([review, major_fail]) == "FAIL"


def test_report_lists_only_non_pass_findings():
    diffs = [
        Difference("MATCH", "p1", "c1", {"score": 1.0}),
        Difference("TEXT_DIFFERENCE", "p2", "c2", {"prod": "a", "client": "b"}, "FAIL", "Minor"),
    ]
    report = ReportGenerator().generate(_doc(["p1", "p2"]), _doc(["c1", "c2"], "client"), diffs)

    assert report["verdict"] == "PASS"
    assert report["warnings"] == 1
    assert [f["client_id"] for f in report["findings"]] == ["c2"]
    # Both pairs matched; one of them differs, so it is matched but not clean.
    assert report["summary"]["matched_pairs"] == 2
    assert report["summary"]["clean_pairs"] == 1
    assert report["similarity_percent"] == 100.0


# ---- element-count summary ----------------------------------------------


def test_one_pair_with_three_sub_differences_counts_as_one_matched_element():
    # The bug this replaced counted records: 3 findings and no MATCH record
    # read as "0 matched of 3 compared" for a single matched element.
    diffs = [
        Difference("TEXT_DIFFERENCE", "p1", "c1", {}, "FAIL", "Major"),
        Difference("POSITION_DIFFERENCE", "p1", "c1", {}, "FAIL", "Major"),
        Difference("SIZE_DIFFERENCE", "p1", "c1", {}, "REVIEW", "Minor"),
    ]
    s = _summary(diffs, ["p1"], ["c1"])

    assert s["matched_pairs"] == 1
    assert s["clean_pairs"] == 0
    assert s["comparable"] == 1
    assert s["similarity_percent"] == 100.0
    assert s["clean_percent"] == 0.0
    assert s["difference_records"] == 3


def test_self_compare_is_fully_matched_and_clean():
    ids = [(f"p{i}", f"c{i}") for i in range(5)]
    diffs = [Difference("MATCH", p, c, {"score": 1.0}) for p, c in ids]
    s = _summary(diffs, [p for p, _ in ids], [c for _, c in ids])

    assert s["matched_pairs"] == 5
    assert s["similarity_percent"] == 100.0
    assert s["clean_percent"] == 100.0


def test_ignored_missing_and_extra_stay_out_of_the_denominator():
    # §H dynamic content is never compared, so it can neither help nor hurt
    # the percentage — it is only reported as `ignored`.
    diffs = [
        Difference("MATCH", "p1", "c1", {"score": 1.0}),
        Difference("MISSING_IN_PRODUCTION", None, "c_clock", {"ignored": "dynamic content"}, "PASS"),
        Difference("EXTRA_IN_PRODUCTION", "p_poster", None, {"ignored": "dynamic content"}, "PASS"),
    ]
    s = _summary(diffs, ["p1", "p_poster"], ["c1", "c_clock"])

    assert (s["missing"], s["extra"], s["ignored"]) == (0, 0, 2)
    assert s["comparable"] == 1
    assert s["similarity_percent"] == 100.0


def test_dynamic_only_matched_pair_leaves_the_denominator():
    # A poster tile the differ matched but skipped as dynamic content (§H) was
    # never really compared, so it must not count as matched or clean — only
    # the real chrome pair does.
    diffs = [
        Difference("MATCH", "p_tab", "c_tab", {"score": 0.98}),
        Difference("MATCH", "p_tile", "c_tile", {"score": 0.9, "ignored": "dynamic content"}),
    ]
    s = _summary(diffs, ["p_tab", "p_tile"], ["c_tab", "c_tile"])

    assert (s["matched_pairs"], s["clean_pairs"]) == (1, 1)
    assert s["ignored"] == 1
    assert s["comparable"] == 1
    assert s["similarity_percent"] == 100.0


def test_language_pair_numbers_match_the_element_count_spec():
    # The real run that reported 0.0%: 7 matched pairs (53 records between
    # them), 18 genuinely missing and 14 genuinely extra elements → 7/39.
    diffs = [Difference("MATCH", f"p{i}", f"c{i}", {"score": 0.9}) for i in range(7)]
    diffs += [Difference("MISSING_IN_PRODUCTION", None, f"cm{i}", {}, "FAIL", "Major") for i in range(18)]
    diffs += [Difference("EXTRA_IN_PRODUCTION", f"pe{i}", None, {}, "FAIL", "Major") for i in range(14)]
    s = _summary(diffs, [f"p{i}" for i in range(7)], [f"c{i}" for i in range(7)])

    assert (s["matched_pairs"], s["missing"], s["extra"]) == (7, 18, 14)
    assert s["comparable"] == 39
    assert s["similarity_percent"] == 17.9
    assert s["clean_percent"] == 17.9


def test_empty_comparison_is_zero_percent_with_a_warning():
    report = ReportGenerator().generate(_doc([]), _doc([], "client"), [])

    assert report["similarity_percent"] == 0.0
    assert report["summary"]["clean_percent"] == 0.0
    assert report["summary"]["warning"]
