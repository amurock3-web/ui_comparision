# Tests for 15.1: dynamic text formats (E1) and floating regions (C1).

import yaml

from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import DEFAULT_CONFIG_PATH, ElementMatcher
from tests.test_group_shift import _doc, _el, _graph


def _pair(p_text, c_text, cls="button", dy=0.0):
    prod = _doc([_el("b", cls, 0.1, 0.5 + dy, text=p_text)], "production")
    client = _doc([_el("b", cls, 0.1, 0.5, text=c_text)], "client")
    return prod, client, _graph({"grp": ["b"]})


def _run(prod, client, graph, **engine_kwargs):
    result = ElementMatcher().match(prod, client, graph, graph)
    return DifferenceEngine(**engine_kwargs).compare(prod, client, graph, graph, result)


def _open(differences, kind):
    return [d for d in differences if d.type == kind and d.verdict != "PASS"]


def test_same_price_format_different_value_passes():
    assert _open(_run(*_pair("₹299/month", "₹199/month")), "TEXT_DIFFERENCE") == []


def test_episode_numbers_may_change():
    assert _open(_run(*_pair("S2 E10", "S1 E3")), "TEXT_DIFFERENCE") == []


def test_broken_format_fails_with_the_expected_format():
    found = _open(_run(*_pair("199", "₹199/month")), "TEXT_DIFFERENCE")
    assert len(found) == 1 and found[0].details["expected_format"] == "price"


def test_plain_labels_are_still_compared():
    assert len(_open(_run(*_pair("Films", "Movies")), "TEXT_DIFFERENCE")) == 1


def test_floating_region_absorbs_a_move_within_its_offset(tmp_path):
    rules = tmp_path / "ss_test.yaml"
    rules.write_text(yaml.safe_dump({"regions": [
        {"name": "promo", "type": "FLOATING", "bbox_norm": [0, 0.4, 1, 0.3],
         "max_offset_norm": 0.03}]}), encoding="utf-8")
    # dy 0.025 of a 1000x1000 screen = 0.0177 of the diagonal: over C1's 0.01 pass
    moved = _pair("Play", "Play", dy=0.025)
    assert len(_open(_run(*moved), "POSITION_DIFFERENCE")) == 1
    assert _open(_run(*moved, rules_path=rules), "POSITION_DIFFERENCE") == []
    far = _pair("Play", "Play", dy=0.06)  # 0.042 of the diagonal: beyond the float
    assert len(_open(_run(*far, rules_path=rules), "POSITION_DIFFERENCE")) == 1


def test_disabled_compares_formatted_text_as_before(tmp_path):
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["comparison"]["dynamic_text"]["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    prod, client, graph = _pair("₹299/month", "₹199/month")
    result = ElementMatcher(path).match(prod, client, graph, graph)
    differences = DifferenceEngine(path).compare(prod, client, graph, graph, result)
    assert len(_open(differences, "TEXT_DIFFERENCE")) == 1
