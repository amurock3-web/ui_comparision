"""
Orchestration entry point: OCR -> VLM -> Fusion -> Graph for one screen.

Comparison (matching/diff/report) is intentionally not wired in yet —
input/client/ has no screenshot yet, so Production-vs-Client comparison
is deferred until a real client image is supplied.
"""

import argparse
from pathlib import Path

from src.fusion.fuse import FusionEngine
from src.graph.build import UIGraphBuilder
from src.ocr.engine import OCREngine
from src.vlm.engine import VLMEngine


def process_screen(image_path: Path, screen_id: str, source_label: str = "production"):
    image_path = Path(image_path)

    print(f"\n=== [1/4] OCR - screen {screen_id!r} ===")
    ocr_result = OCREngine().run(image_path, screen_id=screen_id)
    ocr_result.save_json(Path(f"output/ocr/{screen_id}_ocr.json"))

    print(f"\n=== [2/4] VLM - screen {screen_id!r} ===")
    vlm_result = VLMEngine().analyze(image_path, ocr_result, screen_id=screen_id)
    vlm_result.save_json(Path(f"output/vlm/{screen_id}_vlm.json"))

    print(f"\n=== [3/4] Fusion - screen {screen_id!r} ===")
    grounded_cards = VLMEngine().ground_content_cards_experimental(image_path, screen_id=screen_id)
    ui_doc = FusionEngine().fuse(ocr_result, vlm_result, grounded_cards, screen_id=screen_id, source=source_label)
    ui_doc.save_json(Path(f"output/json/{screen_id}_{source_label}.json"))

    print(f"\n=== [4/4] Graph - screen {screen_id!r} ===")
    graph = UIGraphBuilder().build(ui_doc)
    UIGraphBuilder.save_graph_json(graph, Path(f"output/graph/{screen_id}_{source_label}_graph.json"))

    return ui_doc, graph


def main():
    parser = argparse.ArgumentParser(description="Run OCR -> VLM -> Fusion -> Graph on one screenshot.")
    parser.add_argument("--image", required=True, help="Path to the screenshot.")
    parser.add_argument("--screen-id", required=True, help="Screen identifier, e.g. ss012.")
    parser.add_argument("--source", default="production", choices=["production", "client"])
    args = parser.parse_args()

    for out_dir in ("output/ocr", "output/vlm", "output/json", "output/graph"):
        Path(out_dir).mkdir(parents=True, exist_ok=True)

    ui_doc, graph = process_screen(Path(args.image), args.screen_id, args.source)

    print(f"Elements: {len(ui_doc.elements)}")
    print(f"Graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
    print("Comparison stage not run - client-vs-production comparison is deferred.")


if __name__ == "__main__":
    main()
