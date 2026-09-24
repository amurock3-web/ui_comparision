# Tests for src/comparison/layout_checks.py — B3 section order, B4 tab/nav
# order, B5 alignment, B8 clipping (docs/test_cases_pass_fail.md §B).
#
# The graphs are built by hand in the shape src/graph/layout.py emits (virtual
# screen root, virtual section groups, CONTAINS + ABOVE/LEFT_OF/ALIGNED_WITH,
# `clipped`), following the _graph() helper style of test_group_shift.py. No
# screenshots, no pipeline: these checks only ever see a graph and a
# MatchResult, and the ids are shared by both sides so a match is id -> id.

import networkx as nx

from src.comparison.layout_checks import alignment, clipping, section_order, tab_order
from src.comparison.matcher import ElementMatch, MatchResult

W, H = 1000, 1000


def _graph():
    g = nx.MultiDiGraph()
    g.add_node("screen", class_="screen", text=None, bbox=[0, 0, W, H],
               normalized_bbox=[0, 0, 1, 1], path="", virtual=True)
    return g


def _add(g, parent, id_, cls, bbox, text=None, **extra):
    x, y, w, h = bbox
    g.add_node(id_, class_=cls, text=text, bbox=[x, y, w, h],
               normalized_bbox=[x / W, y / H, w / W, h / H], **{"clipped": False, **extra})
    g.add_edge(parent, id_, relationship="CONTAINS")
    return id_


def _group(g, parent, id_, cls, bbox):
    g.add_node(id_, class_=cls, text=None, bbox=list(bbox), normalized_bbox=None, virtual=True)
    g.add_edge(parent, id_, relationship="CONTAINS")
    return id_


def _order(g, ids, relationship):
    for a, b in zip(ids, ids[1:]):
        g.add_edge(a, b, relationship=relationship)


def _matched(ids):
    """Every id matched to itself — these checks never do their own matching."""
    return MatchResult([ElementMatch(i, i, 1.0, {}) for i in ids], [], [])


# ---- screens ----------------------------------------------------------

SECTIONS = [("s_cw", "Continue Watching"), ("s_trend", "Trending"), ("s_movies", "Movies")]
TABS = ["Home", "Movies", "Live TV"]


def _sections(g, order):
    """A stack of section groups (title + its rail) in top-to-bottom `order`."""
    groups = []
    for i, (sid, label) in enumerate(order):
        y = 200 + i * 200
        grp = _group(g, "screen", f"grp_{sid}", "section", [50, y, 900, 180])
        _add(g, grp, sid, "section_title", [50, y, 300, 40], label)
        _add(g, grp, f"{sid}_rail", "content_card", [50, y + 50, 900, 130])
        _order(g, [sid, f"{sid}_rail"], "ABOVE")
        groups.append(grp)
    _order(g, groups, "ABOVE")
    return groups


def _tab_bar(g, labels):
    bar = _add(g, "screen", "nav", "navigation_bar", [0, 0, W, 80])
    tabs = [_add(g, bar, f"tab_{l.lower().replace(' ', '')}", "tab_item",
                 [100 + i * 250, 10, 200, 60], l) for i, l in enumerate(labels)]
    _order(g, tabs, "LEFT_OF")
    return tabs


def _column(g, xs, clipped_on=()):
    """A left-aligned column of buttons; the client side carries ALIGNED_WITH."""
    ids = [_add(g, "screen", f"btn{i}", "button", [x, 800 + i * 60, 200, 50], f"Btn {i}",
                clipped=(f"btn{i}" in clipped_on)) for i, x in enumerate(xs)]
    _order(g, ids, "ABOVE")
    return ids


def _screen(section_order_=SECTIONS, tabs=TABS, xs=(100, 100, 100), aligned=True, clipped_on=()):
    g = _graph()
    _tab_bar(g, tabs)
    _sections(g, section_order_)
    ids = _column(g, xs, clipped_on)
    if aligned:  # what the client designed; production is measured against it
        for a, b in zip(ids, ids[1:]):
            g.add_edge(a, b, relationship="ALIGNED_WITH", axes=["left"])
    return g


