"""
Element matching between Production and Client (design.md §7, rules.md §7).

Scores every candidate (production, client) pair by combining class, text,
spatial, bbox/IoU, and graph-neighborhood ("context") similarity, then
resolves correspondence with a single greedy pass over all candidates
sorted by score — the highest-scoring pair is kept, and any element that
loses a contested match falls through to its next-best remaining
candidate. This mirrors the "candidate list + best match + conflict
resolution" idea from Moradi et al., "AI for context-aware visual change
detection in software test automation" (Section 3.3), but as one global
sort instead of their per-node loop, which gives the same outcome more
directly.

Unlike that paper's context score — which recurses through neighbors of
neighbors until it revisits an already-seen node, with no bound on depth
or cost — the context score here only looks at each element's direct
graph neighbors (one hop). That keeps cost at O(degree) per pair instead
of risking exponential blowup on dense UIs, at the cost of not
propagating similarity transitively through the graph.

A second pass handles panels that moved as one piece. After pass 1 the
confident matches ("anchors") inside each layout-graph container give that
container a median shift; still-unmatched elements are then re-scored with
the production box moved back by their container's shift. The shift is
per container, never global — on the SunNXT language screen the bottom
sheet moved ~0.058 while the header behind it moved ~0.004, and a global
correction would have made a header tab reachable from a sheet tab with
the same label.

Weights and the minimum-match-score threshold are read from
config/config.yaml (matching.weights, matching.minimum_match_score,
matching.group_shift) per design.md §13 — not hard-coded.
"""

import difflib
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from shapely.geometry import box

from src.schema.ui_element import UIDocument

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


def _is_dynamic(el, by_id) -> bool:
    """§H ignore list: anything inside a content_card is live data, and
    anything fusion tagged ignored (the status bar). Lives here because both
    the matcher (anchor selection) and the differ need the same rule."""
    if el.metadata.get("ignored"):
        return True
    parent = by_id.get(el.parent_id) if el.parent_id else None
    return parent is not None and parent.class_ == "content_card"


def _normalize_text(text):
    if not text:
        return ""
    return " ".join(text.lower().split())


def _text_score(text_a, text_b) -> float:
    a, b = _normalize_text(text_a), _normalize_text(text_b)
    if not a and not b:
        return 0.5  # neither side has text — uninformative, not a mismatch
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _class_score(class_a, class_b) -> float:
    if class_a is None or class_b is None:
        return 0.5  # unclassified evidence — don't penalize as a hard mismatch
    return 1.0 if class_a == class_b else 0.0


def _normalized_center(normalized_bbox):
    x, y, w, h = normalized_bbox
    return [x + w / 2, y + h / 2]


def _spatial_score(center_a, center_b) -> float:
    dist = ((center_a[0] - center_b[0]) ** 2 + (center_a[1] - center_b[1]) ** 2) ** 0.5
    return 1 - min(dist, 1.0)


def _iou(normalized_bbox_a, normalized_bbox_b) -> float:
    ax, ay, aw, ah = normalized_bbox_a
    bx, by, bw, bh = normalized_bbox_b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    box_a = box(ax, ay, ax + aw, ay + ah)
    box_b = box(bx, by, bx + bw, by + bh)
    union = box_a.union(box_b).area
    if union == 0:
        return 0.0
    return box_a.intersection(box_b).area / union


def _unshift(normalized_bbox, shift):
    """Production box moved back by its group's shift (x/y only)."""
    dx, dy = shift
    x, y, w, h = normalized_bbox
    return [x - dx, y - dy, w, h]


def _container_of(graph, node_id):
    """The layout container that CONTAINS this node (row/stack/section/overlay)."""
    if graph is None or node_id not in graph:
        return None
    for u, _, data in graph.in_edges(node_id, data=True):
        if data.get("relationship") == "CONTAINS":
            return u
    return None


def _mad(values, centre) -> float:
    """Median absolute deviation — spread that one outlier cannot inflate."""
    return statistics.median([abs(v - centre) for v in values]) if values else 0.0


