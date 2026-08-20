from pathlib import Path
from src.ocr.engine import OCREngine
from src.ocr.visualize import draw_ocr_result

IMAGE_PATH = Path("input/production/ss012.png")
OUTPUT_DIR = Path("output/ocr")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

engine = OCREngine(lang="en")
result = engine.run(IMAGE_PATH, screen_id="ss012")

result.save_json(OUTPUT_DIR / "ss012_ocr.json")
draw_ocr_result(IMAGE_PATH, result, OUTPUT_DIR / "ss012_ocr_visualization.png")

print(f"Elements: {result.element_count if hasattr(result,'element_count') else len(result.elements)}")
print(f"Inference time: {result.inference_time_seconds:.2f}s")
print(f"Tier breakdown: "
      f"high={sum(1 for e in result.elements if e.confidence_tier=='high')} "
      f"medium={sum(1 for e in result.elements if e.confidence_tier=='medium')} "
      f"low={sum(1 for e in result.elements if e.confidence_tier=='low')}")