"""
Report generation (design.md §12, docs/test_cases_pass_fail.md §0).

Produces the summary block (screen verdict, similarity %, counts by
difference type) and per-difference findings from a
DifferenceEngine.compare() result. Findings list only REVIEW/FAIL items;
PASS items (MATCH, ignored dynamic content, in-tolerance) are only
counted. Visual evidence is a separate module — see
src/reporting/visualize.py.

Similarity is an element count, not a record count: matched pairs over
matched + missing + extra, so a pair with three sub-differences counts as
one compared element and ignored dynamic content stays out of the
denominator entirely.

Screen verdict: any Critical/Major FAIL → FAIL; else any REVIEW → REVIEW;
else PASS (Minor FAILs are listed as warnings).

Each finding carries the test-case id it belongs to (spec_id), and the
report lists every test case in docs/test_cases_pass_fail.md as checked or
not built (coverage), so a PASS reads as "passed the checks we have", never
"the screen is fine". `confidence` counts, per side, what the pipeline was
unsure of or skipped: a verdict on a shaky extraction is a weak verdict.
"""

import json
import re
from pathlib import Path

import yaml

from src.reporting.grouping import group_findings

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "test_cases_pass_fail.md"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "config.yaml"

SPEC_BY_TYPE = {
    "ORIENTATION_DIFFERENCE": "A1",
    "BLANK_SCREEN": "A2",
    "THEME_DIFFERENCE": "A3",
    "SCALING_DIFFERENCE": "A5",
    "COLOR_DIFFERENCE": "D1",
    "BACKGROUND_COLOR_DIFFERENCE": "D2",
    "BADGE_COLOR_DIFFERENCE": "D5",
    "SECTION_ORDER_DIFFERENCE": "B3",
    "TAB_ORDER_DIFFERENCE": "B4",
    "ALIGNMENT_DIFFERENCE": "B5",
    "CLIPPING_DIFFERENCE": "B8",
    "MISSING_IN_PRODUCTION": "B1",
    "EXTRA_IN_PRODUCTION": "B2",
    "CLASS_DIFFERENCE": "C4",
    "TEXT_DIFFERENCE": "E1",
    "TEXT_STYLE_DIFFERENCE": "E3",  # same letters, different case or spacing
    "POSITION_DIFFERENCE": "C1",
    "GROUP_SHIFT": "C1",  # a whole panel moved; reported once, not per member
    "SIZE_DIFFERENCE": "C2",
    "STRUCTURAL_DIFFERENCE": "graph",  # no spec row; the matcher's context hint
    "ELEMENT_COMPARISON_SKIPPED": "info",  # no spec row; why the rest is absent
    "MATCH_LEVEL": "info",  # no spec row; which level applied and what it skipped
    "ACCEPTANCES": "info",  # no spec row; the acceptance file and its stale entries
    "LANGUAGE_DIFFERENCE": "E4",
    "CONTRAST_DIFFERENCE": "D7",
    "TEXT_COLOR_DIFFERENCE": "D3",
    "LOGO_DIFFERENCE": "F1",
    "ICON_DIFFERENCE": "F2",
    "BROKEN_IMAGE": "F3",
}
# Test cases src/comparison/differ.py implements. Keep in step with its docstring.
IMPLEMENTED = {"A1", "A2", "A3", "A5", "B1", "B2", "B3", "B4", "B5", "B8", "B9", "C1", "C2", "C4",
               "D1", "D2", "D3", "D5", "D7", "E1", "E3", "E4", "F1", "F2", "F3"}
RULES = [("H", "Ignore list (poster art, status bar, dynamic text)"),
         ("I", "Uncertainty -> REVIEW (never silent PASS)")]
# Keys in report["summary"] that are not per-difference-type counts.
SUMMARY_FIELDS = ("matched_pairs", "clean_pairs", "missing", "extra", "ignored", "comparable",
                  "similarity_percent", "clean_percent", "difference_records", "warning", "issues",
                  "match_level", "accepted")