def _node_context(graph, node_id, class_by_id):
    """One-hop (relationship, direction, neighbor_class) set around a node."""
    context = set()
    if graph is None or node_id not in graph:
        return context
    for _, v, data in graph.out_edges(node_id, data=True):
        context.add((data.get("relationship"), "out", class_by_id.get(v)))
    for u, _, data in graph.in_edges(node_id, data=True):
        context.add((data.get("relationship"), "in", class_by_id.get(u)))
    return context


def _context_score(context_a, context_b) -> float:
    union = context_a | context_b
    if not union:
        return 0.5  # both isolated (or no graph supplied) — no structural signal either way
    return len(context_a & context_b) / len(union)


@dataclass
class ElementMatch:
    production_id: str
    client_id: str
    score: float
    breakdown: dict
    match_pass: int = 1
    group: str | None = None
    shift: tuple = (0.0, 0.0)


@dataclass
class MatchResult:
    matches: list
    unmatched_production: list
    unmatched_client: list
    # container id -> {"shift": (dx, dy), "anchors": n, "members": [ids]}
    group_shifts: dict = field(default_factory=dict)
    by_production: dict = field(default_factory=dict)
    by_client: dict = field(default_factory=dict)

    def __post_init__(self):
        self.by_production = {m.production_id: m for m in self.matches}
        self.by_client = {m.client_id: m for m in self.matches}


