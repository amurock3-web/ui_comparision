"""
Layout-tree UI graph — the alternative to UIGraphBuilder (build.py).

build.py links every sibling pair with centre-distance thresholds, which
gives ~700 edges on one screen, stores each relation twice (ABOVE+BELOW),
and never says "3 columns x 4 rows". This builder recovers the layout the
way an Android view hierarchy describes it:

1. Containment tree: each element's parent is the tightest box covering
   >= containment_min_overlap of it, else the tightest covering
   >= loose_containment_overlap (a badge hanging off its card). Fusion's
   parent_id wins where set. Only direct-parent CONTAINS edges.
2. Floating overlays: a child that partly covers >= 2 of its siblings
   (a chip bar floating over a carousel) is not part of their rows. It is
   lifted out as `layer="overlay"`, path "<parent>/o<i>", with OVERLAPS
   edges to what it covers.
3. Recursive XY-cut inside each container: split children into horizontal
   bands (a "stack", top to bottom), each band into vertical bands (a "row",
   left to right), and so on. Two boxes share a band when their spans
   overlap by >= band_min_overlap of the shorter one: a ratio, so detector
   jitter of a few pixels cannot split a row the way it split ALIGNED_WITH.
   A container whose children form one group gets `layout` set on itself;
   nested groups become virtual nodes (class_ "row"/"stack"/"flat").
4. Sections: inside a stack, a section_title and the member right below it
   are wrapped in a virtual "section" node, so "title + its carousel" is
   one unit a comparison can find missing or reordered.
5. Order edges between neighbours only: ABOVE inside a stack/section,
   LEFT_OF inside a row. The rest follows by transitivity; no reverse
   edges. Children that cannot be cut at all (they overlap on both axes)
   form a "flat" group and get OVERLAPS: the likely-duplicate signal.
6. ALIGNED_WITH: per container, left/centre/right/top/middle/bottom
   coordinates of its children are clustered; consecutive members of a
   cluster get one edge, with the shared axes in `axes`.
7. clipped: an element touching the content edge (image border, or the
   bottom of the ignored status bar) or an occluder (navigation_bar, a
   floating overlay) is cut off by scroll position, not by design, so a
   comparison should not fail it for being smaller or missing.
8. Every node carries `path` (child index at each level, e.g. "/2/1" =
   screen stack band 2, column 1), `layout`, and `rel_bbox` (bbox relative
   to its tree parent), for matching by structure instead of by pixels.
   The screen and group nodes have `virtual=True`.
9. Occluded slots: a row with fewer cards than its nearest longer row of
   the same class, where the missing column lies under a floating overlay,
   gets a placeholder node (id occ_NNNN, confidence 0, clipped, with
   `occluded_by`) so a card hidden behind the pill is not read as missing.
"""

import networkx as nx
import yaml
from pathlib import Path

from src.graph.build import DEFAULT_CONFIG_PATH, UIGraphBuilder, _containment_overlap, _rect

SCREEN_ID = "screen"
OCCLUDER_CLASSES = {"navigation_bar"}
ALIGN_AXES = {
    "left": lambda b: b[0], "center_x": lambda b: b[0] + b[2] / 2, "right": lambda b: b[0] + b[2],
    "top": lambda b: b[1], "center_y": lambda b: b[1] + b[3] / 2, "bottom": lambda b: b[1] + b[3],
}


def _span(bbox, axis):
    return (bbox[1], bbox[1] + bbox[3]) if axis == "y" else (bbox[0], bbox[0] + bbox[2])


def _union(bboxes):
    x1 = min(b[0] for b in bboxes)
    y1 = min(b[1] for b in bboxes)
    x2 = max(b[0] + b[2] for b in bboxes)
    y2 = max(b[1] + b[3] for b in bboxes)
    return [x1, y1, x2 - x1, y2 - y1]


def _rel(b, pb):
    return [(b[0] - pb[0]) / pb[2], (b[1] - pb[1]) / pb[3], b[2] / pb[2], b[3] / pb[3]]


