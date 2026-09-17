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

Implemented types: MATCH, MISSING_IN_PRODUCTION, EXTRA_IN_PRODUCTION,
CLASS_DIFFERENCE, TEXT_DIFFERENCE, POSITION_DIFFERENCE, SIZE_DIFFERENCE,
STRUCTURAL_DIFFERENCE (driven by the matcher's one-hop context score).
GEOMETRY_DIFFERENCE, ORDER_DIFFERENCE, and UNCERTAIN from rules.md §8 are
not yet implemented.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.comparison.matcher import ElementMatcher, _normalize_text, _normalized_center
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
        cfg = yaml.safe_load(Path(config_path).read_text()).get("comparison", {})
        self.structural_similarity_threshold = cfg.get("structural_similarity_threshold", 0.5)
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
        self._matcher = ElementMatcher(config_path)

    def compare(
        self,
        production_doc: UIDocument,
        client_doc: UIDocument,
        production_graph=None,
        client_graph=None,
        match_result=None,
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

        for m in match_result.matches:
            p = prod_by_id[m.production_id]
            c = client_by_id[m.client_id]
            if self._is_dynamic(c, client_by_id):
                differences.append(Difference("MATCH", p.id, c.id, {"score": m.score, "ignored": "dynamic content"}))
                continue
            sub_differences = self._sub_differences(p, c, m.breakdown)
            if not sub_differences:
                differences.append(Difference("MATCH", p.id, c.id, {"score": m.score}))
            else:
                differences.extend(sub_differences)

        return differences

    @staticmethod
    def _is_dynamic(el, by_id) -> bool:
        """§H ignore list: anything inside a content_card is live data, and
        anything fusion tagged ignored (the status bar)."""
        if el.metadata.get("ignored"):
            return True
        parent = by_id.get(el.parent_id) if el.parent_id else None
        return parent is not None and parent.class_ == "content_card"

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

    def _sub_differences(self, p, c, breakdown) -> list:
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

        # E1 — static UI text only (§H).
        if c.class_ in self.static_text_classes and (p.text or c.text):
            p_text, c_text = _normalize_text(p.text), _normalize_text(c.text)
            if p_text != c_text:
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
        w, h = self._screen
        position_distance = (
            ((p_center[0] - c_center[0]) * w) ** 2 + ((p_center[1] - c_center[1]) * h) ** 2
        ) ** 0.5 / (w ** 2 + h ** 2) ** 0.5
        grounded = "vlm_grounded" in (p.metadata.get("bbox_source"), c.metadata.get("bbox_source"))
        bands = self.vlm_grounded_position_bands if grounded else self.position_bands
        if position_distance > bands["pass"]:
            if position_distance <= bands["fail"]:
                verdict, severity = REVIEW, None
            else:
                verdict, severity = FAIL, MAJOR if position_distance > bands["major"] else MINOR
            found.append(
                Difference(
                    type="POSITION_DIFFERENCE",
                    production_id=p.id,
                    client_id=c.id,
                    details={
                        "production_center": p_center,
                        "client_center": c_center,
                        "distance_of_diagonal": position_distance,
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
        if breakdown["context"] < self.structural_similarity_threshold:
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
