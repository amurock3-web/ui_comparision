# Tests for src/comparison/matcher.py and differ.py — matching, missing/extra,
# text/geometry/structural differences (rules.md §14).

import networkx as nx

from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import ElementMatcher
from src.graph.build import UIGraphBuilder
from src.schema.ui_element import UIDocument, UIElement

W, H = 1000, 1000


def _el(id_, cls, bbox, text=None):
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


def _doc(elements, source="production"):
    return UIDocument(screen_id="ss_test", source=source, image_width=W, image_height=H, elements=elements)


def _types(differences):
    return [d.type for d in differences]


# ---- matcher ----------------------------------------------------------


def test_identical_elements_match():
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "button", [10, 10, 100, 40], "Submit")], source="client")

    result = ElementMatcher().match(prod, client)

    assert len(result.matches) == 1
    assert result.matches[0].production_id == "p1"
    assert result.matches[0].client_id == "c1"
    assert not result.unmatched_production
    assert not result.unmatched_client


def test_unmatched_production_and_client_elements_reported():
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "icon", [800, 800, 20, 20])], source="client")

    result = ElementMatcher().match(prod, client)

    assert result.unmatched_production == ["p1"]
    assert result.unmatched_client == ["c1"]


def test_conflicted_match_goes_to_higher_scoring_pair():
    # Two production buttons both compete for the one client button, but
    # p1's text matches exactly while p2's does not — p1 should win the
    # contested match, and p2 should fall through unmatched rather than
    # silently stealing the client element (greedy sort-then-pick from
    # matcher.py implements the paper's "highest score keeps the match,
    # loser falls back to its next candidate" rule).
    prod = _doc(
        [
            _el("p1", "button", [10, 10, 100, 40], "Submit"),
            _el("p2", "button", [10, 10, 100, 40], "Cancel"),
        ]
    )
    client = _doc([_el("c1", "button", [10, 10, 100, 40], "Submit")], source="client")

    result = ElementMatcher().match(prod, client)

    assert result.by_production["p1"].client_id == "c1"
    assert "p2" not in result.by_production
    assert "p2" in result.unmatched_production


def test_context_score_breaks_tie_between_otherwise_identical_candidates():
    # Both client candidates are identical to p_card on class/text/geometry,
    # so only the graph-neighborhood ("context") score can distinguish
    # them. c_card_good shares p_card's neighborhood structure (an
    # outgoing LEFT_OF edge to some other element); c_card_bad is
    # isolated in the graph. The matcher should prefer the structurally
    # similar candidate.
    p_card = _el("p_card", "content_card", [0, 0, 100, 100])
    prod = _doc([p_card])
    prod_graph = nx.MultiDiGraph()
    prod_graph.add_edge("p_card", "ghost", relationship="LEFT_OF")

    c_card_good = _el("c_card_good", "content_card", [0, 0, 100, 100])
    c_card_bad = _el("c_card_bad", "content_card", [0, 0, 100, 100])
    client = _doc([c_card_good, c_card_bad], source="client")
    client_graph = nx.MultiDiGraph()
    client_graph.add_edge("c_card_good", "ghost", relationship="LEFT_OF")
    # c_card_bad is left out of client_graph entirely — an isolated node.

    result = ElementMatcher().match(prod, client, prod_graph, client_graph)

    assert result.by_production["p_card"].client_id == "c_card_good"


# ---- differ -------------------------------------------------------------


def test_clean_match_reports_match():
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "button", [10, 10, 100, 40], "Submit")], source="client")

    differences = DifferenceEngine().compare(prod, client)

    assert _types(differences) == ["MATCH"]


def test_missing_and_extra_reported():
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "icon", [800, 800, 20, 20])], source="client")

    differences = DifferenceEngine().compare(prod, client)

    types = _types(differences)
    assert "MISSING_IN_PRODUCTION" in types
    assert "EXTRA_IN_PRODUCTION" in types


