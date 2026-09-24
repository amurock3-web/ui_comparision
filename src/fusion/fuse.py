"""
OCR + VLM fusion (design.md §4, architecture.md §6).

The VLM (src/vlm/engine.py, default `analyze()`) is classify-only: it
returns class/text/description/approximate_location, never a bbox.
Testing showed VLM-provided bboxes are NOT deterministic — repeated calls
on the identical image/prompt produced different box counts and
positions (see VLMEngine.analyze_grounded_experimental()'s docstring).
That's disqualifying for a tool whose whole job is "did this change
between two screenshots" — non-deterministic geometry would produce
spurious diffs even comparing a screenshot against itself. So this
module gets real geometry from OCR wherever possible, with one
exception — content_card, see below:

- content_card: geometry comes exclusively from a direct VLM grounding
  call (VLMEngine.ground_content_cards_experimental()), passed in as the
  required `grounded_cards` argument to fuse() — there is no fallback.
  An earlier deterministic grid-inference approach (OCR section_title
  anchors defining row bands, each row's width divided evenly by card
  count) was removed 2026-09-07: it silently dropped whole rows on
  screens with more rows than approximate_location's top/middle/bottom
  vocabulary can distinguish (see git history for
  `_infer_card_bboxes`/`_find_row_anchors` if this needs revisiting).
  Tested 2026-09-07: near-deterministic within a back-to-back sequence
  (~1px agreement across 3 runs at temperature=0), but a
  session-to-session comparison showed ~4% normalized position drift —
  wider than this module's other geometry sources — so these elements
  are tagged metadata.bbox_source="vlm_grounded" (source stays "vlm")
  for differ.py to apply a looser position tolerance than it uses for
  bbox_source="ocr_exact" (not yet implemented in differ.py). No
  fallback exists if the grounding call fails or returns nothing — every
  content_card element comes from `grounded_cards.elements` as-is.
- overlay_badge: DETERMINISTIC OCR keyword match. Any high-confidence OCR
  text matching a narrow badge keyword set, whose center falls inside an
  inferred content_card bbox, gets promoted using OCR's exact bbox.
  Deliberately narrow keyword set — expand only with evidence from real
  screenshots.
- Every other VLM classification (section_title, tab_item, icon,
  cast_card, celebrity_card, navigation_bar, ...): matched from VLM's
  ocr_ref_id to OCR's exact bbox by id when the VLM gave one (Set-of-Marks
  style — see _match_for_class docstring), else from VLM text to OCR's
  exact bbox via text similarity, else a zone-only fallback (highest-
  confidence unused OCR box inside approximate_location's zone, no text
  comparison) — see _match_for_class for the full precedence and why each
  fallback exists. Applied uniformly to every class since 2026-09-07 (was
  previously restricted to a "text-matchable" class allowlist, which left
  icon/cast_card/celebrity_card/navigation_bar unmatched even when an
  exact-text OCR box existed, e.g. an "icon" labeled "Search" never
  matched OCR's own "Search" text). A VLM element that still has no match
  after all three attempts is tagged metadata.match_status="uncertain"
  (rules.md §10 — preserve uncertainty explicitly, don't just leave it
  implicit in bbox=None).
- Unmatched OCR text whose center falls inside a content_card's bbox
  (e.g. a poster's title/subtitle text like "WALTER") gets parent_id set
  to that card's element id instead of staying a floating top-level
  element — it's unclassified, but its position in the hierarchy is
  known. Unmatched OCR text that ALSO isn't inside any card is kept as
  evidence (source="ocr", class=None, never destroy evidence per
  rules.md §10) and tagged metadata.match_status="uncertain" — genuinely
  unexplained, not silently dropped.
"""

import re
from pathlib import Path
from typing import Optional

import yaml
from difflib import SequenceMatcher

from src.ocr.engine import confidence_tier
from src.schema.ui_element import UIDocument, UIElement

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"

# No direct measurement exists for grid-inferred or otherwise-ungrounded
# VLM classifications — treat as medium confidence (rules.md §10: don't
# overstate certainty by defaulting to 1.0).
UNGROUNDED_CONFIDENCE = 0.5

