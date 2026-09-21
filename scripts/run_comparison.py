import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from scripts._test_utils import next_test_number
from src.comparison.differ import DifferenceEngine
from src.comparison.matcher import ElementMatcher
from src.fusion.fuse import FusionEngine
from src.graph.build import UIGraphBuilder
from src.ocr.engine import OCREngine
from src.vlm.engine import VLMEngine

# The pair to diff, as two command-line arguments or the defaults below.
# Screen ids follow the file names, so only the paths need changing. There's
# no real client screenshot in the repo yet - drop one in input/client/.
#   python -m scripts.run_comparison [production.png] [client.png]
PRODUCTION_IMAGE = Path(sys.argv[1] if len(sys.argv) > 1 else "input/production/ss012.png")
CLIENT_IMAGE = Path(sys.argv[2] if len(sys.argv) > 2 else "input/client/ss012.png")
PRODUCTION_SCREEN_ID = PRODUCTION_IMAGE.stem
CLIENT_SCREEN_ID = CLIENT_IMAGE.stem

OUTPUT_DIR = Path("output/comparison")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREFIX = f"test{next_test_number(OUTPUT_DIR)}_{PRODUCTION_SCREEN_ID}_comparison"


def build_document(image_path: Path, screen_id: str, source: str):
    ocr_result = OCREngine(lang="en").run(image_path, screen_id=screen_id)
    vlm_result = VLMEngine().analyze(image_path, ocr_result, screen_id=screen_id)
    grounded_cards = VLMEngine().ground_content_cards_experimental(image_path, screen_id=screen_id)
    ui_doc = FusionEngine().fuse(ocr_result, vlm_result, grounded_cards, screen_id=screen_id, source=source)
    graph = UIGraphBuilder().build(ui_doc)
    return ui_doc, graph


production_doc, production_graph = build_document(PRODUCTION_IMAGE, PRODUCTION_SCREEN_ID, "production")
client_doc, client_graph = build_document(CLIENT_IMAGE, CLIENT_SCREEN_ID, "client")

match_result = ElementMatcher().match(production_doc, client_doc, production_graph, client_graph)
differences = DifferenceEngine().compare(
    production_doc, client_doc, production_graph, client_graph, match_result
)

(OUTPUT_DIR / f"{PREFIX}.json").write_text(
    json.dumps([asdict(d) for d in differences], indent=2, ensure_ascii=False),
    encoding="utf-8",
)

type_counts = Counter(d.type for d in differences)

print(f"Production elements: {len(production_doc.elements)}")
print(f"Client elements: {len(client_doc.elements)}")
print(f"Matches: {len(match_result.matches)}")
print(f"Unmatched production: {len(match_result.unmatched_production)}")
print(f"Unmatched client: {len(match_result.unmatched_client)}")
print(f"Difference breakdown: {dict(type_counts)}")

print(f"\nDifferences JSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
