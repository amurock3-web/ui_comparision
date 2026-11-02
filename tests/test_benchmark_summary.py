# Tests for 18.4: scorecard summary, tester load (P3, P4, P6) and --compare-to.

import json

import yaml

from scripts.run_benchmark import (compare_runs, flagged_elements, load_previous, score_real,
                                   summarise, summarise_real)
from scripts.run_benchmark import tester_load as load_of  # pytest would collect test*
from src.comparison.matcher import DEFAULT_CONFIG_PATH


def _case(outcome, case="c", screen="s", false_alarms=()):
    return {"screen": screen, "case": case, "expected": "E1", "outcome": outcome,
            "cause": None, "false_alarms": list(false_alarms)}


def _finding(verdict="REVIEW", client_id="a", production_id=None):
    return {"verdict": verdict, "client_id": client_id, "production_id": production_id}


def _real_row(load, case="pair"):
    return {"case": case, "verdict_ok": False, "violations": [], "misses": [], "unlisted": [],
            "tester_load": load, "findings": load + 1, "flagged_elements": load - 1,
            "over_budget": load > 5}


def _previous(cases=(), real_rows=(), false_alarms=0):
    summary = summarise(list(cases))
    summary["false_alarms"] = false_alarms
    return {"summary": summary, "cases": list(cases),
            "real_summary": summarise_real(list(real_rows), 5), "real": list(real_rows)}


def _compare(previous, rows=(), real_rows=()):
    return compare_runs("old", previous, summarise(list(rows)), list(rows),
                        summarise_real(list(real_rows), 5), list(real_rows))


def _line(lines, label):
    return next(x for x in lines if x.startswith(label))


def test_budget_is_in_config():
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    assert cfg["benchmark"]["review_budget_per_screen"] == 5


def test_summary_counts_lenient_and_exact_apart():
    s = summarise([_case("caught"), _case("caught"), _case("caught as other"), _case("missed")])
    assert (s["flagged_at_edit"], s["caught"], s["defect_cases"]) == (3, 2, 4)
    assert s["exact_id_percent"] == 50


def test_percent_matches_the_comparison_line():
    # 17/19 is 89.47%: rounded once it is 89 in both places, not 89.5 then 90.
    rows = [_case("caught", str(i)) for i in range(17)] + [_case("caught as other", "x"), _case("caught as other", "y")]
    assert summarise(rows)["exact_id_percent"] == 89
    assert "17/19 89%" in _line(_compare(_previous(rows), rows), "exact spec id")


def test_summary_with_no_defect_cases_has_no_rate():
    assert summarise([])["exact_id_percent"] == 0


def test_tester_load_counts_every_issue_including_unlisted():
    manifest = {"expected_verdict": "REVIEW", "must_flag": [{"spec_id": "D3"}],
                "may_flag": [{"spec_id": "C2"}], "must_not_flag": [{"spec_id": "D1"}]}
    findings = [{"spec_id": s, "verdict": "REVIEW", "class": None, "text": None}
                for s in ("D3", "C2", "D1", "E1")]
    report = {"verdict": "REVIEW", "findings": findings,
              "issues": [{"verdict": "REVIEW"} for _ in findings]}
    assert len(score_real(manifest, report)["unlisted"]) == 1
    assert load_of(report) == 4


def test_tester_load_uses_issues_not_findings():
    report = {"findings": [_finding(), _finding()], "issues": [{"verdict": "FAIL"}]}
    assert load_of(report) == 1


def test_tester_load_without_issues_counts_findings():
    assert load_of({"findings": [_finding(), _finding("FAIL")]}) == 2


def test_flagged_elements_counts_each_element_once_and_skips_screen_level():
    report = {"findings": [_finding(client_id="a"), _finding("FAIL", client_id="a"),
                           _finding(client_id=None, production_id="p"),
                           _finding("FAIL", client_id=None)]}
    assert flagged_elements(report) == 2


def test_over_budget_at_six_not_five():
    s = summarise_real([_real_row(5, "a"), _real_row(6, "b")], 5)
    assert s["pairs_over_budget"] == 1
    assert (s["max_tester_load"], s["mean_tester_load"], s["budget"]) == (6, 5.5, 5)


