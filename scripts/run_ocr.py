import sys
from pathlib import Path

from scripts._test_utils import next_test_number
from src.ocr.engine import OCREngine
from src.ocr.visualize import draw_ocr_result

IMAGE_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "input/production/ss012.png")
SCREEN_ID = IMAGE_PATH.stem
OUTPUT_DIR = Path("output/ocr")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREFIX = f"test{next_test_number(OUTPUT_DIR)}_{SCREEN_ID}_ocr"

engine = OCREngine(lang="en")
result = engine.run(IMAGE_PATH, screen_id=SCREEN_ID)

result.save_json(OUTPUT_DIR / f"{PREFIX}.json")
draw_ocr_result(IMAGE_PATH, result, OUTPUT_DIR / f"{PREFIX}_visualization.png")

print(f"Elements: {result.element_count if hasattr(result,'element_count') else len(result.elements)}")
print(f"Inference time: {result.inference_time_seconds:.2f}s")
print(f"Tier breakdown: "
      f"high={sum(1 for e in result.elements if e.confidence_tier=='high')} "
      f"medium={sum(1 for e in result.elements if e.confidence_tier=='medium')} "
      f"low={sum(1 for e in result.elements if e.confidence_tier=='low')}")

print(f"\nJSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
print(f"Visualization saved to: {OUTPUT_DIR / f'{PREFIX}_visualization.png'}")
