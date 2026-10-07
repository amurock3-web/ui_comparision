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

from src.comparison.text_cleanup import clean_label
from shapely.geometry import box

from src.schema.ui_element import UIDocument

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


POSTER_CARDS = ("content_card", "cast_card", "celebrity_card")


def _inside_share(inner, outer) -> float:
    """Share of `inner`'s area inside `outer`; both [x, y, w, h] normalized."""
    ix = max(0.0, min(inner[0] + inner[2], outer[0] + outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[1] + inner[3], outer[1] + outer[3]) - max(inner[1], outer[1]))
    area = inner[2] * inner[3]
    return ix * iy / area if area > 0 else 0.0


def _is_dynamic(el, by_id, on_card_overlap=0.75, on_card_classes=("overlay_badge",)) -> bool:
    """§H ignore list: anything on a poster card is live data, and anything
    fusion tagged ignored (the status bar). Lives here because both the
    matcher (anchor selection) and the differ need the same rule.

    "On a card" is the parent link when fusion made one, else geometry: at
    least `on_card_overlap` of the element's box inside a card. Fusion leaves
    detector badges without a parent - on the Trending Search run all 12
    "Free" / "Most Viewed" / crown badges had parent_id None and were each
    reported as a Major B1/B2 although only the posters had changed.
    on_card_overlap=None switches the geometric test off, and it only ever
    applies to on_card_classes (badges): a Subscribe button or back arrow on a
    hero banner is chrome and must still be compared.
    """
    if el.metadata.get("ignored"):
        return True
    parent = by_id.get(el.parent_id) if el.parent_id else None
    if parent is not None:
        # A known parent wins over geometry: JioHotstar's floating TV/Movies/Sports
        # pill lies over a poster row, and its tabs (parent: navigation_bar) were
        # ignored as "on a card", so removing the TV tab went unreported.
        return parent.class_ in POSTER_CARDS
    if on_card_overlap is None or el.class_ not in on_card_classes or not el.normalized_bbox:
        return False
    return any(other.class_ in POSTER_CARDS and other.normalized_bbox
               and _inside_share(el.normalized_bbox, other.normalized_bbox) >= on_card_overlap
               for other in by_id.values() if other is not el)


def _on_card_overlap(full_config):
    """The geometric on-card threshold, or None when the rule is switched off."""
    if not full_config.get("comparison", {}).get("badges_on_cards_are_dynamic", True):
        return None
    return full_config.get("graph", {}).get("loose_containment_overlap", 0.75)


def _on_card_classes(full_config):
    """The classes the geometric on-card test applies to."""
    return tuple(full_config.get("comparison", {}).get("dynamic_on_card_classes", ["overlay_badge"]))


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


def _containment(normalized_bbox_a, normalized_bbox_b) -> float:
    """Intersection over the SMALLER box: how much the smaller one sits inside
    the larger. Where IoU asks "are these the same box", this asks "is one of
    these inside the other", which is what survives an element changing size.

    Needed because a shrinking element defeats IoU: on the benchmark's
    relabel_title case "Action Crime" -> "Action" narrows the title box, IoU
    falls to 0.29 and the pair scores 0.66 against a 0.70 threshold - so the
    size change prevents the match that would have reported the text change.
    """
    ax, ay, aw, ah = normalized_bbox_a
    bx, by, bw, bh = normalized_bbox_b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return 0.0
    box_a, box_b = box(ax, ay, ax + aw, ay + ah), box(bx, by, bx + bw, by + bh)
    smaller = min(box_a.area, box_b.area)
    return box_a.intersection(box_b).area / smaller if smaller else 0.0


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