def test_real_summary_with_no_pairs():
    s = summarise_real([], 5)
    assert (s["max_tester_load"], s["mean_tester_load"], s["pairs_over_budget"]) == (0, 0.0, 0)


def test_compare_marks_a_drop_in_exact_id():
    rows = [_case("caught as other", "a"), _case("caught", "b")]
    lines = _compare(_previous([_case("caught", "a"), _case("caught", "b")]), rows)
    assert _line(lines, "exact spec id").endswith("<< DROP")
    assert "<<" not in _line(lines, "flagged at edit")


def test_compare_marks_a_drop_in_the_headline():
    rows = [_case("missed", "a"), _case("caught", "b")]
    lines = _compare(_previous([_case("caught", "a"), _case("caught", "b")]), rows)
    assert _line(lines, "flagged at edit").endswith("<< DROP")


def test_compare_marks_a_rise_in_false_alarms():
    rows = [_case("caught", "a", false_alarms=[{"spec_id": "B2"}])]
    lines = _compare(_previous([_case("caught", "a")]), rows)
    assert _line(lines, "false alarms").endswith("<< RISE")


def test_compare_shows_a_swap_that_nets_to_zero():
    previous = _previous([_case("caught", "a"), _case("caught as other", "b")])
    lines = _compare(previous, [_case("caught as other", "a"), _case("caught", "b")])
    assert "<<" not in _line(lines, "exact spec id")
    assert "  s/a: caught -> caught as other" in lines
    assert "  s/b: caught as other -> caught" in lines


def test_compare_with_nothing_changed_marks_nothing():
    rows = [_case("caught", "a")]
    lines = _compare(_previous(rows), rows)
    assert not any("<<" in x for x in lines) and "outcome changes: none" in lines


def test_compare_notes_different_cases():
    lines = _compare(_previous([_case("caught", "a")]), [_case("caught", "b")])
    assert any(x.startswith("note: different cases") for x in lines)


def test_compare_real_pair_shows_load_and_marks_false_alarms():
    row = {**_real_row(9), "violations": [{"spec_id": "D1"}]}
    lines = _compare(_previous(real_rows=[_real_row(7)]), real_rows=[row])
    assert _line(lines, "real false alarms").endswith("<< RISE")
    assert _line(lines, "pair tester_load").split()[-2:] == ["7", "9"]


def test_compare_says_when_the_previous_run_lacks_the_section():
    assert "previous run has no real pairs" in _compare(_previous([_case("caught")]), real_rows=[_real_row(3)])
    assert "previous run has no benchmark cases" in _compare(_previous(real_rows=[_real_row(3)]), [_case("caught")])


def _saved_run(tmp_path, with_report):
    row = {"case": "pair", "report": "cases/real_pair_report.html", "findings": 3,
           "violations": [], "misses": [], "unlisted": []}
    (tmp_path / "results.json").write_text(json.dumps(
        {"summary": {"cases": 0}, "cases": [], "real_summary": {"cases": 1, "false_alarms": 0}, "real": [row]}),
        encoding="utf-8")
    if with_report:
        (tmp_path / "cases").mkdir()
        (tmp_path / "cases/real_pair_report.json").write_text(json.dumps(
            {"findings": [_finding(), _finding(), _finding(client_id="b")],
             "issues": [{"verdict": "REVIEW"}, {"verdict": "FAIL"}]}), encoding="utf-8")


def test_old_run_gets_its_load_from_the_saved_report(tmp_path):
    _saved_run(tmp_path, with_report=True)
    row = load_previous(tmp_path)["real"][0]
    assert (row["tester_load"], row["flagged_elements"]) == (2, 2)


def test_old_run_without_a_report_prints_na(tmp_path):
    _saved_run(tmp_path, with_report=False)
    lines = _compare(load_previous(tmp_path), real_rows=[_real_row(3)])
    assert _line(lines, "pair tester_load").split()[-2:] == ["n/a", "3"]
    assert _line(lines, "pair findings").split()[-2:] == ["3", "4"]
