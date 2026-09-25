"""
Layout-structure checks B3 / B4 / B5 / B8 (docs/test_cases_pass_fail.md §B).

The client design is the reference and production is under test, so every
finding is worded from the client's side: this is the order/alignment the
client asked for, this is what production did with it.

Pure functions over the two layout graphs (src/graph/layout.py) plus an
existing MatchResult (src/comparison/matcher.py). They do no matching and
return no verdict: the caller owns the bands, the severity and the wording.
Every threshold is an argument, never read from config here.

All four read data layout.py already emits and nothing consumed until now:
  B3/B4  ABOVE (stack/section) and LEFT_OF (row) order edges
  B5     ALIGNED_WITH edges and their `axes`
  B8     the `clipped` flag (and `occluded_by` on a placeholder)

Ordering uses difflib.SequenceMatcher opcodes, as matcher.py does for text,
so a finding names *which* item moved rather than "the orders differ".

Each function returns a list of plain dicts, empty when the two sides agree.
"""

import difflib

from src.comparison.matcher import _normalize_text
from src.graph.layout import ALIGN_AXES

ORDER_RELATIONSHIPS = ("ABOVE", "LEFT_OF")


def _top_left(graph, node):
    bbox = graph.nodes[node].get("bbox") or [0, 0]
    return (bbox[1], bbox[0])


def _label(graph, node):
    """What a human calls this node in a report."""
    data = graph.nodes[node]
    return data.get("text") or data.get("class_") or node


def _contained(graph, node):
    return [v for _, v, d in graph.out_edges(node, data=True)
            if d.get("relationship") == "CONTAINS"]


def _members(graph, container):
    """CONTAINS children in layout order: top-to-bottom, or left-to-right.

    layout.py emits ABOVE / LEFT_OF between *consecutive* siblings only, so
    following that chain is the order — no reverse edges to undo, no sort key
    to invent.
    """
    kids = _contained(graph, container)
    if len(kids) < 2:
        return kids
    kin = set(kids)
    after = {u: v for u, v, d in graph.out_edges(kids, data=True)
             if d.get("relationship") in ORDER_RELATIONSHIPS and v in kin}
    heads = [k for k in kids if k not in set(after.values())]
    if len(heads) == 1:
        chain = [heads[0]]
        while after.get(chain[-1]) and len(chain) <= len(kids):
            chain.append(after[chain[-1]])
        if len(chain) == len(kids):
            return chain
    # ponytail: a flat group, an overlay set or a partial chain has no single
    # order, so fall back to the y/x the builder cut its bands on. Swap in a
    # topological sort if partially-ordered containers ever matter.
    return sorted(kids, key=lambda k: _top_left(graph, k))


def _reading_order(graph):
    """Every node once, depth-first, in the order a user reads the screen."""
    roots = [n for n in graph
             if not any(d.get("relationship") == "CONTAINS"
                        for _, _, d in graph.in_edges(n, data=True))]
    order, seen = [], set()
    pending = sorted(roots, key=lambda n: _top_left(graph, n))
    while pending:
        node = pending.pop(0)
        if node in seen:
            continue
        seen.add(node)
        order.append(node)
        pending = _members(graph, node) + pending
    return order


def _ranks(graph):
    return {node: i for i, node in enumerate(_reading_order(graph))}


def _enclosing(graph, node, class_):
    """Nearest ancestor of this class (the `section` wrapping a title), or None."""
    seen = set()
    while node is not None and node not in seen:
        seen.add(node)
        node = next((u for u, _, d in graph.in_edges(node, data=True)
                     if d.get("relationship") == "CONTAINS"), None)
        if node is not None and graph.nodes[node].get("class_") == class_:
            return node
    return None


