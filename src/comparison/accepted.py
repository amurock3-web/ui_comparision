"""
Accepted differences (Applitools-style "accept once"), Phase 14.4.

A human reviews a finding and says it is expected (a deliberate copy change, a
known colour tweak). The decision goes into a plain YAML file, by default
baselines/accepted_differences.yaml, and the next run reports that finding as
PASS with details["accepted"] instead of raising it again. Everything is local
plain files (rules.md §2).

An entry matches a finding when the client screen, type and element class are
equal, the client text is equal (normalised), the client element centre is
within `center_tolerance` (normalized units), and the signature matches: the
production text for text findings, the production colour within `color_de` for
colour findings. Entries that matched nothing this run are returned as stale,
so an old decision never hides silently.
"""

import datetime
from pathlib import Path

import yaml

from src.comparison.color_checks import delta_e2000, to_lab

TEXT_TYPES = ("TEXT_DIFFERENCE", "TEXT_STYLE_DIFFERENCE", "LANGUAGE_DIFFERENCE")
COLOR_TYPES = ("COLOR_DIFFERENCE", "BADGE_COLOR_DIFFERENCE", "TEXT_COLOR_DIFFERENCE")


def _norm(text):
    return " ".join(str(text).split()).casefold() if text else ""


def signature(finding_type, details) -> object:
    """What must stay the same for an acceptance to keep applying."""
    if finding_type in TEXT_TYPES:
        return _norm(details.get("production_text"))
    if finding_type in COLOR_TYPES and details.get("production_rgb"):
        return list(details["production_rgb"])
    return None


def load(path) -> list:
    path = Path(path)
    if not path.is_file():
        return []
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("accepted") or []


def _matches(entry, screen, d, element, center_tolerance, color_de) -> bool:
    if (entry.get("client_screen_id") != screen or entry.get("type") != d.type
            or element is None or entry.get("client_class") != element.class_
            or _norm(entry.get("client_text")) != _norm(element.text)):
        return False
    center = [element.normalized_bbox[0] + element.normalized_bbox[2] / 2,
              element.normalized_bbox[1] + element.normalized_bbox[3] / 2]
    ex, ey = entry.get("client_center_norm") or (None, None)
    if ex is None or abs(ex - center[0]) > center_tolerance or abs(ey - center[1]) > center_tolerance:
        return False
    want, got = entry.get("signature"), signature(d.type, d.details)
    if d.type in COLOR_TYPES and want and got:
        return delta_e2000(to_lab(want), to_lab(got)) <= color_de
    return want == got


def apply(differences, entries, screen, client_by_id, center_tolerance=0.02, color_de=3.0):
    """Mark accepted findings PASS in place; return the entries that matched nothing."""
    used = set()
    for d in differences:
        if d.verdict == "PASS":
            continue
        element = client_by_id.get(d.client_id)
        for i, entry in enumerate(entries):
            if _matches(entry, screen, d, element, center_tolerance, color_de):
                d.details = {**d.details, "accepted": {"note": entry.get("note"),
                                                       "date": entry.get("date"),
                                                       "by": entry.get("accepted_by")}}
                d.verdict, d.severity = "PASS", None
                used.add(i)
                break
    return [e for i, e in enumerate(entries) if i not in used and e.get("client_screen_id") == screen]


def entry_for(report, finding, note, accepted_by="") -> dict:
    """An acceptance entry for one report finding (needs client_center_norm)."""
    if not finding.get("client_center_norm"):
        raise ValueError("finding has no client element to anchor on (production-only "
                         "findings such as EXTRA_IN_PRODUCTION cannot be accepted yet)")
    return {
        "client_screen_id": report.get("client_screen") or report.get("screen"),
        "type": finding["type"],
        "client_class": finding.get("class"),
        "client_text": finding.get("text"),
        "client_center_norm": [round(v, 4) for v in finding["client_center_norm"]],
        "signature": signature(finding["type"], finding.get("details") or {}),
        "note": note,
        "accepted_by": accepted_by,
        "date": datetime.date.today().isoformat(),
    }


def append(path, new_entries):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = load(path) + list(new_entries)
    path.write_text(yaml.safe_dump({"accepted": entries}, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return len(entries)
