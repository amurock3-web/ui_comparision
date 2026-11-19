# Tests for Phase 20.1 / 20.2: scripts/evaluate.py on hand-made results.json rows.

import pytest

from scripts.evaluate import evaluate, pool, to_html, wilson, z_value

Z = z_value(0.95)


def _case(outcome, expected="B1", verdict="FAIL", false_alarms=0, screen="s", case=None):
    return {"screen": screen, "case": case or f"{outcome}_{id(object())}", "expected": expected,
            "outcome": outcome, "verdict": verdict,
            "false_alarms": [{"spec_id": "C2", "verdict": "FAIL"}] * false_alarms}


def _identity(verdict="PASS", false_alarms=0, case="identity"):
    return _case("pass ok" if not false_alarms else "false alarm", expected=None, verdict=verdict,
                 false_alarms=false_alarms, case=case)


def _real(expected, verdict, violations=0, load=3):
    return {"case": f"pair_{expected}_{verdict}", "expected_verdict": expected, "verdict": verdict,
            "violations": [{}] * violations, "misses": [], "unlisted": [], "tester_load": load}


def test_known_counts_give_expected_precision_recall_f1():
    rows = [_case("caught", case="a"), _case("caught", case="b"), _case("caught", case="c", false_alarms=1),
            _case("caught as other", case="d"), _case("missed", verdict="PASS", case="e"),
            _identity(verdict="REVIEW", false_alarms=1)]
    f = evaluate({"cases": rows}, Z, 5)["findings"]
    lenient, exact = f["lenient"], f["exact"]
    assert (lenient["tp"], lenient["fn"], lenient["fp"]) == (4, 1, 2)
    assert lenient["recall"]["value"] == pytest.approx(4 / 5)
    assert lenient["precision"]["value"] == pytest.approx(4 / 6)
    assert lenient["f1"] == pytest.approx(16 / 22)
    assert (exact["tp"], exact["fn"], exact["fp"]) == (3, 2, 2)
    assert exact["recall"]["value"] == exact["precision"]["value"] == pytest.approx(3 / 5)
    assert f["false_alarms_per_screen"]["mean"] == pytest.approx(2 / 6)
    assert f["false_alarms_per_screen"]["max"] == 1
    assert f["false_alarms_per_screen"]["screens_with_false_alarm"]["k"] == 2


def test_wilson_17_of_19_matches_hand_calculation():
    # p = 0.8947, z = 1.96: centre (p + z^2/2n)/(1 + z^2/n) = 0.8284, half-width 0.1423
    lo, hi = wilson(17, 19, Z)
    assert lo == pytest.approx(0.6861, abs=1e-3)
    assert hi == pytest.approx(0.9706, abs=1e-3)
    assert wilson(0, 0, Z) is None
    assert wilson(19, 19, Z)[1] == pytest.approx(1.0)


def test_zero_defects_does_not_divide_by_zero_and_precision_is_na():
    for rows in ([_identity()], [_identity(verdict="FAIL", false_alarms=2)], []):
        f = evaluate({"cases": rows}, Z, 5)["findings"]
        for variant in ("lenient", "exact"):
            assert f[variant]["precision"]["value"] is None
            assert f[variant]["recall"]["value"] is None
            assert f[variant]["f1"] is None


def test_per_spec_counts_outcomes_and_false_alarm_ids():
    rows = [_case("caught", expected="B1", case="a"), _case("missed", expected="B1", case="b"),
            _case("caught as other", expected="E1", case="c", false_alarms=1)]
    table = evaluate({"cases": rows}, Z, 5)["per_spec"]
    assert table["B1"] == {"n": 2, "caught": 1, "caught as other": 0, "missed": 1, "false_alarms": 0}
    assert table["E1"]["caught as other"] == 1
    assert table["C2"] == {"n": 0, "caught": 0, "caught as other": 0, "missed": 0, "false_alarms": 1}


def test_screen_matrix_covers_every_cell():
    rows = [_case("caught", verdict="FAIL", case="tp"), _case("missed", verdict="PASS", case="fn"),
            _identity(verdict="PASS", case="tn"), _identity(verdict="REVIEW", false_alarms=1, case="fp")]
    s = evaluate({"cases": rows}, Z, 5)["screen"]
    assert (s["tp"], s["fn"], s["tn"], s["fp"]) == (1, 1, 1, 1)
    assert s["accuracy"]["value"] == s["sensitivity"]["value"] == s["specificity"]["value"] == 0.5
    assert s["review_rate"]["k"] == 1 and s["review_rate"]["n"] == 2  # REVIEW identity / 2 flagged
    assert "2 identity" in s["warning"]
    assert evaluate({"cases": rows}, Z, 2)["screen"]["warning"] is None
    assert evaluate({"cases": []}, Z, 5)["screen"]["warning"] is None  # real-only run


def test_real_pair_with_wrong_verdict_is_counted_once():
    r = evaluate({"cases": [], "real": [_real("REVIEW", "FAIL", violations=2, load=15)],
                  "real_summary": {"budget": 5}}, Z, 5)["real"]
    assert r["confusion"]["REVIEW"]["FAIL"] == 1
    assert sum(n for row in r["confusion"].values() for n in row.values()) == 1
    assert (r["verdict_exact"]["k"], r["verdict_exact"]["n"]) == (0, 1)
    assert r["false_alarms"] == 2
    assert r["tester_load"] == {"mean": 15.0, "max": 15, "over_budget": 1}


def test_pool_combines_runs_and_refuses_duplicates():
    a = {"cases": [_case("caught", screen="ss012", case="rotate")]}
    b = {"cases": [_case("missed", screen="ss031", case="rotate")],
         "real": [_real("REVIEW", "FAIL")], "real_summary": {"budget": 5}}
    pooled = pool({"a": a, "b": b})
    assert len(pooled["cases"]) == 2 and len(pooled["real"]) == 1
    assert pooled["real_summary"]["budget"] == 5
    with pytest.raises(SystemExit, match="ss012/rotate"):
        pool({"a": a, "a2": a})
    with pytest.raises(SystemExit, match="real/"):
        pool({"b": b, "b2": {"real": b["real"], "real_summary": {"budget": 5}}})


def test_html_draws_every_chart_escapes_names_and_handles_na():
    run = evaluate({"cases": [_case("caught", case="a"), _case("missed", verdict="PASS", case="b"), _identity()],
                    "real": [_real("REVIEW", "FAIL")], "real_summary": {"budget": 5}}, Z, 5)
    empty = evaluate({"cases": []}, Z, 5)  # every rate n/a, no real pairs
    page = to_html("t", {"<run>": run, "all": empty}, "<run>", [("results.json", "2026-11-19")], 0.95)
    assert page.count("<svg") == 3  # intervals, per spec, real-pair confusion
    assert "&lt;run&gt;" in page and "<run>" not in page
    assert "n/a" in page
    assert "expected REVIEW, got FAIL: 1" in page
    assert to_html("t", {"all": empty}, "all", [], 0.95).count("<svg") == 2  # no real pairs, no matrix
