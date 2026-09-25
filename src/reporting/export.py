"""Turn a report.json into ticket rows (one per issue) so testers stop re-typing findings.

Only FAIL/REVIEW is exported; findings the reviewer accepted or the differ ignored are dropped.
Older reports without "issues" fall back to one row per finding.
"""
import csv
from datetime import date
from pathlib import Path

DEFAULT_COLUMNS = [
    "run_id", "date", "screen", "spec_id", "severity", "verdict",
    "element_class", "element_text", "description", "count", "report_path",
]


def _open(finding: dict) -> bool:
    details = finding.get("details") or {}
    return finding.get("verdict") in ("FAIL", "REVIEW") and "accepted" not in details and "ignored" not in details


def to_ticket_rows(report: dict, report_path: str, columns: list[str]) -> list[dict]:
    findings = report.get("findings", [])
    issues = report.get("issues")
    if issues is None:
        issues = [{
            "spec_id": f.get("spec_id"), "class": f.get("class"), "verdict": f.get("verdict"),
            "severity": f.get("severity"), "finding_indices": [i],
            "summary": f"{f.get('class')} {f.get('type')}" + (f": {f['text']}" if f.get("text") else ""),
        } for i, f in enumerate(findings)]

    path = Path(report_path)
    run_id = path.parent.name
    day = date.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else ""
    rows = []
    for issue in issues:
        members = [findings[i] for i in issue.get("finding_indices", []) if i < len(findings) and _open(findings[i])]
        if not members or issue.get("verdict") not in ("FAIL", "REVIEW"):
            continue
        fields = {
            "run_id": run_id, "date": day, "screen": report.get("screen", ""),
            "spec_id": issue.get("spec_id"), "severity": issue.get("severity"), "verdict": issue.get("verdict"),
            "element_class": issue.get("class"), "element_text": members[0].get("text") or "",
            "description": issue.get("summary", ""), "count": len(members), "report_path": str(report_path),
        }
        rows.append({c: fields.get(c, "") for c in columns})
    return rows


def write_csv(rows: list[dict], columns: list[str], path) -> None:
    # utf-8-sig: the BOM makes Excel read Tamil text and ₹ correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