class ElementMatcher:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        cfg = yaml.safe_load(Path(config_path).read_text()).get("matching", {})
        self.min_score = cfg.get("minimum_match_score", 0.70)
        weights = cfg.get("weights", {})
        self.w_class = weights.get("class", 0.25)
        self.w_text = weights.get("text", 0.25)
        self.w_spatial = weights.get("spatial", 0.2)
        self.w_iou = weights.get("iou", 0.2)
        self.w_context = weights.get("context", 0.1)
        gs = cfg.get("group_shift", {})
        self.group_shift_enabled = gs.get("enabled", True)
        self.min_anchors = gs.get("min_anchors", 3)
        self.anchor_min_text_score = gs.get("anchor_min_text_score", 0.9)
        self.anchor_min_iou = gs.get("anchor_min_iou", 0.5)
        self.max_spread_norm = gs.get("max_spread_norm", 0.01)

    def match(
        self,
        production_doc: UIDocument,
        client_doc: UIDocument,
        production_graph=None,
        client_graph=None,
    ) -> MatchResult:
        prod_class_by_id = {el.id: el.class_ for el in production_doc.elements}
        client_class_by_id = {el.id: el.class_ for el in client_doc.elements}

        prod_context = {
            el.id: _node_context(production_graph, el.id, prod_class_by_id)
            for el in production_doc.elements
        }
        client_context = {
            el.id: _node_context(client_graph, el.id, client_class_by_id)
            for el in client_doc.elements
        }

        def score_pair(p, c, shift):
            pb = p.normalized_bbox if shift == (0.0, 0.0) else _unshift(p.normalized_bbox, shift)
            breakdown = {
                "class": _class_score(p.class_, c.class_),
                "text": _text_score(p.text, c.text),
                "spatial": _spatial_score(
                    _normalized_center(pb), _normalized_center(c.normalized_bbox)
                ),
                "iou": _iou(pb, c.normalized_bbox),
                "context": _context_score(prod_context[p.id], client_context[c.id]),
            }
            score = (
                self.w_class * breakdown["class"]
                + self.w_text * breakdown["text"]
                + self.w_spatial * breakdown["spatial"]
                + self.w_iou * breakdown["iou"]
                + self.w_context * breakdown["context"]
            )
            return score, breakdown

        matched_p, matched_c = set(), set()
        matches = []

        def resolve(pairs, pass_no, shift_of=lambda cid: (None, (0.0, 0.0))):
            """Greedy global sort: best pair wins, losers fall through to their
            next-best remaining candidate."""
            for score, pid, cid, breakdown in sorted(pairs, key=lambda cand: cand[0], reverse=True):
                if pid in matched_p or cid in matched_c:
                    continue
                matched_p.add(pid)
                matched_c.add(cid)
                group, shift = shift_of(cid)
                matches.append(ElementMatch(pid, cid, round(score, 4), breakdown,
                                            match_pass=pass_no, group=group, shift=shift))

        # Pass 1 — unshifted, exactly as before.
        pass1 = []
        for p in production_doc.elements:
            for c in client_doc.elements:
                score, breakdown = score_pair(p, c, (0.0, 0.0))
                if score >= self.min_score:
                    pass1.append((score, p.id, c.id, breakdown))
        resolve(pass1, 1)

        prod_by_id = {el.id: el for el in production_doc.elements}
        client_by_id = {el.id: el for el in client_doc.elements}
        group_shifts = {}

        if self.group_shift_enabled:
            group_shifts = self._group_shifts(matches, prod_by_id, client_by_id, client_graph)
            if group_shifts:
                shift_of = lambda cid: self._shift_for(cid, client_graph, group_shifts)
                # The shifts are only known after pass 1, so record them on
                # those matches too: their residual (differ.py C1) is measured
                # against their group, not against the screen.
                for m in matches:
                    m.group, m.shift = shift_of(m.client_id)
                # Pass 2 — only the elements pass 1 could not place, and only
                # their own container's shift, so a shifted candidate can never
                # reach a same-label element in a different container.
                pass2 = []
                for p in production_doc.elements:
                    if p.id in matched_p:
                        continue
                    for c in client_doc.elements:
                        if c.id in matched_c:
                            continue
                        _, shift = shift_of(c.id)
                        if shift == (0.0, 0.0):
                            continue
                        score, breakdown = score_pair(p, c, shift)
                        if score >= self.min_score:
                            pass2.append((score, p.id, c.id, breakdown))
                resolve(pass2, 2, shift_of)

        unmatched_production = [el.id for el in production_doc.elements if el.id not in matched_p]
        unmatched_client = [el.id for el in client_doc.elements if el.id not in matched_c]

        return MatchResult(matches, unmatched_production, unmatched_client, group_shifts)

    def _is_anchor(self, p, c, breakdown, client_by_id) -> bool:
        """A pair trustworthy enough to vote on where its container moved."""
        if p.class_ is None or p.class_ != c.class_:
            return False
        if _is_dynamic(c, client_by_id):
            return False
        if p.text and c.text and breakdown["text"] >= self.anchor_min_text_score:
            return True
        return breakdown["iou"] >= self.anchor_min_iou

    def _group_shifts(self, matches, prod_by_id, client_by_id, client_graph) -> dict:
        """Median (dx, dy) per client container, from that container's anchors."""
        anchors = {}
        for m in matches:
            p, c = prod_by_id[m.production_id], client_by_id[m.client_id]
            if not self._is_anchor(p, c, m.breakdown, client_by_id):
                continue
            group = _container_of(client_graph, c.id)
            if group is None:
                continue
            pc, cc = _normalized_center(p.normalized_bbox), _normalized_center(c.normalized_bbox)
            anchors.setdefault(group, []).append((pc[0] - cc[0], pc[1] - cc[1]))

        shifts = {}
        for group, votes in anchors.items():
            if len(votes) < self.min_anchors:
                continue
            dxs, dys = [v[0] for v in votes], [v[1] for v in votes]
            dx, dy = statistics.median(dxs), statistics.median(dys)
            if _mad(dxs, dx) > self.max_spread_norm or _mad(dys, dy) > self.max_spread_norm:
                continue  # did not move as one piece
            members = [v for _, v, data in client_graph.out_edges(group, data=True)
                       if data.get("relationship") == "CONTAINS"]
            shifts[group] = {"shift": (dx, dy), "anchors": len(votes), "members": members}
        return shifts

    def _shift_for(self, client_id, client_graph, shifts):
        """This element's container shift, else the nearest one above it."""
        group = _container_of(client_graph, client_id)
        while group is not None:
            if group in shifts:
                return group, shifts[group]["shift"]
            group = _container_of(client_graph, group)
        return None, (0.0, 0.0)
