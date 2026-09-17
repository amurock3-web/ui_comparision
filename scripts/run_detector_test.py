"""Detector only (no OCR, no VLM): detect one screenshot, save JSON + boxes drawn on the image.

    $env:UI_DETECTOR_PYTHON = "C:\\Users\\pralhadraj.joshi\\UI_Detection_model_training\\.venv\\Scripts\\python.exe"
    python -m scripts.run_detector_test [image_path]
"""
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

from scripts._test_utils import next_test_number
from src.detector.engine import load_detector
from src.fusion.visualize import draw_fusion_result
from src.schema.ui_element import UIDocument

IMAGE_PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "input/production/ss012.png")
SCREEN_ID = IMAGE_PATH.stem
OUTPUT_DIR = Path("output/detector")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PREFIX = f"test{next_test_number(OUTPUT_DIR)}_{SCREEN_ID}_detector"

detector = load_detector()
elements = detector.detect(IMAGE_PATH)
W, H = Image.open(IMAGE_PATH).size
doc = UIDocument(screen_id=SCREEN_ID, source="fused", image_width=W, image_height=H, elements=elements)

doc.save_json(OUTPUT_DIR / f"{PREFIX}.json")
draw_fusion_result(IMAGE_PATH, doc, OUTPUT_DIR / f"{PREFIX}_visualization.png")

print(f"Engine: {type(detector).__name__}  image: {IMAGE_PATH}  ({W}x{H})")
print(f"Elements: {len(elements)}")
for cls, n in Counter(e.class_ for e in elements).most_common():
    print(f"  {cls:16s} {n}")
print("Tier breakdown: " + " ".join(f"{t}={sum(e.confidence_tier == t for e in elements)}"
                                    for t in ("high", "medium", "low")))
print(f"Low-confidence-class hits: {sum(bool(e.metadata['low_confidence_class']) for e in elements)}")
print(f"\nJSON saved to: {OUTPUT_DIR / f'{PREFIX}.json'}")
print(f"Visualization saved to: {OUTPUT_DIR / f'{PREFIX}_visualization.png'}")
