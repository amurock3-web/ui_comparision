"""
UI graph construction using NetworkX (design.md §6, architecture.md §8).

Turns a fused UIDocument into a graph: each element becomes a node, and
relationships (CONTAINS, ABOVE, BELOW, LEFT_OF, RIGHT_OF, ALIGNED_WITH,
OVERLAPS, ORDERED_BEFORE) are inferred from geometry — not every
mathematically possible pair, only meaningful ones (architecture.md §8 /
design.md §6). Only CONTAINS is materialized (not a separate CHILD_OF
reverse edge); the reverse is derivable via graph.reverse() if needed.
"""

import json
from pathlib import Path

import networkx as nx
import yaml
from networkx.readwrite import json_graph
from shapely.geometry import box

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def _rect(bbox: list):
    x, y, w, h = bbox
    return box(x, y, x + w, y + h)


def _containment_overlap(parent_bbox: list, child_bbox: list) -> float:
    """Fraction of child's area that lies inside parent."""
    child_area = _rect(child_bbox).area
    if child_area == 0:
        return 0.0
    return _rect(parent_bbox).intersection(_rect(child_bbox)).area / child_area


def _iou(bbox_a: list, bbox_b: list) -> float:
    ra, rb = _rect(bbox_a), _rect(bbox_b)
    union = ra.union(rb).area
    if union == 0:
        return 0.0
    return ra.intersection(rb).area / union


class UIGraphBuilder:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        cfg = yaml.safe_load(Path(config_path).read_text()).get("graph", {})
        self.containment_min_overlap = cfg.get("containment_min_overlap", 0.9)
        self.alignment_epsilon = cfg.get("alignment_epsilon_norm", 0.01)
        self.adjacency_max_gap = cfg.get("adjacency_max_gap_norm", 0.05)

    def build(self, ui_document) -> "nx.MultiDiGraph":
        # MultiDiGraph, not DiGraph: two elements can be related in more
        # than one way at once (e.g. LEFT_OF and ALIGNED_WITH between the
        # same pair) — a plain DiGraph only keeps one edge per ordered
        # pair and the second add_edge() would silently overwrite the
        # first relationship.
        graph = nx.MultiDiGraph()
        elements = ui_document.elements
        W, H = ui_document.image_width, ui_document.image_height

        print(f"[GRAPH] Building UI graph from {len(elements)} elements...")

        for el in elements:
            graph.add_node(
                el.id,
                class_=el.class_,
                text=el.text,
                bbox=el.bbox,
                normalized_bbox=el.normalized_bbox,
                confidence=el.confidence,
            )

        # Fusion can now produce elements with no geometry at all (a VLM
        # classification like "icon" with no OCR-matchable text and no
        # grid rule — see fusion/fuse.py). They're still nodes above, just
        # excluded from every geometry-based relationship below since
        # there's nothing to compare.
        geo_elements = [el for el in elements if el.bbox is not None]
        ungrounded = len(elements) - len(geo_elements)
        if ungrounded:
            print(f"[GRAPH] {ungrounded} element(s) have no geometry (classification-only) — "
                  "added as nodes, no geometric edges.")

        # CONTAINS: strictly larger element whose bbox covers most of the
        # smaller element's area. Skip self-pairs and near-identical boxes
        # (those go to OVERLAPS instead, they're not a containment).
        parent_of = {}
        for a in geo_elements:
            for b in geo_elements:
                if a.id == b.id:
                    continue
                a_area = a.bbox[2] * a.bbox[3]
                b_area = b.bbox[2] * b.bbox[3]
                if a_area <= b_area:
                    continue
                overlap = _containment_overlap(a.bbox, b.bbox)
                if overlap >= self.containment_min_overlap:
                    graph.add_edge(a.id, b.id, relationship="CONTAINS")
                    # keep the tightest (smallest-area) containing parent
                    current = parent_of.get(b.id)
                    if current is None or a_area < current[1]:
                        parent_of[b.id] = (a.id, a_area)

        # OVERLAPS: meaningful IoU but not a containment relationship —
        # flags likely-duplicate detections.
        for i, a in enumerate(geo_elements):
            for b in geo_elements[i + 1:]:
                iou = _iou(a.bbox, b.bbox)
                if 0.05 < iou < self.containment_min_overlap:
                    graph.add_edge(a.id, b.id, relationship="OVERLAPS")
                    graph.add_edge(b.id, a.id, relationship="OVERLAPS")

        # Spatial relations only within siblings (same parent, or both
        # top-level) — avoids generating every O(n^2) pair across the
        # whole screen (design.md §6: "avoid generating every
        # mathematically possible relation").
        groups = {}
        for el in geo_elements:
            parent_id = parent_of.get(el.id, (None, None))[0]
            groups.setdefault(parent_id, []).append(el)

        for siblings in groups.values():
            self._add_spatial_edges(graph, siblings, W, H)

        print(f"[GRAPH] Done - {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges.")

        return graph

    def _add_spatial_edges(self, graph, siblings, W, H):
        for i, a in enumerate(siblings):
            for b in siblings[i + 1:]:
                ax, ay = a.center[0] / W, a.center[1] / H
                bx, by = b.center[0] / W, b.center[1] / H
                dx, dy = bx - ax, by - ay

                if abs(dx) > abs(dy) and abs(dx) > self.adjacency_max_gap:
                    left, right = (a, b) if dx > 0 else (b, a)
                    graph.add_edge(left.id, right.id, relationship="LEFT_OF")
                    graph.add_edge(right.id, left.id, relationship="RIGHT_OF")
                    if dx > 0:
                        graph.add_edge(a.id, b.id, relationship="ORDERED_BEFORE")
                    else:
                        graph.add_edge(b.id, a.id, relationship="ORDERED_BEFORE")
                elif abs(dy) > self.adjacency_max_gap:
                    above, below = (a, b) if dy > 0 else (b, a)
                    graph.add_edge(above.id, below.id, relationship="ABOVE")
                    graph.add_edge(below.id, above.id, relationship="BELOW")
                    if dy > 0:
                        graph.add_edge(a.id, b.id, relationship="ORDERED_BEFORE")
                    else:
                        graph.add_edge(b.id, a.id, relationship="ORDERED_BEFORE")

                a_left, a_top = a.normalized_bbox[0], a.normalized_bbox[1]
                b_left, b_top = b.normalized_bbox[0], b.normalized_bbox[1]
                if abs(a_left - b_left) <= self.alignment_epsilon or abs(a_top - b_top) <= self.alignment_epsilon:
                    graph.add_edge(a.id, b.id, relationship="ALIGNED_WITH")
                    graph.add_edge(b.id, a.id, relationship="ALIGNED_WITH")

    @staticmethod
    def save_graph_json(graph, path: Path):
        data = json_graph.node_link_data(graph, edges="edges")
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
