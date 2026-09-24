"""
Difference engine (architecture.md §12, design.md §8-11, rules.md §8).

The client design is the reference and production is what's under test
(docs/test_cases_pass_fail.md). Runs ElementMatcher (matcher.py) to find
correspondences, then classifies each element/pair into the difference
taxonomy. An unmatched client element is MISSING_IN_PRODUCTION, an
unmatched production element is EXTRA_IN_PRODUCTION (the "unmatched node
= a change" idea from Moradi et al., Section 3.4). A matched pair is
inspected for sub-differences using the score breakdown ElementMatcher
already computed plus the raw element fields; a pair with no
sub-difference is reported as MATCH.

Every Difference carries a verdict (PASS / REVIEW / FAIL) and, for FAIL,
a severity (Critical / Major / Minor), per test_cases_pass_fail.md §0.
Implemented checks: B1/B2 (missing/extra), B9 (card count, REVIEW only),
C1 (position bands, looser for bbox_source="vlm_grounded"), C2 (size
bands), C4 (class), E1 (static-text label). Dynamic content (§H) —
anything inside a content_card — is never compared; text is compared only
for static-text classes.

A panel that moved as one piece is reported once as GROUP_SHIFT (C1) and
its members are judged only on their residual — see matcher.py's second
pass, which also re-matches the members the move had pushed apart.

Implemented types: MATCH, MISSING_IN_PRODUCTION, EXTRA_IN_PRODUCTION, GROUP_SHIFT,
CLASS_DIFFERENCE, TEXT_DIFFERENCE, POSITION_DIFFERENCE, SIZE_DIFFERENCE,
STRUCTURAL_DIFFERENCE (driven by the matcher's one-hop context score).
GEOMETRY_DIFFERENCE, ORDER_DIFFERENCE, and UNCERTAIN from rules.md §8 are
not yet implemented.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from PIL import Image

from src.comparison import color_checks, layout_checks, screen_checks
from src.comparison.matcher import (ElementMatcher, _is_dynamic, _normalize_text,
                                    _normalized_center)
from src.schema.ui_element import UIDocument

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"

PASS, REVIEW, FAIL = "PASS", "REVIEW", "FAIL"
CRITICAL, MAJOR, MINOR = "Critical", "Major", "Minor"


@dataclass
class Difference:
    type: str
    production_id: str | None
    client_id: str | None
    details: dict
    verdict: str = PASS
    severity: str | None = None


def _same_but_for_style(a: str, b: str) -> bool:
    """Same letters, different case or internal spacing (E3, not E1).

    `_normalize_text` already lowercases and collapses runs of whitespace, so
    what is left to ignore is whitespace entirely: "sun nxt" vs "sunnxt".
    Deliberately not applied to dynamic text - only static labels reach here.
    """
    return bool(a) and "".join(a.split()) == "".join(b.split())


def _within_one_edit(a: str, b: str) -> bool:
    """True if a and b differ by at most one insert/delete/substitute."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)):] == b[i + 1:]