ALL_IDS = ([s for s, _ in SECTIONS] + [f"{s}_rail" for s, _ in SECTIONS]
           + ["nav", "tab_home", "tab_movies", "tab_livetv", "btn0", "btn1", "btn2"])


# ---- B3 / B4 no-change ------------------------------------------------


def test_identical_layouts_produce_no_findings():
    client, production = _screen(), _screen()
    match = _matched(ALL_IDS)

    assert section_order(production, client, match) == []
    assert tab_order(production, client, match) == []
    assert alignment(production, client, match) == []
    assert clipping(production, client, match) == []


# ---- B3 ---------------------------------------------------------------


def test_swapped_sections_are_detected_and_the_mover_is_named():
    client = _screen()
    swapped = [SECTIONS[1], SECTIONS[0], SECTIONS[2]]
    production = _screen(section_order_=swapped)

    found = section_order(production, client, _matched(ALL_IDS))

    assert len(found) == 1
    assert found[0]["client_order"] == ["Continue Watching", "Trending", "Movies"]
    assert found[0]["production_order"] == ["Trending", "Continue Watching", "Movies"]
    # SequenceMatcher's minimal edit names one of the swapped pair, not "the
    # orders differ" — a tester then has one rail to look at, not three.
    assert [m["label"] for m in found[0]["moved"]] == ["Trending"]
    moved = found[0]["moved"][0]
    assert (moved["client_index"], moved["production_index"]) == (1, 0)
    assert moved["section_id"] == "grp_s_trend"  # the whole rail, for highlighting


def test_an_unmatched_section_is_left_to_b1_b2():
    client = _screen()
    production = _screen(section_order_=[SECTIONS[0], SECTIONS[2]])
    match = _matched([i for i in ALL_IDS if not i.startswith("s_trend")])

    found = section_order(production, client, match)

    assert found == []  # the two that survived are still in order


# ---- B4 ---------------------------------------------------------------


def test_reordered_tab_bar_is_detected():
    client = _screen()
    production = _screen(tabs=["Movies", "Home", "Live TV"])

    found = tab_order(production, client, _matched(ALL_IDS))

    assert len(found) == 1
    assert found[0]["bar_id"] == "nav"
    assert found[0]["client_order"] == ["Home", "Movies", "Live TV"]
    assert found[0]["production_order"] == ["Movies", "Home", "Live TV"]
    assert [m["label"] for m in found[0]["moved"]] == ["Movies"]


# ---- B5 ---------------------------------------------------------------


def test_broken_left_alignment_is_detected_with_its_offset():
    client = _screen()
    production = _screen(xs=(100, 100, 160), aligned=False)

    found = alignment(production, client, _matched(ALL_IDS))

    assert len(found) == 1
    assert found[0]["axis"] == "left"
    assert found[0]["client_ids"] == ["btn1", "btn2"]
    assert round(found[0]["production_offset_norm"], 3) == 0.06
    assert found[0]["client_offset_norm"] == 0.0


def test_alignment_jitter_within_tolerance_is_not_reported():
    client = _screen()
    production = _screen(xs=(100, 100, 108), aligned=False)  # 0.008 < 0.015

    assert alignment(production, client, _matched(ALL_IDS)) == []


def test_alignment_tolerance_is_an_argument():
    client = _screen()
    production = _screen(xs=(100, 100, 108), aligned=False)

    assert len(alignment(production, client, _matched(ALL_IDS), tolerance_norm=0.005)) == 1


# ---- B8 ---------------------------------------------------------------


def test_element_clipped_in_production_only_is_detected():
    client = _screen()
    production = _screen(clipped_on=("btn2",))

    found = clipping(production, client, _matched(ALL_IDS))

    assert len(found) == 1
    assert found[0]["clipped_in"] == "production"
    assert found[0]["client_id"] == "btn2"
    assert found[0]["note"] is None


def test_element_clipped_in_the_client_only_is_reported_as_a_scroll_artefact():
    client = _screen(clipped_on=("btn2",))
    production = _screen()

    found = clipping(production, client, _matched(ALL_IDS))

    assert [f["clipped_in"] for f in found] == ["client"]
    assert "scroll position" in found[0]["note"]
