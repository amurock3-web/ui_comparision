"""Run-to-run history (phase 15.5): which findings are new, fixed or still open
since the previous report for the same baseline.

A finding's identity is (type, client_id, signature): production text for text
types, production rgb rounded to 10 for colour types, the sign of the offset
for position types, else "". Element ids come from the stored client baseline,
so client_id is stable across runs; production ids are not.
"""
import json
import re
from collections import Counter
from pathlib import Path


def _sign(v) -> int:
    return (v > 0) - (v < 0)


def signature(finding: dict):
    t, d = finding.get("type", ""), finding.get("details") or {}
    if "COLOR" in t:
        rgb = d.get("production_rgb")
        return tuple(round(v, -1) for v in rgb) if rgb else ""
    if "TEXT" in t or t == "LANGUAGE_DIFFERENCE":
        return d.get("production_text", finding.get("text")) or ""
    if t in ("POSITION_DIFFERENCE", "GROUP_SHIFT"):
        if "dx_px" in d:
            dx, dy = d["dx_px"], d.get("dy_px", 0)
        elif d.get("production_center") and d.get("client_center"):
            (px, py), (cx, cy) = d["production_center"], d["client_center"]
            dx, dy = px - cx, py - cy
        else:
            return ""
        return (_sign(dx), _sign(dy))
    return ""


def identity(finding: dict) -> tuple:
    return (finding.get("type"), finding.get("client_id"), signature(finding))


def diff(previous_report: dict, current_report: dict) -> dict:
    """{"new", "fixed", "still_open"}: lists of findings (current ones for new and
    still_open, previous ones for fixed). Duplicate identities pair off one to one."""
    remaining = Counter(identity(f) for f in previous_report.get("findings", []))
    new, still_open = [], []
    for f in current_report.get("findings", []):
        key = identity(f)
        if remaining[key] > 0:
            remaining[key] -= 1
            still_open.append(f)
        else:
            new.append(f)
    fixed = []
    for f in previous_report.get("findings", []):
        key = identity(f)
        if remaining[key] > 0:
            remaining[key] -= 1
            fixed.append(f)
    return {"new": new, "fixed": fixed, "still_open": still_open}


def _run_number(run) -> int:
    if isinstance(run, int):
        return run
    m = re.match(r"test(\d+)_", Path(run).name)
    return int(m.group(1)) if m else 0


def find_previous(run_dir_root, baseline_key: str, before):
    """Report path for `baseline_key` from the latest batch run numbered below
    `before` (a run number or a testN_* run dir), read from each run's
    summary.json. None when no earlier run compared that baseline cleanly."""
    limit = _run_number(before)
    runs = sorted((d for d in Path(run_dir_root).glob("test*_*") if 0 < _run_number(d) < limit),
                  key=_run_number, reverse=True)
    for run in runs:
        summary = run / "summary.json"
        if not summary.is_file():
            continue
        for row in json.loads(summary.read_text(encoding="utf-8")).get("rows", []):
            if row.get("baseline") == baseline_key and row.get("report") and not row.get("error"):
                path = run / row["report"]
                if path.is_file():
                    return path
    return None
