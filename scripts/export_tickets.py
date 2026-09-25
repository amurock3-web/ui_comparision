"""Export a report.json's FAIL/REVIEW issues as ticket rows (CSV, opens in Excel).

    python -m scripts.export_tickets <report.json> [--out file.csv]

Columns and their order come from config/ticket_export.yaml.
"""
import argparse
import json
from pathlib import Path

import yaml

import scripts._test_utils  # noqa: F401  (UTF-8 console output)
from src.reporting.export import DEFAULT_COLUMNS, to_ticket_rows, write_csv

CONFIG = Path("config/ticket_export.yaml")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report")
    ap.add_argument("--out")
    args = ap.parse_args()

    report_path = Path(args.report)
    out = Path(args.out) if args.out else report_path.with_name(report_path.stem + "_tickets.csv")
    columns = DEFAULT_COLUMNS
    if CONFIG.exists():
        columns = (yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}).get("columns") or DEFAULT_COLUMNS

    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = to_ticket_rows(report, str(report_path), columns)
    write_csv(rows, columns, out)
    print(f"{len(rows)} ticket rows -> {out}")


if __name__ == "__main__":
    main()
