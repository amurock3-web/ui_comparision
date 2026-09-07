"""
Difference engine (architecture.md §12, design.md §8-11, rules.md §8).

Runs ElementMatcher (matcher.py) to find correspondences between
Production and Client elements, then classifies each element/pair into
the difference taxonomy. An unmatched production element or unmatched
client element is reported as MISSING_IN_CLIENT / EXTRA_IN_CLIENT
directly from the matcher's leftovers (the "unmatched node = a change"
idea from Moradi et al., Section 3.4). A matched pair is inspected for
sub-differences using the score breakdown ElementMatcher already
computed (class/text/spatial/iou/context) plus the raw element fields;
a pair with no sub-difference is reported as MATCH.

Implemented types: MATCH, MISSING_IN_CLIENT, EXTRA_IN_CLIENT,
CLASS_DIFFERENCE, TEXT_DIFFERENCE, POSITION_DIFFERENCE, SIZE_DIFFERENCE,
STRUCTURAL_DIFFERENCE (driven by the matcher's one-hop context score).
GEOMETRY_DIFFERENCE, ORDER_DIFFERENCE, and UNCERTAIN from rules.md §8 are
not yet implemented — they need sibling-ordering and aspect-ratio
comparison design that hasn't been calibrated against real screenshot
pairs yet.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from src.comparison.matcher import ElementMatcher, _normalized_center
from src.schema.ui_element import UIDocument

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"


@dataclass
class Difference:
    type: str
    production_id: str | None
    client_id: str | None
    details: dict


class DifferenceEngine:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        cfg = yaml.safe_load(Path(config_path).read_text()).get("comparison", {})
        self.text_similarity_threshold = cfg.get("text_similarity_threshold", 0.85)
        self.position_threshold_norm = cfg.get("position_threshold_norm", 0.02)
        self.size_ratio_threshold = cfg.get("size_ratio_threshold", 0.15)
        self.structural_similarity_threshold = cfg.get("structural_similarity_threshold", 0.5)
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

        differences = []

        for pid in match_result.unmatched_production:
            el = prod_by_id[pid]
            differences.append(
                Difference(
                    type="MISSING_IN_CLIENT",
                    production_id=pid,
                    client_id=None,
                    details={"class": el.class_, "text": el.text, "confidence": el.confidence},
                )
            )

        for cid in match_result.unmatched_client:
            el = client_by_id[cid]
            differences.append(
                Difference(
                    type="EXTRA_IN_CLIENT",
                    production_id=None,
                    client_id=cid,
                    details={"class": el.class_, "text": el.text, "confidence": el.confidence},
                )
            )

        for m in match_result.matches:
            p = prod_by_id[m.production_id]
            c = client_by_id[m.client_id]
            sub_differences = self._sub_differences(p, c, m.breakdown)
            if not sub_differences:
                differences.append(
                    Difference(
                        type="MATCH",
                        production_id=p.id,
                        client_id=c.id,
                        details={"score": m.score},
                    )
                )
            else:
                differences.extend(sub_differences)

        return differences

    def _sub_differences(self, p, c, breakdown) -> list:
        found = []

        if p.class_ is not None and c.class_ is not None and p.class_ != c.class_:
            found.append(
                Difference(
                    type="CLASS_DIFFERENCE",
                    production_id=p.id,
                    client_id=c.id,
                    details={"production_class": p.class_, "client_class": c.class_},
                )
            )

        if p.text or c.text:
            if breakdown["text"] < self.text_similarity_threshold:
                found.append(
                    Difference(
                        type="TEXT_DIFFERENCE",
                        production_id=p.id,
                        client_id=c.id,
                        details={"production_text": p.text, "client_text": c.text, "similarity": breakdown["text"]},
                    )
                )

        p_center = _normalized_center(p.normalized_bbox)
        c_center = _normalized_center(c.normalized_bbox)
        position_distance = ((p_center[0] - c_center[0]) ** 2 + (p_center[1] - c_center[1]) ** 2) ** 0.5
        if position_distance > self.position_threshold_norm:
            found.append(
                Difference(
                    type="POSITION_DIFFERENCE",
                    production_id=p.id,
                    client_id=c.id,
                    details={"production_center": p_center, "client_center": c_center, "distance": position_distance},
                )
            )

        p_w, p_h = p.normalized_bbox[2], p.normalized_bbox[3]
        c_w, c_h = c.normalized_bbox[2], c.normalized_bbox[3]
        width_ratio_diff = abs(p_w - c_w) / max(p_w, c_w, 1e-9)
        height_ratio_diff = abs(p_h - c_h) / max(p_h, c_h, 1e-9)
        if width_ratio_diff > self.size_ratio_threshold or height_ratio_diff > self.size_ratio_threshold:
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
                )
            )

        if breakdown["context"] < self.structural_similarity_threshold:
            found.append(
                Difference(
                    type="STRUCTURAL_DIFFERENCE",
                    production_id=p.id,
                    client_id=c.id,
                    details={"context_similarity": breakdown["context"]},
                )
            )

        return found
