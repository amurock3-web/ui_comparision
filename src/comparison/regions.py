"""
Match levels and regions (Applitools-style), one mechanism for 14.1 and 15.0.

A match level says which spec families a finding may come from:
    STRICT         every check (the default, today's behaviour)
    LAYOUT         structure and geometry only - no D colour, E text, F image
    IGNORE_COLORS  everything except D
    NONE           nothing: an ignore region
The level -> skipped families mapping lives in config (comparison.match_levels.skip).

A region of type FLOATING is not a level: an element inside it may move up to
max_offset_norm (fraction of the screen diagonal, C1's unit) without a C1
finding. A rules file may also add dynamic-text `patterns: {name: regex}` (E1).

Where a level comes from, most specific wins: a region covering the element
(>= min_overlap of the element's area; the smallest such region) > the
screen's rules file (config/screen_rules/<client screen id>.yaml) > the config
default. A rules file looks like:

    match_level: LAYOUT
    regions:
      - {name: hero, type: STRICT, bbox_norm: [0, 0.06, 1, 0.30]}
      - {name: promo, type: NONE, bbox_norm: [0, 0.8, 1, 0.1], min_overlap: 0.5}

A skipped finding is not deleted (rules.md §10, keep evidence): it becomes
PASS with details["ignored"] = "match level <LEVEL>", so it drops out of the
findings list and the similarity denominator exactly like other ignored items.
"""

from pathlib import Path

import yaml

LEVELS = ("STRICT", "LAYOUT", "IGNORE_COLORS", "NONE")
REGION_TYPES = LEVELS + ("FLOATING",)
ALL_FAMILIES = ("A", "B", "C", "D", "E", "F", "G")


def load_rules(screen_id, rules_dir, default_level="STRICT", default_regions=(),
               rules_path=None, level_override=None) -> dict:
    """{"match_level", "regions", "source"} for one client screen.

    Config default regions (e.g. the status bar) come first, the rules file's
    regions after them. `rules_path` / `level_override` are the CLI overrides.
    """
    path = Path(rules_path) if rules_path else Path(rules_dir) / f"{screen_id}.yaml"
    data = {}
    if path.is_file():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    elif rules_path:
        raise FileNotFoundError(f"rules file not found: {path}")
    level = (level_override or data.get("match_level") or default_level).upper()
    regions = [dict(r) for r in default_regions] + [dict(r) for r in data.get("regions") or []]
    if level not in LEVELS:
        raise ValueError(f"unknown match level {level!r} in {path}")
    for r in regions:
        r["type"] = str(r.get("type", "")).upper()
        if r["type"] not in REGION_TYPES:
            raise ValueError(f"unknown region type {r['type']!r} in {path}")
    return {"match_level": level, "regions": regions, "patterns": data.get("patterns") or {},
            "source": str(path) if path.is_file() else None}


def _overlap(box, region) -> float:
    """Share of `box`'s area inside `region`; both [x, y, w, h] normalized."""
    x, y, w, h = box
    rx, ry, rw, rh = region
    ix = max(0.0, min(x + w, rx + rw) - max(x, rx))
    iy = max(0.0, min(y + h, ry + rh) - max(y, ry))
    return ix * iy / (w * h) if w > 0 and h > 0 else 0.0


def _smallest_covering(bbox_norm, regions):
    covering = [r for r in regions
                if _overlap(bbox_norm, r["bbox_norm"]) >= r.get("min_overlap", 0.5)]
    return min(covering, key=lambda r: r["bbox_norm"][2] * r["bbox_norm"][3]) if covering else None


def level_for(bbox_norm, rules) -> str:
    """Match level for one element: its smallest covering region, else the screen's."""
    if bbox_norm:
        region = _smallest_covering(
            bbox_norm, [r for r in rules["regions"] if r["type"] != "FLOATING"])
        if region is not None:
            return region["type"]
    return rules["match_level"]


def floating_offset(bbox_norm, rules):
    """max_offset_norm of the smallest FLOATING region covering the element, or None."""
    if not bbox_norm:
        return None
    region = _smallest_covering(
        bbox_norm, [r for r in rules["regions"] if r["type"] == "FLOATING"])
    return region.get("max_offset_norm") if region is not None else None


def skipped_families(level, skip_map) -> tuple:
    return ALL_FAMILIES if level == "NONE" else tuple(skip_map.get(level, ()))


def apply_match_levels(differences, rules, skip_map, element_of, spec_of) -> list:
    """Turn findings the applicable level skips into PASS / ignored, in place.

    element_of(d) -> the element whose position decides the level (or None for
    screen-level findings, which take the screen's level); spec_of(d, element)
    -> the spec id, whose first letter is the family.
    """
    for d in differences:
        if d.verdict == "PASS":
            continue
        el = element_of(d)
        level = level_for(el.normalized_bbox if el is not None else None, rules)
        if spec_of(d, el)[:1] in skipped_families(level, skip_map):
            d.details = {**d.details, "ignored": f"match level {level}"}
            d.verdict, d.severity = "PASS", None
    return differences
