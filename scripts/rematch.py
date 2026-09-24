"""Re-run matching -> differ -> report from two saved fused JSONs - no detector, no OCR.

The detector + OCR pass costs ~90s per screen, and iterating on the matcher,
the differ or the report never needs it: run_comparison.py and src/app.py now
save each side's fused UIDocument, and this script picks those up. Same chain
as scripts/run_comparison.py from the graph stage on, so the report is
identical; runs in a second or two. Passing one JSON as both sides is the
self-compare sanity check (everything should match, nothing should differ).

    python -m scripts.rematch <production_fused.json> <client_fused.json>
    python -m scripts.rematch <fused.json> <fused.json>            # self-compare
    python -m scripts.rematch <p.json> <c.json> --production-image a.png --client-image b.png

Output, per run, in output/rematch/:
  testN_<screen>_comparison.json   every difference (MATCH included)
  testN_<screen>_report.json       verdict, findings, coverage, confidence
  testN_<screen>_report.html       the page to read (self-contained)
  testN_<screen>_report.png        side-by-side image used in the page
"""
import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from scripts._test_utils import next_test_number
from scripts.build_graph_from_fusion import find_screenshot
from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import ElementMatcher
from src.graph.layout import LayoutGraphBuilder
from src.reporting.html_report import write_html_report
from src.reporting.report import ReportGenerator
from src.schema.ui_element import UIDocument

OUTPUT_DIR = Path("output/rematch")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def _screenshot_beside(json_path: Path, doc: UIDocument):
    """src/app.py keeps the uploaded screenshots in the run folder next to the
    fused JSONs, named production_*/client_* - the same prefix as doc.source."""
    return next((p for p in sorted(json_path.parent.glob(f"{doc.source}_*"))
                 if p.suffix.lower() in IMAGE_EXTS), None)


def load(json_path: Path, image_override):
    """Fused JSON -> (UIDocument, layout graph, screenshot). The graph is built
    exactly as src/pipeline.py builds it. A UIDocument stores no image path, so
    the screenshot is the override, else the app run folder's copy, else
    input/{production,client}/<screen_id>.* - the report needs it to draw."""
    doc = UIDocument.model_validate_json(json_path.read_text(encoding="utf-8"))
    image = (Path(image_override) if image_override
             else _screenshot_beside(json_path, doc) or find_screenshot(doc.screen_id))
    if image is None or not image.is_file():
        raise SystemExit(f"no screenshot found for {json_path} ({doc.screen_id}) - "
                         f"pass --production-image / --client-image")
    return doc, LayoutGraphBuilder().build(doc), image


def main():
    parser = argparse.ArgumentParser(description="Re-match two saved fused UIDocuments.")
    parser.add_argument("production_json", type=Path)
    parser.add_argument("client_json", type=Path)
    parser.add_argument("--production-image")
    parser.add_argument("--client-image")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    production_doc, production_graph, production_image = load(args.production_json, args.production_image)
    client_doc, client_graph, client_image = load(args.client_json, args.client_image)

    prefix = f"test{next_test_number(OUTPUT_DIR)}_{production_doc.screen_id}"

    match_result = ElementMatcher().match(production_doc, client_doc, production_graph, client_graph)
    differences = DifferenceEngine().compare(
        production_doc, client_doc, production_graph, client_graph, match_result,
        production_image=production_image, client_image=client_image,
    )

    (OUTPUT_DIR / f"{prefix}_comparison.json").write_text(
        json.dumps([asdict(d) for d in differences], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    report = ReportGenerator().generate(production_doc, client_doc, differences)
    ReportGenerator.save_json(report, OUTPUT_DIR / f"{prefix}_report.json")
    html_path = write_html_report(report, production_image, client_image, production_doc, client_doc,
                                  differences, OUTPUT_DIR / f"{prefix}_report.html",
                                  production_graph, client_graph)

    type_counts = Counter(d.type for d in differences)

    print(f"Production: {args.production_json}  (screenshot {production_image})")
    print(f"Client:     {args.client_json}  (screenshot {client_image})")
    print(f"Production elements: {len(production_doc.elements)}")
    print(f"Client elements: {len(client_doc.elements)}")
    print(f"Matches: {len(match_result.matches)}")
    print(f"Unmatched production: {len(match_result.unmatched_production)}")
    print(f"Unmatched client: {len(match_result.unmatched_client)}")
    print(f"Difference breakdown: {dict(type_counts)}")
    print(f"Verdict: {report['verdict']}  similarity {report['similarity_percent']}%")

    # One line per pair: the matcher's decisions are what phase 12 is tuning, so
    # they belong in the console, not only inside the HTML.
    production_by_id = {e.id: e for e in production_doc.elements}
    print("\nMatched pairs (production -> client, class, text, score):")
    for match in sorted(match_result.matches, key=lambda m: -m.score):
        element = production_by_id[match.production_id]
        text = " ".join((element.text or "").split())[:40]
        print(f"  {match.production_id:<22} -> {match.client_id:<22} "
              f"{element.class_ or '-':<16} {text!r:<42} {match.score:.3f}")

    print(f"\nDifferences JSON saved to: {OUTPUT_DIR / f'{prefix}_comparison.json'}")
    print(f"Report JSON saved to:      {OUTPUT_DIR / f'{prefix}_report.json'}")
    print(f"HTML report saved to:      {html_path}")


if __name__ == "__main__":
    main()
