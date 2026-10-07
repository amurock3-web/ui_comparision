# Phase 14b false-alarm fixes, from the Trending Search run (output/app/20260925_145307):
# F1 badges on a card are dynamic, F2 rescue pass, F3 clipped -> REVIEW, F4 glyph cleanup in
# E1 and matching, and E1 on an unread label.

import networkx as nx

from src.comparison.differ import Difference, DifferenceEngine
from src.comparison.matcher import ElementMatcher, _is_dynamic
from tests.test_group_shift import _doc, _el, _graph


def _run(prod_els, client_els, graph=None):
    prod, client = _doc(prod_els, "production"), _doc(client_els, "client")
    graph = graph if graph is not None else _graph({"grp": [e.id for e in client_els]})
    result = ElementMatcher().match(prod, client, graph, graph)
    return result, DifferenceEngine().compare(prod, client, graph, graph, result)


def _open(differences, kind=None):
    return [d for d in differences if d.verdict != "PASS" and (kind is None or d.type == kind)]


# ---- F1 ----------------------------------------------------------------

def test_badge_on_a_card_without_parent_is_dynamic():
    card = _el("card", "content_card", 0.1, 0.1, w=0.4, h=0.3)
    badge = _el("b", "overlay_badge", 0.4, 0.12, w=0.08, h=0.04, text="Free")  # fully inside
    by_id = {e.id: e for e in (card, badge)}
    assert _is_dynamic(badge, by_id)
    assert not _is_dynamic(badge, by_id, on_card_overlap=None)  # switched off


def test_extra_badge_on_a_card_is_ignored_but_off_card_still_fails():
    card = _el("card", "content_card", 0.1, 0.1, w=0.4, h=0.3)
    on_card = _el("b1", "overlay_badge", 0.4, 0.12, w=0.08, h=0.04, text="Free")
    header_chip = _el("b2", "overlay_badge", 0.7, 0.8, w=0.08, h=0.04, text="Free")
    _, differences = _run([card, on_card, header_chip], [_el("card", "content_card", 0.1, 0.1, w=0.4, h=0.3)])
    extra = _open(differences, "EXTRA_IN_PRODUCTION")
    assert [d.production_id for d in extra] == ["b2"]


# ---- F2 ----------------------------------------------------------------

def test_same_element_with_unread_text_is_rescued_not_missing_and_extra():
    client = [_el("s", "search_bar", 0.05, 0.85, w=0.9, h=0.05, text="Search Movies, TV shows")]
    prod = [_el("s", "search_bar", 0.05, 0.835, w=0.9, h=0.055, text=None)]
    result, differences = _run(prod, client)
    assert [m.match_pass for m in result.matches] == [3]
    assert _open(differences, "MISSING_IN_PRODUCTION") == []
    assert _open(differences, "EXTRA_IN_PRODUCTION") == []


def test_two_equal_candidates_stay_unmatched_as_review():
    client = [_el("c", "button", 0.40, 0.50, text="Play")]
    prod = [_el("p1", "button", 0.39, 0.52, text=None), _el("p2", "button", 0.41, 0.48, text=None)]
    result, differences = _run(prod, client)
    assert result.matches == []
    assert {d.verdict for d in differences if d.type in ("MISSING_IN_PRODUCTION",
                                                          "EXTRA_IN_PRODUCTION")} == {"REVIEW"}


def test_different_classes_or_far_apart_are_not_rescued():
    client = [_el("c", "button", 0.4, 0.5, text="Play")]
    assert _run([_el("p", "tab_item", 0.4, 0.51)], client)[0].matches == []
    assert _run([_el("p", "button", 0.4, 0.8)], client)[0].matches == []


# ---- F3 ----------------------------------------------------------------

def test_fail_on_a_clipped_element_is_capped_at_review():
    graph = nx.DiGraph()
    graph.add_node("c1", clipped=True)
    d = Difference("COLOR_DIFFERENCE", "p1", "c1", {}, "FAIL", "Major")
    DifferenceEngine()._cap_clipped([d], None, graph)
    assert d.verdict == "REVIEW" and d.details["original_severity"] == "Major"


# ---- F4 + unread text ------------------------------------------------------

def test_icon_glyph_in_a_tab_label_is_not_a_text_difference():
    client = [_el("t", "tab_item", 0.6, 0.9, text="Languages")]
    prod = [_el("t", "tab_item", 0.6, 0.9, text="9 Languages")]
    assert _open(_run(prod, client)[1], "TEXT_DIFFERENCE") == []