def spec_id(difference, element) -> str:
    """Test-case id for one difference; an unmatched card is B9, not B1/B2."""
    if (difference.type in ("MISSING_IN_PRODUCTION", "EXTRA_IN_PRODUCTION")
            and element is not None and element.class_ == "content_card"):
        return "B9"
    return SPEC_BY_TYPE.get(difference.type, difference.type)


def load_spec(path: Path = SPEC_PATH) -> list:
    """[(id, check)] from the spec's tables: every row starting "| A1 | ...". """
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([A-G]\d)\s*\|\s*([^|]+?)\s*\|", line)
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows


def coverage(findings, skipped=(), level=None) -> list:
    """Every spec test case: checked (with its worst verdict here), skipped by the
    screen's match level (skipped is not passed), or not built."""
    worst = {}
    rank = {"PASS": 0, "REVIEW": 1, "FAIL": 2}
    for f in findings:
        if rank[f["verdict"]] > rank.get(worst.get(f["spec_id"]), -1):
            worst[f["spec_id"]] = f["verdict"]
    def status(i):
        if i not in IMPLEMENTED:
            return "not built"
        return f"skipped ({level})" if i[:1] in skipped else "checked"

    rows = [{"id": i, "check": check, "status": status(i),
             "result": worst.get(i, "PASS") if status(i) == "checked" else None}
            for i, check in load_spec()]
    rows += [{"id": i, "check": check, "status": "applied", "result": None} for i, check in RULES]
    return rows


def confidence(doc) -> dict:
    els = doc.elements
    return {
        "elements": len(els),
        "uncertain": sum(1 for e in els if e.metadata.get("match_status") == "uncertain"),
        "ignored": sum(1 for e in els if e.metadata.get("ignored")),
        "low_confidence": sum(1 for e in els if e.confidence_tier == "low"),
        "unclassified": sum(1 for e in els if e.class_ is None),
    }


def screen_verdict(differences) -> str:
    if any(d.verdict == "FAIL" and d.severity in ("Critical", "Major") for d in differences):
        return "FAIL"
    if any(d.verdict == "REVIEW" for d in differences):
        return "REVIEW"
    return "PASS"


