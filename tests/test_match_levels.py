# Tests for match levels and regions (src/comparison/regions.py, Phase 15.0).
# A level decides which spec families may produce findings; a region relaxes
# (or tightens) only the elements inside it; skipped is never reported as PASS.

import pytest

from src.comparison.differ import Difference
from src.comparison.regions import apply_match_levels, level_for, load_rules
from src.reporting.report import coverage, spec_id
from src.schema.ui_element import UIElement

SKIP = {"STRICT": [], "LAYOUT": ["D", "E", "F"], "IGNORE_COLORS": ["D"]}


def _el(id_, x, y, w=0.1, h=0.05):
    return UIElement(id=id_, **{"class": "button"}, text="Play",
                     bbox=[x * 1000, y * 1000, w * 1000, h * 1000],
                     normalized_bbox=[x, y, w, h], center=[0, 0],
                     confidence=0.9, confidence_tier="high", source="fused")


def _rules(level="STRICT", regions=()):
    return {"match_level": level, "regions": list(regions), "source": None}


def _apply(differences, rules, elements):
    by_id = {e.id: e for e in elements}
    return apply_match_levels(differences, rules, SKIP,
                              element_of=lambda d: by_id.get(d.client_id),
                              spec_of=spec_id)


def _findings():
    return [Difference("TEXT_DIFFERENCE", "p1", "c1", {}, "FAIL", "Major"),
            Difference("COLOR_DIFFERENCE", "p1", "c1", {}, "FAIL", "Major"),
            Difference("POSITION_DIFFERENCE", "p1", "c1", {}, "FAIL", "Major")]


def _open(differences):
    return sorted(d.type for d in differences if d.verdict != "PASS")


def test_layout_skips_text_and_colour_but_keeps_position():
    out = _apply(_findings(), _rules("LAYOUT"), [_el("c1", 0.1, 0.5)])
    assert _open(out) == ["POSITION_DIFFERENCE"]
    assert out[0].details["ignored"] == "match level LAYOUT"


def test_ignore_colors_skips_only_colour():
    out = _apply(_findings(), _rules("IGNORE_COLORS"), [_el("c1", 0.1, 0.5)])
    assert _open(out) == ["POSITION_DIFFERENCE", "TEXT_DIFFERENCE"]


def test_region_relaxes_only_the_elements_inside_it():
    hero = {"name": "hero", "type": "LAYOUT", "bbox_norm": [0, 0.4, 1, 0.3]}
    inside, outside = _el("c1", 0.1, 0.5), _el("c2", 0.1, 0.9)
    diffs = _findings() + [Difference("TEXT_DIFFERENCE", "p2", "c2", {}, "FAIL", "Major")]
    out = _apply(diffs, _rules("STRICT", [hero]), [inside, outside])
    assert [d.client_id for d in out if d.type == "TEXT_DIFFERENCE" and d.verdict != "PASS"] == ["c2"]


def test_none_region_ignores_everything_inside():
    band = {"name": "status_bar", "type": "NONE", "bbox_norm": [0, 0, 1, 0.04], "min_overlap": 0.5}
    assert level_for([0.1, 0.0, 0.1, 0.03], _rules("STRICT", [band])) == "NONE"
    assert level_for([0.1, 0.03, 0.1, 0.05], _rules("STRICT", [band])) == "STRICT"  # 20% inside
    missing = [Difference("MISSING_IN_PRODUCTION", None, "c1", {}, "FAIL", "Critical")]
    assert _open(_apply(missing, _rules("STRICT", [band]), [_el("c1", 0.1, 0.0, h=0.03)])) == []


def test_smallest_covering_region_wins():
    rules = _rules("STRICT", [{"name": "page", "type": "LAYOUT", "bbox_norm": [0, 0, 1, 1]},
                              {"name": "cta", "type": "STRICT", "bbox_norm": [0, 0.4, 0.5, 0.3]}])
    assert level_for([0.1, 0.5, 0.1, 0.05], rules) == "STRICT"
    assert level_for([0.7, 0.9, 0.1, 0.05], rules) == "LAYOUT"


def test_strict_changes_nothing():
    out = _apply(_findings(), _rules("STRICT"), [_el("c1", 0.1, 0.5)])
    assert _open(out) == ["COLOR_DIFFERENCE", "POSITION_DIFFERENCE", "TEXT_DIFFERENCE"]


def test_coverage_says_skipped_not_pass():
    rows = {r["id"]: r for r in coverage([], skipped=("D", "E", "F"), level="LAYOUT")}
    assert rows["E1"]["status"] == "skipped (LAYOUT)" and rows["E1"]["result"] is None
    assert rows["C1"]["status"] == "checked" and rows["C1"]["result"] == "PASS"


def test_rules_file_is_found_by_screen_id_and_overridable(tmp_path):
    (tmp_path / "home.yaml").write_text(
        "match_level: layout\nregions:\n  - {name: promo, type: none, bbox_norm: [0, 0.8, 1, 0.1]}\n",
        encoding="utf-8")
    rules = load_rules("home", tmp_path)
    assert rules["match_level"] == "LAYOUT" and rules["regions"][0]["type"] == "NONE"
    assert load_rules("home", tmp_path, level_override="STRICT")["match_level"] == "STRICT"
    assert load_rules("other", tmp_path)["match_level"] == "STRICT"
    with pytest.raises(ValueError):
        (tmp_path / "bad.yaml").write_text("match_level: FUZZY\n", encoding="utf-8")
        load_rules("bad", tmp_path)