class DifferenceEngine:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        full = yaml.safe_load(Path(config_path).read_text())
        cfg = full.get("comparison", {})
        # A3 masks the status bar, which fusion already measures - one value.
        self.status_bar_height_norm = full.get("fusion", {}).get("status_bar_height_norm", 0.04)
        self.structural_similarity_threshold = cfg.get("structural_similarity_threshold", 0.5)
        # Off by default: it has no spec row, and on the SunNXT language pair it
        # fired on 9 of 18 matched pairs. Two screens with different element
        # counts can never share a neighbourhood, so it flags the screens the
        # rest of the report already flags. Kept as a hint for debugging.
        self.report_structural = cfg.get("report_structural_difference", False)
        self.position_bands = cfg.get("position_bands", {"pass": 0.01, "fail": 0.03, "major": 0.06})
        self.vlm_grounded_position_bands = cfg.get(
            "vlm_grounded_position_bands", {"pass": 0.04, "fail": 0.08, "major": 0.12}
        )
        self.size_bands = cfg.get("size_bands", {"pass": 0.05, "fail": 0.15})
        self.static_text_classes = set(
            cfg.get("static_text_classes", ["tab_item", "button", "section_title", "search_bar"])
        )
        self.critical_classes = set(
            cfg.get("critical_classes", ["button", "tab_item", "navigation_bar", "logo"])
        )
        self.screen_cfg = cfg.get("screen", {})
        self.color_cfg = cfg.get("color", {})
        self.layout_cfg = cfg.get("layout", {})
        self._matcher = ElementMatcher(config_path)

    def compare(
        self,
        production_doc: UIDocument,
        client_doc: UIDocument,
        production_graph=None,
        client_graph=None,
        match_result=None,
        production_image=None,
        client_image=None,
    ) -> list:
        if match_result is None:
            match_result = self._matcher.match(production_doc, client_doc, production_graph, client_graph)

        prod_by_id = {el.id: el for el in production_doc.elements}
        client_by_id = {el.id: el for el in client_doc.elements}
        # C1 is "% of screen diagonal"; measured in the reference (client) screen.
        self._screen = (client_doc.image_width, client_doc.image_height)

        differences = []

        for cid in match_result.unmatched_client:
            el = client_by_id[cid]
            differences.append(self._unmatched("MISSING_IN_PRODUCTION", el, client_by_id, None, cid))

        for pid in match_result.unmatched_production:
            el = prod_by_id[pid]
            differences.append(self._unmatched("EXTRA_IN_PRODUCTION", el, prod_by_id, pid, None))

        images = None
        if production_image is not None and client_image is not None:
            differences.extend(self._screen_level(production_image, client_image))
            images = (Image.open(production_image).convert("RGB"),
                      Image.open(client_image).convert("RGB"))
            differences.extend(
                self._background_color(images, production_doc, client_doc))

        differences.extend(self._group_shifts(match_result, client_by_id))
        if production_graph is not None and client_graph is not None:
            differences.extend(
                self._layout_structure(production_graph, client_graph, match_result))

        for m in match_result.matches:
            p = prod_by_id[m.production_id]
            c = client_by_id[m.client_id]
            if self._is_dynamic(c, client_by_id):
                differences.append(Difference("MATCH", p.id, c.id, {"score": m.score, "ignored": "dynamic content"}))
                continue
            sub_differences = self._sub_differences(p, c, m.breakdown, m.shift)
            if images is not None:
                sub_differences += self._element_color(p, c, images, client_graph)
            if not sub_differences:
                differences.append(Difference("MATCH", p.id, c.id, {"score": m.score}))
            else:
                differences.extend(sub_differences)

        return differences

    _is_dynamic = staticmethod(_is_dynamic)  # §H rule lives in matcher.py

    def _screen_level(self, production_image, client_image) -> list:
        """A1/A2/A3/A5 — the two frames compared before any detection. These
        answer "are we even looking at the same kind of screen?", so a failure
        here makes every element-level finding below it suspect."""
        cfg = self.screen_cfg
        found = []

        orientation = screen_checks.check_orientation(production_image, client_image)
        if orientation["differ"]:
            found.append(Difference("ORIENTATION_DIFFERENCE", None, None, orientation,
                                    FAIL, CRITICAL))

        blank = screen_checks.check_blank(
            production_image, client_image,
            dominant_colour_fraction_max=cfg.get("dominant_colour_fraction_max", 0.90),
            edge_density_min=cfg.get("edge_density_min", 0.005),
        )
        if blank["any_blank"]:
            found.append(Difference("BLANK_SCREEN", None, None, blank, FAIL, CRITICAL))

        theme = screen_checks.check_theme(
            production_image, client_image,
            dark_luminance_max=cfg.get("dark_luminance_max", 0.45),
            status_bar_height_norm=self.status_bar_height_norm,
        )
        if theme["differ"]:
            found.append(Difference("THEME_DIFFERENCE", None, None, theme, FAIL, MAJOR))

        bands = cfg.get("aspect_bands", {"pass": 0.05, "fail": 0.15})
        scaling = screen_checks.check_scaling(production_image, client_image,
                                              aspect_tolerance=bands["pass"])
        # A pure resolution difference at the same aspect ratio is a device
        # difference, not a defect - everything downstream is normalized.
        if scaling["aspect_ratio_difference"] > bands["pass"]:
            fail = scaling["aspect_ratio_difference"] > bands["fail"]
            found.append(Difference("SCALING_DIFFERENCE", None, None, scaling,
                                    FAIL if fail else REVIEW, MAJOR if fail else None))
        return found

    def _layout_structure(self, production_graph, client_graph, match_result) -> list:
        """B3/B4/B5/B8 — order, alignment and clipping, read off the layout graph.

        Nothing here re-derives geometry: the graph already carries the order
        chain, the alignment clusters and `clipped`, and until now nothing
        consumed any of it.
        """
        cfg = self.layout_cfg
        found = []
        args = (production_graph, client_graph, match_result)

        # Each of these names the element it is about, even though the finding
        # describes a relationship: a reader (and the benchmark scorer, which
        # localises a finding through these ids) needs to know *which* tab moved,
        # not just that the order changed. The full list stays in `details`.
        for row in layout_checks.section_order(*args):
            first = (row["moved"] or [{}])[0]
            found.append(Difference("SECTION_ORDER_DIFFERENCE", first.get("production_id"),
                                    first.get("client_id"), row, FAIL, MAJOR))
        for row in layout_checks.tab_order(*args, min_items=cfg.get("min_tab_items", 2)):
            first = (row["moved"] or [{}])[0]
            found.append(Difference("TAB_ORDER_DIFFERENCE", first.get("production_id"),
                                    first.get("client_id"), row, FAIL, MAJOR))
        for row in layout_checks.alignment(
                *args, tolerance_norm=cfg.get("alignment_tolerance_norm", 0.015)):
            # Minor per §B5 - a Minor FAIL is a warning, not a screen FAIL.
            found.append(Difference("ALIGNMENT_DIFFERENCE",
                                    (row["production_ids"] or [None])[0],
                                    (row["client_ids"] or [None])[0], row, FAIL, MINOR))
        for row in layout_checks.clipping(*args):
            # Clipped in the client only is usually just a different scroll
            # position, so it is a REVIEW rather than a defect.
            production_side = row["clipped_in"] == "production"
            found.append(Difference(
                "CLIPPING_DIFFERENCE", row.get("production_id"), row.get("client_id"), row,
                FAIL if production_side else REVIEW, MAJOR if production_side else None))
        return found

    def _color_verdict(self, delta_e, bands):
        if delta_e <= bands["pass"]:
            return PASS, None
        if delta_e <= bands["fail"]:
            return REVIEW, None
        return FAIL, MAJOR

    def _background_color(self, images, production_doc, client_doc) -> list:
        """D2 — the page background, with every detected element masked out so a
        poster cannot be mistaken for the background (rules.md §2)."""
        cfg = self.color_cfg
        bands = cfg.get("background_bands", {"pass": 3.0, "fail": 6.0})
        delta = color_checks.background_color_delta(
            images[0], images[1],
            production_boxes=[el.bbox for el in production_doc.elements if el.bbox],
            client_boxes=[el.bbox for el in client_doc.elements if el.bbox],
        )
        verdict, severity = self._color_verdict(delta.delta_e, bands)
        if verdict == PASS:
            return []
        return [Difference("BACKGROUND_COLOR_DIFFERENCE", None, None,
                           {"delta_e": round(delta.delta_e, 2),
                            "production_rgb": delta.production.rgb,
                            "client_rgb": delta.client.rgb,
                            "notes": delta.notes},
                           verdict, severity)]

    @staticmethod
    def _shows_artwork_through(client_graph, node_id) -> bool:
        """True when this chrome floats over card artwork, so what a colour
        sample picks up is the poster behind it, not the element's own fill.

        Found on the SunNXT home pair: the floating "Movies / Live TV / Free /
        More" pill sampled as rgb(105, 81, 83) in production and rgb(37, 37, 39)
        in the client purely because different posters sat behind it - nine
        Major colour FAILs that were all artwork (rules.md §2 forbids comparing
        it). Geometry and text on these elements are still compared.
        """
        if client_graph is None or node_id not in client_graph:
            return False
        if client_graph.nodes[node_id].get("layer") == "overlay":
            return True
        cards = ("content_card", "cast_card", "celebrity_card")
        return any(client_graph.nodes[v].get("class_") in cards
                   for _, v, data in client_graph.out_edges(node_id, data=True)
                   if data.get("relationship") == "OVERLAPS")

    def _element_color(self, p, c, images, client_graph=None) -> list:
        """D1/D5 — fill colour of matched chrome. Cards are never compared: their
        artwork is dynamic content."""
        cfg = self.color_cfg
        if self._shows_artwork_through(client_graph, c.id):
            return []
        badge = c.class_ == "overlay_badge"
        if not badge and c.class_ not in cfg.get(
                "brand_classes", ["button", "logo", "navigation_bar", "tab_item", "search_bar"]):
            return []
        if not p.bbox or not c.bbox:
            return []
        crops = [img.crop((int(b[0]), int(b[1]), int(b[0] + b[2]), int(b[1] + b[3])))
                 for img, b in zip(images, (p.bbox, c.bbox))]
        if min(crop.width for crop in crops) < 2 or min(crop.height for crop in crops) < 2:
            return []
        inset = cfg.get("badge_inset_fraction", 0.15) if badge else cfg.get("inset_fraction", 0.25)
        delta = color_checks.compare_crops(crops[0], crops[1],
                                           check_id="D5" if badge else "D1",
                                           inset_fraction=inset)
        bands = cfg.get("badge_bands" if badge else "brand_bands",
                        {"pass": 5.0, "fail": 10.0} if badge else {"pass": 3.0, "fail": 6.0})
        verdict, severity = self._color_verdict(delta.delta_e, bands)
        if verdict == PASS:
            return []
        if badge and severity == MAJOR:
            severity = MINOR  # §D: a badge shade is not worth failing a build over
        return [Difference("BADGE_COLOR_DIFFERENCE" if badge else "COLOR_DIFFERENCE",
                           p.id, c.id,
                           {"delta_e": round(delta.delta_e, 2),
                            "production_rgb": delta.production.rgb,
                            "client_rgb": delta.client.rgb},
                           verdict, severity)]

    def _position_verdict(self, distance, bands):
        """C1 bands -> (verdict, severity)."""
        if distance <= bands["pass"]:
            return PASS, None
        if distance <= bands["fail"]:
            return REVIEW, None
        return FAIL, (MAJOR if distance > bands["major"] else MINOR)

    def _diagonal_fraction(self, dx, dy) -> float:
        """A normalized (dx, dy) as a fraction of the screen diagonal (C1's unit)."""
        w, h = self._screen
        return ((dx * w) ** 2 + (dy * h) ** 2) ** 0.5 / (w ** 2 + h ** 2) ** 0.5

    def _group_shifts(self, match_result, client_by_id) -> list:
        """One C1 finding per container that moved as one piece, instead of one
        per member. The members are then judged on their residual only."""
        found = []
        for group, info in match_result.group_shifts.items():
            dx, dy = info["shift"]
            distance = self._diagonal_fraction(dx, dy)
            if distance <= self.position_bands["pass"]:
                continue
            verdict, severity = self._position_verdict(distance, self.position_bands)
            w, h = self._screen
            label = next((client_by_id[i].text for i in info["members"]
                          if i in client_by_id and client_by_id[i].class_ == "section_title"
                          and client_by_id[i].text), None)
            found.append(
                Difference(
                    type="GROUP_SHIFT",
                    production_id=None,
                    client_id=group,
                    details={
                        "group": group,
                        "label": label,
                        "dx_px": round(dx * w, 1),
                        "dy_px": round(dy * h, 1),
                        "distance_of_diagonal": distance,
                        "anchors": info["anchors"],
                        "members": info["members"],
                    },
                    verdict=verdict,
                    severity=severity,
                )
            )
        return found

    def _unmatched(self, diff_type, el, by_id, pid, cid) -> Difference:
        details = {"class": el.class_, "text": el.text, "confidence": el.confidence}
        if self._is_dynamic(el, by_id):
            details["ignored"] = "dynamic content"
            return Difference(diff_type, pid, cid, details, PASS)
        if el.class_ is None or el.metadata.get("match_status") == "uncertain":
            return Difference(diff_type, pid, cid, details, REVIEW)  # §I
        if el.class_ == "content_card":
            return Difference(diff_type, pid, cid, details, REVIEW, MINOR)  # B9
        if diff_type == "MISSING_IN_PRODUCTION" and el.class_ in self.critical_classes:
            return Difference(diff_type, pid, cid, details, FAIL, CRITICAL)  # B1
        return Difference(diff_type, pid, cid, details, FAIL, MAJOR)  # B1 / B2

    def _sub_differences(self, p, c, breakdown, shift=(0.0, 0.0)) -> list:
        found = []

        # C4
        if p.class_ is not None and c.class_ is not None and p.class_ != c.class_:
            found.append(
                Difference(
                    type="CLASS_DIFFERENCE",
                    production_id=p.id,
                    client_id=c.id,
                    details={"production_class": p.class_, "client_class": c.class_},
                    verdict=FAIL,
                    severity=MAJOR,
                )
            )

        # E1 — static UI text only (§H). Two labels that differ only in case or
        # internal spacing are E3 (case/style), not a wrong label: the SunNXT
        # header reads "SUN NXT" in one build and "SUNNXT" in the other, which
        # was a Major FAIL here and is really a styling question for a human.
        if c.class_ in self.static_text_classes and (p.text or c.text):
            p_text, c_text = _normalize_text(p.text), _normalize_text(c.text)
            if p_text != c_text:
                if _same_but_for_style(p_text, c_text):
                    found.append(
                        Difference(
                            type="TEXT_STYLE_DIFFERENCE",
                            production_id=p.id,
                            client_id=c.id,
                            details={"production_text": p.text, "client_text": c.text},
                            verdict=REVIEW,
                        )
                    )
                else:
                    one_slip = _within_one_edit(p_text, c_text)
                    found.append(
                        Difference(
                            type="TEXT_DIFFERENCE",
                            production_id=p.id,
                            client_id=c.id,
                            details={"production_text": p.text, "client_text": c.text, "similarity": breakdown["text"]},
                            verdict=REVIEW if one_slip else FAIL,
                            severity=None if one_slip else MAJOR,
                        )
                    )

        # C1
        p_center = _normalized_center(p.normalized_bbox)
        c_center = _normalized_center(c.normalized_bbox)
        # The residual: how far this element moved *within* its group. A member
        # that rode along with the panel has none, and the panel's own move is
        # reported once as GROUP_SHIFT.
        position_distance = self._diagonal_fraction(
            p_center[0] - c_center[0] - shift[0], p_center[1] - c_center[1] - shift[1]
        )
        grounded = "vlm_grounded" in (p.metadata.get("bbox_source"), c.metadata.get("bbox_source"))
        bands = self.vlm_grounded_position_bands if grounded else self.position_bands
        if position_distance > bands["pass"]:
            verdict, severity = self._position_verdict(position_distance, bands)
            found.append(
                Difference(
                    type="POSITION_DIFFERENCE",
                    production_id=p.id,
                    client_id=c.id,
                    details={
                        "production_center": p_center,
                        "client_center": c_center,
                        "distance_of_diagonal": position_distance,
                        "group_shift": list(shift),
                        "bands": "vlm_grounded" if grounded else "default",
                    },
                    verdict=verdict,
                    severity=severity,
                )
            )

        # C2
        p_w, p_h = p.normalized_bbox[2], p.normalized_bbox[3]
        c_w, c_h = c.normalized_bbox[2], c.normalized_bbox[3]
        width_ratio_diff = abs(p_w - c_w) / max(p_w, c_w, 1e-9)
        height_ratio_diff = abs(p_h - c_h) / max(p_h, c_h, 1e-9)
        size_diff = max(width_ratio_diff, height_ratio_diff)
        if size_diff > self.size_bands["pass"]:
            fail = size_diff > self.size_bands["fail"]
            found.append(
                Difference(
                    type="SIZE_DIFFERENCE",
                    production_id=p.id,
                    client_id=c.id,
                    details={
                        "production_size": [p_w, p_h],
                        "client_size": [c_w, c_h],
                        "width_ratio_diff": width_ratio_diff,
                        "height_ratio_diff": height_ratio_diff,
                    },
                    verdict=FAIL if fail else REVIEW,
                    severity=MAJOR if fail else None,
                )
            )

        # No spec equivalent; graph context is a hint, so a human looks at it.
        if self.report_structural and breakdown["context"] < self.structural_similarity_threshold:
            found.append(
                Difference(
                    type="STRUCTURAL_DIFFERENCE",
                    production_id=p.id,
                    client_id=c.id,
                    details={"context_similarity": breakdown["context"]},
                    verdict=REVIEW,
                )
            )

        return found