class LayoutGraphBuilder:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        full = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        cfg = full.get("graph", {})
        self.containment_min_overlap = cfg.get("containment_min_overlap", 0.9)
        self.loose_containment_overlap = cfg.get("loose_containment_overlap", 0.75)
        self.alignment_epsilon = cfg.get("alignment_epsilon_norm", 0.02)
        self.band_min_overlap = cfg.get("band_min_overlap", 0.5)
        self.edge_margin = cfg.get("edge_margin_norm", 0.005)
        self.float_min_overlap = cfg.get("float_min_overlap", 0.1)
        self.status_bar_height = full.get("fusion", {}).get("status_bar_height_norm", 0.04)

    save_graph_json = staticmethod(UIGraphBuilder.save_graph_json)

    def build(self, ui_document) -> "nx.MultiDiGraph":
        graph = nx.MultiDiGraph()
        W, H = ui_document.image_width, ui_document.image_height
        self._group_count = 0
        self._occluded_count = 0
        graph.add_node(SCREEN_ID, class_="screen", text=None, bbox=[0, 0, W, H],
                       normalized_bbox=[0, 0, 1, 1], confidence=1.0, path="", layout=None,
                       rel_bbox=None, virtual=True)

        for el in ui_document.elements:
            graph.add_node(el.id, class_=el.class_, text=el.text, bbox=el.bbox,
                           normalized_bbox=el.normalized_bbox, confidence=el.confidence,
                           path=None, layout=None, rel_bbox=None, clipped=False)

        # Same exclusion as build.py: no geometry, or ignored by fusion
        # (status bar, swallowed duplicate) -> node only, no edges.
        geo = {el.id: el.bbox for el in ui_document.elements
               if el.bbox is not None and not (el.metadata or {}).get("ignored")}
        classes = {el.id: el.class_ for el in ui_document.elements}
        element_ids = list(geo)

        # Fusion's parent_id wins where set: a tab split out of a floating pill
        # lies inside the card under it too, and the card is the tighter box.
        fused_parent = {el.id: el.parent_id for el in ui_document.elements}
        children_of = {SCREEN_ID: []}
        for cid, cb in geo.items():
            if fused_parent.get(cid) in geo:
                children_of.setdefault(fused_parent[cid], []).append(cid)
                continue
            parent, parent_area = SCREEN_ID, None
            loose, loose_area = None, None
            for pid, pb in geo.items():
                area = pb[2] * pb[3]
                if pid == cid or area <= cb[2] * cb[3]:
                    continue
                overlap = _containment_overlap(pb, cb)
                if overlap >= self.containment_min_overlap:
                    if parent_area is None or area < parent_area:
                        parent, parent_area = pid, area
                elif overlap >= self.loose_containment_overlap:
                    if loose_area is None or area < loose_area:
                        loose, loose_area = pid, area
            # A badge hanging off its card (85% inside on sunnxt_test_ss) is
            # still the card's child; without this it became a sibling and the
            # card "floated" over it as an overlay.
            if parent == SCREEN_ID and loose is not None:
                parent = loose
            children_of.setdefault(parent, []).append(cid)

        # Top-down so a container's own path is set before its children's.
        floating = set()
        pending = [SCREEN_ID]
        while pending:
            owner = pending.pop(0)
            kids = children_of.get(owner, [])
            if not kids:
                continue
            covers = self._floating(kids, geo)
            floating.update(covers)
            rest = [k for k in kids if k not in covers]
            if rest:
                tree = self._sectionize(self._cut(rest, geo, "y"), classes)
                if covers:
                    self._fill_occluded(graph, tree, covers, geo, classes, W, H)
                self._attach(graph, owner, tree, geo)
            self._attach_overlays(graph, owner, covers, geo)
            self._add_alignment(graph, rest, geo, W)
            pending.extend(kids)

        self._mark_clipped(graph, element_ids, geo, classes, floating, W, H)

        print(f"[LAYOUT] {graph.number_of_nodes()} nodes ({self._group_count} groups, "
              f"{len(floating)} overlay, {self._occluded_count} occluded, "
              f"{sum(1 for i in element_ids if graph.nodes[i]['clipped'])} clipped), "
              f"{graph.number_of_edges()} edges.")
        return graph

    def _partial_overlap(self, a, b, geo):
        """Share of the smaller box covered, or 0 if either contains the other."""
        if (_containment_overlap(geo[a], geo[b]) >= self.containment_min_overlap
                or _containment_overlap(geo[b], geo[a]) >= self.containment_min_overlap):
            return 0.0
        smaller = min(geo[a][2] * geo[a][3], geo[b][2] * geo[b][3])
        if smaller == 0:
            return 0.0
        return _rect(geo[a]).intersection(_rect(geo[b])).area / smaller

    def _floating(self, kids, geo):
        """{child: [siblings it covers]} for children floating over >= 2 siblings."""
        covers = {}
        for k in kids:
            covered = [s for s in kids
                       if s != k and self._partial_overlap(k, s, geo) >= self.float_min_overlap]
            if len(covered) >= 2:
                covers[k] = covered
        return covers

    def _bands(self, ids, geo, axis):
        bands = []
        for i in sorted(ids, key=lambda i: _span(geo[i], axis)[0]):
            lo, hi = _span(geo[i], axis)
            if bands:
                band_lo, band_hi = bands[-1][1]
                overlap = min(hi, band_hi) - max(lo, band_lo)
                if overlap >= self.band_min_overlap * min(hi - lo, band_hi - band_lo):
                    bands[-1][0].append(i)
                    bands[-1][1] = (min(lo, band_lo), max(hi, band_hi))
                    continue
            bands.append([[i], (lo, hi)])
        return [members for members, _ in bands]

    def _cut(self, ids, geo, axis):
        """Recursive XY-cut. Returns an element id or (layout, [subtrees])."""
        if len(ids) == 1:
            return ids[0]
        other = "x" if axis == "y" else "y"
        for a, b in ((axis, other), (other, axis)):
            bands = self._bands(ids, geo, a)
            if len(bands) > 1:
                return ("stack" if a == "y" else "row", [self._cut(m, geo, b) for m in bands])
        return ("flat", list(ids))

    def _sectionize(self, tree, classes):
        """In every stack, wrap a section_title and the member below it."""
        if isinstance(tree, str):
            return tree
        layout, subs = tree
        subs = [self._sectionize(s, classes) for s in subs]
        if layout == "stack":
            is_title = lambda s: isinstance(s, str) and classes.get(s) == "section_title"
            wrapped, i = [], 0
            while i < len(subs):
                if is_title(subs[i]) and i + 1 < len(subs) and not is_title(subs[i + 1]):
                    wrapped.append(("section", [subs[i], subs[i + 1]]))
                    i += 2
                else:
                    wrapped.append(subs[i])
                    i += 1
            if len(wrapped) == 1:
                return wrapped[0]
            subs = wrapped
        return (layout, subs)

    def _rows(self, tree):
        """Every row in the tree whose members are all elements (mutable lists)."""
        if isinstance(tree, str):
            return []
        layout, subs = tree
        found = [subs] if layout == "row" and all(isinstance(s, str) for s in subs) else []
        return found + [r for sub in subs for r in self._rows(sub)]

    def _fill_occluded(self, graph, tree, covers, geo, classes, W, H):
        """Add a placeholder for each column a row is missing under an overlay.

        The columns come from the vertically nearest longer row of the same
        class (the Watchlist row above "Peacock's Finest"), so a row that is
        short only because the carousel scrolled differently, with nothing
        covering the gap, is left alone.
        """
        # ponytail: a row cut down to one visible card collapses to a bare id
        # in the tree and is not filled; handle it if a screen shows it.
        rows = self._rows(tree)
        for row in rows:
            cls = classes.get(row[0])
            if any(classes.get(m) != cls for m in row):
                continue
            ry = _union([geo[m] for m in row])
            refs = [r for r in rows
                    if len(r) > len(row) and all(classes.get(m) == cls for m in r)]
            if not refs:
                continue
            ref = min(refs, key=lambda r: abs(_union([geo[m] for m in r])[1] - ry[1]))
            for col in ref:
                cx, _, cw, _ = geo[col]
                if any(min(cx + cw, geo[m][0] + geo[m][2]) - max(cx, geo[m][0])
                       >= self.band_min_overlap * min(cw, geo[m][2]) for m in row):
                    continue
                slot = [cx, ry[1], cw, ry[3]]
                over = next((f for f in covers
                             if _rect(slot).intersection(_rect(geo[f])).area
                             >= self.float_min_overlap * cw * ry[3]), None)
                if over is None:
                    continue
                self._occluded_count += 1
                oid = f"occ_{self._occluded_count:04d}"
                geo[oid], classes[oid] = slot, cls
                graph.add_node(oid, class_=cls, text=None, bbox=slot,
                               normalized_bbox=[cx / W, ry[1] / H, cw / W, ry[3] / H],
                               confidence=0.0, path=None, layout=None, rel_bbox=None,
                               clipped=True, occluded_by=over)
                covers[over].append(oid)
                row.append(oid)
            row.sort(key=lambda m: geo[m][0])

    def _attach(self, graph, owner, tree, geo):
        """Hang `tree` under `owner`: CONTAINS, order edges, path, rel_bbox."""
        if isinstance(tree, str):
            members = [tree]
        else:
            graph.nodes[owner]["layout"], subtrees = tree
            members = []
            for sub in subtrees:
                if isinstance(sub, str):
                    members.append(sub)
                    continue
                self._group_count += 1
                gid = f"grp_{self._group_count:04d}"
                bbox = _union([geo[i] for i in self._leaves(sub)])
                geo[gid] = bbox
                graph.add_node(gid, class_=sub[0], text=None, bbox=bbox, normalized_bbox=None,
                               confidence=1.0, path=None, layout=None, rel_bbox=None, virtual=True)
                members.append(gid)

        pb = graph.nodes[owner]["bbox"]
        for index, m in enumerate(members):
            graph.add_edge(owner, m, relationship="CONTAINS")
            graph.nodes[m]["path"] = f"{graph.nodes[owner]['path']}/{index}"
            graph.nodes[m]["rel_bbox"] = _rel(geo[m], pb)

        layout = graph.nodes[owner]["layout"]
        if layout in ("stack", "section", "row"):
            rel = "LEFT_OF" if layout == "row" else "ABOVE"
            for a, b in zip(members, members[1:]):
                graph.add_edge(a, b, relationship=rel)
        elif layout == "flat":
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    graph.add_edge(a, b, relationship="OVERLAPS")
                    graph.add_edge(b, a, relationship="OVERLAPS")

        if not isinstance(tree, str):
            for m, sub in zip(members, tree[1]):
                if not isinstance(sub, str):
                    self._attach(graph, m, sub, geo)

    def _attach_overlays(self, graph, owner, covers, geo):
        pb = graph.nodes[owner]["bbox"]
        for index, f in enumerate(sorted(covers, key=lambda i: (geo[i][1], geo[i][0]))):
            graph.add_edge(owner, f, relationship="CONTAINS")
            graph.nodes[f].update(path=f"{graph.nodes[owner]['path']}/o{index}",
                                  rel_bbox=_rel(geo[f], pb), layer="overlay")
            for s in covers[f]:
                graph.add_edge(f, s, relationship="OVERLAPS")
                graph.add_edge(s, f, relationship="OVERLAPS")

    def _leaves(self, tree):
        if isinstance(tree, str):
            return [tree]
        return [leaf for sub in tree[1] for leaf in self._leaves(sub)]

    def _add_alignment(self, graph, ids, geo, W):
        # ponytail: gap-chained clustering can drift across a long run of
        # nearly-aligned boxes; switch to anchor-based clusters if it shows.
        tol = self.alignment_epsilon * W
        axes_by_pair = {}
        for axis, coord in ALIGN_AXES.items():
            ordered = sorted(ids, key=lambda i: coord(geo[i]))
            for a, b in zip(ordered, ordered[1:]):
                if coord(geo[b]) - coord(geo[a]) <= tol:
                    axes_by_pair.setdefault(tuple(sorted((a, b))), []).append(axis)
        for (a, b), axes in axes_by_pair.items():
            graph.add_edge(a, b, relationship="ALIGNED_WITH", axes=axes)

    def _mark_clipped(self, graph, element_ids, geo, classes, floating, W, H):
        # ponytail: any non-occluder touching the content edge counts as
        # clipped, so a deliberately edge-to-edge element (a full-bleed
        # banner) is flagged too; exempt it by class if that shows up.
        m = self.edge_margin * W
        top = self.status_bar_height * H
        occluders = [i for i in element_ids if classes[i] in OCCLUDER_CLASSES] + sorted(floating)
        for i in element_ids:
            if i in occluders:
                continue
            x, y, w, h = geo[i]
            clipped = x <= m or y <= top + m or x + w >= W - m or y + h >= H - m
            if not clipped:
                # An element whose centre lies inside the occluder is part of
                # it (a nav tab whose icon pokes above the bar), not hidden
                # behind it. Trending Search: the "Home" tab was flagged
                # clipped and every finding on it carried a false-alarm note.
                cx, cy = x + w / 2, y + h / 2
                grown = _rect([x - m, y - m, w + 2 * m, h + 2 * m])
                clipped = any(
                    not (geo[o][0] <= cx <= geo[o][0] + geo[o][2]
                         and geo[o][1] <= cy <= geo[o][1] + geo[o][3])
                    and grown.intersects(_rect(geo[o]))
                    and _containment_overlap(geo[o], geo[i]) < self.containment_min_overlap
                    and _containment_overlap(geo[i], geo[o]) < self.containment_min_overlap
                    for o in occluders)
            graph.nodes[i]["clipped"] = clipped


def describe(graph, node=SCREEN_ID, depth=0):
    """Indented text dump of the layout tree, for eyeballing a screen."""
    data = graph.nodes[node]
    label = f"{node} {data.get('class_')}"
    if data.get("layout"):
        n = sum(1 for _, _, d in graph.out_edges(node, data=True) if d["relationship"] == "CONTAINS")
        label += f" [{data['layout']} x{n}]"
    if data.get("layer") == "overlay":
        label += " [overlay]"
    if data.get("occluded_by"):
        label += f" (occluded by {data['occluded_by']})"
    elif data.get("clipped"):
        label += " (clipped)"
    if data.get("text"):
        label += f' "{data["text"]}"'
    lines = ["  " * depth + label]
    for _, child, d in graph.out_edges(node, data=True):
        if d["relationship"] == "CONTAINS":
            lines.append(describe(graph, child, depth + 1))
    return "\n".join(lines)