def test_status_bar_text_is_ignored():
    clock = _el("c1", "button", [900, 5, 60, 20], "3:58").model_copy(
        update={"class_": None, "source": "ocr", "metadata": {"ignored": "status_bar"}})
    differences = DifferenceEngine().compare(_doc([]), _doc([clock], source="client"))

    assert _types(differences) == ["MISSING_IN_PRODUCTION"]
    assert differences[0].verdict == "PASS"


def test_class_difference_flagged_for_matched_pair():
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "icon", [10, 10, 100, 40], "Submit")], source="client")

    differences = DifferenceEngine().compare(prod, client)

    assert "CLASS_DIFFERENCE" in _types(differences)


def test_text_difference_flagged_for_matched_pair():
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "button", [10, 10, 100, 40], "Cancel")], source="client")

    differences = DifferenceEngine().compare(prod, client)

    assert "TEXT_DIFFERENCE" in _types(differences)


def test_position_difference_flagged_for_shifted_element():
    # Shifted just enough to clear the C1 pass band (1% of diagonal) while
    # staying close enough that class/text/IoU/spatial still add up past
    # minimum_match_score — a bigger shift instead makes the matcher
    # correctly decide these are two unrelated elements (see
    # test_large_shift_is_treated_as_missing_and_extra_not_a_match below)
    # rather than one shifted element.
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "button", [40, 10, 100, 40], "Submit")], source="client")

    differences = DifferenceEngine().compare(prod, client)

    assert "POSITION_DIFFERENCE" in _types(differences)


def test_large_shift_is_treated_as_missing_and_extra_not_a_match():
    # A large enough position shift drops the combined score below
    # minimum_match_score entirely, so the matcher reports two separate,
    # unrelated elements rather than a wildly-shifted match — the
    # matching threshold, not the differ's position threshold, is what
    # decides whether these are "the same element that moved" at all.
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "button", [500, 10, 100, 40], "Submit")], source="client")

    differences = DifferenceEngine().compare(prod, client)

    types = _types(differences)
    assert "MISSING_IN_PRODUCTION" in types
    assert "EXTRA_IN_PRODUCTION" in types
    assert "POSITION_DIFFERENCE" not in types


def test_size_difference_flagged_for_resized_element():
    prod = _doc([_el("p1", "button", [10, 10, 100, 40], "Submit")])
    client = _doc([_el("c1", "button", [10, 10, 300, 40], "Submit")], source="client")

    differences = DifferenceEngine().compare(prod, client)

    assert "SIZE_DIFFERENCE" in _types(differences)


def test_structural_difference_flagged_when_sibling_context_changes():
    # p_badge sits inside p_card, next to a p_label sibling (giving it a
    # CONTAINS-from-card edge plus a LEFT_OF/ALIGNED_WITH edge to the
    # label). In the client, the badge itself is pixel-for-pixel
    # identical (same class/text/position/size) but the label sibling is
    # gone, so the badge's structural context has shrunk. Class/text/
    # geometry checks alone would call this a perfect MATCH; only the
    # context score should catch it.
    p_card = _el("p_card", "content_card", [0, 0, 300, 300])
    p_badge = _el("p_badge", "overlay_badge", [10, 10, 40, 20], "Free")
    p_label = _el("p_label", "metadata_text", [200, 10, 40, 20], "New")
    prod = _doc([p_card, p_badge, p_label])
    prod_graph = UIGraphBuilder().build(prod)

    c_card = _el("c_card", "content_card", [0, 0, 300, 300])
    c_badge = _el("c_badge", "overlay_badge", [10, 10, 40, 20], "Free")
    client = _doc([c_card, c_badge], source="client")
    client_graph = UIGraphBuilder().build(client)

    differences = DifferenceEngine().compare(prod, client, prod_graph, client_graph)

    badge_diffs = [d for d in differences if d.production_id == "p_badge"]
    assert any(d.type == "STRUCTURAL_DIFFERENCE" for d in badge_diffs)
    # The card itself has no structural change (it still contains the
    # badge either way) and should report as a clean match.
    card_diffs = [d for d in differences if d.production_id == "p_card"]
    assert card_diffs and card_diffs[0].type == "MATCH"
