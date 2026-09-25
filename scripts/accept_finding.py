"""Accept a finding (or a whole issue) so the next run reports it as PASS (accepted).

    python -m scripts.accept_finding <report.json> --finding N --note "deliberate copy change"
    python -m scripts.accept_finding <report.json> --issue issue_003 --note "..."

N is the finding's index in report.json's "findings" list (0-based). Appends to
the acceptance file from config (comparison.accepted_differences.path); never
edits past reports. Re-run the comparison (e.g. scripts.rematch) to see it applied.
"""
import argparse
import json
from pathlib import Path

import yaml

import scripts._test_utils  # noqa: F401  (UTF-8 console: OCR text is Tamil/CJK)
from src.comparison import accepted

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("report", type=Path)
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--finding", type=int, help="index into report.json findings")
    which.add_argument("--issue", help="issue id from report.json issues, e.g. issue_003")
    ap.add_argument("--note", required=True, help="why this difference is expected")
    ap.add_argument("--by", default="", help="who accepted it")
    args = ap.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    if args.issue:
        issue = next((i for i in report.get("issues") or [] if i["issue_id"] == args.issue), None)
        if issue is None:
            raise SystemExit(f"no issue {args.issue} in {args.report}")
        indices = issue["finding_indices"]
    else:
        indices = [args.finding]
    findings = [report["findings"][i] for i in indices]

    cfg = yaml.safe_load((ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    path = ROOT / cfg["comparison"].get("accepted_differences", {}).get(
        "path", "baselines/accepted_differences.yaml")
    entries = [accepted.entry_for(report, f, args.note, args.by) for f in findings]
    total = accepted.append(path, entries)
    for f in findings:
        print(f"accepted {f['spec_id']} {f['type']} {f.get('class')} {f.get('text')!r}")
    print(f"{len(entries)} added, {total} in {path}")


if __name__ == "__main__":
    main()