def _compare_order(client_ids, match_result, prod_ranks):
    """(client order, production order, moved) over the ids matched on both sides.

    Both sequences are *client* ids; the second is sorted by where each one's
    matched production element sits in production's reading order. Anything a
    SequenceMatcher opcode does not call "equal" is an item that moved, which
    is the one item a tester has to look at. Unmatched ids are dropped here —
    they are already B1/B2 findings and must not be reported twice.
    """
    paired = [c for c in client_ids
              if c in match_result.by_client
              and match_result.by_client[c].production_id in prod_ranks]
    in_production = sorted(paired, key=lambda c: prod_ranks[match_result.by_client[c].production_id])
    moved = []
    matcher = difflib.SequenceMatcher(None, paired, in_production, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        for c in paired[i1:i2] + in_production[j1:j2]:
            if c not in moved:
                moved.append(c)
    return paired, in_production, moved


def _moved_details(graph, match_result, client_order, production_order, moved, section_class=None):
    return [{"client_id": c,
             "production_id": match_result.by_client[c].production_id,
             "label": _label(graph, c),
             "class": graph.nodes[c].get("class_"),
             "section_id": _enclosing(graph, c, section_class) if section_class else None,
             "client_index": client_order.index(c),
             "production_index": production_order.index(c)}
            for c in moved]


def section_order(production_graph, client_graph, match_result,
                  title_class="section_title", section_class="section"):
    """B3 — are the sections in the same top-to-bottom order on both sides?

    A section's identity is its `section_title`: layout.py wraps a title and
    the member below it in a virtual `section` node, but the title is the part
    that matches across the two screens, so the title carries the order and the
    section id comes along for highlighting the whole rail.

    Returns [] or a single finding dict.
    """
    titles = [n for n in _reading_order(client_graph)
              if client_graph.nodes[n].get("class_") == title_class]
    client_order, production_order, moved = _compare_order(
        titles, match_result, _ranks(production_graph))
    if not moved:
        return []
    return [{
        "check": "B3",
        "client_order": [_label(client_graph, c) for c in client_order],
        "production_order": [_label(client_graph, c) for c in production_order],
        "moved": _moved_details(client_graph, match_result, client_order,
                                production_order, moved, section_class),
        "compared": len(client_order),
        "skipped_unmatched": [c for c in titles if c not in client_order],
    }]


def _bars(graph, item_classes, bar_classes, min_items):
    """(container, ordered items) for every tab / nav bar in the graph."""
    for node in graph:
        members = _members(graph, node)
        items = [m for m in members if graph.nodes[m].get("class_") in item_classes]
        if len(items) < min_items and graph.nodes[node].get("class_") in bar_classes:
            # A navigation_bar whose children the detector did not class as
            # tabs: its members are the items by virtue of being in the bar.
            items = [m for m in members if not graph.nodes[m].get("virtual")]
        if len(items) >= min_items:
            yield node, items


def _swapped_labels(production_graph, client_graph, match_result, items):
    """Items in one bar that traded labels with each other.

    A swapped tab bar is genuinely ambiguous and the matcher can read it either
    way. Pair the tabs by text and their positions cross, so the order changed
    (B4). Pair them by position - same box, different label - and it reads as
    two independent label changes (E1). Both descriptions are true, and on the
    benchmark the matcher chose by position on two of three screens, so B4 went
    silent on a deliberate tab swap.

    This finds the case directly: two matched items in the same bar where each
    one's production text is the other's client text. That is a swap however
    the matcher paired them.
    """
    labelled = []
    for c in items:
        m = match_result.by_client.get(c)
        if m is None:
            continue
        p_text = _normalize_text(production_graph.nodes[m.production_id].get("text")
                                 if m.production_id in production_graph else None)
        labelled.append((c, _normalize_text(client_graph.nodes[c].get("text")), p_text))

    swaps = []
    for i, (c_a, client_a, prod_a) in enumerate(labelled):
        for c_b, client_b, prod_b in labelled[i + 1:]:
            if not (client_a and client_b) or client_a == client_b:
                continue
            if prod_a == client_b and prod_b == client_a:
                swaps.append((c_a, c_b))
    return swaps


def tab_order(production_graph, client_graph, match_result,
              item_classes=("tab_item",),
              bar_classes=("navigation_bar", "tab_bar"),
              min_items=2):
    """B4 — are the items inside each tab / nav bar in the same left-to-right order?

    Order matters here even when every tab is present, so this fires on a pure
    permutation that B1/B2 cannot see. A bar is any container holding at least
    `min_items` members of `item_classes`, or a node of `bar_classes` (whose
    own members then count as the items).

    Returns one finding dict per bar whose order changed.
    """
    prod_ranks = _ranks(production_graph)
    found = []
    for bar, items in _bars(client_graph, item_classes, bar_classes, min_items):
        client_order, production_order, moved = _compare_order(items, match_result, prod_ranks)
        swaps = _swapped_labels(production_graph, client_graph, match_result, items)
        if not moved and not swaps:
            continue
        if not moved and swaps:
            # The matcher paired these by position, so the order looks intact
            # and only the labels moved. Name the swapped pair directly.
            moved_details = []
            for c_a, c_b in swaps:
                for c in (c_a, c_b):
                    m = match_result.by_client.get(c)
                    other = c_b if c is c_a else c_a
                    moved_details.append({
                        "client_id": c,
                        "production_id": m.production_id if m else None,
                        "label": _label(client_graph, c),
                        "class": client_graph.nodes[c].get("class_"),
                        "section_id": None,
                        "client_index": items.index(c),
                        "production_index": items.index(other),
                    })
        else:
            moved_details = _moved_details(client_graph, match_result, client_order,
                                           production_order, moved)
        found.append({
            "check": "B4",
            "bar_id": bar,
            "bar_class": client_graph.nodes[bar].get("class_"),
            "client_order": [_label(client_graph, c) for c in client_order],
            "production_order": [_label(client_graph, c) for c in production_order],
            "moved": moved_details,
            "swapped_labels": [[_label(client_graph, a), _label(client_graph, b)] for a, b in swaps],
            "compared": len(client_order),
            "skipped_unmatched": [c for c in items if c not in client_order],
        })
    return found


def alignment(production_graph, client_graph, match_result, tolerance_norm=0.015):
    """B5 — client elements sharing an edge/centre that production pulled apart.

    The client's own ALIGNED_WITH edges define what "aligned" means, so this
    never invents an alignment the designer did not draw. What is measured is
    how much *further* apart the pair sits in production than in the client:
    those edges are clustered at graph.alignment_epsilon_norm (0.02 = 2% of
    width), which is looser than B5's 1.5%, so an absolute test would fail a
    pair the client itself never aligned tightly.

    tolerance_norm: growth in the shared coordinate that counts as broken, as a
    fraction of screen width (x axes) or height (y axes). Default 0.015 =
    test_cases_pass_fail.md B5 "one item sticks out >1.5%".

    Returns one finding dict per (pair, axis) that came apart.
    """
    found = []
    for a, b, data in client_graph.edges(data=True):
        if data.get("relationship") != "ALIGNED_WITH":
            continue
        match_a, match_b = match_result.by_client.get(a), match_result.by_client.get(b)
        if match_a is None or match_b is None:
            continue  # unmatched: already a B1/B2 finding
        boxes = [client_graph.nodes[a].get("normalized_bbox"),
                 client_graph.nodes[b].get("normalized_bbox"),
                 production_graph.nodes[match_a.production_id].get("normalized_bbox")
                 if match_a.production_id in production_graph else None,
                 production_graph.nodes[match_b.production_id].get("normalized_bbox")
                 if match_b.production_id in production_graph else None]
        if any(box is None for box in boxes):
            continue
        client_a, client_b, prod_a, prod_b = boxes
        for axis in data.get("axes", []):
            coord = ALIGN_AXES[axis]
            client_offset = abs(coord(client_a) - coord(client_b))
            production_offset = abs(coord(prod_a) - coord(prod_b))
            if production_offset - client_offset <= tolerance_norm:
                continue
            found.append({
                "check": "B5",
                "axis": axis,
                "client_ids": [a, b],
                "production_ids": [match_a.production_id, match_b.production_id],
                "labels": [_label(client_graph, a), _label(client_graph, b)],
                "client_offset_norm": client_offset,
                "production_offset_norm": production_offset,
                "offset_growth_norm": production_offset - client_offset,
                "tolerance_norm": tolerance_norm,
            })
    return found


def clipping(production_graph, client_graph, match_result):
    """B8 — elements cut off on one side and not the other.

    layout.py already sets `clipped` on anything touching the content edge or
    running under a navigation_bar / floating overlay; nothing read it until
    now. Clipped in production only is the defect. The reverse is reported too
    but is usually a scroll-position artefact, which `note` says out loud so
    the report can rank it below the real thing.

    Returns one finding dict per matched pair that disagrees.
    """
    found = []
    for m in match_result.matches:
        if m.production_id not in production_graph or m.client_id not in client_graph:
            continue
        prod, client = production_graph.nodes[m.production_id], client_graph.nodes[m.client_id]
        if bool(prod.get("clipped")) == bool(client.get("clipped")):
            continue
        in_production = bool(prod.get("clipped"))
        side = prod if in_production else client
        found.append({
            "check": "B8",
            "clipped_in": "production" if in_production else "client",
            "production_id": m.production_id,
            "client_id": m.client_id,
            "class": client.get("class_") or prod.get("class_"),
            "label": _label(client_graph, m.client_id),
            "occluded_by": side.get("occluded_by"),
            "production_bbox": prod.get("normalized_bbox"),
            "client_bbox": client.get("normalized_bbox"),
            "note": None if in_production else
                    "clipped in the client only - usually scroll position, not a defect",
        })
    return found
