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

import re

import yaml

from PIL import Image

from src.comparison import (accepted, color_checks, contrast_checks, image_checks,
                            layout_checks, pixel_geometry, regions, screen_checks,
                            script_checks, text_cleanup)
from src.comparison.matcher import (ElementMatcher, _container_of, _is_dynamic, _on_card_overlap,
                                    _normalize_text, _normalized_center)
from src.graph.layout import SCREEN_ID
from src.reporting.report import spec_id
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


def _merge_alignment_rows(rows) -> list:
    """One finding per broken alignment group, not one per linked pair.

    The layout graph links aligned elements in a chain, so three items sharing a
    left edge produce two ALIGNED_WITH links. When that column breaks, B5 fires
    once per link and the same column is reported twice. Rows on the same axis
    that share an element describe one group: merge them, keep every element,
    and report the worst offset.
    """
    merged = []
    for row in rows:
        ids = set(row.get("client_ids") or []) | set(row.get("production_ids") or [])
        for other in merged:
            if other["axis"] != row["axis"]:
                continue
            other_ids = set(other.get("client_ids") or []) | set(other.get("production_ids") or [])
            if not (ids & other_ids):
                continue
            for key in ("client_ids", "production_ids", "labels"):
                seen = other.get(key) or []
                other[key] = seen + [v for v in (row.get(key) or []) if v not in seen]
            if row["offset_growth_norm"] > other["offset_growth_norm"]:
                for key in ("offset_growth_norm", "production_offset_norm", "client_offset_norm"):
                    other[key] = row[key]
            break
        else:
            merged.append(dict(row))
    return merged


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
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH, rules_path=None,
                 match_level=None):
        full = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        cfg = full.get("comparison", {})
        self.on_card_overlap = _on_card_overlap(full)
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
        # A rotated or blank screen is not comparable element by element.
        self.stop_on_critical_screen_failure = cfg.get("stop_on_critical_screen_failure", True)
        self.color_cfg = cfg.get("color", {})
        self.layout_cfg = cfg.get("layout", {})
        self.pixel_verify_cfg = cfg.get("pixel_verify", {})
        self.language_cfg = cfg.get("language", {})
        self.contrast_cfg = cfg.get("contrast", {})
        self.image_cfg = cfg.get("image", {})
        # Match levels + regions (src/comparison/regions.py). The status-bar band
        # is a default NONE region, sized by fusion's own status_bar_height_norm.
        self.levels_cfg = cfg.get("match_levels", {})
        self.default_regions = [dict(r) for r in self.levels_cfg.get("regions") or []]
        if self.levels_cfg.get("status_bar_region", True):
            self.default_regions.insert(0, {"name": "status_bar", "type": "NONE",
                                            "bbox_norm": [0, 0, 1, self.status_bar_height_norm],
                                            "min_overlap": 0.5})
        self.rules_path, self.match_level_override = rules_path, match_level
        self.dynamic_text_cfg = cfg.get("dynamic_text", {})
        self.accepted_cfg = cfg.get("accepted_differences", {})
        self.cap_clipped = cfg.get("cap_clipped_to_review", True)
        self.glyph_cfg = cfg.get("glyph_cleanup", {})
        self._rules = None
        layout = self.layout_cfg
        self.drop_alignment_collateral = layout.get("drop_alignment_collateral", True)
        self.merge_alignment_chains = layout.get("merge_alignment_chains", True)
        group_shift = full.get("matching", {}).get("group_shift", {})
        self.merge_nested_shifts = group_shift.get("merge_nested", True)
        self.shift_spread_norm = group_shift.get("max_spread_norm", 0.01)
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
        self._rules = self._load_rules(client_doc.screen_id)
        # C1 is "% of screen diagonal"; measured in the reference (client) screen.
        self._screen = (client_doc.image_width, client_doc.image_height)

        differences = []

        # Screen level first, because a Critical failure here makes every
        # element-level finding below meaningless: on a screen rotated 90
        # degrees every element really has moved and resized, so the report
        # became A1 plus a wall of A5/B1/B2/B9/C1/C2 noise. Say it once.
        images = None
        if production_image is not None and client_image is not None:
            screen_level = self._screen_level(production_image, client_image)
            differences.extend(screen_level)
            blocking = [d for d in screen_level
                        if d.verdict == FAIL and d.severity == CRITICAL]
            if blocking and self.stop_on_critical_screen_failure:
                differences.append(Difference(
                    "ELEMENT_COMPARISON_SKIPPED", None, None,
                    {"because": [d.type for d in blocking],
                     "production_elements": len(production_doc.elements),
                     "client_elements": len(client_doc.elements)},
                    REVIEW))
                return differences
            images = (Image.open(production_image).convert("RGB"),
                      Image.open(client_image).convert("RGB"))
            differences.extend(
                self._background_color(images, production_doc, client_doc))

        ambiguous = getattr(match_result, "ambiguous", set())
        for cid in match_result.unmatched_client:
            el = client_by_id[cid]
            differences.append(self._unmatched("MISSING_IN_PRODUCTION", el, client_by_id, None, cid,
                                               cid in ambiguous))

        for pid in match_result.unmatched_production:
            el = prod_by_id[pid]
            differences.append(self._unmatched("EXTRA_IN_PRODUCTION", el, prod_by_id, pid, None,
                                               pid in ambiguous))

        differences.extend(self._group_shifts(match_result, client_by_id, client_graph))
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
                sub_differences = self._pixel_verify_size(p, c, sub_differences, images,
                                                          client_graph)
                sub_differences += self._text_contrast(p, c, images, client_graph)
                sub_differences += self._image_identity(p, c, images)
            if not sub_differences:
                differences.append(Difference("MATCH", p.id, c.id, {"score": m.score}))
            else:
                differences.extend(sub_differences)

        if images is not None:
            differences.extend(self._broken_images(images, production_doc, match_result,
                                                   client_by_id))
        differences = self._cap_clipped(differences, production_graph, client_graph)
        differences = self._drop_alignment_collateral(differences)
        differences = self._apply_match_levels(differences, client_doc.screen_id,
                                               prod_by_id, client_by_id)
        return self._apply_acceptances(differences, client_doc.screen_id, client_by_id)

    def _cap_clipped(self, differences, production_graph, client_graph) -> list:
        """A finding on a cut-off element is REVIEW at most (Phase 14b F3).

        The report already says "cut off ... may be a false alarm" for these;
        a Major FAIL next to that note contradicts it. The original verdict and
        severity stay in details, so nothing is hidden. B8 itself is exempt:
        it is the clipping finding, with its own rule in _layout_structure.
        """
        if not self.cap_clipped:
            return differences

        def clipped(graph, node_id):
            return graph is not None and node_id in graph and graph.nodes[node_id].get("clipped")

        for d in differences:
            if d.verdict != FAIL or d.type == "CLIPPING_DIFFERENCE":
                continue
            if clipped(production_graph, d.production_id) or clipped(client_graph, d.client_id):
                d.details = {**d.details, "capped": "element is cut off",
                             "original_verdict": d.verdict, "original_severity": d.severity}
                d.verdict, d.severity = REVIEW, None
        return differences

    def _clean(self, el):
        """Label text without OCR'd icon glyphs ("9 Languages" -> "Languages")."""
        cfg = self.glyph_cfg
        if not el.text or not cfg.get("enabled", True) or el.class_ not in cfg.get(
                "classes", ["tab_item", "button", "search_bar", "section_title"]):
            return el.text
        return text_cleanup.clean_label(el.text, cfg.get("max_len", 2))[0]

    def _apply_acceptances(self, differences, screen_id, client_by_id) -> list:
        """14.4: findings a human accepted come back as PASS with details.accepted.

        With no acceptance file (the default) nothing changes. Otherwise one
        ACCEPTANCES record lists the entries for this screen that matched
        nothing, so a stale decision is visible instead of silently unused.
        """
        cfg = self.accepted_cfg
        path = Path(DEFAULT_CONFIG_PATH).parents[1] / cfg.get(
            "path", "baselines/accepted_differences.yaml")
        entries = accepted.load(path) if cfg.get("enabled", True) else []
        if not entries:
            return differences
        stale = accepted.apply(differences, entries, screen_id, client_by_id,
                               cfg.get("center_tolerance_norm", 0.02),
                               self.color_cfg.get("brand_bands", {}).get("pass", 3.0))
        differences.append(Difference("ACCEPTANCES", None, None,
                                      {"file": str(path), "stale": stale}, PASS))
        return differences

    def _load_rules(self, screen_id) -> dict:
        cfg = self.levels_cfg
        return regions.load_rules(
            screen_id, Path(DEFAULT_CONFIG_PATH).parent / cfg.get("rules_dir", "screen_rules"),
            cfg.get("default", "STRICT"), self.default_regions,
            self.rules_path, self.match_level_override)

    def _text_format(self, text):
        """Name of the dynamic-text pattern `text` fully matches, or None (15.1)."""
        cfg = self.dynamic_text_cfg
        if not cfg.get("enabled", True) or not text:
            return None
        patterns = {**(cfg.get("patterns") or {}), **((self._rules or {}).get("patterns") or {})}
        return next((name for name, rx in patterns.items()
                     if re.fullmatch(rx, text.strip(), re.IGNORECASE)), None)

    def _apply_match_levels(self, differences, screen_id, prod_by_id, client_by_id) -> list:
        """Relax findings by match level (screen rules file, regions, config default).

        STRICT with no rules file and only the status-bar region is today's
        output: fusion already ignores what lies in the status bar. Otherwise
        one MATCH_LEVEL record says which level and which families were
        skipped, so the report can mark them "skipped" rather than "PASS".
        """
        cfg = self.levels_cfg
        rules = self._rules or self._load_rules(screen_id)
        skip_map = cfg.get("skip", {"LAYOUT": ["D", "E", "F"], "IGNORE_COLORS": ["D"]})
        regions.apply_match_levels(
            differences, rules, skip_map,
            element_of=lambda d: client_by_id.get(d.client_id) or prod_by_id.get(d.production_id),
            spec_of=spec_id)
        if rules["match_level"] == "STRICT" and rules["source"] is None:
            return differences  # the default: output identical to before match levels
        differences.append(Difference(
            "MATCH_LEVEL", None, None,
            {"level": rules["match_level"], "rules_file": rules["source"],
             "skipped": list(regions.skipped_families(rules["match_level"], skip_map)),
             "regions": [r.get("name") for r in rules["regions"]]},
            PASS))
        return differences

    # Findings whose element is already the subject of a report: an alignment
    # complaint about the same element adds nothing.
    _ALIGNMENT_ROOT_CAUSES = ("MISSING_IN_PRODUCTION", "EXTRA_IN_PRODUCTION",
                              "POSITION_DIFFERENCE", "SIZE_DIFFERENCE", "GROUP_SHIFT")

    def _drop_alignment_collateral(self, differences) -> list:
        """B5 fires on the *neighbours* of whatever actually changed.

        Remove one element and the items it used to line up with are no longer
        aligned, so a single removal is reported three times: once as B1 and
        twice as B5. The removal is the finding; the alignment is its shadow.
        Only alignment findings are dropped, and only when their own element is
        already named by a root-cause finding.
        """
        if not self.drop_alignment_collateral:
            return differences
        blamed = {d.production_id for d in differences
                  if d.type in self._ALIGNMENT_ROOT_CAUSES and d.verdict != PASS}
        blamed |= {d.client_id for d in differences
                   if d.type in self._ALIGNMENT_ROOT_CAUSES and d.verdict != PASS}
        blamed.discard(None)
        kept = []
        for d in differences:
            if d.type == "ALIGNMENT_DIFFERENCE":
                involved = set(d.details.get("client_ids") or []) | \
                           set(d.details.get("production_ids") or [])
                if involved & blamed:
                    continue
            kept.append(d)
        return kept

    def _is_dynamic(self, el, by_id) -> bool:
        return _is_dynamic(el, by_id, self.on_card_overlap)  # §H rule lives in matcher.py

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
        alignment_rows = layout_checks.alignment(
            *args, tolerance_norm=cfg.get("alignment_tolerance_norm", 0.015))
        if self.merge_alignment_chains:
            alignment_rows = _merge_alignment_rows(alignment_rows)
        for row in alignment_rows:
            # Minor per §B5 - a Minor FAIL is a warning, not a screen FAIL.
            found.append(Difference("ALIGNMENT_DIFFERENCE",
                                    (row["production_ids"] or [None])[0],
                                    (row["client_ids"] or [None])[0], row, FAIL, MINOR))
        for row in layout_checks.clipping(*args):
            # Clipped in the client only is usually just a different scroll
            # position, so it is a REVIEW rather than a defect.
            production_side = row["clipped_in"] == "production"
            if self.cap_clipped and row.get("class") in (
                    "content_card", "cast_card", "celebrity_card"):
                production_side = False  # a cut-off card is scroll position (F3)
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

    def _pixel_verify_size(self, p, c, found, images, client_graph=None) -> list:
        """C2 re-measured from pixels: confirm or drop a box-based size finding.

        Detector boxes wobble a few px between screenshots (bottom-nav "Profile"
        0.0477 vs 0.0447 of screen height, identical by eye). A tight box of the
        pixels that stand out from each crop's own background is measured on
        both sides and recorded in details["pixel_check"]. With
        pixel_verify.enabled the finding is dropped when the tight sizes agree
        within size_bands.pass and both measurements are reliable; otherwise it
        stays as it was. It never creates a finding (rules.md §7).
        """
        cfg = self.pixel_verify_cfg
        size = next((d for d in found if d.type == "SIZE_DIFFERENCE"), None)
        if size is None or not p.bbox or not c.bbox:
            return found
        artwork = self._shows_artwork_through(client_graph, c.id)
        tight = []
        for img, (x, y, w, h) in zip(images, (p.bbox, c.bbox)):
            mx = max(cfg.get("margin_min_px", 4), w * cfg.get("margin_frac", 0.15))
            my = max(cfg.get("margin_min_px", 4), h * cfg.get("margin_frac", 0.15))
            box = (max(0, int(x - mx)), max(0, int(y - my)),
                   min(img.width, int(x + w + mx)), min(img.height, int(y + h + my)))
            tight.append(pixel_geometry.tight_box(
                img.crop(box), cfg.get("contrast_threshold", 12.0),
                cfg.get("min_pixels", 16), artwork))
        wd, hd = pixel_geometry.size_diff(tight[0], tight[1], images[0].size, images[1].size)
        reliable = tight[0].reliable and tight[1].reliable
        within = max(wd, hd) <= self.size_bands["pass"]
        size.details["pixel_check"] = {
            "production_tight_px": [tight[0].w, tight[0].h],
            "client_tight_px": [tight[1].w, tight[1].h],
            "width_ratio_diff": round(wd, 4),
            "height_ratio_diff": round(hd, 4),
            "reliable": reliable,
            "note": "; ".join(n for n in (tight[0].note, tight[1].note) if n),
            "confirmed": reliable and not within,
        }
        if cfg.get("enabled", False) and reliable and within:
            return [d for d in found if d is not size]
        return found

    @staticmethod
    def _crop(img, bbox):
        x, y, w, h = bbox
        return img.crop((int(x), int(y), int(x + w), int(y + h)))

    def _text_contrast(self, p, c, images, client_graph=None) -> list:
        """D7 contrast and D3 text colour on matched static text.

        Text and background are split per crop by k-means (the smaller cluster
        is text). Skipped when the label floats over artwork (the "background"
        would be a poster) or either split is unreliable. D7 passes at the
        WCAG AA ratio, or when production is as readable as the design within
        a tolerance - a low-contrast design is the reference, not a defect.
        Measured 2026-09-25 on the SunNXT pairs: only "SUNNXT SHORTS" (1.29:1
        vs 2.63:1, text dE 12.3) and "Profile" (text dE 5.1) cross a band.
        """
        cfg = self.contrast_cfg
        if (not cfg.get("enabled", True) or c.class_ not in self.static_text_classes
                or not c.text or not p.text or not p.bbox or not c.bbox
                or self._shows_artwork_through(client_graph, c.id)):
            return []
        # A logo label is not text colour (Trending Search: the "SUN NXT"
        # Home tab gave dE 32 by reading the dark background as "text").
        wordmarks = [_normalize_text(w).replace(" ", "") for w in cfg.get("logo_wordmarks", [])]
        if any(_normalize_text(t).replace(" ", "") in wordmarks for t in (p.text, c.text)):
            return []
        band = cfg.get("tab_text_band", 0.4)

        def text_crop(img, el):
            # Tabs stack an icon over the label: measure the label band only.
            x, y, w, h = el.bbox
            if el.class_ == "tab_item" and band:
                y, h = y + h * (1 - band), h * band
            return self._crop(img, (x, y, w, h))

        m = contrast_checks.measure_pair(text_crop(images[0], p), text_crop(images[1], c),
                                         min_cluster_de=cfg.get("min_cluster_de", 10.0))
        if not (m.production.reliable and m.client.reliable):
            return []
        found = []
        ratio = m.production_ratio
        tolerance = cfg.get("same_as_template_tolerance", 0.5)
        if ratio < cfg.get("pass_ratio", 4.5) and ratio < m.client_ratio - tolerance:
            fail = ratio < cfg.get("fail_ratio", 3.0)
            found.append(Difference(
                "CONTRAST_DIFFERENCE", p.id, c.id,
                {"production_ratio": round(ratio, 2), "client_ratio": round(m.client_ratio, 2)},
                FAIL if fail else REVIEW, MAJOR if fail else None))
        bands = cfg.get("text_color_bands", {"pass": 5.0, "fail": 10.0})
        if m.text_delta_e > bands["pass"]:
            fail = m.text_delta_e > bands["fail"]
            found.append(Difference(
                "TEXT_COLOR_DIFFERENCE", p.id, c.id,
                {"delta_e": round(m.text_delta_e, 2),
                 "production_rgb": m.production.text.rgb, "client_rgb": m.client.text.rgb},
                FAIL if fail else REVIEW, MAJOR if fail else None))
        return found

    def _image_identity(self, p, c, images) -> list:
        """F1 logo / F2 icon: is it the same picture? Resize-then-SSIM is right
        here - identity, not size, which is C2's job. No detection on the
        SunNXT pairs is a logo or icon today, so this is idle on them."""
        cfg = self.image_cfg
        logo = c.class_ in cfg.get("logo_classes", ["logo"])
        icon = c.class_ in cfg.get("icon_classes", ["icon"])
        if not cfg.get("enabled", True) or not (logo or icon) or not p.bbox or not c.bbox:
            return []
        score = image_checks.ssim(self._crop(images[0], p.bbox), self._crop(images[1], c.bbox))
        details = {"ssim": round(score, 3)}
        if logo:
            bands = cfg.get("logo_bands", {"pass": 0.90, "fail": 0.75})
            if score >= bands["pass"]:
                return []
            fail = score < bands["fail"]
            return [Difference("LOGO_DIFFERENCE", p.id, c.id, details,
                               FAIL if fail else REVIEW, CRITICAL if fail else None)]
        if score >= cfg.get("icon_pass", 0.85):
            return []
        return [Difference("ICON_DIFFERENCE", p.id, c.id, details, FAIL, MAJOR)]

    def _broken_images(self, images, production_doc, match_result, client_by_id) -> list:
        """F3: a production card that is almost flat - the image did not load.

        A presence check on the container, allowed by section H; what the poster
        shows is never compared. When the matched design card is flat too (a
        mockup with grey placeholders) it is not a defect. Measured 2026-09-25:
        every benchmark blank_poster card has luminance std 0.0; the flattest
        real card on any screen is 17.4 (production 27.2).
        """
        cfg = self.image_cfg
        if not cfg.get("enabled", True):
            return []
        cards = cfg.get("card_classes", ["content_card", "cast_card", "celebrity_card"])
        max_std = cfg.get("flat_max_std", 5.0)
        max_edges = cfg.get("flat_max_edge_density", 0.01)

        def flat(img, bbox):
            f = image_checks.flatness(self._crop(img, bbox))
            return (f.pixels > 0 and f.luminance_std <= max_std
                    and f.edge_density <= max_edges), f

        client_of = {m.production_id: m.client_id for m in match_result.matches}
        found = []
        for el in production_doc.elements:
            if el.class_ not in cards or not el.bbox or el.metadata.get("ignored"):
                continue
            is_flat, f = flat(images[0], el.bbox)
            if not is_flat:
                continue
            c = client_by_id.get(client_of.get(el.id))
            if c is not None and c.bbox and flat(images[1], c.bbox)[0]:
                continue  # placeholder in the design too
            found.append(Difference(
                "BROKEN_IMAGE", el.id, c.id if c else None,
                {"luminance_std": round(f.luminance_std, 2),
                 "edge_density": round(f.edge_density, 4)},
                FAIL, MAJOR))
        return found

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

    def _merged_shift_chains(self, shifts, client_graph) -> dict:
        """Nested containers that carry the same shift are one move.

        The matcher estimates a shift per container, and the screen root often
        agrees with the panel inside it: on the SunNXT language pair "screen"
        (-136 px) and the sheet tabs (-139 px) are the same sheet move, reported
        twice. A container joins its nearest shifted ancestor when both dx and
        dy agree within max_spread_norm; chains merge transitively. Returns
        {reported group: [every group in its chain]}. The reported group is the
        outermost one that is not the screen root (the root is a last-resort
        bucket, not a panel), or the root when it is alone.
        """
        def ancestors(group):
            up = _container_of(client_graph, group)
            while up is not None:
                yield up
                up = _container_of(client_graph, up)

        top = {g: g for g in shifts}

        def find(g):
            while top[g] != g:
                g = top[g]
            return g

        for g, info in shifts.items():
            if not self.merge_nested_shifts or client_graph is None:
                break
            parent = next((a for a in ancestors(g) if a in shifts), None)
            if parent is None:
                continue
            (dx, dy), (px, py) = info["shift"], shifts[parent]["shift"]
            if abs(dx - px) <= self.shift_spread_norm and abs(dy - py) <= self.shift_spread_norm:
                top[find(g)] = find(parent)

        chains = {}
        for g in shifts:
            chains.setdefault(find(g), []).append(g)
        reported = {}
        for chain in chains.values():
            panels = [g for g in chain if g != SCREEN_ID] or chain
            outer = min(panels, key=lambda g: sum(1 for _ in ancestors(g)))
            reported[outer] = chain
        return reported

    def _group_shifts(self, match_result, client_by_id, client_graph=None) -> list:
        """One C1 finding per container that moved as one piece, instead of one
        per member. The members are then judged on their residual only."""
        found = []
        shifts = match_result.group_shifts
        for group, chain in self._merged_shift_chains(shifts, client_graph).items():
            info = shifts[group]
            dx, dy = info["shift"]
            distance = self._diagonal_fraction(dx, dy)
            if distance <= self.position_bands["pass"]:
                continue
            verdict, severity = self._position_verdict(distance, self.position_bands)
            w, h = self._screen
            members = list(info["members"])
            for g in chain:
                members += [m for m in shifts[g]["members"] if m not in members]
            label = next((client_by_id[i].text for i in members
                          if i in client_by_id and client_by_id[i].class_ == "section_title"
                          and client_by_id[i].text), None)
            details = {
                "group": group,
                "label": label,
                "dx_px": round(dx * w, 1),
                "dy_px": round(dy * h, 1),
                "distance_of_diagonal": distance,
                # Anchors vote in every container above them, so an outer
                # group's count already includes its inner ones: max, not sum.
                "anchors": max(shifts[g]["anchors"] for g in chain),
                "members": members,
            }
            if len(chain) > 1:
                details["merged_groups"] = [g for g in chain if g != group]
            found.append(Difference("GROUP_SHIFT", None, group, details, verdict, severity))
        return found

    def _unmatched(self, diff_type, el, by_id, pid, cid, ambiguous=False) -> Difference:
        details = {"class": el.class_, "text": el.text, "confidence": el.confidence}
        if self._is_dynamic(el, by_id):
            details["ignored"] = "dynamic content"
            return Difference(diff_type, pid, cid, details, PASS)
        if ambiguous:
            # The rescue pass saw more than one plausible partner (rules.md §I).
            details["ambiguous_rescue"] = True
            return Difference(diff_type, pid, cid, details, REVIEW)
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
            p_text, c_text = _normalize_text(self._clean(p)), _normalize_text(self._clean(c))
            lang = self.language_cfg
            wrong_script = (lang.get("enabled", True) and p.text and c.text and
                            script_checks.scripts_differ(p.text, c.text,
                                                         lang.get("min_share", 0.6)))
            if wrong_script:
                # E4 - a label in another script is a wrong-language build, not
                # a wrong label: reported once as Critical, with no E1 on top.
                found.append(Difference(
                    "LANGUAGE_DIFFERENCE", p.id, c.id,
                    {"production_text": p.text, "client_text": c.text,
                     "production_script": script_checks.dominant_script(p.text)[0],
                     "client_script": script_checks.dominant_script(c.text)[0]},
                    FAIL, CRITICAL))
            elif p_text != c_text and not (p_text and c_text):
                # OCR read nothing on one side: that is "not read", not a wrong
                # label (Trending Search: the production search bar had no text).
                found.append(Difference(
                    "TEXT_DIFFERENCE", p.id, c.id,
                    {"production_text": p.text, "client_text": c.text,
                     "similarity": breakdown["text"], "note": "no text read on one side"},
                    REVIEW))
            elif p_text != c_text and self._text_format(c.text) and \
                    self._text_format(c.text) == self._text_format(p.text):
                pass  # 15.1: same format (price, duration, episode...), value may change
            elif p_text != c_text:
                expected = self._text_format(c.text)
                if expected:
                    # The design shows a formatted value; production broke the format.
                    found.append(Difference(
                        "TEXT_DIFFERENCE", p.id, c.id,
                        {"production_text": p.text, "client_text": c.text,
                         "similarity": breakdown["text"], "expected_format": expected},
                        FAIL, MAJOR))
                elif _same_but_for_style(p_text, c_text):
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
        floating = regions.floating_offset(c.normalized_bbox, self._rules) if self._rules else None
        if floating is not None:
            # 15.1: allowed to float this far; REVIEW/FAIL bands above it as usual.
            bands = {**bands, "pass": max(bands["pass"], floating),
                     "fail": max(bands["fail"], floating), "major": max(bands["major"], floating)}
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