class ReportGenerator:
    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH):
        full = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        cmp = full.get("comparison", {})
        # Issues reuse the checks' own PASS bands: two findings are "the same
        # issue" when they differ by less than a check would notice.
        self.group = full.get("reporting", {}).get("group_findings", True)
        self.group_args = {
            "color_pass_de": cmp.get("color", {}).get("brand_bands", {}).get("pass", 3.0),
            "size_pass": cmp.get("size_bands", {}).get("pass", 0.05),
            "position_step": full.get("matching", {}).get("group_shift", {})
                                 .get("max_spread_norm", 0.01),
        }

    def generate(self, production_doc, client_doc, differences) -> dict:
        counts = {}
        for d in differences:
            counts[d.type] = counts.get(d.type, 0) + 1

        # Similarity counts elements, not Difference records (design.md §12):
        # one matched pair with three sub-differences is one compared element
        # that differs, not three uncompared ones.
        pair_records = {}
        for d in differences:
            if d.production_id and d.client_id:
                pair_records.setdefault((d.production_id, d.client_id), []).append(d)
        # A pair whose every record was ignored (§H dynamic content, e.g. a
        # poster tile) was never actually compared, so it counts as neither
        # matched nor clean - otherwise dynamic tiles inflate the similarity
        # of a screen whose real chrome nobody checked.
        pair_verdicts = {
            ids: [d.verdict for d in records]
            for ids, records in pair_records.items()
            if not all(d.details.get("ignored") for d in records)
        }
        matched_pairs = len(pair_verdicts)
        clean_pairs = sum(1 for v in pair_verdicts.values() if all(x == "PASS" for x in v))
        # A PASS on an unmatched element means §H ignored it as dynamic
        # content — it was never compared, so it is not a miss.
        missing = sum(1 for d in differences
                      if d.type == "MISSING_IN_PRODUCTION" and d.verdict != "PASS")
        extra = sum(1 for d in differences
                    if d.type == "EXTRA_IN_PRODUCTION" and d.verdict != "PASS")
        ignored = sum(1 for d in differences if d.details.get("ignored"))
        comparable = matched_pairs + missing + extra  # the denominator; ignored stays out
        similarity = round(100 * matched_pairs / comparable, 1) if comparable else 0.0
        clean = round(100 * clean_pairs / comparable, 1) if comparable else 0.0

        prod_by_id = {el.id: el for el in production_doc.elements}
        client_by_id = {el.id: el for el in client_doc.elements}

        findings = []
        for d in differences:
            if d.verdict == "PASS":
                continue
            p = prod_by_id.get(d.production_id)
            c = client_by_id.get(d.client_id)
            reference = c or p
            findings.append({
                "type": d.type,
                "spec_id": spec_id(d, reference),
                "verdict": d.verdict,
                "severity": d.severity,
                "production_id": d.production_id,
                "client_id": d.client_id,
                "class": reference.class_ if reference else None,
                "text": reference.text if reference else None,
                "details": d.details,
                # Where the finding is, for the results page and for accepting it.
                "production_bbox_norm": p.normalized_bbox if p else None,
                "client_bbox_norm": c.normalized_bbox if c else None,
                "client_center_norm": ([c.normalized_bbox[0] + c.normalized_bbox[2] / 2,
                                        c.normalized_bbox[1] + c.normalized_bbox[3] / 2]
                                       if c and c.normalized_bbox else None),
            })
        accepted_findings = [
            {"type": d.type, "spec_id": spec_id(d, client_by_id.get(d.client_id)
                                                 or prod_by_id.get(d.production_id)),
             "production_id": d.production_id, "client_id": d.client_id,
             "accepted": d.details["accepted"]}
            for d in differences if d.details.get("accepted")]
        acceptances = next((d.details for d in differences if d.type == "ACCEPTANCES"), None)

        summary = {
            "matched_pairs": matched_pairs,
            "clean_pairs": clean_pairs,
            "missing": missing,
            "extra": extra,
            "ignored": ignored,
            "comparable": comparable,
            "similarity_percent": similarity,
            "clean_percent": clean,
            # Record count, kept for debugging; never read it as an element count.
            "difference_records": len(differences),
        }
        if acceptances is not None:
            summary["accepted"] = len(accepted_findings)
        level = next((d.details for d in differences if d.type == "MATCH_LEVEL"), None)
        if level is not None:
            summary["match_level"] = level["level"]
        issues = group_findings(findings, **self.group_args) if self.group else None
        if issues is not None:
            summary["issues"] = len(issues)
        if not comparable:
            summary["warning"] = "Nothing comparable on this screen — extraction found no matchable elements."
        report = {
            "screen": production_doc.screen_id,
            "client_screen": client_doc.screen_id,
            "verdict": screen_verdict(differences),
            "warnings": sum(1 for f in findings if f["verdict"] == "FAIL" and f["severity"] == "Minor"),
            "similarity_percent": similarity,
            "summary": {**summary, **counts},
            "findings": findings,
            "coverage": coverage(findings, level["skipped"] if level else (),
                                 level["level"] if level else None),
            "confidence": {"production": confidence(production_doc), "client": confidence(client_doc)},
        }
        if issues is not None:
            # Presentation only: findings, verdict and similarity are unchanged.
            report["issues"] = issues
        if acceptances is not None:
            report["accepted"] = accepted_findings
            report["stale_acceptances"] = acceptances["stale"]
        return report

    @staticmethod
    def save_json(report: dict, path: Path):
        Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
