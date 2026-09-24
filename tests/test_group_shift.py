# Tests for the per-group shift (matcher.py pass 2, differ.py GROUP_SHIFT).
#
# Evidence these are modelled on: on the SunNXT language pair the bottom sheet
# sits ~136 px (0.058 normalized) lower in the client while the header behind
# it moved ~10 px, which produced six separate position findings and left 7 of
# 8 text-less tiles unmatched. A group that moved as one piece must be reported
# once and its members judged on their residual only.

import networkx as nx
import yaml

from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import DEFAULT_CONFIG_PATH, ElementMatcher
from src.schema.ui_element import UIDocument, UIElement

W, H = 1000, 1000
SHIFT = 0.058          # the language sheet's measured move
CARD = (0.2, 0.05)     # small enough that a shift drops IoU to 0


def _el(id_, cls, x, y, w=0.2, h=0.05, text=None):
    return UIElement(
        id=id_, **{"class": cls}, text=text,
        bbox=[x * W, y * H, w * W, h * H],
        normalized_bbox=[x, y, w, h],
        center=[(x + w / 2) * W, (y + h / 2) * H],
        confidence=0.9, confidence_tier="high", source="fused",
    )


def _doc(elements, source):
    return UIDocument(screen_id="ss_test", source=source,
                      image_width=W, image_height=H, elements=elements)


def _graph(containers):
    """{container_id: [member_ids]} -> a layout graph with CONTAINS edges."""
    g = nx.DiGraph()
    for container, members in containers.items():
        g.add_node(container, class_=None)
        for m in members:
            g.add_node(m)
            g.add_edge(container, m, relationship="CONTAINS")
    return g


def _panel(dy, extra_dy_on=None):
    """A 6-member panel: 3 text anchors + 3 text-less cards, production moved
    up by `dy` relative to the client."""
    ids = ["a1", "a2", "a3", "c1", "c2", "c3"]
    ys = {"a1": 0.30, "a2": 0.40, "a3": 0.50, "c1": 0.60, "c2": 0.70, "c3": 0.80}
    labels = {"a1": "Sun NXT", "a2": "Sun NXT Shorts", "a3": "Save"}
    classes = {"a1": "tab_item", "a2": "tab_item", "a3": "button"}

    client = [_el(i, classes.get(i, "content_card"), 0.1, ys[i],
                  *CARD, text=labels.get(i)) for i in ids]
    prod = [_el(i, classes.get(i, "content_card"), 0.1,
                ys[i] - dy - (extra_dy_on == i) * 0.03, *CARD, text=labels.get(i))
            for i in ids]
    graph = _graph({"grp_panel": ids})
    return _doc(prod, "production"), _doc(client, "client"), graph


def _compare(prod, client, graph, config_path=DEFAULT_CONFIG_PATH):
    result = ElementMatcher(config_path).match(prod, client, graph, graph)
    differences = DifferenceEngine(config_path).compare(prod, client, graph, graph, result)
    return result, differences


def _types(differences, kind):
    return [d for d in differences if d.type == kind]


def test_panel_that_moved_as_one_piece_is_reported_once():
    result, differences = _compare(*_panel(SHIFT))

    assert len(_types(differences, "GROUP_SHIFT")) == 1
    assert _types(differences, "POSITION_DIFFERENCE") == []
    shift = _types(differences, "GROUP_SHIFT")[0]
    assert shift.details["anchors"] == 3
    assert round(shift.details["dy_px"]) == -58


def test_text_less_cards_are_recovered_by_the_second_pass():
    result, differences = _compare(*_panel(SHIFT))

    by_pass = {m.client_id: m.match_pass for m in result.matches}
    assert [by_pass.get(i) for i in ("a1", "a2", "a3")] == [1, 1, 1]
    assert [by_pass.get(i) for i in ("c1", "c2", "c3")] == [2, 2, 2]
    assert result.unmatched_client == [] and result.unmatched_production == []


