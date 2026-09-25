"""Read the run folders under output/app/<run>/ for the History and Results pages.

Every field is optional: older runs lack "issues" / "summary.issues" /
"summary.matched_pairs", and a run that crashed may have no report.json at all.
"""

import json
import re
from datetime import datetime
from pathlib import Path

RUN_RE = re.compile(r"\d{8}_\d{6}")
# Whitelisted names only: a run id of digits and a report[_N].html|pdf|png, so
# "..", slashes or any other file in the folder can never match.
FILE_RE = re.compile(r"/run/(\d{8}_\d{6})/(report(?:_\d+)?\.(?:html|pdf|png))")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def run_file(url_path: str, runs_dir: Path) -> Path | None:
    """The file a /run/<run>/report.<ext> URL names, or None if it is not whitelisted or missing."""
    m = FILE_RE.fullmatch(url_path)
    if m and (runs_dir / m[1] / m[2]).is_file():
        return runs_dir / m[1] / m[2]
    return None


def headline(report: dict) -> str:
    """The one line above the report: how many of the comparable elements paired
    up, and where the rest went. Counts live in report["summary"]; .get keeps an
    older report.json (or a field that moves back to the top level) from
    crashing the page."""
    s = report.get("summary", {})

    def n(key):
        return s.get(key, report.get(key, 0))

    matched, missing, extra = n("matched_pairs"), n("missing"), n("extra")
    return (f"Matched {matched} of {matched + missing + extra} elements "
            f"({n('similarity_percent')}%) · clean {n('clean_pairs')} · "
            f"missing {missing} · extra {extra} · ignored {n('ignored')}")


def _input_name(run_dir: Path, side: str) -> str | None:
    """The uploaded screenshot is saved as <side>_<screen id><ext>."""
    for p in sorted(run_dir.glob(f"{side}_*")):
        if p.suffix.lower() in IMAGE_EXTS:
            return p.name[len(side) + 1:]
    return None


def read_run(run_dir: Path) -> dict:
    try:
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            report = {}
    except (OSError, ValueError):
        report = {}
    s = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    issues = s.get("issues")
    if issues is None and isinstance(report.get("issues"), list):
        issues = len(report["issues"])
    try:
        date = datetime.strptime(run_dir.name, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        date = None
    return {
        "run": run_dir.name,
        "date": date,
        "production": _input_name(run_dir, "production"),
        "client": _input_name(run_dir, "client"),
        "verdict": report.get("verdict"),
        "similarity": report.get("similarity_percent", s.get("similarity_percent")),
        "findings": len(report["findings"]) if isinstance(report.get("findings"), list) else None,
        "issues": issues,
        "headline": headline(report) if "matched_pairs" in s else None,
        "has_html": (run_dir / "report.html").is_file(),
        "has_pdf": (run_dir / "report.pdf").is_file(),
        "baseline": _baseline_key(run_dir),
    }


def _baseline_key(run_dir: Path) -> str | None:
    """The stored baseline a run compared against (baseline.json), None for an uploaded client."""
    try:
        return json.loads((run_dir / "baseline.json").read_text(encoding="utf-8")).get("key")
    except (OSError, ValueError, AttributeError):
        return None


def list_runs(runs_dir: Path) -> list[dict]:
    """Every run folder, newest first (run ids are timestamps, so name order is time order)."""
    if not runs_dir.is_dir():
        return []
    return [read_run(d) for d in sorted(runs_dir.iterdir(), key=lambda d: d.name, reverse=True)
            if d.is_dir() and RUN_RE.fullmatch(d.name)]
