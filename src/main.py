"""
Orchestration entry point: OCR -> VLM -> Fusion -> Graph -> Comparison ->
Report, for a Production/Client screenshot pair.
"""

import argparse
from pathlib import Path

from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import ElementMatcher
from src.fusion.fuse import FusionEngine
from src.graph.build import UIGraphBuilder
from src.ocr.engine import OCREngine
from src.reporting.report import ReportGenerator
from src.reporting.visualize import draw_comparison_result
from src.vlm.engine import VLMEngine


def process_screen(image_path: Path, screen_id: str, source_label: str):
    image_path = Path(image_path)

    print(f"\n=== OCR - {source_label} screen {screen_id!r} ===")
    ocr_result = OCREngine().run(image_path, screen_id=screen_id)
    ocr_result.save_json(Path(f"output/ocr/{screen_id}_{source_label}_ocr.json"))

    print(f"\n=== VLM - {source_label} screen {screen_id!r} ===")
    vlm_result = VLMEngine().analyze(image_path, ocr_result, screen_id=screen_id)
    vlm_result.save_json(Path(f"output/vlm/{screen_id}_{source_label}_vlm.json"))

    print(f"\n=== Fusion - {source_label} screen {screen_id!r} ===")
    grounded_cards = VLMEngine().ground_content_cards_experimental(image_path, screen_id=screen_id)
    ui_doc = FusionEngine().fuse(ocr_result, vlm_result, grounded_cards, screen_id=screen_id, source=source_label)
    ui_doc.save_json(Path(f"output/json/{screen_id}_{source_label}.json"))

    print(f"\n=== Graph - {source_label} screen {screen_id!r} ===")
    graph = UIGraphBuilder().build(ui_doc)
    UIGraphBuilder.save_graph_json(graph, Path(f"output/graph/{screen_id}_{source_label}_graph.json"))

    return ui_doc, graph


def main():
    parser = argparse.ArgumentParser(description="Compare a Production screenshot against a Client screenshot.")
    parser.add_argument("--production-image", required=True, help="Path to the production screenshot.")
    parser.add_argument("--production-screen-id", required=True)
    parser.add_argument("--client-image", required=True, help="Path to the client screenshot.")
    parser.add_argument("--client-screen-id", required=True)
    args = parser.parse_args()

    for out_dir in ("output/ocr", "output/vlm", "output/json", "output/graph", "output/reports"):
        Path(out_dir).mkdir(parents=True, exist_ok=True)

    prod_doc, prod_graph = process_screen(Path(args.production_image), args.production_screen_id, "production")
    client_doc, client_graph = process_screen(Path(args.client_image), args.client_screen_id, "client")

    print("\n=== Comparison ===")
    match_result = ElementMatcher().match(prod_doc, client_doc, prod_graph, client_graph)
    differences = DifferenceEngine().compare(prod_doc, client_doc, prod_graph, client_graph, match_result)

    print("\n=== Report ===")
    report = ReportGenerator().generate(prod_doc, client_doc, differences)
    screen_id = args.production_screen_id
    ReportGenerator.save_json(report, Path(f"output/reports/{screen_id}_report.json"))
    drawn = draw_comparison_result(
        args.production_image, args.client_image, prod_doc, client_doc, differences,
        Path(f"output/reports/{screen_id}_comparison_visualization.png"),
    )

    print(f"Similarity: {report['similarity_percent']}%")
    print(f"Summary: {report['summary']}")
    print(f"Differences highlighted in visualization: {drawn}")
    print(f"Report saved to: output/reports/{screen_id}_report.json")
    print(f"Visualization saved to: output/reports/{screen_id}_comparison_visualization.png")


if __name__ == "__main__":
    main()
