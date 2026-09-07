from collections import Counter
from pathlib import Path

from scripts._test_utils import next_test_number
from src.fusion.fuse import FusionEngine
from src.fusion.visualize import draw_fusion_result
from src.ocr.engine import OCREngine
from src.vlm.engine import VLMEngine

IMAGE_PATH = Path("input/production/ss012.png")
SCREEN_ID = "ss012"
OUTPUT_DIR = Path("output/fusion")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREFIX = f"test{next_test_number(OUTPUT_DIR)}_{SCREEN_ID}_fusion"

ocr_result = OCREngine(lang="en").run(IMAGE_PATH, screen_id=SCREEN_ID)
vlm_result = VLMEngine().analyze(IMAGE_PATH, ocr_result, screen_id=SCREEN_ID)
grounded_cards = VLMEngine().ground_content_cards_experimental(IMAGE_PATH, screen_id=SCREEN_ID)
ui_doc = FusionEngine().fuse(ocr_result, vlm_result, grounded_cards, screen_id=SCREEN_ID, source="production")

ui_doc.save_json(OUTPUT_DIR / f"{PREFIX}.json")
skipped = draw_fusion_result(IMAGE_PATH, ui_doc, OUTPUT_DIR / f"{PREFIX}_visualization.png")

class_counts = Counter(e.class_ for e in ui_doc.elements)
source_counts = Counter(e.source for e in ui_doc.elements)
grounded = sum(1 for e in ui_doc.elements if e.bbox is not None)

print(f"Elements: {len(ui_doc.elements)}")
print(f"Class breakdown: {dict(class_counts)}")
print(f"Source breakdown: {dict(source_counts)}")
print(f"With geometry: {grounded}/{len(ui_doc.elements)} (skipped in image: {skipped})")

print(f"\nJSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
print(f"Visualization saved to: {OUTPUT_DIR / f'{PREFIX}_visualization.png'}")