# A zone-only match (position agreement alone, no text comparison — see
# _match_for_class) is weaker evidence than a real text match: discount
# the matched OCR element's confidence rather than reporting it at face
# value (rules.md §10, don't silently promote a positional guess to fact).
ZONE_ONLY_CONFIDENCE_DISCOUNT = 0.5

# Confidence for a content_card grounded directly by the VLM (see
# VLMEngine.ground_content_cards_experimental()). Higher than
# UNGROUNDED_CONFIDENCE (that's a guess; this is a real measurement) but
# below OCR-exact's usual near-1.0 (measured ~4% session-to-session
# position drift, see module docstring) — rules.md §10: don't overstate
# certainty either direction.
VLM_GROUNDED_CONFIDENCE = 0.75

# Detector classes whose OCR text is separate content, not their own label
# (fuse_detections()). Text on posters/photos is dropped (it is artwork: titles,
# garbage reads of Tamil art); text in a navigation_bar stays a child element.
POSTER_CLASSES = {"content_card", "cast_card", "celebrity_card"}
CONTAINER_CLASSES = POSTER_CLASSES | {"navigation_bar"}
CHILD_TEXT_CLASSES = CONTAINER_CLASSES - POSTER_CLASSES

# A low-tier detection at least this much inside a more confident detection of
# another class is a duplicate guess (ss012: a 0.32 content_card 93% inside the
# floating tab bar's 0.94 tab_item) - ignored instead of uncertain.
DUPLICATE_INSIDE_FRACTION = 0.8


