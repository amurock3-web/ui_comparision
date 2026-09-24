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

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "test_cases_pass_fail.md"

SPEC_BY_TYPE = {
    "MISSING_IN_PRODUCTION": "B1",
    "EXTRA_IN_PRODUCTION": "B2",
    "CLASS_DIFFERENCE": "C4",
    "TEXT_DIFFERENCE": "E1",
    "POSITION_DIFFERENCE": "C1",
    "GROUP_SHIFT": "C1",  # a whole panel moved; reported once, not per member
    "SIZE_DIFFERENCE": "C2",
    "STRUCTURAL_DIFFERENCE": "graph",  # no spec row; the matcher's context hint
}
# Test cases src/comparison/differ.py implements. Keep in step with its docstring.
IMPLEMENTED = {"B1", "B2", "B9", "C1", "C2", "C4", "E1"}
RULES = [("H", "Ignore list (poster art, status bar, dynamic text)"),
         ("I", "Uncertainty -> REVIEW (never silent PASS)")]
# Keys in report["summary"] that are not per-difference-type counts.
SUMMARY_FIELDS = ("matched_pairs", "clean_pairs", "missing", "extra", "ignored", "comparable",
                  "similarity_percent", "clean_percent", "difference_records", "warning")


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


def coverage(findings) -> list:
    """Every spec test case: checked (with its worst verdict here) or not built."""
    worst = {}
    rank = {"PASS": 0, "REVIEW": 1, "FAIL": 2}
    for f in findings:
        if rank[f["verdict"]] > rank.get(worst.get(f["spec_id"]), -1):
            worst[f["spec_id"]] = f["verdict"]
    rows = [{"id": i, "check": check,
             "status": "checked" if i in IMPLEMENTED else "not built",
             "result": worst.get(i, "PASS") if i in IMPLEMENTED else None}
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
            })

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
        if not comparable:
            summary["warning"] = "Nothing comparable on this screen — extraction found no matchable elements."
        return {
            "screen": production_doc.screen_id,
            "verdict": screen_verdict(differences),
            "warnings": sum(1 for f in findings if f["verdict"] == "FAIL" and f["severity"] == "Minor"),
            "similarity_percent": similarity,
            "summary": {**summary, **counts},
            "findings": findings,
            "coverage": coverage(findings),
            "confidence": {"production": confidence(production_doc), "client": confidence(client_doc)},
        }

    @staticmethod
    def save_json(report: dict, path: Path):
        Path(path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
