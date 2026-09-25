# Tests for accepted differences (src/comparison/accepted.py, Phase 14.4).

from src.comparison import accepted
from src.comparison.differ import Difference
from tests.test_group_shift import _el


def _entry(**over):
    e = {"client_screen_id": "home", "type": "TEXT_DIFFERENCE", "client_class": "tab_item",
         "client_text": "Movies", "client_center_norm": [0.2, 0.525],
         "signature": "films", "note": "renamed on purpose", "date": "2026-09-25"}
    return {**e, **over}


def _finding(prod_text="Films"):
    return Difference("TEXT_DIFFERENCE", "p1", "c1",
                      {"production_text": prod_text, "client_text": "Movies"}, "FAIL", "Major")


CLIENT = {"c1": _el("c1", "tab_item", 0.1, 0.5, text="Movies")}  # centre (0.2, 0.525)


def test_accepted_text_finding_becomes_pass():
    d = _finding()
    stale = accepted.apply([d], [_entry()], "home", CLIENT)
    assert d.verdict == "PASS" and d.details["accepted"]["note"] == "renamed on purpose"
    assert stale == []


def test_same_text_on_another_screen_is_not_accepted():
    d = _finding()
    accepted.apply([d], [_entry(client_screen_id="search")], "home", CLIENT)
    assert d.verdict == "FAIL"


def test_a_different_production_text_is_not_covered():
    d = _finding("Cinema")
    accepted.apply([d], [_entry()], "home", CLIENT)
    assert d.verdict == "FAIL"


def test_element_moved_beyond_tolerance_is_not_accepted():
    d = _finding()
    accepted.apply([d], [_entry(client_center_norm=[0.2, 0.6])], "home", CLIENT)
    assert d.verdict == "FAIL"


def test_unused_entry_is_reported_stale():
    stale = accepted.apply([], [_entry()], "home", CLIENT)
    assert [e["note"] for e in stale] == ["renamed on purpose"]


def test_colour_acceptance_tolerates_a_tiny_shade_change():
    d = Difference("COLOR_DIFFERENCE", "p1", "c1",
                   {"production_rgb": [106, 100, 100], "client_rgb": [40, 40, 42]}, "FAIL", "Major")
    entry = _entry(type="COLOR_DIFFERENCE", signature=[105, 99, 99])
    accepted.apply([d], [entry], "home", CLIENT)
    assert d.verdict == "PASS"


def test_entry_round_trips_through_the_file(tmp_path):
    report = {"screen": "home_prod", "client_screen": "home"}
    finding = {"type": "TEXT_DIFFERENCE", "class": "tab_item", "text": "Movies",
               "details": {"production_text": "Films"}, "client_center_norm": [0.2, 0.525]}
    path = tmp_path / "accepted.yaml"
    assert accepted.append(path, [accepted.entry_for(report, finding, "ok")]) == 1
    d = _finding()
    accepted.apply([d], accepted.load(path), "home", CLIENT)
    assert d.verdict == "PASS"


def test_no_file_means_nothing_accepted(tmp_path):
    assert accepted.load(tmp_path / "missing.yaml") == []
