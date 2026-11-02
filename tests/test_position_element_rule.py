# Tests for 18.2: C1's element-size rule (P2). On 1080x2340 the diagonal is 2577 px,
# so the bands are pass 25.8 px, fail 77.3 px, major 154.6 px.

import yaml

from src.comparison.differ import DifferenceEngine
from src.comparison.layout_checks import moved_beyond_own_size
from src.comparison.matcher import DEFAULT_CONFIG_PATH, ElementMatcher
from src.schema.ui_element import UIDocument, UIElement
from tests.test_group_shift import _graph

W, H = 1080, 2340
TODAYS_KEYS = {"production_center", "client_center", "distance_of_diagonal", "group_shift", "bands"}


def _el(id_, y, w=200, h=40, x=100, text="Movies", cls="tab_item", **metadata):
    return UIElement(
        id=id_, **{"class": cls}, text=text,
        bbox=[x, y, w, h],
        normalized_bbox=[x / W, y / H, w / W, h / H],
        center=[x + w / 2, y + h / 2],
        confidence=0.9, confidence_tier="high", source="fused", metadata=metadata,
    )


def _doc(elements, source):
    return UIDocument(screen_id="ss_test", source=source, image_width=W, image_height=H,
                      elements=elements)


def _moved(move_px, **el_args):
    y = 1200
    return (_doc([_el("b", y + move_px, **el_args)], "production"),
            _doc([_el("b", y, **el_args)], "client"), _graph({"grp": ["b"]}))


def _run(prod, client, graph, **engine_args):
    config_path = engine_args.get("config_path", DEFAULT_CONFIG_PATH)
    result = ElementMatcher(config_path).match(prod, client, graph, graph)
    return DifferenceEngine(**engine_args).compare(prod, client, graph, graph, result)


def _c1(differences):
    return [d for d in differences if d.type == "POSITION_DIFFERENCE"]


def _rule_off(tmp_path):
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["comparison"]["position_element_rule"]["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def test_small_tab_moved_beyond_its_size_is_a_minor_fail():
    d = _c1(_run(*_moved(45)))[0]
    assert (d.verdict, d.severity) == ("FAIL", "Minor")
    assert d.details["verdict_rule"] == "element" and d.details["rule_fired"] is True
    assert d.details["shift_px"] == 45.0 and d.details["element_min_side_px"] == 40.0


def test_move_below_the_pass_band_is_not_reported():
    assert _c1(_run(*_moved(20))) == []


def test_large_banner_stays_review_on_the_diagonal_band():
    d = _c1(_run(*_moved(60, w=1000, h=400, text="Banner", cls="button")))[0]
    assert (d.verdict, d.severity) == ("REVIEW", None)
    assert d.details["verdict_rule"] == "diagonal" and d.details["rule_fired"] is False


def test_diagonal_fail_is_not_credited_to_the_rule():
    d = _c1(_run(*_moved(100)))[0]  # 3.9%: already FAIL Minor by the diagonal
    assert (d.verdict, d.severity) == ("FAIL", "Minor")
    assert d.details["verdict_rule"] == "diagonal" and d.details["rule_fired"] is True


def test_major_stays_above_six_percent():
    d = _c1(_run(*_moved(200)))[0]
    assert (d.verdict, d.severity) == ("FAIL", "Major")
    assert d.details["verdict_rule"] == "diagonal"


def test_disabled_gives_todays_verdict_and_details(tmp_path):
    d = _c1(_run(*_moved(45), config_path=_rule_off(tmp_path)))[0]
    assert (d.verdict, d.severity) == ("REVIEW", None)
    assert set(d.details) == TODAYS_KEYS


def test_self_compare_passes():
    doc = _doc([_el("b", 1200)], "client")
    differences = _run(doc, doc, _graph({"grp": ["b"]}))
    assert all(d.verdict == "PASS" for d in differences)


def test_floating_region_keeps_its_own_allowance(tmp_path):
    rules = tmp_path / "ss_test.yaml"
    rules.write_text(yaml.safe_dump({"regions": [
        {"name": "promo", "type": "FLOATING", "bbox_norm": [0, 0.4, 1, 0.3],
         "max_offset_norm": 0.015}]}), encoding="utf-8")
    d = _c1(_run(*_moved(45), rules_path=rules))[0]
    assert d.verdict == "REVIEW" and d.details["rule_fired"] is False


def test_vlm_grounded_box_keeps_its_looser_bands():
    d = _c1(_run(*_moved(150, bbox_source="vlm_grounded")))[0]  # 5.8%: REVIEW on the VLM bands
    assert d.verdict == "REVIEW" and d.details["rule_fired"] is False


def _panel(move_px, extra_on=None, extra_px=0):
    ids = [f"t{i}" for i in range(6)]
    client = [_el(i, 400 + 200 * n, text=f"Tab {i}") for n, i in enumerate(ids)]
    prod = [_el(i, 400 + 200 * n + move_px + (i == extra_on) * extra_px, text=f"Tab {i}")
            for n, i in enumerate(ids)]
    return _doc(prod, "production"), _doc(client, "client"), _graph({"grp_panel": ids})


def test_group_shift_stays_on_the_diagonal_bands():
    differences = _run(*_panel(45))  # 45 px on 40 px tabs, but the whole panel moved
    shift = [d for d in differences if d.type == "GROUP_SHIFT"]
    assert len(shift) == 1 and shift[0].verdict == "REVIEW" and "rule_fired" not in shift[0].details
    assert _c1(differences) == []


def test_member_is_judged_on_its_move_within_the_group():
    d = _c1(_run(*_panel(45, extra_on="t2", extra_px=45)))
    assert [x.client_id for x in d] == ["t2"]
    assert d[0].verdict == "FAIL" and d[0].details["shift_px"] == 45.0


def test_cut_off_element_is_capped_back_to_review():
    prod, client, graph = _moved(45)
    graph.nodes["b"]["clipped"] = True
    d = _c1(_run(prod, client, graph))[0]
    assert d.verdict == "REVIEW" and d.details["original_verdict"] == "FAIL"


def test_pure_rule_needs_both_conditions():
    assert moved_beyond_own_size(45, 40, 25.8)
    assert not moved_beyond_own_size(20, 10, 25.8)   # below the pass band
    assert not moved_beyond_own_size(60, 400, 25.8)  # within its own size
    assert not moved_beyond_own_size(45, 40, 25.8, factor=2.0)