def _normalize(text: Optional[str]) -> str:
    if text is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _similarity(a: Optional[str], b: Optional[str]) -> float:
    a, b = _normalize(a), _normalize(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


_VERTICAL_LOCATION_TOKENS = {"top", "middle", "bottom"}
_HORIZONTAL_LOCATION_TOKENS = {"left", "center", "right"}


def _location_zone_bounds(location_str: str, image_width: int, image_height: int):
    """Convert a VLM approximate_location string like 'bottom-left' into
    a pixel-space rectangle for positional disambiguation.

    Tokenizes on "-" and classifies each token into the vertical
    (top/middle/bottom) or horizontal (left/center/right) vocabulary the
    prompt documents (prompts.py's approximate_location instruction),
    instead of a fixed-priority substring `if/elif` chain. The old
    substring check silently favored whichever of "top"/"bottom"/"middle"
    (or "left"/"right"/"center") it happened to test first, with no
    signal that the input didn't cleanly parse — e.g. a malformed
    three-token value like "bottom-middle-right" (seen in production,
    not in the documented two-token vocabulary) silently resolved to a
    specific zone via that arbitrary code order. Now: exactly one
    recognized token for an axis narrows that axis's zone same as
    before; zero or more than one (ambiguous/malformed) leaves that axis
    unrestricted rather than guessing — rules.md §10, don't silently
    promote an uncertain signal to a confident fact. Note this doesn't
    fix a token that's simply wrong (e.g. the model saying "right" for
    something that's actually centered) — that's a VLM output problem,
    not a parsing one; this only removes the parser's own guessing."""
    tokens = (location_str or "").split("-")
    vertical = [t for t in tokens if t in _VERTICAL_LOCATION_TOKENS]
    horizontal = [t for t in tokens if t in _HORIZONTAL_LOCATION_TOKENS]

    x0, x1 = 0, image_width
    y0, y1 = 0, image_height

    if len(vertical) == 1:
        if vertical[0] == "top":
            y1 = image_height / 3
        elif vertical[0] == "bottom":
            y0 = image_height * 2 / 3
        else:  # "middle"
            y0, y1 = image_height / 3, image_height * 2 / 3

    if len(horizontal) == 1:
        if horizontal[0] == "left":
            x1 = image_width / 3
        elif horizontal[0] == "right":
            x0 = image_width * 2 / 3
        else:  # "center"
            x0, x1 = image_width / 3, image_width * 2 / 3

    return x0, y0, x1, y1


def _in_zone(ocr_el, zone) -> bool:
    x0, y0, x1, y1 = zone
    cx, cy = ocr_el.center
    return x0 <= cx <= x1 and y0 <= cy <= y1


def _point_in_bbox(point, bbox, padding=0) -> bool:
    px, py = point
    x, y, w, h = bbox
    return (x - padding) <= px <= (x + w + padding) and (y - padding) <= py <= (y + h + padding)


def _inside_fraction(a, b) -> float:
    """Share of bbox a's area that lies inside bbox b."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return iw * ih / (aw * ah) if aw * ah else 0.0


def _reading_order(ocr_elements):
    """Lines top to bottom, left to right within a line. Two boxes share a
    line when their centers are within half a box height; a plain (y, x)
    sort breaks on sub-pixel jitter ("Live TV Movies Free More" on ss012)."""
    lines = []
    for el in sorted(ocr_elements, key=lambda e: e.center[1]):
        if lines and abs(el.center[1] - lines[-1][0].center[1]) <= el.bbox[3] / 2:
            lines[-1].append(el)
        else:
            lines.append([el])
    return [el for line in lines for el in sorted(line, key=lambda e: e.center[0])]


class FusionEngine:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        cfg = yaml.safe_load(Path(config_path).read_text()).get("fusion", {})
        self.text_similarity_threshold = cfg.get("text_similarity_threshold", 0.6)
        self.badge_keywords = set(cfg.get("badge_keywords", ["free", "new"]))
        self.badge_containment_padding = cfg.get("badge_containment_padding", 40)
        self.status_bar_height_norm = cfg.get("status_bar_height_norm", 0.04)

    def _match_ocr_for_text(self, vlm_text, ocr_elements, used_ocr_ids, location_str="", W=None, H=None):
        """Match VLM text to an OCR detection by similarity, preferring
        candidates whose position agrees with approximate_location —
        identical text can appear more than once on screen (a badge and
        a nav tab both saying "Free"), and text similarity alone can't
        disambiguate that; position can."""
        candidates = []
        for ocr_el in ocr_elements:
            if ocr_el.id in used_ocr_ids:
                continue
            score = _similarity(vlm_text, ocr_el.text)
            if score >= self.text_similarity_threshold:
                candidates.append((ocr_el, score))

        if not candidates:
            return None, 0.0
        if len(candidates) == 1 or not location_str or not W:
            return max(candidates, key=lambda c: c[1])

        zone = _location_zone_bounds(location_str, W, H)
        in_zone_candidates = [c for c in candidates if _in_zone(c[0], zone)]
        if in_zone_candidates:
            return max(in_zone_candidates, key=lambda c: c[1])
        return max(candidates, key=lambda c: c[1])

    def _match_for_class(self, vlm_el, ocr_elements, used_ocr_ids, W, H):
        """Ground a VLM classification to an OCR detection.

        Preference order: 1) SoM id match ("som_id") — the VLM's own
        ocr_ref_id says exactly which OCR box it means, no guessing at
        all (arXiv:2408.00203, OmniParser's Set-of-Marks: showing the
        model numbered candidate boxes and having it answer with an id,
        instead of re-describing the element in free text and leaving a
        downstream step to guess the association, raised GPT-4V's
        correct-box accuracy from 70.5% to 93.8% in their SeeAssign eval).
        2) text-similarity match. 3) ZONE-ONLY fallback (highest-
        confidence unused OCR element inside approximate_location's zone,
        no text comparison at all) when vlm_el.text is empty or nothing
        clears the similarity threshold.

        Text-similarity and zone matching remain as fallbacks for when
        ocr_ref_id is absent, wrong, or already claimed by an earlier
        element — e.g. two OCR titles sharing a common prefix ("Action
        Crime"/"Action Drama"/"Action Comedy") score 0.6-0.85 against each
        other by text similarity alone, and a title sitting a few px on
        the wrong side of a rigid position-zone boundary used to get
        silently matched to the wrong title; an id match sidesteps both
        failure modes because it doesn't re-derive the association at all.

        The zone-only fallback exists because the VLM's "text" field has
        been observed to come back null far more often than it should —
        including for elements OCR itself reads at high confidence in
        the same run — a known effect of schema-constrained decoding
        biasing toward the "safe" null branch of a nullable field (see
        this fix's plan notes / the "Let Me Speak Freely?" paper,
        arXiv:2408.02442). class + approximate_location remain reliable
        even when text isn't, so grounding shouldn't depend on text.

        Returns (ocr_element_or_None, method, score) where method is
        "som_id", "text_similarity" or "zone_only_fallback", and score is
        the text similarity score (only meaningful for text_similarity).
        """
        if vlm_el.ocr_ref_id:
            for ocr_el in ocr_elements:
                if ocr_el.id == vlm_el.ocr_ref_id and ocr_el.id not in used_ocr_ids:
                    return ocr_el, "som_id", 1.0
            # id was hallucinated, stale, or already claimed — fall through
            # to text/zone matching rather than leaving this ungrounded.

        if vlm_el.text:
            ocr_match, score = self._match_ocr_for_text(
                vlm_el.text, ocr_elements, used_ocr_ids,
                location_str=vlm_el.approximate_location, W=W, H=H,
            )
            if ocr_match:
                return ocr_match, "text_similarity", score

        if not vlm_el.approximate_location or not W:
            return None, None, None

        zone = _location_zone_bounds(vlm_el.approximate_location, W, H)
        candidates = [
            ocr_el for ocr_el in ocr_elements
            if ocr_el.id not in used_ocr_ids and _in_zone(ocr_el, zone)
        ]
        if not candidates:
            return None, None, None
        return max(candidates, key=lambda e: e.confidence), "zone_only_fallback", None

    def _promote_badges(self, ocr_elements, card_bboxes, used_ocr_ids):
        """Deterministic badge detection: high-confidence OCR text
        matching a badge keyword, whose center falls inside a
        content_card's bbox, becomes an overlay_badge using OCR's exact
        bbox. No VLM involvement — see module docstring."""
        badge_matches = []
        for ocr_el in ocr_elements:
            if ocr_el.id in used_ocr_ids:
                continue
            if ocr_el.confidence_tier == "low":
                continue
            if _normalize(ocr_el.text) not in self.badge_keywords:
                continue
            for card_bbox in card_bboxes:
                if _point_in_bbox(ocr_el.center, card_bbox, padding=self.badge_containment_padding):
                    badge_matches.append((ocr_el, card_bbox))
                    used_ocr_ids.add(ocr_el.id)
                    break
        return badge_matches

    def fuse(self, ocr_result, vlm_result, grounded_cards, screen_id: str = None,
             source: str = "fused") -> UIDocument:
        """grounded_cards is required: a VLMGroundedResult from
        VLMEngine.ground_content_cards_experimental() — the sole
        content_card geometry source (see module docstring). There is no
        fallback if it's empty or the call failed upstream; that's the
        caller's responsibility to handle."""
        screen_id = screen_id or ocr_result.screen
        W, H = ocr_result.image_width, ocr_result.image_height
        ocr_elements = ocr_result.elements
        vlm_elements = vlm_result.elements

        print(f"[FUSION] Fusing {len(ocr_elements)} OCR + {len(vlm_elements)} VLM observations...")

        used_ocr_ids = set()
        elements = []
        counter = 0

        for vlm_el in vlm_elements:
            if vlm_el.class_ in ("overlay_badge", "content_card"):
                # Badges are never VLM-only — handled ONLY via OCR
                # keyword+containment below, since VLM grounding for small
                # elements like badges produced imprecise, offset boxes in
                # testing. content_cards come solely from grounded_cards
                # (added after this loop) — skip the classify-only
                # placeholder here so cards aren't duplicated.
                continue

            bbox = normalized_bbox = center = None
            text = vlm_el.text
            confidence = UNGROUNDED_CONFIDENCE
            elem_source = "vlm"
            metadata = {
                "vlm_id": vlm_el.id,
                "description": vlm_el.description,
                "approximate_location": vlm_el.approximate_location,
            }

            ocr_match, method, score = self._match_for_class(vlm_el, ocr_elements, used_ocr_ids, W, H)
            if ocr_match:
                used_ocr_ids.add(ocr_match.id)
                bbox = ocr_match.bbox
                elem_source = "fused"
                metadata["ocr_id"] = ocr_match.id
                metadata["bbox_source"] = "ocr_exact"
                metadata["match_method"] = method
                if method == "som_id":
                    # The VLM told us exactly which OCR box it meant —
                    # no text/position guesswork happened, so this is
                    # at least as trustworthy as a text_similarity hit.
                    text = ocr_match.text
                    confidence = ocr_match.confidence
                elif method == "text_similarity":
                    text = ocr_match.text
                    confidence = ocr_match.confidence
                    metadata["match_score"] = round(score, 3)
                else:
                    # zone_only_fallback: position agreement only, no
                    # text comparison — don't claim ocr_match.text as
                    # this element's text, we never verified it's
                    # actually related. Discount confidence to reflect
                    # the weaker evidence.
                    confidence = round(ocr_match.confidence * ZONE_ONLY_CONFIDENCE_DISCOUNT, 4)
            else:
                # No SoM id, no text match, nothing in its position zone —
                # genuinely unexplained, not just "not text-matchable".
                # Preserve that explicitly (rules.md §10) instead of
                # leaving it implicit in bbox=None.
                metadata["match_status"] = "uncertain"

            if bbox:
                x, y, w, h = bbox
                normalized_bbox = [round(x / W, 5), round(y / H, 5), round(w / W, 5), round(h / H, 5)]
                center = [round(x + w / 2, 2), round(y + h / 2, 2)]

            counter += 1
            elements.append(
                UIElement(
                    id=f"el_{counter:04d}",
                    **{"class": vlm_el.class_},
                    text=text,
                    bbox=bbox,
                    normalized_bbox=normalized_bbox,
                    center=center,
                    confidence=confidence,
                    confidence_tier=confidence_tier(confidence),
                    source=elem_source,
                    metadata=metadata,
                )
            )

        card_id_bbox_pairs = []
        for g_el in grounded_cards.elements:
            counter += 1
            card_el_id = f"el_{counter:04d}"
            elements.append(
                UIElement(
                    id=card_el_id,
                    **{"class": "content_card"},
                    text=None,
                    bbox=g_el.bbox,
                    normalized_bbox=g_el.normalized_bbox,
                    center=g_el.center,
                    confidence=VLM_GROUNDED_CONFIDENCE,
                    confidence_tier=confidence_tier(VLM_GROUNDED_CONFIDENCE),
                    source="vlm",
                    metadata={"bbox_source": "vlm_grounded", "grounded_id": g_el.id},
                )
            )
            card_id_bbox_pairs.append((card_el_id, g_el.bbox))
        card_bbox_list = [bbox for _card_id, bbox in card_id_bbox_pairs]

        for ocr_el, _card_bbox in self._promote_badges(ocr_elements, card_bbox_list, used_ocr_ids):
            counter += 1
            elements.append(
                UIElement(
                    id=f"el_{counter:04d}",
                    **{"class": "overlay_badge"},
                    text=ocr_el.text,
                    bbox=ocr_el.bbox,
                    normalized_bbox=ocr_el.normalized_bbox,
                    center=ocr_el.center,
                    confidence=ocr_el.confidence,
                    confidence_tier=ocr_el.confidence_tier,
                    source="fused",
                    metadata={"ocr_id": ocr_el.id, "bbox_source": "ocr_exact", "detection": "keyword_match_in_card"},
                )
            )

        for ocr_el in ocr_elements:
            if ocr_el.id in used_ocr_ids:
                continue

            parent_id = None
            for card_el_id, card_bbox in card_id_bbox_pairs:
                if _point_in_bbox(ocr_el.center, card_bbox):
                    parent_id = card_el_id
                    break

            metadata = {"ocr_id": ocr_el.id}
            if parent_id is None:
                # Not text-matched to anything AND not inside any known
                # card — genuinely unexplained, not just unclassified.
                metadata["match_status"] = "uncertain"

            counter += 1
            elements.append(
                UIElement(
                    id=f"el_{counter:04d}",
                    text=ocr_el.text,
                    bbox=ocr_el.bbox,
                    normalized_bbox=ocr_el.normalized_bbox,
                    center=ocr_el.center,
                    confidence=ocr_el.confidence,
                    confidence_tier=ocr_el.confidence_tier,
                    source="ocr",
                    parent_id=parent_id,
                    metadata=metadata,
                )
            )

        grounded = sum(1 for e in elements if e.bbox is not None)
        print(f"[FUSION] Done - {len(elements)} elements ({grounded} with geometry, "
              f"{len(elements) - grounded} classification-only).")

        return UIDocument(screen_id=screen_id, source=source, image_width=W, image_height=H, elements=elements)

    def fuse_detections(self, detections, ocr_result, vlm_result=None, screen_id: str = None,
                        source: str = "fused") -> UIDocument:
        """Detector-first fusion (src/detector/, the default in main.py).

        - Every detection is kept as-is: class, bbox and confidence come
          from the detector, which is deterministic (unlike VLM grounding).
        - Each OCR box goes to the smallest detection containing its
          center, preferring any non-container over a container (the
          floating tab bar on ss012 overlays poster cards smaller than
          itself). Inside a poster/photo (POSTER_CLASSES) the text is
          artwork: it is dropped and only its id is kept in the card's
          metadata.ocr_ids (the raw OCR JSON still has it). Inside a
          navigation_bar it stays a child element (parent_id set).
          Otherwise it becomes the detection's text, in reading order.
          A low-tier container never hosts text: on ss012 a false 0.32
          content_card over the floating tab bar was swallowing the tab
          labels as "dynamic" card text, hiding them from comparison.
        - A tab_item holding >= 2 side-by-side OCR words is an unsplit tab
          bar: it becomes a navigation_bar (metadata.split_from) and each
          word a child tab_item.
        - Detections wholly inside the status-bar band are ignored="status_bar".
        - OCR text inside no detection is kept as evidence, marked
          match_status="uncertain" (rules.md §10).
        - Detections of a low_confidence_class, or in the "low" tier, are
          also marked uncertain, so differ reports them as REVIEW - unless a
          low-tier one lies mostly inside a more confident detection of
          another, non-container class (DUPLICATE_INSIDE_FRACTION): then it is tagged
          ignored="overlapped_by_higher_confidence" (kept, never compared).
        - vlm_result is optional; main.py runs the VLM only when something
          came out uncertain. A VLM classification tied to OCR by som_id
          or text similarity (never zone-only) then either classifies an
          orphan OCR box, or confirms an uncertain detection of the same
          class that contains that OCR box.
        """
        screen_id = screen_id or ocr_result.screen
        W, H = ocr_result.image_width, ocr_result.image_height
        print(f"[FUSION] Fusing {len(detections)} detections + {len(ocr_result.elements)} OCR"
              f"{f' + {len(vlm_result.elements)} VLM' if vlm_result else ''} observations...")

        dets = []
        for i, d in enumerate(detections, 1):
            meta = dict(d.metadata, detector_id=d.id)
            if d.metadata.get("low_confidence_class") or d.confidence_tier == "low":
                meta["match_status"] = "uncertain"
            dets.append(d.model_copy(update={"id": f"el_{i:04d}", "metadata": meta}))
        for d in dets:
            if d.confidence_tier == "low" and any(
                    o.class_ != d.class_ and o.confidence > d.confidence
                    # A badge on a card lies inside it by design; only a
                    # non-container box can make a weaker one a duplicate
                    # (sunnxt_test_ss lost a 0.34 "Free" badge to its card).
                    and o.class_ not in CONTAINER_CLASSES
                    and _inside_fraction(d.bbox, o.bbox) >= DUPLICATE_INSIDE_FRACTION for o in dets):
                d.metadata.pop("match_status", None)
                d.metadata["ignored"] = "overlapped_by_higher_confidence"
            # §H, same band as the orphan-OCR rule below: the detector does box
            # status-bar text on some apps (clock, battery, a notification).
            # Whole box inside the band, not just its centre: ss012's top-row
            # cards peek out under the status bar with centres at y~73 < 96.
            if d.bbox[1] + d.bbox[3] <= self.status_bar_height_norm * H:
                d.metadata.pop("match_status", None)
                d.metadata["ignored"] = "status_bar"

        host_of = {}  # ocr id -> smallest detection containing its center
        for ocr_el in ocr_result.elements:
            hosts = [d for d in dets if _point_in_bbox(ocr_el.center, d.bbox)
                     and not (d.class_ in CONTAINER_CLASSES and d.confidence_tier == "low")]
            if hosts:
                host_of[ocr_el.id] = min(hosts, key=lambda d: (d.class_ in CONTAINER_CLASSES,
                                                               d.bbox[2] * d.bbox[3]))

        # One tab_item box over several side-by-side words is a tab bar the
        # detector did not split (the "TV | Movies | Sports" pill). Hosts are
        # decided above, while it is still a non-container tab_item, so the
        # cards under it cannot claim its words; from here it is a
        # navigation_bar and each word becomes a child tab_item below.
        for d in dets:
            if d.class_ != "tab_item":
                continue
            words = sorted((o for o in ocr_result.elements if host_of.get(o.id) is d),
                           key=lambda o: o.bbox[0])
            if len(words) >= 2 and all(a.bbox[0] + a.bbox[2] <= b.bbox[0]
                                       for a, b in zip(words, words[1:])):
                d.class_ = "navigation_bar"
                d.metadata["split_from"] = "tab_item"

        covered = {}  # detection id -> OCR boxes it takes (label text, or dropped poster text)
        for ocr_el in ocr_result.elements:
            host = host_of.get(ocr_el.id)
            if host is not None and host.class_ not in CHILD_TEXT_CLASSES:
                covered.setdefault(host.id, []).append(ocr_el)
        for d in dets:
            if d.id in covered:
                ocr_els = _reading_order(covered[d.id])
                d.metadata["ocr_ids"] = [o.id for o in ocr_els]
                if d.class_ not in POSTER_CLASSES:
                    d.text = " ".join(o.text for o in ocr_els)

        vlm_class = {}  # orphan ocr id -> (vlm element, method)
        if vlm_result is not None:
            used = set()
            for vlm_el in vlm_result.elements:
                if vlm_el.class_ in ("overlay_badge", "content_card"):
                    continue
                ocr_match, method, _ = self._match_for_class(vlm_el, ocr_result.elements, used, W, H)
                if ocr_match is None or method == "zone_only_fallback":
                    continue
                used.add(ocr_match.id)
                host = host_of.get(ocr_match.id)
                if host is None:
                    vlm_class[ocr_match.id] = (vlm_el, method)
                elif host.metadata.get("match_status") == "uncertain" and host.class_ == vlm_el.class_:
                    del host.metadata["match_status"]
                    host.metadata["vlm_confirmed"] = vlm_el.id

        elements = list(dets)
        for ocr_el in ocr_result.elements:
            host = host_of.get(ocr_el.id)
            if host is not None and host.class_ not in CHILD_TEXT_CLASSES:
                continue  # already a label, or dropped poster text
            metadata = {"ocr_id": ocr_el.id}
            cls, el_source = None, "ocr"
            if ocr_el.id in vlm_class:
                vlm_el, method = vlm_class[ocr_el.id]
                cls, el_source = vlm_el.class_, "fused"
                metadata.update(vlm_id=vlm_el.id, match_method=method, bbox_source="ocr_exact")
            elif host is not None and host.metadata.get("split_from") == "tab_item":
                cls, el_source = "tab_item", "fused"
                metadata["bbox_source"] = "ocr_exact"
            elif host is None and ocr_el.center[1] < self.status_bar_height_norm * H:
                metadata["ignored"] = "status_bar"  # §H: clock/battery, never compared
            elif host is None:
                metadata["match_status"] = "uncertain"
            elements.append(UIElement(
                id=f"el_{len(elements) + 1:04d}", **{"class": cls}, text=ocr_el.text,
                bbox=ocr_el.bbox, normalized_bbox=ocr_el.normalized_bbox, center=ocr_el.center,
                confidence=ocr_el.confidence, confidence_tier=ocr_el.confidence_tier,
                source=el_source, parent_id=host.id if host else None, metadata=metadata,
            ))

        uncertain = sum(1 for e in elements if e.metadata.get("match_status") == "uncertain")
        print(f"[FUSION] Done - {len(elements)} elements ({len(dets)} detections, {uncertain} uncertain).")
        return UIDocument(screen_id=screen_id, source=source, image_width=W, image_height=H, elements=elements)
