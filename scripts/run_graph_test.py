from collections import Counter
from pathlib import Path

from scripts._test_utils import next_test_number
from src.fusion.fuse import FusionEngine
from src.graph.build import UIGraphBuilder
from src.graph.visualize import draw_graph_result
from src.ocr.engine import OCREngine
from src.vlm.engine import VLMEngine

IMAGE_PATH = Path("input/production/ss012.png")
SCREEN_ID = "ss012"
OUTPUT_DIR = Path("output/graph")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREFIX = f"test{next_test_number(OUTPUT_DIR)}_{SCREEN_ID}_graph"

ocr_result = OCREngine(lang="en").run(IMAGE_PATH, screen_id=SCREEN_ID)
vlm_result = VLMEngine().analyze(IMAGE_PATH, ocr_result, screen_id=SCREEN_ID)
grounded_cards = VLMEngine().ground_content_cards_experimental(IMAGE_PATH, screen_id=SCREEN_ID)
ui_doc = FusionEngine().fuse(ocr_result, vlm_result, grounded_cards, screen_id=SCREEN_ID, source="production")

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
