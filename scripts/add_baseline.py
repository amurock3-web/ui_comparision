"""Store a client design as a reusable baseline (src/baselines.py): detector + OCR
run once here (~45-90 s), then run_comparison --baseline / run_batch reuse it.

    python -m scripts.add_baseline <client_image> --screen <id> [--device phone|tablet|tv] [--language ta]
    python -m scripts.add_baseline --list
"""
import argparse
from pathlib import Path

import scripts._test_utils  # noqa: F401  UTF-8 console
from src.baselines import add_baseline, list_baselines


def main():
    parser = argparse.ArgumentParser(description="Add a client baseline.")
    parser.add_argument("client_image", type=Path, nargs="?")
    parser.add_argument("--screen", help="screen id (default: image file stem)")
    parser.add_argument("--device", choices=["phone", "tablet", "tv"], help="default: from aspect ratio")
    parser.add_argument("--language", help='default: "default"')
    parser.add_argument("--list", action="store_true", help="list stored baselines and exit")
    args = parser.parse_args()

    if args.list or args.client_image is None:
        for row in list_baselines():
            print(f"{row['key']:<40} {'STALE, re-add' if row['stale'] else 'ok':<14} {row['meta'].get('created')}")
        return
    baseline = add_baseline(args.client_image, args.screen or args.client_image.stem, args.device, args.language)
    print(f"Baseline {baseline.key}: {len(baseline.doc.elements)} elements, stored in {baseline.path}")


if __name__ == "__main__":
    main()