def test_a_member_that_moved_further_still_gets_its_own_finding():
    # The median ignores the outlier, so its residual survives as a C1.
    _, differences = _compare(*_panel(SHIFT, extra_dy_on="a3"))

    assert len(_types(differences, "GROUP_SHIFT")) == 1
    outliers = _types(differences, "POSITION_DIFFERENCE")
    assert [d.client_id for d in outliers] == ["a3"]


def test_too_few_anchors_means_no_shift():
    # One anchor is below min_anchors, so the container cannot vote at all.
    prod, client, _ = _panel(SHIFT)
    graph = _graph({"grp_panel": ["a1", "c1", "c2", "c3"]})
    prod = _doc([e for e in prod.elements if e.id not in ("a2", "a3")], "production")
    client = _doc([e for e in client.elements if e.id not in ("a2", "a3")], "client")

    result, differences = _compare(prod, client, graph)

    assert result.group_shifts == {}
    assert _types(differences, "GROUP_SHIFT") == []
    assert set(result.unmatched_client) == {"c1", "c2", "c3"}


def test_two_groups_get_their_own_shifts():
    # The header moves a little, the sheet a lot — a global correction would
    # have used one number for both.
    header_ids, sheet_ids = ["h1", "h2", "h3"], ["s1", "s2", "s3"]
    labels = {"h1": "SUN NXT", "h2": "SUN NXT SHORTS", "h3": "Search",
              "s1": "Sun NXT", "s2": "Sun NXT Shorts", "s3": "Save"}
    ys = dict(zip(header_ids + sheet_ids, [0.05, 0.10, 0.15, 0.50, 0.60, 0.70]))
    moves = {**{i: 0.004 for i in header_ids}, **{i: SHIFT for i in sheet_ids}}

    client = [_el(i, "tab_item", 0.1, ys[i], *CARD, text=labels[i]) for i in ys]
    prod = [_el(i, "tab_item", 0.1, ys[i] - moves[i], *CARD, text=labels[i]) for i in ys]
    graph = _graph({"grp_header": header_ids, "grp_sheet": sheet_ids})

    result, _ = _compare(_doc(prod, "production"), _doc(client, "client"), graph)

    dys = {g: round(info["shift"][1], 3) for g, info in result.group_shifts.items()}
    assert dys == {"grp_header": -0.004, "grp_sheet": -round(SHIFT, 3)}


def test_anchors_that_disagree_apply_no_shift():
    ids = ["a1", "a2", "a3"]
    labels = {"a1": "Sun NXT", "a2": "Sun NXT Shorts", "a3": "Save"}
    moves = {"a1": 0.058, "a2": 0.020, "a3": 0.090}  # spread far above 0.01
    ys = {"a1": 0.30, "a2": 0.40, "a3": 0.50}

    client = [_el(i, "tab_item", 0.1, ys[i], *CARD, text=labels[i]) for i in ids]
    prod = [_el(i, "tab_item", 0.1, ys[i] - moves[i], *CARD, text=labels[i]) for i in ids]
    graph = _graph({"grp_panel": ids})

    result, differences = _compare(_doc(prod, "production"), _doc(client, "client"), graph)

    assert result.group_shifts == {}
    assert _types(differences, "GROUP_SHIFT") == []


def test_self_compare_has_no_shift_and_no_findings():
    prod, client, graph = _panel(0.0)
    result, differences = _compare(prod, _doc(client.elements, "client"), graph)

    assert all(m.shift == (0.0, 0.0) for m in result.matches)
    assert _types(differences, "GROUP_SHIFT") == []
    assert all(d.verdict == "PASS" for d in differences)


def test_disabled_reproduces_the_old_behaviour(tmp_path):
    cfg = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    cfg["matching"]["group_shift"]["enabled"] = False
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    result, differences = _compare(*_panel(SHIFT), config_path=path)

    assert result.group_shifts == {}
    assert _types(differences, "GROUP_SHIFT") == []
    # Without the second pass the text-less cards are unmatched again.
    assert set(result.unmatched_client) == {"c1", "c2", "c3"}
    assert all(m.match_pass == 1 for m in result.matches)
