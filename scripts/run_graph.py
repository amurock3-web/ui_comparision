"""Graph build on detector-first fusion, the same method as main.py:
YOLO detector + OCR -> fuse_detections (no VLM) -> UIGraphBuilder.

    python -m scripts.run_graph [image.png]

The detector's separate interpreter comes from UI_DETECTOR_PYTHON
(see config/detector.yaml and environment.md §9).
"""
import sys
from collections import Counter
from pathlib import Path

from scripts._test_utils import next_test_number
from src.detector.engine import load_detector
from src.fusion.fuse import FusionEngine
from src.graph.build import UIGraphBuilder
from src.graph.visualize import draw_graph_result
from src.ocr.engine import OCREngine

IMAGE_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "input/production/ss012.png")
SCREEN_ID = IMAGE_PATH.stem
OUTPUT_DIR = Path("output/graph")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREFIX = f"test{next_test_number(OUTPUT_DIR)}_{SCREEN_ID}_graph"

detections = load_detector().detect(IMAGE_PATH)
ocr_result = OCREngine(lang="en").run(IMAGE_PATH, screen_id=SCREEN_ID)
ui_doc = FusionEngine().fuse_detections(detections, ocr_result, screen_id=SCREEN_ID, source="production")

graph = UIGraphBuilder().build(ui_doc)
UIGraphBuilder.save_graph_json(graph, OUTPUT_DIR / f"{PREFIX}.json")
skipped, edges_drawn = draw_graph_result(IMAGE_PATH, graph, OUTPUT_DIR / f"{PREFIX}_visualization.png")

relationship_counts = Counter(data["relationship"] for _, _, data in graph.edges(data=True))

print(f"Nodes: {graph.number_of_nodes()}")
print(f"Edges: {graph.number_of_edges()}")
print(f"Relationship breakdown: {dict(relationship_counts)}")
print(f"Visualization: {edges_drawn} edges drawn (CONTAINS only), {skipped} node(s) skipped (no geometry)")

print(f"\nGraph JSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
print(f"Visualization saved to: {OUTPUT_DIR / f'{PREFIX}_visualization.png'}")