def test_unread_label_is_review_not_fail():
    client = [_el("t", "button", 0.4, 0.5, text="Play")]
    prod = [_el("t", "button", 0.4, 0.5, text=None)]
    found = _open(_run(prod, client)[1], "TEXT_DIFFERENCE")
    assert [d.verdict for d in found] == ["REVIEW"]


# ---- Phase 17 fixes --------------------------------------------------------

def test_known_non_card_parent_wins_over_geometry():
    # JioHotstar: the floating TV/Movies/Sports pill lies over a poster row.
    card = _el("card", "content_card", 0.0, 0.8, w=0.35, h=0.1)
    nav = _el("nav", "navigation_bar", 0.2, 0.82, w=0.5, h=0.05)
    tab = _el("tv", "tab_item", 0.27, 0.84, w=0.05, h=0.03, text="TV").model_copy(update={"parent_id": "nav"})
    assert not _is_dynamic(tab, {e.id: e for e in (card, nav, tab)})
    on_card = tab.model_copy(update={"parent_id": "card"})
    assert _is_dynamic(on_card, {e.id: e for e in (card, nav, on_card)})


def test_removed_tab_on_a_floating_bar_over_posters_is_reported():
    card = _el("card", "content_card", 0.0, 0.8, w=0.35, h=0.1)
    nav = _el("nav", "navigation_bar", 0.2, 0.82, w=0.5, h=0.05)
    tab = _el("tv", "tab_item", 0.27, 0.84, w=0.05, h=0.03, text="TV").model_copy(update={"parent_id": "nav"})
    missing = _open(_run([card, nav], [card, nav, tab])[1], "MISSING_IN_PRODUCTION")
    assert [d.client_id for d in missing] == ["tv"]


def test_a_few_pixels_on_a_small_box_is_not_a_size_change():
    client = [_el("t", "section_title", 0.04, 0.3, w=0.126, h=0.039, text="VILLAN")]
    prod = [_el("t", "section_title", 0.04, 0.3, w=0.122, h=0.036, text="VILLAN")]  # 3-4 px, 8%
    assert _open(_run(prod, client)[1], "SIZE_DIFFERENCE") == []


def test_size_change_above_the_pixel_floor_is_still_reported():
    client = [_el("s", "tab_item", 0.06, 0.9, w=0.100, h=0.1, text="Search")]
    prod = [_el("s", "tab_item", 0.05, 0.9, w=0.128, h=0.1, text="Search")]  # 28 px, 22%
    found = _open(_run(prod, client)[1], "SIZE_DIFFERENCE")
    assert [d.verdict for d in found] == ["FAIL"] and found[0].details["change_px"][0] > 4


def test_pixel_floor_zero_is_the_old_relative_rule():
    client = [_el("t", "section_title", 0.04, 0.3, w=0.126, h=0.039, text="VILLAN")]
    prod = [_el("t", "section_title", 0.04, 0.3, w=0.122, h=0.036, text="VILLAN")]
    p, c = _doc(prod, "production"), _doc(client, "client")
    graph = _graph({"grp": ["t"]})
    engine = DifferenceEngine()
    engine.size_min_px = 0
    found = _open(engine.compare(p, c, graph, graph, ElementMatcher().match(p, c, graph, graph)),
                  "SIZE_DIFFERENCE")
    assert [d.verdict for d in found] == ["REVIEW"]


def test_chrome_on_a_hero_card_is_compared_badges_are_not():
    # SunNXT detail page: Subscribe and the back arrow sit on the hero, with no parent.
    hero = _el("hero", "content_card", 0.0, 0.05, w=1.0, h=0.25)
    subscribe = _el("sub", "button", 0.33, 0.19, w=0.32, h=0.04, text="Subscribe")
    badge = _el("free", "overlay_badge", 0.9, 0.06, w=0.08, h=0.03, text="Free")
    by_id = {e.id: e for e in (hero, subscribe, badge)}
    assert not _is_dynamic(subscribe, by_id)
    assert _is_dynamic(badge, by_id)
    missing = _open(_run([hero], [hero, subscribe])[1], "MISSING_IN_PRODUCTION")
    assert [d.client_id for d in missing] == ["sub"]
