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

Weights and the minimum-match-score threshold are read from
config/config.yaml (matching.weights, matching.minimum_match_score) per
design.md §13 — not hard-coded.
"""

import difflib
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from shapely.geometry import box

from src.schema.ui_element import UIDocument

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


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


@dataclass
class MatchResult:
    matches: list
    unmatched_production: list
    unmatched_client: list
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

        candidates = []
        for p in production_doc.elements:
            for c in client_doc.elements:
                breakdown = {
                    "class": _class_score(p.class_, c.class_),
                    "text": _text_score(p.text, c.text),
                    "spatial": _spatial_score(
                        _normalized_center(p.normalized_bbox), _normalized_center(c.normalized_bbox)
                    ),
                    "iou": _iou(p.normalized_bbox, c.normalized_bbox),
                    "context": _context_score(prod_context[p.id], client_context[c.id]),
                }
                score = (
                    self.w_class * breakdown["class"]
                    + self.w_text * breakdown["text"]
                    + self.w_spatial * breakdown["spatial"]
                    + self.w_iou * breakdown["iou"]
                    + self.w_context * breakdown["context"]
                )
                if score >= self.min_score:
                    candidates.append((score, p.id, c.id, breakdown))

        candidates.sort(key=lambda cand: cand[0], reverse=True)

        matched_p, matched_c = set(), set()
        matches = []
        for score, pid, cid, breakdown in candidates:
            if pid in matched_p or cid in matched_c:
                continue
            matched_p.add(pid)
            matched_c.add(cid)
            matches.append(ElementMatch(pid, cid, round(score, 4), breakdown))

        unmatched_production = [el.id for el in production_doc.elements if el.id not in matched_p]
        unmatched_client = [el.id for el in client_doc.elements if el.id not in matched_c]

        return MatchResult(matches, unmatched_production, unmatched_client)
