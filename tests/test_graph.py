# Tests for src/graph/build.py — graph construction (rules.md §14).

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


def _ungrounded_el(id_, cls, text=None):
    # Mirrors what fusion produces for a VLM classification with no OCR
    # text match and no grid rule (e.g. "icon") — no geometry at all.
    return UIElement(
        id=id_, **{"class": cls}, text=text,
        bbox=None, normalized_bbox=None, center=None,
        confidence=0.5, confidence_tier="medium", source="vlm",
    )


def _doc(elements):
    return UIDocument(screen_id="ss_test", source="production", image_width=W, image_height=H, elements=elements)


def _relationships(graph, u, v):
    """All relationship labels on edges from u to v (a MultiDiGraph can hold more than one)."""
    if not graph.has_edge(u, v):
        return set()
    return {data["relationship"] for data in graph.get_edge_data(u, v).values()}


def test_containment_edge_created():
    card = _el("card", "content_card", [0, 0, 200, 300])
    badge = _el("badge", "overlay_badge", [10, 10, 40, 20])
    doc = _doc([card, badge])

    graph = UIGraphBuilder().build(doc)

    assert "CONTAINS" in _relationships(graph, "card", "badge")


def test_left_of_edge_created_for_siblings():
    card1 = _el("card1", "content_card", [0, 0, 100, 100])
    card2 = _el("card2", "content_card", [300, 0, 100, 100])
    doc = _doc([card1, card2])

    graph = UIGraphBuilder().build(doc)

    # Same top edge (both y=0), so both LEFT_OF/RIGHT_OF *and* ALIGNED_WITH
    # should be present — a MultiDiGraph, not a single overwritten edge.
    assert "LEFT_OF" in _relationships(graph, "card1", "card2")
    assert "RIGHT_OF" in _relationships(graph, "card2", "card1")


def test_relations_not_generated_for_every_possible_pair():
    # A grid of 20 same-size, non-overlapping elements: no pair should
    # ever get a CONTAINS edge (nothing actually contains anything here),
    # and no single ordered pair should accumulate an unbounded number of
    # relationship types — this is the "don't generate every
    # mathematically possible relation" requirement (design.md §6). At
    # this scale, brute-force pairwise comparison itself is fine (only
    # ~190 pairs) — see the docstring note in src/graph/build.py.
    elements = []
    for i in range(20):
        row, col = divmod(i, 5)
        elements.append(_el(f"el_{i}", "content_card", [col * 150, row * 150, 100, 100]))
    doc = _doc(elements)

    graph = UIGraphBuilder().build(doc)

    relationships = [data["relationship"] for _, _, data in graph.edges(data=True)]
    assert "CONTAINS" not in relationships

    for u, v in {(u, v) for u, v in graph.edges()}:
        assert len(_relationships(graph, u, v)) <= 3


def test_ungrounded_element_added_as_node_with_no_geometric_edges():
    card = _el("card", "content_card", [0, 0, 200, 300])
    icon = _ungrounded_el("icon", "icon")
    doc = _doc([card, icon])

    graph = UIGraphBuilder().build(doc)

    assert graph.number_of_nodes() == 2
    assert "icon" in graph.nodes
    assert graph.nodes["icon"]["bbox"] is None
    assert graph.out_degree("icon") == 0
    assert graph.in_degree("icon") == 0