def _agreed_shift(votes, tolerance, quorum):
    """The (dx, dy) a container's anchors agree on, or None.

    Anchors further than `tolerance` from the median are dropped rather than
    averaged in - a member that moved on its own must not drag the panel's
    estimate, and it still gets its own C1 finding from the residual. What is
    left has to be at least `quorum` votes, so a shift is never inferred from
    the one or two anchors that happened to survive the trim.

    Plain median absolute deviation was tried first and was too forgiving: it
    tolerates up to half the votes disagreeing, which on the SunNXT language
    screen let a sheet-wide shift be accepted while two header tabs that had
    not moved with it voted against.
    """
    if len(votes) < quorum:
        return None
    mx = statistics.median([v[0] for v in votes])
    my = statistics.median([v[1] for v in votes])
    kept = [v for v in votes
            if abs(v[0] - mx) <= tolerance and abs(v[1] - my) <= tolerance]
    if len(kept) < quorum:
        return None
    return (statistics.median([v[0] for v in kept]),
            statistics.median([v[1] for v in kept]), len(kept))


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
    # Leftovers the rescue pass could have paired more than one way (rules.md
    # §I: never guess) - reported REVIEW instead of a confident B1/B2.
    ambiguous: set = field(default_factory=set)
    by_production: dict = field(default_factory=dict)
    by_client: dict = field(default_factory=dict)

    def __post_init__(self):
        self.by_production = {m.production_id: m for m in self.matches}
        self.by_client = {m.client_id: m for m in self.matches}


