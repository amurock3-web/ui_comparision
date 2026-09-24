# Tests for src/graph/layout.py — layout-tree graph.

from src.graph.layout import LayoutGraphBuilder
from tests.test_graph import _doc, _el


def _rels(graph, rel):
    return {(u, v) for u, v, d in graph.edges(data=True) if d["relationship"] == rel}


def test_grid_with_badge_and_nav_bar():
    # 2x2 card grid (with 12px detector jitter on one card), a badge inside
    # card a, and a nav bar holding 3 tabs.
    elements = [
        _el("a", "content_card", [0, 0, 300, 400]),
        _el("b", "content_card", [350, 12, 300, 400]),
        _el("c", "content_card", [12, 450, 300, 400]),
        _el("d", "content_card", [350, 450, 300, 400]),
        _el("badge", "overlay_badge", [20, 20, 50, 50]),
        _el("nav", "navigation_bar", [0, 900, 1000, 100]),
        _el("t1", "tab_item", [50, 920, 100, 60]),
        _el("t2", "tab_item", [450, 920, 100, 60]),
        _el("t3", "tab_item", [850, 920, 100, 60]),
    ]
    graph = LayoutGraphBuilder().build(_doc(elements))
    nodes = graph.nodes

    assert nodes["screen"]["layout"] == "stack"
    assert nodes["nav"]["layout"] == "row"
    assert {nodes[n]["path"] for n in ("a", "b", "c", "d")} == {"/0/0", "/0/1", "/1/0", "/1/1"}
    assert nodes["nav"]["path"] == "/2"
    assert nodes["badge"]["path"] == "/0/0/0"

    contains = _rels(graph, "CONTAINS")
    assert ("a", "badge") in contains and ("screen", "badge") not in contains  # direct parent only
    assert _rels(graph, "LEFT_OF") >= {("a", "b"), ("c", "d"), ("t1", "t2"), ("t2", "t3")}
    assert ("t1", "t3") not in _rels(graph, "LEFT_OF")  # neighbours only
    assert not _rels(graph, "BELOW") and not _rels(graph, "RIGHT_OF")

    aligned = {tuple(sorted((u, v))): d["axes"] for u, v, d in graph.edges(data=True)
               if d["relationship"] == "ALIGNED_WITH"}
    assert "top" in aligned[("a", "b")]  # 12px apart, inside the tolerance
    assert "left" in aligned[("b", "d")]
    assert "top" in aligned[("t1", "t2")]


def test_overlapping_siblings_become_flat_with_overlaps():
    elements = [
        _el("card", "content_card", [0, 0, 400, 400]),
        _el("chip", "tab_item", [200, 100, 400, 100]),  # half on the card, not inside it
    ]
    graph = LayoutGraphBuilder().build(_doc(elements))
    assert graph.nodes["screen"]["layout"] == "flat"
    assert ("card", "chip") in _rels(graph, "OVERLAPS")


def test_clipped_by_screen_edge_and_nav_bar():
    elements = [
        _el("a", "content_card", [100, 100, 300, 300]),
        _el("b", "content_card", [700, 100, 300, 300]),   # touches the right edge
        _el("c", "content_card", [100, 600, 300, 300]),   # bottom touches the nav bar
        _el("nav", "navigation_bar", [0, 900, 1000, 100]),
        _el("tab", "tab_item", [100, 920, 100, 60]),     # inside the nav bar
    ]
    nodes = LayoutGraphBuilder().build(_doc(elements)).nodes
    assert nodes["b"]["clipped"] and nodes["c"]["clipped"]
    assert not nodes["a"]["clipped"]
    assert not nodes["nav"]["clipped"] and not nodes["tab"]["clipped"]


def test_section_title_grouped_with_its_row():
    elements = [
        _el("title1", "section_title", [20, 50, 200, 40]),
        _el("c1", "content_card", [20, 120, 300, 300]),
        _el("c2", "content_card", [400, 120, 300, 300]),
        _el("title2", "section_title", [20, 460, 200, 40]),
        _el("c3", "content_card", [20, 530, 300, 300]),
        _el("c4", "content_card", [400, 530, 300, 300]),
    ]
    graph = LayoutGraphBuilder().build(_doc(elements))
    sections = [n for n, d in graph.nodes(data=True) if d["class_"] == "section"]
    assert len(sections) == 2
    assert graph.nodes["title1"]["path"] == "/0/0"
    assert graph.nodes["c1"]["path"] == "/0/1/0"
    row = next(v for u, v in _rels(graph, "ABOVE") if u == "title1")
    assert graph.nodes[row]["class_"] == "row"


def test_floating_chip_bar_lifted_out_as_overlay():
    elements = [
        _el("c1", "content_card", [50, 300, 250, 400]),
        _el("c2", "content_card", [375, 300, 250, 400]),
        _el("c3", "content_card", [700, 300, 250, 400]),
        _el("chip", "tab_item", [100, 600, 800, 100]),
    ]
    graph = LayoutGraphBuilder().build(_doc(elements))
    nodes = graph.nodes
    assert nodes["chip"]["layer"] == "overlay" and nodes["chip"]["path"] == "/o0"
    assert nodes["screen"]["layout"] == "row"
    assert {("chip", "c1"), ("chip", "c2"), ("chip", "c3")} <= _rels(graph, "OVERLAPS")
    assert all(nodes[c]["clipped"] for c in ("c1", "c2", "c3"))