class ElementMatcher:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        full = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        cfg = full.get("matching", {})
        self.on_card_overlap = _on_card_overlap(full)
        self.on_card_classes = _on_card_classes(full)
        glyph = full.get("comparison", {}).get("glyph_cleanup", {})
        self.glyph_classes = set(glyph.get("classes", ["tab_item", "button", "search_bar",
                                                        "section_title"])
                                 if glyph.get("enabled", True) else [])
        self.glyph_max_len = glyph.get("max_len", 2)
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
        # How much credit a contained-but-not-overlapping box gets against a
        # true IoU. Below 1.0 because containment is weaker evidence: a small
        # box sits fully inside any large one it happens to overlap.
        self.containment_credit = cfg.get("containment_credit", 0.5)
        rescue = cfg.get("rescue", {})
        self.rescue_enabled = rescue.get("enabled", True)
        self.rescue_max_distance = rescue.get("max_center_distance", 0.03)
        self.rescue_min_text = rescue.get("min_text_score", 0.5)
        self.rescue_min_margin = rescue.get("min_margin", 0.01)

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
                "text": _text_score(self._clean(p), self._clean(c)),
                "spatial": _spatial_score(
                    _normalized_center(pb), _normalized_center(c.normalized_bbox)
                ),
                "iou": max(_iou(pb, c.normalized_bbox),
                           self.containment_credit * _containment(pb, c.normalized_bbox)),
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

        ambiguous = set()
        if self.rescue_enabled:
            shift_of = ((lambda cid: self._shift_for(cid, client_graph, group_shifts))
                        if group_shifts else (lambda cid: (None, (0.0, 0.0))))
            rescued, ambiguous = self._rescue(production_doc, client_doc, matched_p, matched_c,
                                              prod_by_id, client_by_id, shift_of)
            for p, c in rescued:
                group, shift = shift_of(c.id)
                score, breakdown = score_pair(p, c, shift)
                matched_p.add(p.id)
                matched_c.add(c.id)
                matches.append(ElementMatch(p.id, c.id, round(score, 4), breakdown,
                                            match_pass=3, group=group, shift=shift))

        unmatched_production = [el.id for el in production_doc.elements if el.id not in matched_p]
        unmatched_client = [el.id for el in client_doc.elements if el.id not in matched_c]

        return MatchResult(matches, unmatched_production, unmatched_client, group_shifts,
                           ambiguous=ambiguous)

    def _clean(self, el):
        """Label without OCR'd icon glyphs, for the classes glyph_cleanup covers."""
        if el.text and el.class_ in self.glyph_classes:
            return clean_label(el.text, self.glyph_max_len)[0]
        return el.text

    def _rescue(self, production_doc, client_doc, matched_p, matched_c,
                prod_by_id, client_by_id, shift_of):
        """Pass 3: one element reported twice, as MISSING and as EXTRA.

        Found on the Trending Search pair: the search bar is in both screenshots
        30 px apart, but OCR attached no text to the production one, so the text
        score was 0 and the pair stayed under minimum_match_score - one bar, two
        Major FAILs. Leftovers of the same (non-null) class whose centres lie
        within max_center_distance of the diagonal (after the group shift) and
        whose texts agree, or where exactly one side has none, are paired - but only
        when they are each other's nearest candidate by a clear margin. Anything
        closer to a tie is marked ambiguous and becomes REVIEW, never a guess.
        Weights and minimum_match_score are untouched; rescued pairs are then
        judged normally (C1/C2/E1...), so a real move is still reported once.
        """
        W, H = client_doc.image_width or 1, client_doc.image_height or 1
        diag = (W ** 2 + H ** 2) ** 0.5

        def distance(p, c):
            _, (sx, sy) = shift_of(c.id)
            pc, cc = _normalized_center(p.normalized_bbox), _normalized_center(c.normalized_bbox)
            return (((pc[0] - sx - cc[0]) * W) ** 2 + ((pc[1] - sy - cc[1]) * H) ** 2) ** 0.5 / diag

        def usable(el, by_id, matched):
            return (el.id not in matched and el.class_ and el.normalized_bbox
                    and not _is_dynamic(el, by_id, self.on_card_overlap, self.on_card_classes))

        prods = [p for p in production_doc.elements if usable(p, prod_by_id, matched_p)]
        clients = [c for c in client_doc.elements if usable(c, client_by_id, matched_c)]
        cands = {}
        for c in clients:
            for p in prods:
                # Text-less look-alikes (a grid of unlabelled cards) cannot be
                # told apart by position alone: the neighbour is as close as
                # the element itself. At least one side must carry a label.
                if p.class_ != c.class_ or not (p.text or c.text):
                    continue
                if p.text and c.text and _text_score(p.text, c.text) < self.rescue_min_text:
                    continue
                d = distance(p, c)
                if d <= self.rescue_max_distance:
                    cands[(p.id, c.id)] = d

        def ranked(key_index, element_id):
            return sorted(d for k, d in cands.items() if k[key_index] == element_id)

        rescued, ambiguous = [], set()
        for (pid, cid), d in sorted(cands.items(), key=lambda kv: kv[1]):
            by_c, by_p = ranked(1, cid), ranked(0, pid)
            clear = all(len(r) == 1 or r[1] - r[0] >= self.rescue_min_margin for r in (by_c, by_p))
            if by_c[0] == d and by_p[0] == d and clear:
                rescued.append((prod_by_id[pid], client_by_id[cid]))
            else:
                ambiguous |= {pid, cid}
        taken = {p.id for p, _ in rescued} | {c.id for _, c in rescued}
        return rescued, ambiguous - taken

    def _is_anchor(self, p, c, breakdown, client_by_id) -> bool:
        """A pair trustworthy enough to vote on where its container moved."""
        if p.class_ is None or p.class_ != c.class_:
            return False
        if _is_dynamic(c, client_by_id, self.on_card_overlap, self.on_card_classes):
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
            pc, cc = _normalized_center(p.normalized_bbox), _normalized_center(c.normalized_bbox)
            vote = (pc[0] - cc[0], pc[1] - cc[1])
            # Vote in every container above this element, not just the nearest
            # one: the layout tree splits a panel into rows, so a row rarely
            # holds min_anchors on its own while the panel around it does. The
            # nearest container that both clears min_anchors and agrees wins,
            # and the screen root usually mixes panels and fails the spread
            # test - which is the point, there is no global shift.
            group = _container_of(client_graph, c.id)
            while group is not None:
                anchors.setdefault(group, []).append(vote)
                group = _container_of(client_graph, group)

        shifts = {}
        for group, votes in anchors.items():
            agreed = _agreed_shift(votes, self.max_spread_norm, self.min_anchors)
            if agreed is None:
                continue  # too few anchors, or they did not move as one piece
            dx, dy, kept = agreed
            members = [v for _, v, data in client_graph.out_edges(group, data=True)
                       if data.get("relationship") == "CONTAINS"]
            shifts[group] = {"shift": (dx, dy), "anchors": kept, "members": members}
        return shifts

    def _shift_for(self, client_id, client_graph, shifts):
        """This element's container shift, else the nearest one above it.

        Nearest wins, which is what keeps this honest: on the SunNXT language
        screen the header tabs take their own container's +21 px while the
        sheet's rows take -139 px. The screen root is allowed only as the last
        resort, for the elements the layout tree left hanging directly off it
        (here the Save button and the subtitle, which did ride with the sheet)
        - without it they get no shift and their panel's move is reported
        against each of them separately.
        """
        group = _container_of(client_graph, client_id)
        while group is not None:
            if group in shifts:
                return group, shifts[group]["shift"]
            group = _container_of(client_graph, group)
        return None, (0.0, 0.0)
